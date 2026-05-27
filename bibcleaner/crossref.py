"""CrossRef API client — reliable published-venue data for journal and proceedings papers."""

import os
import logging
import requests
from difflib import SequenceMatcher
from typing import Optional

logger = logging.getLogger(__name__)

_CROSSREF_URL = "https://api.crossref.org/works"
_PREPRINT_TYPES = {"posted-content", "report", "dataset"}
_PUBLISHED_TYPES = {
    "journal-article": "article",
    "proceedings-article": "inproceedings",
    "book-chapter": "incollection",
    "monograph": "book",
}


def _normalize(text: str) -> str:
    return " ".join((text or "").lower().split())


def _format_authors(author_list: list) -> list:
    names = []
    for a in author_list or []:
        given = (a.get("given") or "").strip()
        family = (a.get("family") or "").strip()
        if family:
            names.append(f"{given} {family}".strip() if given else family)
    return names


def search(title: str, rows: int = 5) -> list:
    """Return raw CrossRef items for a title query."""
    if not title:
        return []
    mailto = os.environ.get("CROSSREF_MAILTO", "")
    params: dict = {"query.title": title, "rows": rows}
    if mailto:
        params["mailto"] = mailto
    try:
        resp = requests.get(
            _CROSSREF_URL,
            params=params,
            headers={"User-Agent": "bibcleaner/0.1 (https://github.com/hzahera/bib-cleaner)"},
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json().get("message", {}).get("items", [])
        logger.warning(f"CrossRef HTTP {resp.status_code}")
    except Exception as exc:
        logger.warning(f"CrossRef request failed: {exc}")
    return []


def best_match(
    title: str,
    authors: Optional[list] = None,
    year: Optional[str] = None,
) -> Optional[dict]:
    """Return the best-matching CrossRef item, or None if no confident match."""
    items = search(title, rows=5)
    if not items:
        return None

    title_norm = _normalize(title)
    year_str = str(year).strip() if year else ""

    best, best_score = None, 0.0
    for item in items:
        # Skip preprints
        if item.get("type") in _PREPRINT_TYPES:
            continue

        cr_titles = item.get("title") or []
        if not cr_titles:
            continue
        sim = SequenceMatcher(None, title_norm, _normalize(cr_titles[0])).ratio()
        if sim < 0.85:
            continue

        published = (item.get("published") or {}).get("date-parts", [[None]])[0]
        cr_year = str(published[0]) if published and published[0] else ""
        year_score = 1.0 if year_str and cr_year == year_str else (
            0.5 if year_str and cr_year and abs(int(cr_year) - int(year_str)) <= 1 else 0.0
        )

        score = 0.8 * sim + 0.2 * year_score
        if score > best_score:
            best_score = score
            best = item

    return best if best_score >= 0.85 else None


def normalize(item: dict) -> Optional[dict]:
    """Convert a raw CrossRef item to the common enrichment dict."""
    if not item:
        return None

    work_type = item.get("type", "")
    entry_type = _PUBLISHED_TYPES.get(work_type)
    if not entry_type:
        return None

    containers = item.get("container-title") or []
    container = containers[0] if containers else ""

    doi = item.get("DOI") or ""
    if "arxiv" in doi.lower():
        doi = None

    published = (item.get("published") or {}).get("date-parts", [[None]])[0]
    year = str(published[0]) if published and published[0] else None

    out = {
        "entry_type": entry_type,
        "authors": _format_authors(item.get("author", [])),
        "year": year,
        "doi": doi or None,
        "pages": item.get("page"),
        "volume": item.get("volume"),
        "number": item.get("issue"),
        "journal": container if entry_type == "article" else None,
        "booktitle": container if entry_type == "inproceedings" else None,
    }
    return out
