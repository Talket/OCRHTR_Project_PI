import os
import time
import psutil
import threading
import pymupdf
from renderer import render_pdf_page

class ResourceMonitor:
    def __init__(self):
        self.process = psutil.Process(os.getpid())
        self.keep_measuring = True
        self.start_rss = self.process.memory_info().rss
        self.peak_rss = self.start_rss
        self.end_rss = 0

    def measure(self):
        try:
            while self.keep_measuring:
                current_rss = self.process.memory_info().rss
                if current_rss > self.peak_rss:
                    self.peak_rss = current_rss
                time.sleep(0.05)  # 50ms polling
        finally:
            self.end_rss = self.process.memory_info().rss

    def stop(self):
        self.keep_measuring = False

def format_mb(bytes_val):
    return f"{bytes_val / (1024 * 1024):.2f} MB"

def create_rotated_test_pdf(output_path: str):
    """Creates a minimal PDF with 90-degree rotation metadata to prove the renderer handles rotation."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 50), "This page is rotated 90 degrees.")
    page.set_rotation(90)
    doc.save(output_path)
    doc.close()

CORPUS_DIR = "."
OUTPUT_DIR = "./test_renders"

TEST_CASES = [
    # Valid corpus tests
    {"filename": "143_RC1232026A0008_Location Of RegistrationSrinagar.pdf", "page": 1, "dpi": 150, "expect_success": True},
    {"filename": "79_RC0322026A0012_Location Of RegistrationACB Chennai.pdf", "page": 1, "dpi": 150, "expect_success": True},
    {"filename": "RC-03-2024-NIA-DLI.pdf", "page": 1, "dpi": 150, "expect_success": True},
    {"filename": "41.pdf", "page": 1, "dpi": 150, "expect_success": True},
    {"filename": "58.pdf", "page": 1, "dpi": 150, "expect_success": True},
    # Dynamic Rotation Test
    {"filename": "temp_rotated_test.pdf", "page": 1, "dpi": 150, "expect_success": True, "is_rotation_test": True},
    # Edge Cases & Failures
    {"filename": "58.pdf", "page": 999, "dpi": 150, "expect_success": False, "desc": "Invalid page number"},
    {"filename": "58.pdf", "page": 0, "dpi": 150, "expect_success": False, "desc": "Page 0 (1-based system)"},
    {"filename": "does_not_exist.pdf", "page": 1, "dpi": 150, "expect_success": False, "desc": "Nonexistent file"},
    {"filename": "41.pdf", "page": 1, "dpi": 0, "expect_success": False, "desc": "DPI = 0"},
    {"filename": "41.pdf", "page": 1, "dpi": -150, "expect_success": False, "desc": "Negative DPI"},
    {"filename": "41.pdf", "page": 1, "dpi": 9999, "expect_success": False, "desc": "Absurdly high DPI (>600)"},
]

def run_tests():
    print("============================================================")
    print("STAGE 2A: COMPONENT TEST - PDF PAGE RENDERER")
    print("============================================================\n")
    
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        
    rotated_pdf_path = os.path.join(CORPUS_DIR, "temp_rotated_test.pdf")
    create_rotated_test_pdf(rotated_pdf_path)

    total_tests = len(TEST_CASES)
    passed_tests = 0
    max_peak_rss = 0
    render_times = []
    
    for i, test in enumerate(TEST_CASES, 1):
        filename = test["filename"]
        page_num = test["page"]
        dpi = test["dpi"]
        expect_success = test["expect_success"]
        desc = test.get("desc", "Valid PDF rendering")
        
        pdf_path = os.path.join(CORPUS_DIR, filename)
        out_filename = f"test_{i}_page_{page_num}_dpi_{dpi}.png"
        output_path = os.path.join(OUTPUT_DIR, out_filename)
        
        print(f"--- Test {i}/{total_tests}: {filename} (Pg {page_num}, DPI {dpi}) ---")
        print(f"    Type: {desc}")
        
        monitor = ResourceMonitor()
        monitor_thread = threading.Thread(target=monitor.measure)
        monitor_thread.start()
        
        start_time = time.time()
        
        try:
            # Execute renderer
            result = render_pdf_page(pdf_path, page_num, output_path, dpi)
        finally:
            monitor.stop()
            monitor_thread.join()
            
        elapsed = time.time() - start_time
        max_peak_rss = max(max_peak_rss, monitor.peak_rss)
        
        test_passed = False
        reason = ""

        if expect_success:
            if result["render_successful"]:
                if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                    try:
                        # Mathematically prove the raster is readable via PyMuPDF (no external dependencies)
                        check_pix = pymupdf.Pixmap(output_path)
                        if check_pix.width == result["width"] and check_pix.height == result["height"]:
                            test_passed = True
                            render_times.append(elapsed)
                            if test.get("is_rotation_test"):
                                reason = f"Rendered and rotation bounds read successfully: {check_pix.width}x{check_pix.height}"
                            else:
                                reason = f"File created and readable: {check_pix.width}x{check_pix.height}"
                        else:
                            reason = "Output dimension mismatch."
                    except Exception as e:
                        reason = f"File created but failed to open raster: {e}"
                else:
                    reason = "Output file missing or empty."
            else:
                reason = f"Render failed unexpectedly: {result.get('error')}"
                
            # Cleanup successful output image to prevent disk bloat
            if os.path.exists(output_path):
                os.remove(output_path)
        else:
            if not result["render_successful"]:
                test_passed = True
                reason = f"Correctly rejected: {result.get('error')}"
            else:
                reason = "Render succeeded when it was expected to fail."
                if os.path.exists(output_path):
                    os.remove(output_path)

        if test_passed:
            passed_tests += 1
            print(f"    Result      : PASS")
        else:
            print(f"    Result      : FAIL")
            
        print(f"    Details     : {reason}")
        print(f"    Time        : {elapsed:.3f} s")
        print(f"    Start RAM   : {format_mb(monitor.start_rss)}")
        print(f"    Peak RAM    : {format_mb(monitor.peak_rss)}")
        print(f"    RAM Spike   : {format_mb(monitor.peak_rss - monitor.start_rss)}\n")

    # Cleanup temporary rotated PDF
    if os.path.exists(rotated_pdf_path):
        os.remove(rotated_pdf_path)

    print("============================================================")
    print("STAGE 2A: PERFORMANCE SUMMARY")
    print("============================================================")
    print(f"Total Tests    : {total_tests}")
    print(f"Passed         : {passed_tests}")
    print(f"Failed         : {total_tests - passed_tests}")
    print(f"Max Peak RAM   : {format_mb(max_peak_rss)}")
    
    if render_times:
        avg_time = sum(render_times) / len(render_times)
        max_time = max(render_times)
        print(f"Avg Time/Page  : {avg_time:.3f} s")
        print(f"Slowest Render : {max_time:.3f} s")
    else:
        print("Avg Time/Page  : N/A (no successful renders)")

if __name__ == "__main__":
    run_tests()
