import pytest
from httpx2 import ASGITransport, AsyncClient

from bibcleaner.web_api import app


@pytest.mark.anyio
async def test_health_returns_expected_metadata():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "healthy"
    assert "service" in payload
    assert "version" in payload


@pytest.mark.anyio
async def test_clear_bib_missing_file_returns_400():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/clear-bib")

    assert response.status_code == 400
    assert "Missing file upload field" in response.json()["detail"]


@pytest.mark.anyio
async def test_clear_bib_valid_upload_returns_bib_attachment(monkeypatch):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:

        def fake_process(content):
            assert isinstance(content, bytes)
            return "@article{demo,title={Cleaned}}\n"

        monkeypatch.setattr(
            "bibcleaner.web_api.process_bibliography_content", fake_process
        )

        response = await client.post(
            "/clear-bib",
            files={
                "file": (
                    "refs.bib",
                    b"@article{demo,title={A}}",
                    "application/x-bibtex",
                )
            },
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/x-bibtex")
    assert (
        'attachment; filename="cleaned_refs.bib"'
        == response.headers["content-disposition"]
    )
    assert "@article" in response.text


@pytest.mark.anyio
async def test_validation_valid_upload_returns_results(monkeypatch):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:

        def fake_validate(content):
            assert isinstance(content, bytes)
            return [
                {
                    "entry_id": "demo",
                    "errors": ["author"],
                    "warnings": ["doi"],
                }
            ]

        monkeypatch.setattr(
            "bibcleaner.web_api.validate_bibliography_content", fake_validate
        )

        response = await client.post(
            "/validation",
            files={
                "file": (
                    "refs.bib",
                    b"@article{demo,title={A}}",
                    "application/x-bibtex",
                )
            },
        )

    assert response.status_code == 200
    assert response.json() == [
        {
            "entry_id": "demo",
            "errors": ["author"],
            "warnings": ["doi"],
        }
    ]


@pytest.mark.anyio
async def test_validation_rejects_non_bib_upload():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/validation",
            files={
                "file": (
                    "refs.txt",
                    b"not bibtex",
                    "application/x-bibtex",
                )
            },
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Only .bib files are accepted"


@pytest.mark.anyio
async def test_validation_unknown_entry_type_emits_warning():
    bib = b"@weirdType{demo,title={A Demo Entry}}"

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/validation",
            files={
                "file": (
                    "refs.bib",
                    bib,
                    "application/x-bibtex",
                )
            },
        )

    assert response.status_code == 200
    assert response.json() == [
        {
            "entry_id": "demo",
            "errors": [],
            "warnings": ["unknown entry type: weirdtype"],
        }
    ]


@pytest.mark.anyio
async def test_validation_known_type_reports_missing_required_and_optional_fields():
    # Only title is present; article requires author, title, journal, year.
    bib = b"@article{demo,title={A Demo Entry}}"

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/validation",
            files={
                "file": (
                    "refs.bib",
                    bib,
                    "application/x-bibtex",
                )
            },
        )

    assert response.status_code == 200
    assert response.json() == [
        {
            "entry_id": "demo",
            "errors": ["author", "journal", "year"],
            "warnings": ["volume", "number", "pages", "month", "doi", "url"],
        }
    ]
