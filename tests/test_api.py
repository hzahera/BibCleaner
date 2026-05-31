"""API tests using Starlette's synchronous TestClient (no network: enrich=false)."""

import time

from fastapi.testclient import TestClient

from bibcleaner.web_api import app

client = TestClient(app)

SAMPLE_BIB = b"""@inproceedings{vaswani2017,
  title     = {Attention Is All You Need for ImageNet},
  author    = {Vaswani, Ashish and others},
  booktitle = {NeurIPS},
  year      = {2017}
}
"""


def _wait_for_job(job_id, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = client.get(f"/jobs/{job_id}")
        assert resp.status_code == 200
        body = resp.json()
        if body["status"] in ("done", "error"):
            return body
        time.sleep(0.05)
    raise AssertionError("job did not finish in time")


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "healthy"
    assert "version" in body and "active_jobs" in body


def test_job_flow_offline():
    resp = client.post(
        "/jobs",
        files={"file": ("refs.bib", SAMPLE_BIB, "application/x-bibtex")},
        data={"enrich": "false"},
    )
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    body = _wait_for_job(job_id)
    assert body["status"] == "done"

    result = client.get(f"/jobs/{job_id}/result")
    assert result.status_code == 200
    assert result.headers["content-type"].startswith("text/x-bibtex")
    assert result.headers["content-disposition"] == 'attachment; filename="cleaned_refs.bib"'
    # venue normalized + capitalization protected, even with enrichment off
    assert "Advances in Neural Information Processing Systems (NeurIPS)" in result.text
    assert "{ImageNet}" in result.text


def test_job_result_404_for_unknown():
    assert client.get("/jobs/does-not-exist/result").status_code == 404
    assert client.get("/jobs/does-not-exist").status_code == 404


def test_missing_file_returns_400():
    resp = client.post("/jobs")
    assert resp.status_code == 400
    assert "Missing file" in resp.json()["detail"]


def test_non_bib_extension_rejected():
    resp = client.post("/jobs", files={"file": ("notes.txt", b"@x{a}", "text/plain")})
    assert resp.status_code == 400


def test_no_entries_rejected():
    resp = client.post("/jobs", files={"file": ("empty.bib", b"just prose, no entries", "application/x-bibtex")})
    assert resp.status_code == 422


def test_sync_endpoint_offline():
    resp = client.post(
        "/clean-bib",
        files={"file": ("refs.bib", SAMPLE_BIB, "application/x-bibtex")},
    )
    assert resp.status_code == 200
    assert "Advances in Neural Information Processing Systems (NeurIPS)" in resp.text
