# Raspberry Pi OCR/HTR Edge Processing Service

A Python document-processing service designed for a resource-constrained Raspberry Pi and exposed through a FastAPI interface.

It serves as an edge extraction component in a larger document-analysis workflow: receive a document, assess its embedded text layer, route pages for direct extraction or visual processing, and return results for human review.

## Design goals

- Run within Raspberry Pi 3B-class memory and CPU constraints.
- Accept document uploads through a small FastAPI service.
- Detect whether an embedded PDF text layer is absent, sparse, suspicious or reliable.
- Route pages to visual processing when direct extraction is not trustworthy.
- Keep document processing separate from the central application database.

## Main components

| File | Responsibility |
|---|---|
| `api.py` | FastAPI upload and processing endpoints |
| `processor.py` | PDF analysis, text-layer quality checks and routing |
| `renderer.py` | Render PDF pages into images for visual analysis |
| `visual_analyzer.py` | CPU-conscious page-region and layout analysis |
| `stage3_engine.py` | Region-level processing and extraction orchestration |
| `tests/` | API, renderer, visual analysis and processing tests |
| `requirements.txt` | Python dependencies |

## Technology

- Python
- FastAPI and Uvicorn
- PyMuPDF
- python-multipart
- CPU-oriented document and image processing

## Run locally

Use Python 3.10 or newer.

```bash
git clone https://github.com/Talket/OCRHTR_Project_PI.git
cd OCRHTR_Project_PI

python -m venv .venv
# Windows PowerShell:
.venv\\Scripts\\Activate.ps1
# macOS / Linux:
# source .venv/bin/activate

pip install -r requirements.txt
uvicorn api:app --host 0.0.0.0 --port 8000
```

Open `http://127.0.0.1:8000/docs` to inspect the FastAPI routes.

For Raspberry Pi deployment, install a compatible 64-bit Python runtime and dependencies for the Pi OS image in use. Start with a small test document and monitor CPU, memory and temporary-disk usage.

## Integration notes

The service is designed as an extraction component, not the system of record. Persist approved results in the central application only after the human-review stage. Keep source-document identifiers and page references with extracted text so downstream analysis can be traced back to the original document.

## Data provenance and responsible use

The project owner identifies sample and corpus documents as originating from publicly available government websites. Preserve source attribution and retrieval details, and follow the issuing source's terms. Treat extracted allegations as unverified until independently checked against the original source.

## Limitations

This is a prototype, not a certified OCR/HTR product. Extraction quality depends on scan quality, language and script, document layout, and available processing resources. Validate each document class and retain human review for consequential use.