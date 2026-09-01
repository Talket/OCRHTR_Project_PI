import os
import time
import psutil
import threading
import sys
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

# Base regression test cases
TEST_CASES = [
    {"filename": "143_RC1232026A0008_Location Of RegistrationSrinagar.pdf", "page": 1, "desc": "Clean Digital Page"},
    {"filename": "79_RC0322026A0012_Location Of RegistrationACB Chennai.pdf", "page": 1, "desc": "Corrupted Font Page"},
    {"filename": "RC-03-2024-NIA-DLI.pdf", "page": 1, "desc": "Handwritten Devanagari"},
    {"filename": "41.pdf", "page": 1, "desc": "Cursive English"},
    {"filename": "58.pdf", "page": 1, "desc": "Kannada Form"},
    {"filename": "26_RC0032026A0053_Location Of RegistrationNew Delhi.pdf", "page": 1, "desc": "New Delhi FIR Pg 1"},
    {"filename": "temp_blank.pdf", "page": 1, "desc": "Effectively Blank Page", "is_blank": True}
]

# Dynamically target Mumbai Page 2 if present
mumbai_found = False
if os.path.exists(CORPUS_DIR):
    for fname in os.listdir(CORPUS_DIR):
        if "mumbai" in fname.lower() and fname.endswith(".pdf"):
            TEST_CASES.append({"filename": fname, "page": 2, "desc": "MUMBAI FIR TARGET (Pg 2)"})
            mumbai_found = True
            break

def run_tests():
    print("============================================================")
    print("STAGE 2B.1: COMPONENT TEST - BOUNDED VISUAL ANALYZER")
    print("============================================================\n")
    
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        
    blank_pdf_path = os.path.join(CORPUS_DIR, "temp_blank.pdf")
    create_blank_test_pdf(blank_pdf_path)

    total_tests = len(TEST_CASES) + 1 # +1 for invalid file
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
            
            if not os.path.exists(pdf_path) and not test.get("is_blank"):
                print(f"    Result      : SKIP (File not found locally)\n")
                passed_tests += 1
                continue
            
            render_res = render_pdf_page(pdf_path, page_num, img_path, dpi=150)
            if not render_res.get("render_successful"):
                print(f"    Result      : FAIL")
                print(f"    Error       : Renderer failed. Error: {render_res.get('error')}\n")
                failed_tests += 1
                continue
                
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
                
                has_giant_region = False
                
                print(f"    Region Dump ({len(regs)} regions):")
                for r in regs:
                    print(f"      - ID:{r['region_id']:03d} | X:{r['x']:<4} Y:{r['y']:<4} W:{r['width']:<4} H:{r['height']:<4} | Type:{r['region_kind']}")
                    
                    if not (r["x"] >= 0 and r["y"] >= 0): valid_structure, error_reason = False, "Negative coordinate."
                    if not (r["width"] > 0 and r["height"] > 0): valid_structure, error_reason = False, "Zero/negative width/height."
                    if r["x"] + r["width"] > w: valid_structure, error_reason = False, "Region bleeds past right edge."
                    if r["y"] + r["height"] > h: valid_structure, error_reason = False, "Region bleeds past bottom edge."
                    
                    # STRICT DIMENSIONAL CHECK AS REQUESTED
                    if r["width"] > w * 0.5 and r["height"] > h * 0.5:
                        has_giant_region = True
                        print(f"      [!] STRICT VIOLATION: Region {r['region_id']} exceeds 50% width ({w*0.5}) AND 50% height ({h*0.5})")

                if has_giant_region:
                    valid_structure, error_reason = False, "Failed strict constraint: Output contained a massive unsegmented OCR block."

                if valid_structure:
                    if test.get("is_blank"):
                        if len(regs) == 0:
                            passed_tests += 1
                            print(f"    Result      : PASS (Blank page verified empty)")
                        else:
                            failed_tests += 1
                            print(f"    Result      : FAIL")
                            print(f"    Error       : Found {len(regs)} regions on a strictly blank page.")
                    else:
                        passed_tests += 1
                        print(f"    Result      : PASS")
                else:
                    failed_tests += 1
                    print(f"    Result      : FAIL")
                    print(f"    Error       : {error_reason}")
                    
            else:
                failed_tests += 1
                print(f"    Result      : FAIL")
                print(f"    Error       : {analysis_result.get('error')}")

            print(f"    Time        : {elapsed:.3f} s")
            print(f"    Peak RAM    : {format_mb(monitor.peak_rss)}\n")
            
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
    
    print("============================================================")
    if failed_tests == 0:
        print("FINAL VERDICT: PASS")
    else:
        print("FINAL VERDICT: FAIL")
        sys.exit(1)
    print("============================================================")

if __name__ == "__main__":
    run_tests()
