import os
import pymupdf
from typing import Dict, Any

def render_pdf_page(pdf_path: str, page_number: int, output_path: str, dpi: int = 150) -> Dict[str, Any]:
    """
    Renders a single, specific page of a PDF into an image file.
    
    Args:
        pdf_path: Path to the source PDF.
        page_number: The 1-based page number to render.
        output_path: Where to save the resulting image.
        dpi: Dots per inch for rendering resolution (default 150).
        
    Returns:
        Dict containing success status, metadata, or error details.
    """
    # 1. Path Validation
    if not os.path.exists(pdf_path):
        return {
            "render_successful": False,
            "page_number": page_number,
            "error": f"File not found: {pdf_path}"
        }

    # 2. DPI Validation (Reject <=0 and absurdly high values to protect Pi RAM)
    if not isinstance(dpi, int) or dpi <= 0 or dpi > 600:
        return {
            "render_successful": False,
            "page_number": page_number,
            "error": f"Invalid DPI: {dpi}. Must be an integer between 1 and 600."
        }

    try:
        # Context manager guarantees file descriptor is closed
        with pymupdf.open(pdf_path) as doc:
            total_pages = len(doc)
            
            # 3. Page Number Validation (1-based index)
            if page_number < 1 or page_number > total_pages:
                return {
                    "render_successful": False,
                    "page_number": page_number,
                    "error": f"Invalid page number {page_number}. Document has {total_pages} pages."
                }
            
            # PyMuPDF internally uses 0-based indexing
            page_index = page_number - 1
            page = doc.load_page(page_index)
            
            # Matrix handles DPI scaling (72 is standard PDF point resolution)
            # PyMuPDF naturally respects page rotation metadata when generating the pixmap via matrix.
            scale = dpi / 72.0
            matrix = pymupdf.Matrix(scale, scale)
            
            # alpha=False forces a white background instead of transparent,
            # which is preferred for OCR and saves memory.
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            
            # 4. Save directly to output path
            pix.save(output_path)
            
            width = pix.width
            height = pix.height
            
            # Explicitly clear resources to aid immediate garbage collection
            del pix
            del page
            
            return {
                "render_successful": True,
                "page_number": page_number,
                "dpi": dpi,
                "width": width,
                "height": height,
                "output_path": output_path
            }
            
    except Exception as e:
        return {
            "render_successful": False,
            "page_number": page_number,
            "error": f"Rendering exception: {str(e)}"
        }
