"""
Converts uploaded documents (PDF or image) into a list of page images.

PDFs -> rendered to one PNG per page (pdf2image / poppler).
Images (jpg/png) -> treated as a single-page document.

We deliberately do NOT run a separate text-extraction OCR pass (e.g. pytesseract)
as the primary path. Instead each page image is handed to a vision-capable LLM
(see extraction_service.py) which performs OCR + structured extraction in one
call. This is simpler, more robust to poor scans/rotation/varied layouts, and
matches the assignment's allowance for "OCR and/or AI-based document processing".

TODO (Copilot): if you want a text-first fast path for digitally-generated PDFs
(no OCR needed), add a `try_extract_native_text(pdf_path)` using e.g. pypdf and
skip the vision call when text is present and looks complete. Good ROI upgrade,
not required for the MVP.
"""
import os
from pdf2image import convert_from_path


def render_document_to_page_images(file_path: str, file_type: str, output_dir: str) -> list[str]:
    """
    Returns a list of file paths, one PNG per page, in page order.
    """
    os.makedirs(output_dir, exist_ok=True)

    if file_type == "pdf":
        images = convert_from_path(file_path, dpi=200)
        paths = []
        for i, img in enumerate(images, start=1):
            out_path = os.path.join(output_dir, f"page_{i}.png")
            img.save(out_path, "PNG")
            paths.append(out_path)
        return paths

    elif file_type in ("jpg", "jpeg", "png"):
        # Single-page "document"
        out_path = os.path.join(output_dir, "page_1" + os.path.splitext(file_path)[1])
        # Copy/normalize into the working dir so downstream code has a uniform path
        with open(file_path, "rb") as src, open(out_path, "wb") as dst:
            dst.write(src.read())
        return [out_path]

    else:
        raise ValueError(f"Unsupported file_type for OCR: {file_type}")
