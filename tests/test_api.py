import os
import sys
import shutil
import time
import psutil
import pymupdf
from fastapi.testclient import TestClient
from api import app, EVIDENCE_DIR

client = TestClient(app)
CORPUS_DIR = "corpus"

class ResourceMonitor:
    def __init__(self):
        self.process = psutil.Process(os.getpid())
        self.start_rss = self.process.memory_info().rss
        self.peak_rss = self.start_rss
        
    def update(self):
        current_rss = self.process.memory_info().rss
        if current_rss > self.peak_rss:
            self.peak_rss = current_rss

def format_mb(bytes_val: int) -> str:
    return f"{bytes_val / (1024 * 1024):.2f} MB"

def create_fake_file(path: str, content: bytes):
    with open(path, "wb") as f:
        f.write(content)

def setup_module():
    if os.path.exists(EVIDENCE_DIR):
        shutil.rmtree(EVIDENCE_DIR)
    os.makedirs(EVIDENCE_DIR, exist_ok=True)

def test_missing_file():
    print("\n--- Testing API: Missing File Handling ---")
    response = client.post("/process")
    assert response.status_code == 422
    print("✓ Successfully handled missing file upload.")

def test_invalid_signature():
    print("\n--- Testing API: File Signature Rejection ---")
    fake_path = "fake_document.pdf"
    create_fake_file(fake_path, b"This is just raw text, not a PDF.")
    
    try:
        with open(fake_path, "rb") as f:
            response = client.post("/process", files={"file": ("fake_document.pdf", f, "application/pdf")})
        assert response.status_code == 415
        assert "Unsupported or invalid file signature" in response.json()["detail"]
        print("✓ Successfully rejected disguised non-PDF file.")
    finally:
        if os.path.exists(fake_path):
            os.remove(fake_path)

def test_oversized_file():
    print("\n--- Testing API: Oversize File Rejection ---")
    fake_path = "large_document.pdf"
    # Create a dummy file that exceeds 25MB safety limit
    create_fake_file(fake_path, b"0" * (26 * 1024 * 1024))
    
    try:
        with open(fake_path, "rb") as f:
            response = client.post("/process", files={"file": ("large_document.pdf", f, "application/pdf")})
        assert response.status_code == 413
        assert "exceeds maximum size" in response.json()["detail"]
        print("✓ Successfully rejected 25MB+ file to protect Pi RAM.")
    finally:
        if os.path.exists(fake_path):
            os.remove(fake_path)

def test_reliable_digital_pdf():
    print("\n--- Testing API: Reliable Digital FIR (Fast Path) ---")
    pdf_name = "143_RC1232026A0008_Location Of RegistrationSrinagar.pdf"
    pdf_path = os.path.join(CORPUS_DIR, pdf_name)
    if not os.path.exists(pdf_path): return print(f"⚠ Skipped: {pdf_name} missing.")

    with open(pdf_path, "rb") as f:
        response = client.post("/process", files={"file": (pdf_name, f, "application/pdf")})
        
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "processing_completed"
    
    p1 = data["pages"][0]
    assert p1["stage1"]["text_layer_status"] == "reliable_text_layer"
    assert p1["stage2"]["processing_path"] == "bypassed_for_embedded_text"
    assert len(p1["extracted_text"]) > 100
    print("✓ Reliable text correctly routed to fast PyMuPDF extraction.")

def test_suspicious_pdf():
    print("\n--- Testing API: Corrupted FIR (Visual Fallback) ---")
    pdf_name = "79_RC0322026A0012_Location Of RegistrationACB Chennai.pdf"
    pdf_path = os.path.join(CORPUS_DIR, pdf_name)
    if not os.path.exists(pdf_path): return print(f"⚠ Skipped: {pdf_name} missing.")

    with open(pdf_path, "rb") as f:
        response = client.post("/process", files={"file": (pdf_name, f, "application/pdf")})
        
    assert response.status_code == 200
    data = response.json()
    p1 = data["pages"][0]
    
    assert p1["stage1"]["text_layer_status"] == "suspicious_text_layer"
    assert p1["stage2"]["renderer"]["render_successful"] is True
    assert p1["stage3"]["success"] is True
    print("✓ Corrupted text correctly diverted to Stage 2/3 visual pipeline.")

def test_image_upload():
    print("\n--- Testing API: Direct Image Upload ---")
    img_path = "temp_synthetic.png"
    # Create a tiny valid image via PyMuPDF
    doc = pymupdf.open()
    page = doc.new_page(width=200, height=200)
    page.insert_text((10, 50), "Test Image")
    pix = page.get_pixmap()
    pix.save(img_path)
    doc.close()
    
    try:
        with open(img_path, "rb") as f:
            response = client.post("/process", files={"file": ("temp_synthetic.png", f, "image/png")})
            
        assert response.status_code == 200
        data = response.json()
        assert data["document_type"] == "image/png"
        assert data["pages"][0]["stage1"]["text_layer_status"] == "no_text_layer"
        assert "analyzer" in data["pages"][0]["stage2"] # Render skipped, jumped to analyzer
        print("✓ Image file correctly processed without PDF rendering.")
    finally:
        if os.path.exists(img_path): os.remove(img_path)

def test_multipage_pdf_and_evidence():
    print("\n--- Testing API: Multi-Page Processing & Evidence Tracking ---")
    pdf_name = "26_RC0032026A0053_Location Of RegistrationNew Delhi.pdf"
    pdf_path = os.path.join(CORPUS_DIR, pdf_name)
    if not os.path.exists(pdf_path): return print(f"⚠ Skipped: {pdf_name} missing.")

    with open(pdf_path, "rb") as f:
        response = client.post("/process", files={"file": (pdf_name, f, "application/pdf")})
        
    assert response.status_code == 200
    data = response.json()
    assert data["total_pages"] == 5
    
    # Check page isolation and structural metadata
    for p in data["pages"]:
        assert p["status"] == "success", f"Page {p['page']} failed."
        # Evidence preservation check
        if "regions" in p.get("stage3", {}):
            for r in p["stage3"]["regions"]:
                if r.get("evidence_required"):
                    assert os.path.exists(r["evidence_path"]), f"Evidence file {r['evidence_path']} missing from disk!"
                    
    print("✓ Multi-page isolation successful. Evidence files accurately tracked and saved.")

def run_all_tests():
    setup_module()
    monitor = ResourceMonitor()
    
    tests = [
        test_missing_file,
        test_invalid_signature,
        test_oversized_file,
        test_reliable_digital_pdf,
        test_suspicious_pdf,
        test_image_upload,
        test_multipage_pdf_and_evidence
    ]
    
    passed = 0
    start_time = time.time()
    
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"❌ TEST FAILED: {test.__name__}\n   Reason: {str(e)}")
        finally:
            monitor.update()
            
    total_time = time.time() - start_time
            
    print("\n============================================================")
    print("STAGE 4 API INTEGRATION TEST SUMMARY")
    print("============================================================")
    print(f"Tests Run      : {len(tests)}")
    print(f"Tests Passed   : {passed}")
    print(f"Total Run Time : {total_time:.3f} s")
    print(f"Start RAM (RSS): {format_mb(monitor.start_rss)}")
    print(f"Peak RAM (RSS) : {format_mb(monitor.peak_rss)}")
    print("============================================================")
    
    if passed < len(tests):
        sys.exit(1)

if __name__ == "__main__":
    run_all_tests()
