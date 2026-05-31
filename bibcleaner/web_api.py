"""BibCleaner HTTP API.

Because enrichment is rate-limited and can take well over a minute, uploads are
processed as background jobs:

    POST /jobs            -> 202 {"job_id": ...}
    GET  /jobs/{id}       -> {"status", "done", "total", ...}
    GET  /jobs/{id}/result-> the cleaned .bib (200) once status == "done"

A synchronous POST /clean-bib (alias /clear-bib) remains for small uploads and
programmatic use; it runs the same pipeline in a thread so it never blocks the
event loop.
"""

from __future__ import annotations

import os
import re
import time
import uuid
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, asdict
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from . import __version__
from .bibcleaner import process_bibliography_content

logger = logging.getLogger(__name__)

APP_NAME = "BibCleaner API"

# ---- Configuration (env-overridable) -------------------------------------
MAX_UPLOAD_BYTES = int(os.environ.get("BIBCLEANER_MAX_BYTES", 10 * 1024 * 1024))
MAX_ENTRIES = int(os.environ.get("BIBCLEANER_MAX_ENTRIES", 500))
RATE_LIMIT = int(os.environ.get("BIBCLEANER_RATE_LIMIT", 30))        # requests / minute / IP
WORKERS = int(os.environ.get("BIBCLEANER_WORKERS", 2))
JOB_TTL = float(os.environ.get("BIBCLEANER_JOB_TTL", 3600))          # seconds
ALLOWED_ORIGINS = [
    o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "*").split(",") if o.strip()
]

_ENTRY_RE = re.compile(r"^[ \t]*@[A-Za-z]+[ \t]*\{", re.MULTILINE)

app = FastAPI(title=APP_NAME, version=__version__)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    return response


# ---- Rate limiter (per-IP sliding window, per instance) ------------------
class _RateLimiter:
    def __init__(self, limit: int, window: float = 60.0):
        self.limit = limit
        self.window = window
        self._hits: dict = {}
        self._lock = threading.Lock()

    def allow(self, ip: str) -> bool:
        now = time.time()
        with self._lock:
            bucket = self._hits.setdefault(ip, [])
            cutoff = now - self.window
            bucket[:] = [t for t in bucket if t >= cutoff]
            if len(bucket) >= self.limit:
                return False
            bucket.append(now)
            return True


_limiter = _RateLimiter(RATE_LIMIT)


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _enforce_rate_limit(request: Request) -> None:
    if not _limiter.allow(_client_ip(request)):
        raise HTTPException(status_code=429, detail="Too many requests; please slow down")


# ---- Job store + worker pool ---------------------------------------------
@dataclass
class Job:
    id: str
    status: str = "queued"  # queued | processing | done | error
    total: int = 0
    done: int = 0
    filename: str = "cleaned.bib"
    result: Optional[str] = None
    error: Optional[str] = None
    created: float = field(default_factory=time.time)


_jobs: dict = {}
_jobs_lock = threading.Lock()
_executor = ThreadPoolExecutor(max_workers=WORKERS)


def _prune_jobs() -> None:
    cutoff = time.time() - JOB_TTL
    with _jobs_lock:
        for jid in [j for j, job in _jobs.items() if job.created < cutoff]:
            _jobs.pop(jid, None)


def _run_job(job_id: str, text: str, filename: str, opts: dict) -> None:
    job = _jobs.get(job_id)
    if job is None:
        return
    job.status = "processing"

    def progress(done: int, total: int) -> None:
        job.done, job.total = done, total

    try:
        job.result = process_bibliography_content(text, progress=progress, **opts)
        job.filename = filename
        job.status = "done"
    except ValueError as exc:
        job.error, job.status = str(exc), "error"
    except Exception as exc:  # noqa: BLE001 - surface a generic message to the client
        logger.exception("Job %s failed", job_id)
        job.error, job.status = f"Processing failed: {exc}", "error"


# ---- Upload validation ----------------------------------------------------
async def _read_upload(file: Optional[UploadFile]) -> tuple[str, str]:
    if file is None:
        raise HTTPException(status_code=400, detail="Missing file upload field 'file'")

    filename = (file.filename or "").strip()
    if not filename:
        raise HTTPException(status_code=400, detail="Missing uploaded filename")
    if not filename.lower().endswith(".bib"):
        raise HTTPException(status_code=400, detail="Only .bib files are accepted")

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Uploaded file is too large")

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=422, detail="File must be UTF-8 encoded") from exc

    n_entries = len(_ENTRY_RE.findall(text))
    if n_entries == 0:
        raise HTTPException(status_code=422, detail="No BibTeX entries found")
    if n_entries > MAX_ENTRIES:
        raise HTTPException(
            status_code=413,
            detail=f"Too many entries ({n_entries}); limit is {MAX_ENTRIES}",
        )
    return text, filename


def _as_bool(value: Optional[str], default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


# ---- Routes ---------------------------------------------------------------
@app.get("/health")
def health() -> dict:
    with _jobs_lock:
        active = sum(1 for j in _jobs.values() if j.status in ("queued", "processing"))
    return {"status": "healthy", "service": APP_NAME, "version": __version__, "active_jobs": active}


@app.post("/jobs", status_code=202)
async def create_job(
    request: Request,
    file: UploadFile | None = File(default=None),
    enrich: str | None = Form(default=None),
    dedup: str | None = Form(default=None),
    protect_caps: str | None = Form(default=None),
) -> dict:
    _enforce_rate_limit(request)
    text, filename = await _read_upload(file)
    _prune_jobs()

    opts = {
        "enrich": _as_bool(enrich, True),
        "dedup": _as_bool(dedup, False),
        "protect_caps": _as_bool(protect_caps, True),
    }
    job = Job(id=uuid.uuid4().hex, filename=f"cleaned_{filename}")
    with _jobs_lock:
        _jobs[job.id] = job
    _executor.submit(_run_job, job.id, text, job.filename, opts)
    return {"job_id": job.id, "status": job.status}


def _get_job(job_id: str) -> Job:
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown or expired job")
    return job


@app.get("/jobs/{job_id}")
def job_status(job_id: str) -> dict:
    job = _get_job(job_id)
    data = asdict(job)
    data.pop("result", None)  # don't ship the payload in the status poll
    return data


@app.get("/jobs/{job_id}/result")
def job_result(job_id: str) -> Response:
    job = _get_job(job_id)
    if job.status == "error":
        raise HTTPException(status_code=422, detail=job.error or "Processing failed")
    if job.status != "done" or job.result is None:
        raise HTTPException(status_code=409, detail=f"Job is {job.status}; not ready")
    headers = {"Content-Disposition": f'attachment; filename="{job.filename}"'}
    return Response(
        content=job.result, media_type="text/x-bibtex; charset=utf-8", headers=headers
    )


@app.post("/clean-bib")
@app.post("/clear-bib")
async def clean_bib_sync(
    request: Request, file: UploadFile | None = File(default=None)
) -> Response:
    """Synchronous convenience endpoint (small uploads / programmatic use)."""
    _enforce_rate_limit(request)
    text, filename = await _read_upload(file)
    try:
        cleaned = await run_in_threadpool(process_bibliography_content, text)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Synchronous clean failed")
        raise HTTPException(status_code=500, detail=f"Failed to process: {exc}") from exc

    headers = {"Content-Disposition": f'attachment; filename="cleaned_{filename}"'}
    return Response(
        content=cleaned, media_type="text/x-bibtex; charset=utf-8", headers=headers
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(_, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
