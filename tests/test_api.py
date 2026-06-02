"""API tests using FastAPI's synchronous TestClient."""

import time

import pytest
from fastapi.testclient import TestClient

from bibcleaner.web_api import app, _jobs, _jobs_lock, _limiter

client = TestClient(app)

SAMPLE_BIB = b"""@article{demo,
  title = {Attention Is All You Need},
  author = {Vaswani, Ashish and others},
  journal = {arXiv preprint arXiv:1706.03762},
  year = {2017}
}
"""


@pytest.fixture(autouse=True)
def reset_api_state():
    with _jobs_lock:
        _jobs.clear()
    with _limiter._lock:
        _limiter._hits.clear()
    yield
    with _jobs_lock:
        _jobs.clear()
    with _limiter._lock:
        _limiter._hits.clear()


def _wait_for_job(job_id: str, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = client.get(f"/jobs/{job_id}")
        assert response.status_code == 200
        payload = response.json()
        if payload["status"] in {"done", "error"}:
            return payload
        time.sleep(0.01)
    raise AssertionError("job did not finish in time")


def test_health_reports_service_info_and_active_jobs():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
    assert response.json()["service"] == "BibCleaner API"
    assert response.json()["active_jobs"] == 0


def test_job_flow_uses_uploaded_text_and_returns_cleaned_result(monkeypatch):
    seen = {}

    def fake_process(content, **options):
        seen["content"] = content
        seen["options"] = options
        progress = options["progress"]
        progress(1, 1)
        return "@article{demo,title={Cleaned}}\n"

    monkeypatch.setattr("bibcleaner.web_api.process_bibliography_content", fake_process)

    response = client.post(
        "/jobs",
        files={"file": ("refs.bib", SAMPLE_BIB, "application/x-bibtex")},
        data={"enrich": "false", "dedup": "true", "protect_caps": "false"},
    )

    assert response.status_code == 202
    job_id = response.json()["job_id"]

    status = _wait_for_job(job_id)
    assert status["status"] == "done"
    assert status["filename"] == "cleaned_refs.bib"
    assert seen["content"] == SAMPLE_BIB.decode("utf-8")
    assert seen["options"]["enrich"] is False
    assert seen["options"]["dedup"] is True
    assert seen["options"]["protect_caps"] is False

    result = client.get(f"/jobs/{job_id}/result")
    assert result.status_code == 200
    assert result.text == "@article{demo,title={Cleaned}}\n"
    assert result.headers["content-disposition"] == 'attachment; filename="cleaned_refs.bib"'
    assert result.headers["content-type"].startswith("text/x-bibtex")


def test_clean_bib_alias_returns_cleaned_response(monkeypatch):
    seen = {}

    def fake_process(content, **options):
        seen["content"] = content
        seen["options"] = options
        return "@article{demo,title={Sync Cleaned}}\n"

    monkeypatch.setattr("bibcleaner.web_api.process_bibliography_content", fake_process)

    response = client.post(
        "/clear-bib",
        files={"file": ("refs.bib", SAMPLE_BIB, "application/x-bibtex")},
    )

    assert response.status_code == 200
    assert response.text == "@article{demo,title={Sync Cleaned}}\n"
    assert response.headers["content-disposition"] == 'attachment; filename="cleaned_refs.bib"'
    assert response.headers["content-type"].startswith("text/x-bibtex")
    assert seen["content"] == SAMPLE_BIB.decode("utf-8")
    assert seen["options"] == {}


def test_validation_passes_bytes_and_returns_json(monkeypatch):
    seen = {}

    def fake_validate(content):
        seen["content"] = content
        return [{"entry_id": "demo", "errors": ["author"], "warnings": ["doi"]}]

    monkeypatch.setattr("bibcleaner.web_api.validate_bibliography_content", fake_validate)

    response = client.post(
        "/validation",
        files={"file": ("refs.bib", SAMPLE_BIB, "application/x-bibtex")},
    )

    assert response.status_code == 200
    assert response.json() == [{"entry_id": "demo", "errors": ["author"], "warnings": ["doi"]}]
    assert seen["content"] == SAMPLE_BIB


def test_jobs_reject_non_bib_uploads():
    response = client.post(
        "/jobs",
        files={"file": ("notes.txt", b"@article{demo}", "text/plain")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Only .bib files are accepted"


def test_clean_bib_rejects_missing_entries():
    response = client.post(
        "/clean-bib",
        files={"file": ("refs.bib", b"plain text only", "application/x-bibtex")},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "No BibTeX entries found"


def test_unknown_job_endpoints_return_404():
    assert client.get("/jobs/missing").status_code == 404
    assert client.get("/jobs/missing/result").status_code == 404
