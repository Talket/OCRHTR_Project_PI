import os
import tempfile
import uuid
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
from processor import route_document

app = FastAPI(title="Multilingual FIR Document Processor - Stage 1")

# Temporary initial upload ceiling to protect Pi RAM (1GB).
MAX_FILE_SIZE = 25 * 1024 * 1024  

@app.get("/status")
async def get_status():
    return {"status": "online"}

@app.post("/process-document")
async def process_document(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    # Sanitize filename to prevent path traversal
    safe_filename = os.path.basename(file.filename)
    
    # Create temporary file path safely
    fd, temp_path = tempfile.mkstemp(prefix=f"upload_{uuid.uuid4().hex}_")
    
    try:
        file_size = 0
        with os.fdopen(fd, "wb") as buffer:
            while chunk := await file.read(8192):
                file_size += len(chunk)
                if file_size > MAX_FILE_SIZE:
                    raise HTTPException(
                        status_code=413, 
                        detail=f"File exceeds {MAX_FILE_SIZE/(1024*1024)}MB limit."
                    )
                buffer.write(chunk)
        
        try:
            assessment_result = route_document(temp_path)
            assessment_result["file_size_bytes"] = file_size
        except ValueError as e:
            raise HTTPException(status_code=415, detail=str(e))
        
        return JSONResponse(content={
            "status": "assessment_completed",
            "filename": safe_filename,
            "assessment": assessment_result
        })
        
    except HTTPException:
        raise
    finally:
        # Guarantee cleanup on both success and failure paths
        if os.path.exists(temp_path):
            os.remove(temp_path)

if __name__ == "__main__":
    import uvicorn
    # Enforce single worker to cap memory on Raspberry Pi
    uvicorn.run(app, host="0.0.0.0", port=8000, workers=1)
