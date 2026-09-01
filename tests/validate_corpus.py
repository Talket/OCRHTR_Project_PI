import os
import sys
import time
import psutil
import threading
import argparse
import pymupdf
from processor import route_document, assess_text_quality

CORPUS_DIR = "."
VALID_STATES = ["reliable_text_layer", "suspicious_text_layer", "no_text_layer"]

# STRICT 40-PAGE GROUND TRUTH
GROUND_TRUTH = {
    "143_RC1232026A0008_Location Of RegistrationSrinagar.pdf": {
        1: {"status": "reliable_text_layer", "evidence": "Digital table and coherent English", "verified": True},
        2: {"status": "reliable_text_layer", "evidence": "Digital table and coherent English", "verified": True},
        3: {"status": "reliable_text_layer", "evidence": "Digital text narrative", "verified": True},
        4: {"status": "reliable_text_layer", "evidence": "Digital text narrative", "verified": True}
    },
    "79_RC0322026A0012_Location Of RegistrationACB Chennai.pdf": {
        1: {"status": "suspicious_text_layer", "evidence": "Systematic lexical corruption (offehce, Intormation)", "verified": True},
        2: {"status": "suspicious_text_layer", "evidence": "Systematic lexical corruption", "verified": True},
        3: {"status": "suspicious_text_layer", "evidence": "Systematic lexical corruption", "verified": True},
        4: {"status": "suspicious_text_layer", "evidence": "Systematic lexical corruption", "verified": True},
        5: {"status": "suspicious_text_layer", "evidence": "Systematic lexical corruption", "verified": True},
        6: {"status": "suspicious_text_layer", "evidence": "Systematic lexical corruption", "verified": True},
        7: {"status": "suspicious_text_layer", "evidence": "Systematic lexical corruption", "verified": True}
    },
    "RC-03-2024-NIA-DLI.pdf": {
        1: {"status": "no_text_layer", "evidence": "Scanned image empty text", "verified": True},
        2: {"status": "no_text_layer", "evidence": "Scanned image empty text", "verified": True},
        3: {"status": "no_text_layer", "evidence": "Scanned image empty text", "verified": True},
        4: {"status": "no_text_layer", "evidence": "Scanned image empty text", "verified": True},
        5: {"status": "no_text_layer", "evidence": "Scanned image empty text", "verified": True},
        6: {"status": "no_text_layer", "evidence": "Scanned image empty text", "verified": True},
        7: {"status": "no_text_layer", "evidence": "Scanned image empty text", "verified": True},
        8: {"status": "no_text_layer", "evidence": "Scanned image empty text", "verified": True},
        9: {"status": "no_text_layer", "evidence": "Scanned image empty text", "verified": True},
        10: {"status": "no_text_layer", "evidence": "Scanned image empty text", "verified": True},
        11: {"status": "no_text_layer", "evidence": "Scanned image empty text", "verified": True}
    },
    "41.pdf": {
        1: {"status": "no_text_layer", "evidence": "Scanned cursive empty text", "verified": True},
        2: {"status": "no_text_layer", "evidence": "Scanned cursive empty text", "verified": True},
        3: {"status": "no_text_layer", "evidence": "Scanned cursive empty text", "verified": True},
        4: {"status": "no_text_layer", "evidence": "Scanned cursive empty text", "verified": True},
        5: {"status": "no_text_layer", "evidence": "Scanned cursive empty text", "verified": True},
        6: {"status": "no_text_layer", "evidence": "Scanned cursive empty text", "verified": True},
        7: {"status": "no_text_layer", "evidence": "Scanned cursive empty text", "verified": True},
        8: {"status": "no_text_layer", "evidence": "Scanned cursive empty text", "verified": True},
        9: {"status": "no_text_layer", "evidence": "Scanned cursive empty text", "verified": True}
    },
    "58.pdf": {
        1: {"status": "no_text_layer", "evidence": "Scanned image empty text", "verified": True},
        2: {"status": "no_text_layer", "evidence": "Scanned image empty text", "verified": True},
        3: {"status": "no_text_layer", "evidence": "Scanned image empty text", "verified": True},
        4: {"status": "no_text_layer", "evidence": "Scanned image empty text", "verified": True},
        5: {"status": "no_text_layer", "evidence": "Scanned image empty text", "verified": True},
        6: {"status": "no_text_layer", "evidence": "Scanned image empty text", "verified": True},
        7: {"status": "no_text_layer", "evidence": "Scanned image empty text", "verified": True},
        8: {"status": "no_text_layer", "evidence": "Scanned image empty text", "verified": True},
        9: {"status": "no_text_layer", "evidence": "Scanned image empty text", "verified": True}
    }
}

class ResourceMonitor:
    def __init__(self):
        self.process = psutil.Process(os.getpid())
        self.keep_measuring = True
        self.start_rss = self.process.memory_info().rss
        self.peak_rss = self.start_rss
        self.end_rss = 0
        self.cpu_samples = []
        self.process.cpu_percent() # Seed first call

    def measure(self):
        try:
            while self.keep_measuring:
                current_rss = self.process.memory_info().rss
                if current_rss > self.peak_rss:
                    self.peak_rss = current_rss
                self.cpu_samples.append(self.process.cpu_percent())
                time.sleep(0.05) # 50ms polling
        finally:
            self.end_rss = self.process.memory_info().rss

    def stop(self):
        self.keep_measuring = False
        
    def get_avg_cpu(self):
        return sum(self.cpu_samples) / len(self.cpu_samples) if self.cpu_samples else 0
        
    def get_peak_cpu(self):
        return max(self.cpu_samples) if self.cpu_samples else 0

def format_bytes(b): return f"{b / (1024 * 1024):.2f} MB"
def safe_div(n, d): return n / d if d else 0.0

def run_inspection():
    print("============================================================")
    print("INSPECTION MODE: EXTRACTING EMBEDDED TEXT LAYER EVIDENCE")
    print("============================================================\n")
    for filename, _ in GROUND_TRUTH.items():
        filepath = os.path.join(CORPUS_DIR, filename)
        if not os.path.exists(filepath): continue
        print(f"--- Document: {filename} ---")
        with pymupdf.open(filepath) as doc:
            for page_num in range(len(doc)):
                page = doc.load_page(page_num)
                text = page.get_text("text")
                signals = assess_text_quality(text)
                preview = text[:300].replace('\n', ' ') if text else "None"
                print(f"Physical Page {page_num + 1}:")
                print(f"  Extracted length : {len(text)} chars")
                print(f"  Signals          : {signals['quality_signals']}")
                print(f"  First 300 chars  : {preview}\n")

def pre_flight_validation():
    print("============================================================")
    print("PRE-FLIGHT STRICT VALIDATOR")
    print("============================================================")
    
    file_sizes = {}
    total_physical = 0
    total_gt = 0
    
    print(f"{'Document':<55} | {'Phy Pgs':<8} | {'GT Pgs':<8} | {'Size':<10} | {'Match'}")
    print("-" * 100)
    
    for filename, gt_pages in GROUND_TRUTH.items():
        filepath = os.path.join(CORPUS_DIR, filename)
        if not os.path.exists(filepath):
            print(f"FAIL: Missing expected validation file: {filename}")
            return False, {}
            
        file_sizes[filename] = os.path.getsize(filepath)
        
        with pymupdf.open(filepath) as doc:
            physical_count = len(doc)
            
        gt_count = len(gt_pages)
        total_physical += physical_count
        total_gt += gt_count
        match_str = "YES" if physical_count == gt_count else "NO"
        doc_short = filename[:53] + ".." if len(filename) > 55 else filename
        print(f"{doc_short:<55} | {physical_count:<8} | {gt_count:<8} | {format_bytes(file_sizes[filename]):<10} | {match_str}")
        
        if physical_count != gt_count:
            print(f"\nFAIL: {filename} physical pages ({physical_count}) != GT ({gt_count}).")
            return False, {}
            
        for p_num in range(1, physical_count + 1):
            if p_num not in gt_pages:
                print(f"\nFAIL: Missing ground truth for {filename} page {p_num}")
                return False, {}
            gt_data = gt_pages[p_num]
            if gt_data["status"] not in VALID_STATES:
                print(f"\nFAIL: Invalid state '{gt_data['status']}' found.")
                return False, {}
            if not gt_data.get("verified", False):
                print(f"\nFAIL: UNVERIFIED GROUND TRUTH. {filename} page {p_num} missing 'verified: True'.")
                return False, {}
                
    if len(GROUND_TRUTH) != 5:
        print(f"\nFAIL: Must have exactly 5 PDFs. Found {len(GROUND_TRUTH)}.")
        return False, {}
    if total_physical != 40 or total_gt != 40:
        print(f"\nFAIL: Must contain exactly 40 pages. Found {total_physical}.")
        return False, {}

    return True, file_sizes

def run_validation():
    passed_preflight, file_sizes = pre_flight_validation()
    if not passed_preflight:
        print("\nFINAL STAGE 1 VERDICT\nFAIL (Pre-flight aborted)")
        sys.exit(1)

    monitor = ResourceMonitor()
    monitor_thread = threading.Thread(target=monitor.measure)
    monitor_thread.start()
    
    start_time = time.time()
    matrix = {e: {a: 0 for a in VALID_STATES} for e in VALID_STATES}
    stats = {"correct": 0, "incorrect": 0, "page_errors": [], "doc_times": {}}
    
    print("\n============================================================")
    print("PAGE VALIDATION (V4 Zero OCR)")
    print("============================================================")
    print(f"{'Document':<25} | {'Pg':<3} | {'Expected':<18} | {'Actual':<18} | {'OK':<3} | {'Reason/Signals'}")
    print("-" * 115)
    
    try:
        for filename, page_truth in GROUND_TRUTH.items():
            filepath = os.path.join(CORPUS_DIR, filename)
            doc_start = time.time()
            
            try:
                result = route_document(filepath)
            except Exception as e:
                 print(f"\nFAIL: Processing error on {filename}: {e}")
                 print("\nFINAL STAGE 1 VERDICT\nFAIL")
                 return
                 
            for page in result["pages"]:
                p_num = page["page"]
                actual = page["text_layer_status"]
                expected = page_truth[p_num]["status"]
                qs = page["quality_signals"]
                
                signals_str = f"L:{qs.get('text_length',0)} Scr:{qs.get('suspicion_score',0)}"
                if "near_corrupt_ratio" in qs: signals_str += f" Typo:{qs['near_corrupt_ratio']}"
                
                matrix[expected][actual] += 1
                is_correct = (actual == expected)
                if is_correct: stats["correct"] += 1
                else:
                    stats["incorrect"] += 1
                    stats["page_errors"].append(f"{filename} Pg {p_num}: Expected '{expected}', got '{actual}'. Reason: {page['reason']}")
                    
                doc_short = filename[:22] + ".." if len(filename) > 25 else filename
                correct_str = "YES" if is_correct else "NO"
                print(f"{doc_short:<25} | {p_num:<3} | {expected:<18} | {actual:<18} | {correct_str:<3} | {signals_str}")
                    
            stats["doc_times"][filename] = time.time() - doc_start
    finally:
        monitor.stop()
        monitor_thread.join()
        
    total_time = time.time() - start_time
    total_pages = 40
    
    print("\n============================================================")
    print("3x3 CONFUSION MATRIX (Expected \ Predicted)")
    print("============================================================")
    print(f"{'':<20} | {'reliable':<10} | {'suspicious':<10} | {'no_text':<10}")
    print("-" * 60)
    for expected in VALID_STATES:
        r = matrix[expected]['reliable_text_layer']
        s = matrix[expected]['suspicious_text_layer']
        n = matrix[expected]['no_text_layer']
        exp_short = expected.replace("_text_layer", "")
        print(f"{exp_short:<20} | {r:<10} | {s:<10} | {n:<10}")
        
    print("\n============================================================")
    print("CLASS METRICS")
    print("============================================================")
    print(f"{'Class':<20} | {'Precision':<10} | {'Recall':<10} | {'F1':<10}")
    print("-" * 55)
    for cls in VALID_STATES:
        tp = matrix[cls][cls]
        fp = sum(matrix[other][cls] for other in VALID_STATES if other != cls)
        fn = sum(matrix[cls][other] for other in VALID_STATES if other != cls)
        
        precision = safe_div(tp, tp + fp)
        recall = safe_div(tp, tp + fn)
        f1 = safe_div(2 * precision * recall, precision + recall)
        print(f"{cls.replace('_text_layer',''):<20} | {precision:<10.3f} | {recall:<10.3f} | {f1:<10.3f}")

    if stats["incorrect"] > 0:
        print("\nPAGE-LEVEL ERRORS:")
        for err in stats["page_errors"]:
            print(f" - {err}")

    print("\n============================================================")
    print("RESOURCE METRICS (50ms Polling)")
    print("============================================================")
    print("RAM (RSS):")
    print(f"  Start       : {format_bytes(monitor.start_rss)}")
    print(f"  Peak        : {format_bytes(monitor.peak_rss)}")
    print(f"  End         : {format_bytes(monitor.end_rss)}")
    print("\nPROCESS CPU %:")
    print(f"  Avg CPU %   : {monitor.get_avg_cpu():.1f}%")
    print(f"  Peak CPU %  : {monitor.get_peak_cpu():.1f}%")
    print("\nTIMING:")
    print(f"  Total Elapsed : {total_time:.3f} s")
    print(f"  Per Page Avg  : {(total_time/total_pages):.3f} s")
    
    print("\n============================================================")
    print("FINAL STAGE 1 VERDICT")
    print("============================================================")
    if stats["correct"] == total_pages and total_pages == 40:
        print("PASS")
    else:
        print("FAIL")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--inspect", action="store_true")
    args = parser.parse_args()
    if args.inspect: run_inspection()
    else: run_validation()
