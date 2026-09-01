import os
import time
import psutil
import threading
import pymupdf
from renderer import render_pdf_page
from visual_analyzer import analyze_page_image

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
                time.sleep(0.05)
        finally:
            self.end_rss = self.process.memory_info().rss

    def stop(self):
        self.keep_measuring = False

def format_mb(bytes_val: int) -> str:
    return f"{bytes_val / (1024 * 1024):.2f} MB"

def create_blank_test_pdf(output_path: str):
    doc = pymupdf.open()
    doc.new_page()
    doc.save(output_path)
    doc.close()

CORPUS_DIR = "."
OUTPUT_DIR = "./temp_test_images"

# 5 original regression FIRs + 1 new sixth FIR
TEST_CASES = [
    {"filename": "143_RC1232026A0008_Location Of RegistrationSrinagar.pdf", "page": 1, "desc": "Clean Digital Page"},
    {"filename": "79_RC0322026A0012_Location Of RegistrationACB Chennai.pdf", "page": 1, "desc": "Corrupted Font Page"},
    {"filename": "RC-03-2024-NIA-DLI.pdf", "page": 1, "desc": "Handwritten Devanagari"},
    {"filename": "41.pdf", "page": 1, "desc": "Cursive English"},
    {"filename": "58.pdf", "page": 1, "desc": "Kannada Form"},
    {"filename": "26_RC0032026A0053_Location Of RegistrationNew Delhi.pdf", "page": 1, "desc": "New Delhi FIR Pg 1"},
    {"filename": "26_RC0032026A0053_Location Of RegistrationNew Delhi.pdf", "page": 2, "desc": "New Delhi FIR Pg 2"},
    {"filename": "temp_blank.pdf", "page": 1, "desc": "Effectively Blank Page", "is_blank": True}
]

def run_tests():
    print("============================================================")
    print("STAGE 2B.1: COMPONENT TEST - HARDENED VISUAL ANALYZER")
    print("============================================================\n")
    
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        
    blank_pdf_path = os.path.join(CORPUS_DIR, "temp_blank.pdf")
    create_blank_test_pdf(blank_pdf_path)

    total_tests = len(TEST_CASES) + 1 # +1 for invalid file path edge case
    analysis_times = []
    max_peak_rss = 0
    passed_tests = 0
    failed_tests = 0
    
    try:
        for i, test in enumerate(TEST_CASES, 1):
            filename = test["filename"]
            page_num = test["page"]
            desc = test["desc"]
            
            pdf_path = os.path.join(CORPUS_DIR, filename)
            img_filename = f"temp_rendered_{i}.png"
            img_path = os.path.join(OUTPUT_DIR, img_filename)
            
            print(f"--- Test {i}/{total_tests}: {filename} (Pg {page_num}) ---")
            print(f"    Type        : {desc}")
            
            # Render page (Render failure causes a test failure)
            render_res = render_pdf_page(pdf_path, page_num, img_path, dpi=150)
            if not render_res.get("render_successful"):
                print(f"    Result      : FAIL")
                print(f"    Error       : Renderer failed. Error: {render_res.get('error')}\n")
                failed_tests += 1
                continue
                
            # Monitor and Analyze
            monitor = ResourceMonitor()
            monitor_thread = threading.Thread(target=monitor.measure)
            monitor_thread.start()
            
            start_time = time.time()
            try:
                analysis_result = analyze_page_image(img_path)
            finally:
                monitor.stop()
                monitor_thread.join()
                if os.path.exists(img_path):
                    os.remove(img_path)
                
            elapsed = time.time() - start_time
            analysis_times.append(elapsed)
            max_peak_rss = max(max_peak_rss, monitor.peak_rss)
            
            if analysis_result["analysis_successful"]:
                w = analysis_result["width"]
                h = analysis_result["height"]
                regs = analysis_result["regions"]
                
                valid_structure = True
                error_reason = ""
                
                if w <= 0 or h <= 0:
                    valid_structure, error_reason = False, "Invalid image dimensions."
                
                for r in regs:
                    if not (r["x"] >= 0 and r["y"] >= 0): valid_structure, error_reason = False, "Negative coordinate."
                    if not (r["width"] > 0 and r["height"] > 0): valid_structure, error_reason = False, "Zero/negative width/height."
                    if r["x"] + r["width"] > w: valid_structure, error_reason = False, "Region bleeds past right edge."
                    if r["y"] + r["height"] > h: valid_structure, error_reason = False, "Region bleeds past bottom edge."
                    if not (0.0 <= r["content_likelihood"] <= 1.0): valid_structure, error_reason = False, "Likelihood OOB."
                    if r["region_kind"] not in ["text_candidate", "non_text_candidate", "unknown_candidate"]:
                        valid_structure, error_reason = False, f"Invalid kind: {r['region_kind']}"

                if valid_structure:
                    if test.get("is_blank"):
                        if len(regs) == 0:
                            passed_tests += 1
                            print(f"    Result      : PASS (Blank page verified empty)")
                            print(f"    Dimensions  : {w}x{h}")
                        else:
                            failed_tests += 1
                            print(f"    Result      : FAIL")
                            print(f"    Error       : Found {len(regs)} regions on a strictly blank page.")
                    else:
                        passed_tests += 1
                        print(f"    Result      : PASS")
                        print(f"    Dimensions  : {w}x{h}")
                        print(f"    Regions Fnd : {len(regs)}")
                        
                        # Diagnostic Region Metrics
                        if regs:
                            areas = [r["width"] * r["height"] for r in regs]
                            min_area = min(areas)
                            max_area = max(areas)
                            avg_area = sum(areas) / len(areas)
                            small_32 = sum(1 for r in regs if r["width"] < 32 and r["height"] < 32)
                            small_16 = sum(1 for r in regs if r["width"] < 16 and r["height"] < 16)
                            large_block = sum(1 for r in regs if r["width"] > 100 or r["height"] > 20)
                            
                            print(f"    Diagnostics : Count:{len(regs)} | MinArea:{min_area} | MaxArea:{max_area} | AvgArea:{avg_area:.1f}")
                            print(f"                  <32x32:{small_32} | <16x16:{small_16} | >100x20 Block:{large_block}")
                else:
                    failed_tests += 1
                    print(f"    Result      : FAIL")
                    print(f"    Error       : {error_reason}")
                    
            else:
                failed_tests += 1
                print(f"    Result      : FAIL")
                print(f"    Error       : {analysis_result.get('error')}")

            print(f"    Time        : {elapsed:.3f} s")
            print(f"    Start RAM   : {format_mb(monitor.start_rss)}")
            print(f"    Peak RAM    : {format_mb(monitor.peak_rss)}")
            print(f"    RAM Spike   : {format_mb(monitor.peak_rss - monitor.start_rss)}\n")
            
        print(f"--- Test {total_tests}/{total_tests}: Invalid File Path Edge Case ---")
        bad_result = analyze_page_image("does_not_exist_123.png")
        if not bad_result["analysis_successful"] and "not found" in bad_result["error"]:
            print(f"    Result      : PASS (Successfully caught missing file)\n")
            passed_tests += 1
        else:
            print(f"    Result      : FAIL\n")
            failed_tests += 1

    finally:
        if os.path.exists(blank_pdf_path):
            os.remove(blank_pdf_path)

    print("============================================================")
    print("STAGE 2B.1: PERFORMANCE SUMMARY")
    print("============================================================")
    print(f"Total Tests    : {total_tests}")
    print(f"Passed         : {passed_tests}")
    print(f"Failed         : {failed_tests}")
    print(f"Max Peak RAM   : {format_mb(max_peak_rss)}")
    
    if analysis_times:
        avg_time = sum(analysis_times) / len(analysis_times)
        max_time = max(analysis_times)
        print(f"Avg Time/Page  : {avg_time:.3f} s")
        print(f"Slowest Analys : {max_time:.3f} s")
        
    print("============================================================")
    if passed_tests == total_tests and failed_tests == 0:
        print("FINAL VERDICT: PASS")
    else:
        print("FINAL VERDICT: FAIL")
    print("============================================================")

if __name__ == "__main__":
    run_tests()
