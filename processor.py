import os
import re
import pymupdf
from typing import Dict, Any, List, Set

VOCAB_FILE = os.path.join(os.path.dirname(__file__), 'english_vocabulary.txt')
ENGLISH_VOCAB: Set[str] = set()

# Load vocabulary once into an O(1) lookup set
if os.path.exists(VOCAB_FILE):
    with open(VOCAB_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            word = line.strip().lower()
            if word:
                ENGLISH_VOCAB.add(word)

# V4 Mutation Patterns
# Catches Addr€ssl, I{ahe, but ignores U/s, S/o, hyphens, and apostrophes
MUTATED_SYMBOL_PATTERN = re.compile(r'[a-zA-Z]+[{€$£¥©®™~|\[\]\\]+[a-zA-Z]+')
# Catches addra3r (lowercase letters interrupted by digits), ignores RC1232026A0008, 120-B
MUTATED_DIGIT_PATTERN = re.compile(r'^[a-z]+[0-9]+[a-z]+$')

def validate_file_signature(file_path: str) -> str:
    """Validates file format using magic bytes. Protects API from spoofed extensions."""
    try:
        with open(file_path, 'rb') as f:
            header = f.read(12)
    except Exception:
        return 'unknown'
        
    if header.startswith(b'%PDF'): return 'application/pdf'
    if header.startswith(b'\xff\xd8\xff'): return 'image/jpeg'
    if header.startswith(b'\x89PNG\r\n\x1a\n'): return 'image/png'
    if header.startswith(b'II*\x00') or header.startswith(b'MM\x00*'): return 'image/tiff' 
    if header.startswith(b'II+\x00') or header.startswith(b'MM\x00+'): return 'image/tiff' 
    if header.startswith(b'BM'): return 'image/bmp'
    if header.startswith(b'RIFF') and header[8:12] == b'WEBP': return 'image/webp'
    return 'unknown'

def get_edits1(word: str) -> Set[str]:
    """
    Highly optimized Edit Distance 1 generator.
    Generates deletes, transposes, replaces, and inserts.
    """
    letters = 'abcdefghijklmnopqrstuvwxyz'
    splits = [(word[:i], word[i:]) for i in range(len(word) + 1)]
    deletes = [L + R[1:] for L, R in splits if R]
    transposes = [L + R[1] + R[0] + R[2:] for L, R in splits if len(R) > 1]
    replaces = [L + c + R[1:] for L, R in splits if R for c in letters]
    inserts = [L + c + R for L, R in splits for c in letters]
    return set(deletes + transposes + replaces + inserts)

def assess_text_quality(text: str) -> Dict[str, Any]:
    """
    V4 Multi-signal PDF Text Layer Assessor.
    Zero-OCR, Zero-Rendering. Classifies into reliable, suspicious, or no_text.
    """
    if not text or not text.strip():
        return {
            "text_layer_status": "no_text_layer", 
            "recommended_processing": "image_visual_analysis",
            "text_length": 0,
            "reason": "Empty or whitespace only",
            "quality_signals": {}
        }

    text_strip = text.strip()
    text_length = len(text_strip)
    
    if text_length < 15:
        return {
            "text_layer_status": "no_text_layer", 
            "recommended_processing": "image_visual_analysis",
            "text_length": text_length,
            "reason": f"Text layer too sparse ({text_length} chars)",
            "quality_signals": {"text_length": text_length}
        }

    total_chars = len(text)
    signals = {"text_length": text_length}
    suspicion_score = 0
    
    # 1. Script Composition Detection (Indic Safety Check)
    latin_chars = 0
    indic_chars = 0
    
    for c in text:
        code = ord(c)
        if 0x0000 <= code <= 0x024F and c.isalpha():
            latin_chars += 1
        elif 0x0900 <= code <= 0x0D7F: # Covers Devanagari through Malayalam
            indic_chars += 1
            
    is_indic_dominant = indic_chars > (latin_chars * 0.4)
    signals["is_indic_dominant"] = is_indic_dominant

    # 2. Structural Signals
    replacement_chars = text.count('\ufffd')
    rep_ratio = replacement_chars / total_chars
    signals["replacement_char_ratio"] = round(rep_ratio, 4)
    if rep_ratio > 0.05: suspicion_score += 2
    elif rep_ratio > 0.01: suspicion_score += 1

    alnum_chars = sum(1 for c in text if c.isalnum())
    whitespace_chars = sum(1 for c in text if c.isspace())
    non_ws_chars = total_chars - whitespace_chars
    alnum_ratio = alnum_chars / non_ws_chars if non_ws_chars > 0 else 0
    signals["alnum_ratio"] = round(alnum_ratio, 4)
    if alnum_ratio < 0.60: suspicion_score += 1 

    # 3. Lexical and Near-Word Signal Generation (V4 Eligible Denominator)
    tokens = text.split()
    mutated_tokens = 0
    eligible_alpha_tokens = 0
    near_corrupt_tokens = 0
    
    for token in tokens:
        # Check for explicit systemic mutations
        if MUTATED_SYMBOL_PATTERN.search(token) or MUTATED_DIGIT_PATTERN.match(token):
            mutated_tokens += 1
            
        # V4 Near-Word Detection: Only execute if Latin-dominant and Vocab exists
        if not is_indic_dominant and ENGLISH_VOCAB:
            clean_token = re.sub(r'[^a-zA-Z]', '', token)
            
            # ELIGIBILITY FILTER: Must be > 4 chars (avoids U/s, No.) and NOT ALL CAPS (avoids IDs like RC123, NIA)
            if len(clean_token) > 4 and not clean_token.isupper():
                eligible_alpha_tokens += 1
                lower_token = clean_token.lower()
                
                if lower_token not in ENGLISH_VOCAB:
                    # Check Edit Distance 1 for near-miss corruption (e.g. offehce)
                    edits = get_edits1(lower_token)
                    if edits.intersection(ENGLISH_VOCAB):
                        near_corrupt_tokens += 1

        # Apply V4 Structural Mutations Scoring
    mut_ratio = mutated_tokens / len(tokens) if tokens else 0
    signals["mutated_token_ratio"] = round(mut_ratio, 4)

    if mut_ratio >= 0.02:
        suspicion_score += 2

    # Apply V4 Near-Word Lexical Scoring
    if not is_indic_dominant:
        near_corrupt_ratio = (
            near_corrupt_tokens / eligible_alpha_tokens
            if eligible_alpha_tokens > 0
            else 0
        )

        signals["eligible_alpha_tokens"] = eligible_alpha_tokens
        signals["near_corrupt_tokens"] = near_corrupt_tokens
        signals["near_corrupt_ratio"] = round(
            near_corrupt_ratio,
            4
        )

        if near_corrupt_ratio >= 0.05 and near_corrupt_tokens >= 3:
            suspicion_score += 2

    signals["suspicion_score"] = suspicion_score

    # V4 Final Decision
    if suspicion_score >= 2:
        return {
            "text_layer_status": "suspicious_text_layer",
            "recommended_processing": "image_visual_analysis",
            "text_length": text_length,
            "reason": f"Failed multi-signal heuristics (score: {suspicion_score})",
            "quality_signals": signals
        }

    return {
        "text_layer_status": "reliable_text_layer",
        "recommended_processing": "direct_extract_with_visual_verification",
        "text_length": text_length,
        "reason": "Embedded text passed verification",
        "quality_signals": signals
    }

def analyze_pdf(file_path: str) -> List[Dict[str, Any]]:
    pages_assessment = []
    with pymupdf.open(file_path) as doc:
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            text = page.get_text("text")
            assessment = assess_text_quality(text)
            assessment["page"] = page_num + 1
            pages_assessment.append(assessment)
            page = None 
    return pages_assessment

def analyze_image(file_path: str) -> List[Dict[str, Any]]:
    return [{
        "page": 1,
        "text_layer_status": "no_text_layer",
        "recommended_processing": "image_visual_analysis",
        "text_length": 0,
        "reason": "Direct image file upload",
        "quality_signals": {}
    }]

def route_document(file_path: str) -> Dict[str, Any]:
    actual_mime = validate_file_signature(file_path)
    if actual_mime == 'unknown':
        raise ValueError("Unsupported or invalid file signature.")
        
    if actual_mime == "application/pdf":
        pages = analyze_pdf(file_path)
    else:
        pages = analyze_image(file_path)
        
    return {
        "document_type": actual_mime,
        "total_pages": len(pages),
        "pages": pages
    }
