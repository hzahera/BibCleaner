from typing import Optional

from bibcleaner.api import fetch_by_arxiv_id

from .provider import Provider, ProviderQuery, ProviderResult

_ARXIV_VENUES = frozenset({"arxiv", "arxiv.org", "corr", "arxiv e-prints", ""})


def _is_published(paper: dict) -> bool:
    pub_types = [t.lower() for t in (paper.get("publicationTypes") or [])]
    if pub_types == ["preprint"]:
        return False

    venue = (
        (paper.get("publicationVenue") or {}).get("name") or paper.get("venue") or ""
    ).lower().strip()
    return venue not in _ARXIV_VENUES and "arxiv" not in venue


def _to_data(paper: dict) -> Optional[dict]:
    pub_venue = paper.get("publicationVenue") or {}
    venue_type = (pub_venue.get("type") or "").lower()
    venue_name = pub_venue.get("name") or paper.get("venue") or ""
    journal_obj = paper.get("journal") or {}
    journal_is_arxiv = "arxiv" in (journal_obj.get("name") or "").lower()

    conference_hints = {"proceedings", "conference", "symposium", "workshop", "meeting"}
    is_conf = "conference" in venue_type or any(
        hint in venue_name.lower() for hint in conference_hints
    )

    doi = (paper.get("externalIds") or {}).get("DOI") or ""
    if "arxiv" in doi.lower():
        doi = None

    data = {
        "year": paper.get("year"),
        "doi": doi or None,
        "authors": [a["name"] for a in (paper.get("authors") or []) if a.get("name")],
        "pages": journal_obj.get("pages") if not journal_is_arxiv else None,
        "volume": (
            str(journal_obj["volume"])
            if journal_obj.get("volume") and not journal_is_arxiv
            else None
        ),
    }
    if is_conf:
        data["entry_type"] = "inproceedings"
        data["booktitle"] = venue_name
    else:
        data["entry_type"] = "article"
        data["journal"] = journal_obj.get("name") or venue_name

    return data


class SemanticScholarProvider(Provider):
    name = "semanticscholar"

    def lookup(self, query: ProviderQuery) -> ProviderResult:
        if not query.arxiv_id:
            return ProviderResult()

        paper = fetch_by_arxiv_id(query.arxiv_id)
        if not paper:
            return ProviderResult()

        authors = [a["name"] for a in (paper.get("authors") or []) if a.get("name")]
        published_data = _to_data(paper) if _is_published(paper) else None

        return ProviderResult(
            published_data=published_data,
            preprint_authors=authors,
        )
