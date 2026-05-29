from __future__ import annotations

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response

from . import __version__
from .bibcleaner import process_bibliography_content

APP_NAME = "BibCleaner API"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB safeguard
_ALLOWED_CONTENT_TYPES = {
    "application/x-bibtex",
    "text/x-bibtex",
}

app = FastAPI(title=APP_NAME, version=__version__)


@app.get("/health")
def health() -> dict:
    return {"status": "healthy", "service": APP_NAME, "version": __version__}


@app.post("/clear-bib")
@app.post("/clean-bib")
async def clear_bib(file: UploadFile | None = File(default=None)) -> Response:
    if file is None:
        raise HTTPException(status_code=400, detail="Missing file upload field 'file'")

    filename = (file.filename or "").strip()
    if not filename:
        raise HTTPException(status_code=400, detail="Missing uploaded filename")

    if not filename.lower().endswith(".bib"):
        raise HTTPException(status_code=400, detail="Only .bib files are accepted")

    content_type = (file.content_type or "").lower()
    if content_type not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Unsupported content type for .bib upload",
        )

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Uploaded file is too large")

    try:
        cleaned = process_bibliography_content(raw)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process bibliography: {exc}",
        ) from exc

    output_name = f"cleaned_{filename}"
    headers = {"Content-Disposition": f'attachment; filename="{output_name}"'}
    return Response(
        content=cleaned, media_type="text/x-bibtex; charset=utf-8", headers=headers
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(_, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
