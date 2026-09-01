import os
import sys
import time
import re
from stage3_engine import (
    process_page_regions,
    LanguageDetector,
    ContentClassifier,
    TesseractOCRBackend,
    TableExtractionBackend,
    LocalHTRBackend,
    TranslationEngine
)
from renderer import render_pdf_page
from visual_analyzer import analyze_page_image

def run_targeted_mumbai():
    print("============================================================")
    print("FAST TARGETED TEST: MUMBAI PAGE 2")
    print("============================================================\n")

    mumbai_pdf = "1200_RC0262025A0008_Location Of RegistrationACB Mumbai.pdf"
    if not os.path.exists(mumbai_pdf):
        print(f"Error: {mumbai_pdf} not found.")
        sys.exit(1)

    evidence_dir = "./test_evidence_crops"
    os.makedirs(evidence_dir, exist_ok=True)
    temp_img = "temp_mumbai_p2_fast.png"

    # 1. Render Page 2
    print("1. Rendering Mumbai Page 2 (150 DPI)...")
    render_res = render_pdf_page(mumbai_pdf, 2, temp_img, dpi=150)
    assert render_res["render_successful"], f"Rendering failed: {render_res.get('error')}"

    # 2. Visual Analysis
    print("2. Running Visual Analysis (Stage 2B)...")
    ana_res = analyze_page_image(temp_img)
    assert ana_res["analysis_successful"], f"Visual analyzer failed: {ana_res.get('error')}"
    print(f"   Detected {len(ana_res['regions'])} regions.")

    # 3. Stage 3 Processing
    print("3. Running Stage 3 Engine...")
    start_t = time.time()
    try:
        res = process_page_regions(temp_img, ana_res["regions"], evidence_dir, page_num=2, embedded_text="")
    finally:
        if os.path.exists(temp_img):
            os.remove(temp_img)

    elapsed = time.time() - start_t
    print(f"   Stage 3 finished in {elapsed:.2f} s.\n")

    # 4. Verify Assertions
    ocr_regions = [
        r for r in res.get("regions", [])
        if str(r.get("processing_engine", "")).startswith("tesseract")
    ]
    tess_langs = [r.get("tesseract_lang", "") for r in ocr_regions]
    text = res.get("reconstructed_text", "")

    print("--- VALIDATION REPORT ---")
    print(f"Success Status      : {res.get('success')}")
    print(f"Total OCR Regions   : {len(ocr_regions)}")
    print(f"Selected OCR Langs  : {set(tess_langs)}")
    print(f"Total Text Length   : {len(text)} characters")

    has_eng_hin = any("eng" in lang and "hin" in lang for lang in tess_langs)
    has_hindi_chars = any(0x0900 <= ord(c) <= 0x097F for c in text)
    has_english_words = "Shri Vinay Saraf" in text or "Complainant" in text or len(re.findall(r'[A-Za-z]', text)) > 20

    print(f"Routed to eng+hin   : {'PASS' if has_eng_hin else 'FAIL'}")
    print(f"Extracted Hindi     : {'PASS' if has_hindi_chars else 'FAIL'}")
    print(f"Extracted English   : {'PASS' if has_english_words else 'FAIL'}")
    print("-------------------------\n")

    assert has_eng_hin, f"Failed: OCR regions did not route to eng+hin. Got: {set(tess_langs)}"
    assert has_hindi_chars, "Failed: Output contains no Hindi Unicode characters."
    assert has_english_words, "Failed: Output contains no recognizable English text."

    print("FINAL VERDICT: MUMBAI PAGE 2 PASS\n")

if __name__ == "__main__":
    run_targeted_mumbai()

