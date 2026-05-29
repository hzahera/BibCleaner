from fastapi.testclient import TestClient

from bibcleaner.web_api import app


def test_health_returns_expected_metadata():
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "healthy"
    assert "service" in payload
    assert "version" in payload


def test_clear_bib_missing_file_returns_400():
    client = TestClient(app)

    response = client.post("/clear-bib")

    assert response.status_code == 400
    assert "Missing file upload field" in response.json()["detail"]


def test_clear_bib_valid_upload_returns_bib_attachment(monkeypatch):
    client = TestClient(app)

    def fake_process(content):
        assert isinstance(content, bytes)
        return "@article{demo,title={Cleaned}}\n"

    monkeypatch.setattr("bibcleaner.web_api.process_bibliography_content", fake_process)

    response = client.post(
        "/clear-bib",
        files={
            "file": ("refs.bib", b"@article{demo,title={A}}", "application/x-bibtex")
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/x-bibtex")
    assert (
        'attachment; filename="cleaned_refs.bib"'
        == response.headers["content-disposition"]
    )
    assert "@article" in response.text
