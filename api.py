import os
import time
import tempfile
import pymupdf
from typing import Dict, Any
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse, Response

from processor import route_document
from renderer import render_pdf_page
from visual_analyzer import analyze_page_image
from stage3_engine import process_page_regions

app = FastAPI(
    title="Offline Multilingual FIR Processor",
    description="End-to-end production orchestration for arbitrary Indian FIR documents (Raspberry Pi 3B).",
    version="4.1.0"
)

MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024  # 25 MB safety limit for 1GB RAM Pi
EVIDENCE_DIR = os.path.abspath("./api_evidence_crops")

@app.on_event("startup")
async def startup_event():
    os.makedirs(EVIDENCE_DIR, exist_ok=True)

@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    html_content = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Pi FIR Text Extractor</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background: #f4f6f9; color: #333; margin: 0; padding: 20px; }
        .container { max-width: 800px; margin: 40px auto; background: #fff; padding: 30px; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.05); }
        h1 { font-size: 24px; margin-top: 0; color: #111; }
        p { color: #666; font-size: 14px; }
        .upload-box { border: 2px dashed #cbd5e1; padding: 30px; text-align: center; border-radius: 6px; background: #fafafa; margin: 20px 0; cursor: pointer; transition: border-color 0.2s, background 0.2s; position: relative; }
        .upload-box.dragover { border-color: #3b82f6; background: #eff6ff; }
        /* Keep file input functional in DOM without display:none bugs */
        .visually-hidden-input { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); border: 0; }
        button { background: #3b82f6; color: white; border: none; padding: 12px 20px; font-size: 16px; border-radius: 6px; cursor: pointer; width: 100%; font-weight: 600; transition: background 0.2s; }
        button:hover { background: #2563eb; }
        button:disabled { background: #93c5fd; cursor: not-allowed; }
        .btn-copy { width: auto; font-size: 13px; padding: 8px 16px; background: #10b981; margin-bottom: 12px; }
        .btn-copy:hover { background: #059669; }
        .results-header { display: flex; justify-content: space-between; align-items: flex-end; margin-bottom: 10px; }
        #loading { display: none; text-align: center; margin: 20px 0; color: #3b82f6; font-weight: 500; }
        .results { margin-top: 30px; }
        .page-card { background: #fff; border: 1px solid #e2e8f0; border-radius: 6px; padding: 20px; margin-bottom: 20px; }
        .page-header { font-weight: bold; color: #475569; margin-bottom: 10px; border-bottom: 1px solid #f1f5f9; padding-bottom: 5px; display: flex; justify-content: space-between; }
        pre { background: #f8fafc; padding: 15px; border-radius: 4px; white-space: pre-wrap; word-wrap: break-word; font-family: monospace; font-size: 13px; max-height: 300px; overflow-y: auto; border: 1px solid #e2e8f0; margin: 0; }
        .badge { display: inline-block; background: #e0f2fe; color: #0369a1; padding: 4px 10px; border-radius: 12px; font-size: 12px; font-weight: 600; margin-top: 8px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Raspberry Pi FIR Extractor</h1>
        <p>Upload an Indian FIR PDF document to execute automated visual analysis, multi-script layout resolution, and localized text extraction.</p>
        
        <form id="uploadForm">
            <div class="upload-box" id="dropBox">
                <p id="fileNameDisplay"><strong>Click to select FIR PDF</strong> or drag and drop here</p>
                <input type="file" id="fileInput" class="visually-hidden-input" accept="application/pdf">
                <div id="fileBadgeContainer"></div>
            </div>
            <button type="submit" id="submitBtn">Process Document</button>
        </form>

        <div id="loading">Processing document through Pi pipeline... Please wait (this may take up to a minute for scanned pages)...</div>
        <div class="results" id="resultsContainer"></div>
    </div>

    <script>
        let allExtractedText = "";
        let selectedFile = null;

        const fileInput = document.getElementById('fileInput');
        const dropBox = document.getElementById('dropBox');
        const fileNameDisplay = document.getElementById('fileNameDisplay');
        const fileBadgeContainer = document.getElementById('fileBadgeContainer');
        const uploadForm = document.getElementById('uploadForm');
        const submitBtn = document.getElementById('submitBtn');
        const loading = document.getElementById('loading');
        const resultsContainer = document.getElementById('resultsContainer');

        function setFile(file) {
            if (!file) return;
            selectedFile = file;
            fileNameDisplay.innerHTML = `Selected File: <strong>${file.name}</strong>`;
            const sizeMb = (file.size / (1024 * 1024)).toFixed(2);
            fileBadgeContainer.innerHTML = `<span class="badge">${sizeMb} MB | ${file.type || 'PDF'}</span>`;
        }

        // Direct click on drop zone opens file picker
        dropBox.addEventListener('click', () => {
            fileInput.click();
        });

        // Native file picker change handler
        fileInput.addEventListener('change', (e) => {
            if (e.target.files && e.target.files.length > 0) {
                setFile(e.target.files[0]);
            }
        });

        // Drag and drop handlers
        dropBox.addEventListener('dragover', (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropBox.classList.add('dragover');
        });

        dropBox.addEventListener('dragleave', (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropBox.classList.remove('dragover');
        });

        dropBox.addEventListener('drop', (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropBox.classList.remove('dragover');
            if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
                setFile(e.dataTransfer.files[0]);
            }
        });

        async function copyAllText(btn) {
            if (!allExtractedText) return;
            try {
                await navigator.clipboard.writeText(allExtractedText);
                const prev = btn.textContent;
                btn.textContent = "Copied!";
                btn.style.background = "#059669";
                setTimeout(() => {
                    btn.textContent = prev;
                    btn.style.background = "#10b981";
                }, 2000);
            } catch (err) {
                alert("Failed to copy: " + err);
            }
        }

        uploadForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            
            if (!selectedFile) {
                alert("Please click the box and select a PDF file first.");
                return;
            }

            const formData = new FormData();
            formData.append('file', selectedFile);

            submitBtn.disabled = true;
            loading.style.display = 'block';
            resultsContainer.innerHTML = '';
            allExtractedText = "";

            try {
                const response = await fetch('/process', {
                    method: 'POST',
                    body: formData
                });
                
                const data = await response.json();
                if (!response.ok) throw new Error(data.detail || data.error || 'Processing failed');

                allExtractedText = data.pages
                    .map(p => `--- Page ${p.page} ---\n` + (p.extracted_text || ''))
                    .join('\\n\\n');

                let html = `
                    <div class="results-header">
                        <div>
                            <h2>Results for: ${data.filename}</h2>
                            <p>Total Pages: ${data.total_pages} | Processing Time: ${data.processing_summary.total_processing_time}s</p>
                        </div>
                        <button type="button" class="btn-copy" onclick="copyAllText(this)">📋 Copy All Text</button>
                    </div>
                `;

                data.pages.forEach(p => {
                    html += `
                        <div class="page-card">
                            <div class="page-header">
                                <span>Page ${p.page}</span>
                                <span>Status: ${p.status}</span>
                            </div>
                            <pre>${p.extracted_text || '(No text extracted for this page)'}</pre>
                        </div>
                    `;
                });

                resultsContainer.innerHTML = html;
            } catch (err) {
                alert('Error: ' + err.message);
            } finally {
                submitBtn.disabled = false;
                loading.style.display = 'none';
            }
        });
    </script>
</body>
</html>"""
    return HTMLResponse(
        content=html_content,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"}
    )

@app.get("/health")
async def health_check():
    return JSONResponse(status_code=200, content={"status": "healthy"})

@app.post("/process")
async def process_document(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided.")

    fd, temp_path = tempfile.mkstemp(prefix="fir_upload_", suffix=".tmp")
    file_size = 0

    try:
        with os.fdopen(fd, "wb") as buffer:
            while chunk := await file.read(8192):
                file_size += len(chunk)
                if file_size > MAX_FILE_SIZE_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File exceeds maximum size of {MAX_FILE_SIZE_BYTES//(1024*1024)}MB."
                    )
                buffer.write(chunk)

        start_time = time.time()

        try:
            assessment = route_document(temp_path)
        except ValueError as ve:
            raise HTTPException(status_code=415, detail=str(ve))

        doc_type = assessment.get("document_type", "unknown")

        result = {
            "status": "processing_completed",
            "filename": os.path.basename(file.filename),
            "document_type": doc_type,
            "total_pages": assessment.get("total_pages", 0),
            "pages": [],
            "evidence_directory": EVIDENCE_DIR,
            "processing_summary": {
                "total_processing_time": 0.0,
                "pages_successful": 0,
                "pages_failed": 0
            }
        }

        is_pdf = (doc_type == "application/pdf")

        for page_data in assessment.get("pages", []):
            page_num = page_data["page"]
            status = page_data["text_layer_status"]

            page_result = {
                "page": page_num,
                "status": "success",
                "stage1": page_data,
                "stage2": {},
                "stage3": {},
                "extracted_text": "",
                "errors": [],
                "page_processing_time": 0.0
            }

            page_start = time.time()

            try:
                if status == "reliable_text_layer" and is_pdf:
                    try:
                        with pymupdf.open(temp_path) as doc:
                            page_obj = doc.load_page(page_num - 1)
                            page_result["extracted_text"] = page_obj.get_text("text").strip()
                            page_result["stage2"] = {"processing_path": "bypassed_for_embedded_text"}
                            page_result["stage3"] = {"processing_path": "bypassed_for_embedded_text"}
                    except Exception as e:
                        page_result["errors"].append(f"Embedded extraction failed: {str(e)}")
                        page_result["status"] = "partial_failure"
                else:
                    target_image_path = temp_path
                    temp_render_path = None

                    if is_pdf:
                        r_fd, temp_render_path = tempfile.mkstemp(suffix=".png")
                        os.close(r_fd)

                        render_res = render_pdf_page(temp_path, page_num, temp_render_path, dpi=150)
                        page_result["stage2"]["renderer"] = render_res

                        if not render_res.get("render_successful"):
                            raise RuntimeError(f"Rendering failed: {render_res.get('error')}")

                        target_image_path = temp_render_path

                    try:
                        ana_res = analyze_page_image(target_image_path)
                        page_result["stage2"]["analyzer"] = ana_res

                        if not ana_res.get("analysis_successful"):
                            raise RuntimeError(f"Visual analysis failed: {ana_res.get('error')}")

                        hint_text = ""
                        if is_pdf:
                            try:
                                with pymupdf.open(temp_path) as doc:
                                    hint_text = doc.load_page(page_num - 1).get_text("text")
                            except Exception:
                                pass

                        s3_res = process_page_regions(target_image_path, ana_res["regions"], EVIDENCE_DIR, page_num, hint_text)
                        page_result["stage3"] = s3_res

                        if s3_res.get("success"):
                            page_result["extracted_text"] = s3_res.get("reconstructed_text", "")
                        else:
                            page_result["errors"].append(f"Stage 3 failed: {s3_res.get('error')}")
                            page_result["status"] = "partial_failure"

                    finally:
                        if temp_render_path and os.path.exists(temp_render_path):
                            os.remove(temp_render_path)

            except Exception as e:
                page_result["status"] = "failed"
                page_result["errors"].append(str(e))

            finally:
                page_result["page_processing_time"] = round(time.time() - page_start, 3)
                result["pages"].append(page_result)

                if page_result["status"] == "failed":
                    result["processing_summary"]["pages_failed"] += 1
                else:
                    result["processing_summary"]["pages_successful"] += 1

        result["processing_summary"]["total_processing_time"] = round(time.time() - start_time, 3)
        return JSONResponse(status_code=200, content=result)

    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse(status_code=500, content={
            "status": "fatal_error",
            "filename": file.filename if file else "unknown",
            "error": str(e)
        })
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
