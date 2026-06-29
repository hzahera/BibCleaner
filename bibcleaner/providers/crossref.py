"""CrossRef client — published-venue data for journal and proceedings papers.

Supports both exact DOI resolution (preferred) and fuzzy title search.
"""

import asyncio
import os
import time
import logging
import httpx2
from difflib import SequenceMatcher
from typing import Optional

from .provider import Provider, ProviderQuery, ProviderResult

logger = logging.getLogger(__name__)

_CROSSREF_URL = "https://api.crossref.org/works"
_PREPRINT_TYPES = {"posted-content", "report", "dataset"}
_PUBLISHED_TYPES = {
    "journal-article": "article",
    "proceedings-article": "inproceedings",
    "book-chapter": "incollection",
    "monograph": "book",
}
_HEADERS = {"User-Agent": "bibcleaner/0.1 (https://github.com/hzahera/bib-cleaner)"}

_MIN_GAP = 2.0
_last_call: float = 0.0
_throttle_lock = asyncio.Lock()


async def _throttle():
    global _last_call
    async with _throttle_lock:
        elapsed = time.time() - _last_call
        if elapsed < _MIN_GAP:
            await asyncio.sleep(_MIN_GAP - elapsed)
        _last_call = time.time()


def _normalize(text: str) -> str:
    return " ".join((text or "").lower().split())


def _clean_doi(doi: str) -> str:
    doi = (doi or "").strip()
    doi = doi.replace("https://doi.org/", "").replace("http://doi.org/", "")
    doi = doi.replace("doi:", "").strip()
    return doi


def _format_authors(author_list: list) -> list:
    names = []
    for a in author_list or []:
        given = (a.get("given") or "").strip()
        family = (a.get("family") or "").strip()
        if family:
            names.append(f"{given} {family}".strip() if given else family)
    return names


async def search(client, title: str, rows: int = 5) -> list:
    """Return raw CrossRef items for a title query."""
    if not title:
        return []
    mailto = os.environ.get("CROSSREF_MAILTO", "")
    params: dict = {"query.title": title, "rows": rows}
    if mailto:
        params["mailto"] = mailto
    for attempt in range(4):
        await _throttle()
        try:
            resp = await client.get(_CROSSREF_URL, params=params, headers=_HEADERS)
            if resp.status_code == 200:
                return resp.json().get("message", {}).get("items", [])
            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                wait = int(retry_after) if (retry_after or "").isdigit() else 2**attempt
                logger.debug(f"CrossRef rate-limited; retrying in {wait}s")
                await asyncio.sleep(wait)
                continue
            logger.warning(f"CrossRef HTTP {resp.status_code}")
            return []
        except httpx2.ConnectError as exc:
            logger.debug(f"CrossRef connection error (attempt {attempt + 1}): {exc}")
            await asyncio.sleep(1 + attempt)
        except Exception as exc:
            logger.warning(f"CrossRef request failed: {exc}")
            return []
    return []


async def fetch_by_doi(client, doi: str) -> Optional[dict]:
    """Return the raw CrossRef item for an exact DOI, or None."""
    doi = _clean_doi(doi)
    if not doi:
        return None
    mailto = os.environ.get("CROSSREF_MAILTO", "")
    params = {"mailto": mailto} if mailto else {}
    for attempt in range(4):
        await _throttle()
        try:
            resp = await client.get(
                f"{_CROSSREF_URL}/{doi}", params=params, headers=_HEADERS
            )
            if resp.status_code == 200:
                return resp.json().get("message")
            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                wait = int(retry_after) if (retry_after or "").isdigit() else 2**attempt
                logger.debug(f"CrossRef DOI rate-limited; retrying in {wait}s")
                await asyncio.sleep(wait)
                continue
            if resp.status_code != 404:
                logger.warning(f"CrossRef DOI HTTP {resp.status_code} for {doi}")
            return None
        except httpx2.ConnectError as exc:
            logger.debug(f"CrossRef DOI connection error (attempt {attempt + 1}): {exc}")
            await asyncio.sleep(1 + attempt)
        except Exception as exc:
            logger.warning(f"CrossRef DOI request failed: {exc}")
            return None
    return None


async def best_match(
    client,
    title: str,
    authors: Optional[list] = None,
    year: Optional[str] = None,
) -> Optional[dict]:
    """Return the best-matching CrossRef item, or None if no confident match."""
    items = await search(client, title, rows=5)
    if not items:
        return None

    title_norm = _normalize(title)
    year_str = str(year).strip() if year else ""

    best, best_score = None, 0.0
    for item in items:
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
        year_score = (
            1.0
            if year_str and cr_year == year_str
            else (
                0.5
                if year_str and cr_year and abs(int(cr_year) - int(year_str)) <= 1
                else 0.0
            )
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

    return {
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


class CrossrefProvider(Provider):
    name = "crossref"

    def __init__(self, client: httpx2.AsyncClient):
        self.client = client

    async def lookup(self, query: ProviderQuery) -> ProviderResult:
        # Exact DOI resolution takes precedence over fuzzy title search.
        if query.doi:
            item = await fetch_by_doi(self.client, query.doi)
            if item and item.get("type") not in _PREPRINT_TYPES:
                data = normalize(item)
                if data:
                    return ProviderResult(published_data=data, matched=True)

        item = await best_match(self.client, query.title, query.authors, query.year)
        if not item:
            return ProviderResult()

        return ProviderResult(published_data=normalize(item), matched=True)
