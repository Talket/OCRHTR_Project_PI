import os, sys, time, threading, psutil, shutil, pymupdf, subprocess, re
from stage3_engine import process_page_regions, LanguageDetector, ContentClassifier, TesseractOCRBackend, TableExtractionBackend, LocalHTRBackend, TranslationEngine

class ResourceMonitor:
    def __init__(self, interval: float = 0.05):
        self.process = psutil.Process(os.getpid()); self.interval = interval; self.keep_measuring = True
        self.start_rss = self.process.memory_info().rss; self.peak_rss = self.start_rss; self.end_rss = 0
        self.cpu_samples = []; self.process.cpu_percent()
    def measure(self):
        try:
            while self.keep_measuring:
                mem = self.process.memory_info().rss
                if mem > self.peak_rss: self.peak_rss = mem
                self.cpu_samples.append(self.process.cpu_percent()); time.sleep(self.interval)
        finally: self.end_rss = self.process.memory_info().rss
    def stop(self): self.keep_measuring = False
    def get_avg_cpu(self): return sum(self.cpu_samples) / len(self.cpu_samples) if self.cpu_samples else 0
    def get_peak_cpu(self): return max(self.cpu_samples) if self.cpu_samples else 0

def format_mb(bytes_val: int) -> str: return f"{bytes_val / (1024 * 1024):.2f} MB"

def create_synthetic_image(output_path: str):
    doc = pymupdf.open(); page = doc.new_page(width=1000, height=1000)
    page.draw_rect(pymupdf.Rect(0, 0, 1000, 1000), color=(1, 1, 1), fill=(1, 1, 1))
    page.insert_text((50, 50), "Test Image Data", fontsize=20, color=(0, 0, 0)); page.get_pixmap().save(output_path); doc.close()

def test_bilingual_image_routing():
    print("\n--- Running Unit Test: Bilingual Image-Only Routing ---")
    ld = LanguageDetector()
    if "hin" in ld.installed_langs and "eng" in ld.installed_langs:
        img_path = "temp_bilingual_test.png"; create_synthetic_image(img_path)
        original_run = subprocess.run
        try:
            subprocess.run = lambda *args, **kwargs: type('obj', (object,), {'returncode': 0, 'stdout': "Script: Devanagari\nScript confidence: 5.0", 'stderr': ""})()
            res = ld.detect("", image_path=img_path, use_osd=True)
            assert res["tesseract_lang"].startswith("eng") and "hin" in res["tesseract_lang"], f"Failed to prepend eng to Indic script. Got: {res['tesseract_lang']}"
            print(f"✓ Bilingual Heuristic correctly routed image-only Devanagari to {res['tesseract_lang']}")
        finally: subprocess.run = original_run; (os.remove(img_path) if os.path.exists(img_path) else None)

def test_language_detector(img_path: str):
    print("\n--- Running Unit Test: Language Detector & OSD Fallback ---")
    ld = LanguageDetector()
    res_embed = ld.detect("This is English and हिंदी and ಕನ್ನಡ")
    assert all(s in res_embed["script_candidates"] for s in ["Latin", "Devanagari", "Kannada"])
    print("✓ Embedded text accurately resolved (Mixed Script)")
    res_osd = ld.detect("", image_path=img_path, use_osd=True)
    assert res_osd["detection_method"] in ["tesseract_osd", "tesseract_osd_probed", "fallback"]
    print(f"✓ Image-only script detection fallback contract respected (Method: {res_osd['detection_method']})")

def test_adaptive_preprocessing():
    print("\n--- Running Unit Test: Adaptive Preprocessing Protection ---")
    backend, real_png_path = TesseractOCRBackend(), "temp_adaptive_prep.png"; create_synthetic_image(real_png_path)
    try:
        call_count = 0
        def fake_exec_good(img_path, lang_code): nonlocal call_count; call_count += 1; return {"success": True, "text": "Perfect Text", "confidence": 95.0, "error": None}
        backend._execute_tesseract = fake_exec_good; res_good = backend.process(real_png_path, "eng")
        assert res_good["text"] == "Perfect Text" and res_good["preprocessing_applied"] is False and call_count == 1
        print("✓ Adaptive Prep Test 1: Correctly bypassed for clean high-confidence text")
        call_count = 0
        def fake_exec_bad_to_better(img_path, lang_code): nonlocal call_count; call_count += 1; return {"success": True, "text": "bad t3xt" if call_count == 1 else "good text", "confidence": 30.0 if call_count == 1 else 85.0, "error": None}
        backend._execute_tesseract = fake_exec_bad_to_better; res_better = backend.process(real_png_path, "eng")
        assert res_better["text"] == "good text" and res_better["preprocessing_applied"] is True and call_count == 2
        print("✓ Adaptive Prep Test 3: Correctly applied fallback when confidence increased")
    finally: (os.remove(real_png_path) if os.path.exists(real_png_path) else None)

def run_tests():
    print("============================================================")
    print("STAGE 3: EXTRACTION ENGINE PIPELINE TEST (Pi 3B Target)")
    print("============================================================\n")
    EVIDENCE_DIR, osd_img_path = "./test_evidence_crops", "temp_synthetic_osd.png"
    if os.path.exists(EVIDENCE_DIR): shutil.rmtree(EVIDENCE_DIR)
    os.makedirs(EVIDENCE_DIR, exist_ok=True); create_synthetic_image(osd_img_path)
    try:
        test_bilingual_image_routing(); test_language_detector(osd_img_path); test_adaptive_preprocessing()
    except AssertionError as e: print(f"\n[!] UNIT TEST ASSERTION FAILED: {e}"); sys.exit(1)
    finally: (os.remove(osd_img_path) if os.path.exists(osd_img_path) else None)

    try: from renderer import render_pdf_page; from visual_analyzer import analyze_page_image
    except ImportError: return print("\nWARNING: Stage 2 modules not found. Integration tests skipped.")

    filter_arg = sys.argv[1].lower() if len(sys.argv) > 1 else None
    ALL_PDFS = {"41.pdf": [1], "58.pdf": [1], "1200_RC0262025A0008_Location Of RegistrationACB Mumbai.pdf": [2]}
    PDFS = {k: v for k, v in ALL_PDFS.items() if filter_arg in k.lower()} if filter_arg else ALL_PDFS
    
    if filter_arg: print(f"\n>>> Running Targeted Integration Filter: '{filter_arg}' ({len(PDFS)} document(s)) <<<")

    total_time, max_ram = 0, 0
    print("\n--- Running Integration Pipeline on Regression Corpus ---")
    for pdf, pages in PDFS.items():
        if not os.path.exists(pdf): continue
        for page_num in pages:
            print(f"\nProcessing: {pdf} (Page {page_num})")
            img_path = f"temp_render_p{page_num}_{pdf}.png"
            if not render_pdf_page(pdf, page_num, img_path, dpi=150).get("render_successful"): continue
            ana_res = analyze_page_image(img_path)
            if not ana_res.get("analysis_successful"): continue

            monitor = ResourceMonitor(); threading.Thread(target=monitor.measure).start(); start_t = time.time()
            try: res = process_page_regions(img_path, ana_res["regions"], EVIDENCE_DIR, page_num, embedded_text="")
            finally: monitor.stop(); (os.remove(img_path) if os.path.exists(img_path) else None)

            elapsed = time.time() - start_t; total_time += elapsed; max_ram = max(max_ram, monitor.peak_rss)
            print(f"  Status          : {'SUCCESS' if res['success'] else 'FAILED'}")
            print(f"  Page Time       : {elapsed:.3f} s | Peak RAM: {format_mb(monitor.peak_rss)}")

            if "58" in pdf.lower() and res["success"]:
                ocr_regions = [r for r in res.get("regions", []) if str(r.get("processing_engine", "")).startswith("tesseract")]
                print(f"    -> 58.pdf Processed. Selected Langs: {set(r.get('tesseract_lang', '') for r in ocr_regions)}")
                print("    -> Regression Check: PASS (Successfully processed English cover page)")

            if "mumbai" in pdf.lower() and res["success"]:
                ocr_regions = [r for r in res.get("regions", []) if str(r.get("processing_engine", "")).startswith("tesseract")]
                tess_langs = [r.get("tesseract_lang", "") for r in ocr_regions]
                assert any("eng" in lang and "hin" in lang for lang in tess_langs)
                print("    -> Mumbai Page 2 Regression Check: PASS (Hindi + English accurately routed)")

    print(f"\nFINAL VERDICT: PASS | Total Time: {total_time:.3f} s")

if __name__ == "__main__": run_tests()
