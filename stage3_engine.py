import os
import re
import csv
import time
import copy
import shutil
import tempfile
import subprocess
import pymupdf
from typing import List, Dict, Any, Tuple, Optional, Set

class LanguageDetector:
    """
    Detects scripts from embedded text as a primary signal.
    Includes a Bilingual FIR Heuristic: automatically injecting English (if installed)
    when an Indian script is detected, to accurately process real-world multi-script forms.
    """
    def __init__(self):
        self.installed_langs = self._get_installed_langs()
        self.script_blocks = {
            "Latin": {"range": (0x0000, 0x007F), "langs": ["eng"]},
            "Devanagari": {"range": (0x0900, 0x097F), "langs": ["hin", "mar"]},
            "Bengali": {"range": (0x0980, 0x09FF), "langs": ["ben"]},
            "Gurmukhi": {"range": (0x0A00, 0x0A7F), "langs": ["pan"]},
            "Gujarati": {"range": (0x0A80, 0x0AFF), "langs": ["guj"]},
            "Odia": {"range": (0x0B00, 0x0B7F), "langs": ["ori"]},
            "Tamil": {"range": (0x0B80, 0x0BFF), "langs": ["tam"]},
            "Telugu": {"range": (0x0C00, 0x0C7F), "langs": ["tel"]},
            "Kannada": {"range": (0x0C80, 0x0CFF), "langs": ["kan"]},
            "Malayalam": {"range": (0x0D00, 0x0D7F), "langs": ["mal"]},
            "Arabic": {"range": (0x0600, 0x06FF), "langs": ["urd", "ara"]}
        }

    def _get_installed_langs(self) -> Set[str]:
        try:
            result = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True, check=True)
            return set(line.strip() for line in result.stdout.split('\n') if line.strip() and not line.startswith("List of"))
        except Exception:
            return set()
            
    def _resolve_tess_langs(self, script_names: List[str]) -> List[str]:
        valid_langs = []
        for script in script_names:
            if script in self.script_blocks:
                for potential_lang in self.script_blocks[script]["langs"]:
                    if potential_lang in self.installed_langs and potential_lang not in valid_langs:
                        valid_langs.append(potential_lang)
        return valid_langs

    def _probe_stitched_image(self, image_path: str, regions: List[Dict[str, Any]]) -> List[str]:
        try:
            probe_langs = [l for l in self.installed_langs if l != "osd"]
            if not probe_langs: return []
            lang_str = "+".join(probe_langs)

            # Use image_path directly safely if temp_stitch isn't generated
            res = subprocess.run(
                ["tesseract", image_path, "-", "-l", lang_str, "--psm", "6"],
                capture_output=True,
                text=True,
                timeout=30
            )
            text = res.stdout
            
            counts = {script: 0 for script in self.script_blocks}
            total_counted = 0
            for char in text:
                code = ord(char)
                if not char.isalpha() and code <= 0x007F:
                    continue
                for script, data in self.script_blocks.items():
                    if data["range"][0] <= code <= data["range"][1]:
                        counts[script] += 1
                        total_counted += 1
                        break

            if total_counted > 0:
                candidates = [s for s, c in counts.items() if (c / total_counted) > 0.05]
                return candidates
        except Exception:
            pass
        return []

    def detect(self, embedded_text: str, image_path: Optional[str] = None, use_osd: bool = False, regions: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        # 1. Primary: Unicode block inspection
        if embedded_text and embedded_text.strip():
            counts = {script: 0 for script in self.script_blocks}
            total_counted = 0
            
            for char in embedded_text:
                code = ord(char)
                if not char.isalpha() and code <= 0x007F:
                    continue
                for script, data in self.script_blocks.items():
                    if data["range"][0] <= code <= data["range"][1]:
                        counts[script] += 1
                        total_counted += 1
                        break

            if total_counted > 0:
                candidates = [s for s, c in counts.items() if (c / total_counted) > 0.05]
                valid_langs = self._resolve_tess_langs(candidates)
                
                if valid_langs:
                    # BILINGUAL HEURISTIC: Inject English if Indic script found
                    has_indic = any(c != "Latin" for c in candidates)
                    if has_indic and "eng" in self.installed_langs and "eng" not in valid_langs:
                        valid_langs.insert(0, "eng")
                        if "Latin" not in candidates:
                            candidates.insert(0, "Latin")
                            
                    return {
                        "script_candidates": candidates,
                        "selected_script": "+".join(candidates),
                        "tesseract_lang": "+".join(valid_langs),
                        "ocr_supported": True,
                        "detection_method": "unicode_blocks",
                        "detection_confidence": "medium"
                    }
                else:
                    fallback_lang = "eng" if "eng" in self.installed_langs else None
                    return {
                        "script_candidates": candidates,
                        "selected_script": "+".join(candidates),
                        "tesseract_lang": fallback_lang,
                        "ocr_supported": False,
                        "detection_method": "unicode_blocks",
                        "detection_confidence": "medium"
                    }

        # 2. Genuine Tesseract OSD (Opt-in)
        if use_osd and image_path and os.path.exists(image_path):
            try:
                osd_res = subprocess.run(
                    ["tesseract", image_path, "-", "--psm", "0"],
                    capture_output=True, text=True, timeout=10
                )
                script_match = re.search(r"Script:\s*([A-Za-z]+)", osd_res.stdout)
                
                if script_match:
                    detected_script = script_match.group(1)
                    conf_match = re.search(r"Script confidence:\s*([0-9.]+)", osd_res.stdout)
                    conf_val = float(conf_match.group(1)) if conf_match else 0.0
                    
                    probed_scripts = [detected_script]
                    valid_langs = self._resolve_tess_langs(probed_scripts)
                    
                    if valid_langs:
                        # BILINGUAL HEURISTIC FOR OSD
                        if detected_script != "Latin" and "eng" in self.installed_langs and "eng" not in valid_langs:
                            valid_langs.insert(0, "eng")
                            if "Latin" not in probed_scripts:
                                probed_scripts.insert(0, "Latin")
                                
                        return {
                            "script_candidates": probed_scripts,
                            "selected_script": "+".join(probed_scripts),
                            "tesseract_lang": "+".join(valid_langs),
                            "ocr_supported": True,
                            "detection_method": "tesseract_osd",
                            "detection_confidence": "high" if conf_val > 2.0 else "low"
                        }
            except Exception:
                pass 

        # 3. Tertiary: Stitched Image Probe (Fallback if OSD fails/missing and regions exist)
        if use_osd and image_path and regions and os.path.exists(image_path):
            probed_scripts = self._probe_stitched_image(image_path, regions)
            if probed_scripts:
                valid_langs = self._resolve_tess_langs(probed_scripts)
                if valid_langs:
                    if any(s != "Latin" for s in probed_scripts) and "eng" in self.installed_langs and "eng" not in valid_langs:
                        valid_langs.insert(0, "eng")
                        if "Latin" not in probed_scripts:
                            probed_scripts.insert(0, "Latin")
                            
                    return {
                        "script_candidates": probed_scripts,
                        "selected_script": "+".join(probed_scripts),
                        "tesseract_lang": "+".join(valid_langs),
                        "ocr_supported": True,
                        "detection_method": "stitched_unicode_probe",
                        "detection_confidence": "high"
                    }

        # 4. Fast Safe Fallback
        fallback_lang = "eng" if "eng" in self.installed_langs else None
        return {
            "script_candidates": ["unknown"],
            "selected_script": "unknown",
            "tesseract_lang": fallback_lang,
            "ocr_supported": fallback_lang is not None,
            "detection_method": "fallback",
            "detection_confidence": "low"
        }

class ReadingOrderResolver:
    @staticmethod
    def resolve(regions: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], str]:
        if not regions:
            return [], "high"

        safe_regions = copy.deepcopy(regions)
        sorted_by_y = sorted(safe_regions, key=lambda r: r['y'])
        
        lines = []
        current_line = [sorted_by_y[0]]
        
        for region in sorted_by_y[1:]:
            last_region = current_line[-1]
            
            r1_top, r1_bottom = last_region['y'], last_region['y'] + last_region['height']
            r2_top, r2_bottom = region['y'], region['y'] + region['height']
            
            overlap_top = max(r1_top, r2_top)
            overlap_bottom = min(r1_bottom, r2_bottom)
            overlap_height = max(0, overlap_bottom - overlap_top)
            
            min_height = min(last_region['height'], region['height'])
            y_diff = abs(region['y'] - last_region['y'])
            
            if (min_height > 0 and overlap_height / min_height > 0.3) or (y_diff < 15):
                current_line.append(region)
            else:
                lines.append(current_line)
                current_line = [region]
                
        if current_line:
            lines.append(current_line)
            
        ordered_regions = []
        order_index = 1
        line_id = 1
        ordering_confidence = "high"
        
        for line in lines:
            line.sort(key=lambda r: r['x'])
            column_id = 1
            last_x_end = -1
            
            for region in line:
                if last_x_end != -1 and (region['x'] - last_x_end) > 40:
                    column_id += 1
                
                region['reading_order'] = order_index
                region['line_id'] = line_id
                region['column_id'] = column_id
                ordered_regions.append(region)
                
                last_x_end = region['x'] + region['width']
                order_index += 1
                
                if column_id > 3: 
                    ordering_confidence = "low"
            line_id += 1
                
        return ordered_regions, ordering_confidence

class ContentClassifier:
    @staticmethod
    def classify(region: Dict[str, Any]) -> Dict[str, str]:
        w = region.get('width', 0)
        h = region.get('height', 0)
        kind = region.get('region_kind', 'unknown_candidate')
        
        if w <= 0 or h <= 0:
            return {"content_type": "unknown", "classification_confidence": "high", "classification_reason": "Zero dimensions"}

        aspect_ratio = w / float(h)

        if aspect_ratio > 15 or aspect_ratio < 0.05:
            return {"content_type": "non_text", "classification_confidence": "high", "classification_reason": "Extreme aspect ratio (line/rule)"}

        if kind == "text_candidate":
            return {"content_type": "printed_text", "classification_confidence": "medium", "classification_reason": "Stage 2B text candidate"}
            
        if w > 400 and h > 250 and kind == "unknown_candidate":
            return {"content_type": "table", "classification_confidence": "low", "classification_reason": "Massive structural block"}

        if kind == "handwriting_candidate":
            return {"content_type": "handwriting", "classification_confidence": "low", "classification_reason": "Explicit structural candidate"}

        return {"content_type": "unknown", "classification_confidence": "low", "classification_reason": "Ambiguous geometry fallback"}

class OCRBackend:
    def process(self, image_path: str, lang_code: str) -> Dict[str, Any]:
        raise NotImplementedError

class HTRBackend:
    def process(self, image_path: str) -> Dict[str, Any]:
        raise NotImplementedError

class TranslationEngine:
    def translate(self, text: str, source_lang: str) -> Dict[str, Any]:
        if not text.strip():
            return {
                "english_translation": "",
                "translation_engine": "none",
                "translation_successful": True,
                "capability_state": "no_text_provided"
            }
            
        return {
            "english_translation": "",
            "translation_engine": "offline_nmt_stub",
            "translation_successful": False,
            "error": "Offline Neural Machine Translation models exceed Raspberry Pi 3B (1GB) constraints.",
            "capability_state": "unsupported_hardware"
        }

class TableExtractionBackend(OCRBackend):
    def process(self, image_path: str, lang_code: Optional[str]) -> Dict[str, Any]:
        if not lang_code:
            return {"success": False, "table_data": [], "processing_engine": "tesseract_table_cluster", "error": "Language pack not installed", "capability_state": "unsupported"}
            
        with tempfile.NamedTemporaryFile(suffix="", delete=True) as temp_out:
            base_out = temp_out.name
            tsv_path = base_out + ".tsv"
            engine_name = f"tesseract_table_cluster_{lang_code}"
            
            try:
                subprocess.run(
                    ["tesseract", image_path, base_out, "-l", lang_code, "tsv"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    timeout=20,
                    check=True
                )
                
                if not os.path.exists(tsv_path):
                    return {"success": False, "table_data": [], "processing_engine": engine_name, "error": "Missing TSV output"}
                    
                words = []
                with open(tsv_path, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f, delimiter='\t')
                    for row in reader:
                        conf_str = row.get('conf', '-1')
                        try:
                            conf = float(conf_str)
                        except ValueError:
                            conf = -1.0
                            
                        text_val = row.get('text', '').strip()
                        if conf >= 0 and text_val:
                            words.append({
                                'text': text_val,
                                'left': int(row.get('left', 0)),
                                'top': int(row.get('top', 0)),
                                'height': int(row.get('height', 0))
                            })
                            
                words.sort(key=lambda w: w['top'])
                rows = []
                current_row = []
                current_row_top = -1
                
                for w in words:
                    if not current_row:
                        current_row.append(w)
                        current_row_top = w['top']
                    else:
                        if abs(w['top'] - current_row_top) < max(10, w['height'] * 0.5):
                            current_row.append(w)
                        else:
                            rows.append(current_row)
                            current_row = [w]
                            current_row_top = w['top']
                            
                if current_row:
                    rows.append(current_row)
                    
                table_data = []
                for row in rows:
                    row.sort(key=lambda w: w['left'])
                    table_data.append([w['text'] for w in row])
                    
                table_text = "\n".join(["\t".join(r) for r in table_data])
                
                return {
                    "success": True,
                    "text": table_text,
                    "table_data": table_data,
                    "confidence": None,
                    "processing_engine": engine_name,
                    "error": None
                }
                
            except subprocess.TimeoutExpired:
                return {"success": False, "table_data": [], "processing_engine": engine_name, "error": "subprocess timeout"}
            except subprocess.CalledProcessError:
                return {"success": False, "table_data": [], "processing_engine": engine_name, "error": "Tesseract execution failed"}
            except FileNotFoundError:
                return {"success": False, "table_data": [], "processing_engine": engine_name, "error": "Tesseract executable missing"}
            finally:
                if os.path.exists(tsv_path):
                    os.remove(tsv_path)

class TesseractOCRBackend(OCRBackend):
    def _execute_tesseract(self, image_path: str, lang_code: str) -> Dict[str, Any]:
        with tempfile.NamedTemporaryFile(suffix="", delete=True) as temp_out:
            base_out = temp_out.name
            tsv_path = base_out + ".tsv"
            
            try:
                subprocess.run(
                    ["tesseract", image_path, base_out, "-l", lang_code, "tsv"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    timeout=15,
                    check=True
                )
                
                if not os.path.exists(tsv_path):
                    return {"success": False, "text": "", "confidence": None, "error": "Missing TSV output"}
                    
                text_parts = []
                conf_sum = 0.0
                conf_count = 0
                
                with open(tsv_path, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f, delimiter='\t')
                    for row in reader:
                        conf_str = row.get('conf', '-1')
                        try:
                            conf = float(conf_str)
                        except ValueError:
                            conf = -1.0
                            
                        text_val = row.get('text', '').strip()
                        if conf >= 0 and text_val:
                            text_parts.append(text_val)
                            conf_sum += conf
                            conf_count += 1
                            
                extracted_text = " ".join(text_parts).strip()
                avg_conf = round(conf_sum / conf_count, 2) if conf_count > 0 else None
                
                return {"success": True, "text": extracted_text, "confidence": avg_conf, "error": None}
                
            except subprocess.TimeoutExpired:
                return {"success": False, "text": "", "confidence": None, "error": "subprocess timeout"}
            except subprocess.CalledProcessError:
                return {"success": False, "text": "", "confidence": None, "error": "Tesseract execution failed"}
            except FileNotFoundError:
                return {"success": False, "text": "", "confidence": None, "error": "Tesseract executable missing"}
            finally:
                if os.path.exists(tsv_path):
                    os.remove(tsv_path)

    def process(self, image_path: str, lang_code: Optional[str]) -> Dict[str, Any]:
        if not lang_code:
            return {"success": False, "text": "", "confidence": None, "processing_engine": "tesseract", "error": "Language pack not installed", "preprocessing_applied": False}
            
        engine_name = f"tesseract_{lang_code}"
        
        # 1. Primary Pass (Original Crop)
        res_primary = self._execute_tesseract(image_path, lang_code)
        res_primary["processing_engine"] = engine_name
        res_primary["preprocessing_applied"] = False
        
        if not res_primary["success"]:
            return res_primary
            
        conf = res_primary.get("confidence")
        text = res_primary.get("text", "").strip()
        
        # 2. Fast Return
        if text and conf is not None and conf >= 65.0:
            return res_primary
            
        # 3. Adaptive Fallback
        temp_preprocessed = None
        try:
            fd_pre, temp_preprocessed = tempfile.mkstemp(suffix="_prep.png")
            os.close(fd_pre)
            
            try:
                from PIL import Image, ImageEnhance
                with Image.open(image_path) as img:
                    gray = img.convert('L')
                    enhancer = ImageEnhance.Contrast(gray)
                    contrasted = enhancer.enhance(2.0)
                    res_filter = getattr(Image, 'Resampling', Image)
                    upscaled = contrasted.resize((img.width * 2, img.height * 2), res_filter.LANCZOS)
                    upscaled.save(temp_preprocessed)
            except Exception:
                return res_primary
                
            res_fallback = self._execute_tesseract(temp_preprocessed, lang_code)
            res_fallback["processing_engine"] = engine_name
            
            if res_fallback["success"]:
                fb_text = res_fallback.get("text", "").strip()
                fb_conf = res_fallback.get("confidence")
                
                fb_conf_val = fb_conf if fb_conf is not None else 0.0
                pr_conf_val = conf if conf is not None else 0.0
                
                if (not text and fb_text) or (fb_text and fb_conf_val > pr_conf_val):
                    res_fallback["preprocessing_applied"] = True
                    return res_fallback
                    
        except Exception:
            pass 
        finally:
            if temp_preprocessed and os.path.exists(temp_preprocessed):
                os.remove(temp_preprocessed)
                
        return res_primary

class LocalHTRBackend(HTRBackend):
    def process(self, image_path: str) -> Dict[str, Any]:
        return {
            "success": False,
            "text": "",
            "confidence": None,
            "processing_engine": "local_htr_stub",
            "error": "Offline HTR models exceed Raspberry Pi 3B (1GB) constraints.",
            "capability_state": "unsupported_hardware"
        }

def process_page_regions(
    image_path: str, 
    regions: List[Dict[str, Any]], 
    evidence_dir: str,
    page_num: int = 1,
    embedded_text: str = "",
    use_osd: bool = False
) -> Dict[str, Any]:
    
    metrics = {
        "source_regions": len(regions),
        "ocr_blocks": 0,
        "ocr_invocations": 0,
        "htr_stub_calls": 0,
        "evidence_retained": 0
    }

    if not os.path.exists(evidence_dir):
        os.makedirs(evidence_dir, exist_ok=True)

    try:
        doc = pymupdf.open(image_path)
        page = doc[0]
        page_w, page_h = page.rect.width, page.rect.height
    except Exception as e:
        return {
            "success": False, "page": page_num, "error": f"Failed to load image: {str(e)}", 
            "regions": [], "reconstructed_text": "", "ordering_confidence": "low", "metrics": metrics
        }

    try:
        ordered_regions, ordering_conf = ReadingOrderResolver.resolve(regions)
        
        lang_info = LanguageDetector().detect(embedded_text, image_path, use_osd=use_osd, regions=regions)
        
        if not use_osd and (
            lang_info["detection_method"] == "fallback"
            or (lang_info["detection_method"] == "unicode_blocks" and lang_info["selected_script"] == "Latin")
        ):
            oi = LanguageDetector().detect("", image_path, use_osd=True, regions=regions)
            if oi["detection_method"] != "fallback":
                lang_info = oi
            
        ocr_backend = TesseractOCRBackend()
        htr_backend = LocalHTRBackend()
        table_backend = TableExtractionBackend()
        translation_engine = TranslationEngine()
        
        valid_classified_regions = []
        for r in ordered_regions:
            c_info = ContentClassifier.classify(r)
            x, y = r.get('x', -1), r.get('y', -1)
            w, h = r.get('width', 0), r.get('height', 0)
            
            result = {
                "region_id": r.get('region_id', 0),
                "reading_order": r.get('reading_order', 0),
                "line_id": r.get('line_id', 0),
                "column_id": r.get('column_id', 0),
                "content_type": c_info['content_type'],
                "classification_confidence": c_info['classification_confidence'],
                "classification_reason": c_info['classification_reason'],
                "script_candidates": lang_info["script_candidates"],
                "selected_script": lang_info["selected_script"],
                "tesseract_lang": lang_info["tesseract_lang"],
                "x": x, "y": y, "width": w, "height": h,
                "text": "",
                "table_data": [],
                "confidence": None,
                "processing_engine": "none",
                "success": False,
                "error": None,
                "evidence_required": False,
                "evidence_path": None,
                "requires_downstream_text_extraction": False,
                "processing_time": 0.0,
                "preprocessing_applied": False,
                "merged_into": None
            }

            if x < 0 or y < 0 or w <= 0 or h <= 0 or (x + w) > page_w or (y + h) > page_h:
                result["success"] = False
                result["error"] = "Invalid coordinates"
                
            valid_classified_regions.append(result)

        execution_blocks = []
        current_ocr_block = []
        
        for r in valid_classified_regions:
            if not r["success"] and r["error"] == "Invalid coordinates":
                execution_blocks.append({"type": "skip", "regions": [r]})
                continue
                
            if r["content_type"] != "printed_text":
                if current_ocr_block:
                    execution_blocks.append({"type": "ocr_block", "regions": current_ocr_block})
                    current_ocr_block = []
                execution_blocks.append({"type": "individual", "regions": [r]})
            else:
                if not current_ocr_block:
                    current_ocr_block.append(r)
                else:
                    last_r = current_ocr_block[-1]
                    gap = r['x'] - (last_r['x'] + last_r['width'])
                    if (r['line_id'] == last_r['line_id'] and 
                        r['column_id'] == last_r['column_id'] and 
                        r['tesseract_lang'] == last_r['tesseract_lang'] and 
                        -20 <= gap <= 100):
                        current_ocr_block.append(r)
                    else:
                        execution_blocks.append({"type": "ocr_block", "regions": current_ocr_block})
                        current_ocr_block = [r]
                        
        if current_ocr_block:
            execution_blocks.append({"type": "ocr_block", "regions": current_ocr_block})

        structured_regions = []
        for block in execution_blocks:
            start_time = time.time()
            b_type = block["type"]
            b_regions = block["regions"]
            
            if b_type == "skip":
                b_regions[0]["processing_time"] = round(time.time() - start_time, 3)
                structured_regions.append(b_regions[0])
                continue
                
            if b_type == "ocr_block":
                metrics["ocr_blocks"] += 1
                metrics["ocr_invocations"] += 1
                
                min_x = min(r['x'] for r in b_regions)
                min_y = min(r['y'] for r in b_regions)
                max_x = max(r['x'] + r['width'] for r in b_regions)
                max_y = max(r['y'] + r['height'] for r in b_regions)
                
                rect = pymupdf.Rect(min_x, min_y, max_x, max_y)
                fd, temp_crop = tempfile.mkstemp(suffix=".png")
                os.close(fd)
                
                try:
                    pix = page.get_pixmap(clip=rect)
                    pix.save(temp_crop)
                    del pix 
                    
                    res = ocr_backend.process(temp_crop, lang_info["tesseract_lang"])
                    
                    primary = b_regions[0]
                    primary.update(res)
                    primary["processing_time"] = round(time.time() - start_time, 3)
                    structured_regions.append(primary)
                    
                    for other in b_regions[1:]:
                        other["success"] = res["success"]
                        other["processing_engine"] = "merged_into_ocr_block"
                        other["merged_into"] = primary["region_id"]
                        other["processing_time"] = 0.0
                        other["preprocessing_applied"] = res.get("preprocessing_applied", False)
                        other["text"] = "" 
                        structured_regions.append(other)
                        
                except Exception as e:
                    for r in b_regions:
                        r["error"] = f"Block OCR exception: {str(e)}"
                        r["processing_time"] = round(time.time() - start_time, 3)
                        structured_regions.append(r)
                finally:
                    if os.path.exists(temp_crop): os.remove(temp_crop)
                    
            elif b_type == "individual":
                r = b_regions[0]
                rect = pymupdf.Rect(r['x'], r['y'], r['x'] + r['width'], r['y'] + r['height'])
                fd, temp_crop = tempfile.mkstemp(suffix=".png")
                os.close(fd)
                
                requires_evidence = False
                try:
                    pix = page.get_pixmap(clip=rect)
                    pix.save(temp_crop)
                    del pix 
                    
                    c_type = r['content_type']
                    if c_type == "table":
                        metrics["ocr_invocations"] += 1
                        res = table_backend.process(temp_crop, lang_info["tesseract_lang"])
                        r.update(res)
                        r["requires_downstream_text_extraction"] = False
                        requires_evidence = True
                    elif c_type == "handwriting":
                        metrics["htr_stub_calls"] += 1
                        res = htr_backend.process(temp_crop)
                        r.update(res)
                        requires_evidence = True
                    else: 
                        r["success"] = True
                        r["processing_engine"] = "evidence_preservation"
                        requires_evidence = True
                except Exception as e:
                    r["error"] = f"Crop exception: {str(e)}"
                finally:
                    if requires_evidence:
                        base_name = f"page_{page_num}_region_{r['region_id']}_{r['content_type']}"
                        perm_path = os.path.join(evidence_dir, f"{base_name}.png")
                        
                        if os.path.exists(perm_path):
                            counter = 1
                            while os.path.exists(os.path.join(evidence_dir, f"{base_name}_{counter}.png")):
                                counter += 1
                            perm_path = os.path.join(evidence_dir, f"{base_name}_{counter}.png")
                            
                        try:
                            shutil.move(temp_crop, perm_path)
                            r["evidence_required"] = True
                            r["evidence_path"] = perm_path
                            metrics["evidence_retained"] += 1
                        except Exception:
                            r["success"] = False
                            r["error"] = "Failed to preserve evidence"
                            r["evidence_required"] = True
                            if os.path.exists(temp_crop): os.remove(temp_crop)
                    else:
                        if os.path.exists(temp_crop):
                            os.remove(temp_crop)

                r["processing_time"] = round(time.time() - start_time, 3)
                structured_regions.append(r)

        for r in structured_regions:
            if "merged_into" in r:
                del r["merged_into"]

        reconstructed = []
        current_line_id = -1
        line_parts = []
        
        for r in structured_regions:
            if r.get("success") and r.get("text"):
                if r["line_id"] != current_line_id:
                    if line_parts: reconstructed.append(" ".join(line_parts))
                    line_parts = [r["text"]]
                    current_line_id = r["line_id"]
                else:
                    line_parts.append(r["text"])
                    
        if line_parts:
            reconstructed.append(" ".join(line_parts))

        source_text = "\n".join(reconstructed)
        
        trans_res = translation_engine.translate(source_text, lang_info["selected_script"])

        return {
            "success": True,
            "page": page_num,
            "ordering_confidence": ordering_conf,
            "reconstructed_text": source_text, 
            "source_text": source_text,
            "source_language_candidates": lang_info["script_candidates"],
            "selected_script": lang_info["selected_script"],
            "tesseract_lang": lang_info["tesseract_lang"], 
            "ocr_supported": lang_info["ocr_supported"],
            "english_translation": trans_res["english_translation"],
            "translation_capability": trans_res["capability_state"],
            "regions": structured_regions,
            "metrics": metrics
        }
        
    finally:
        doc.close()
