"""Semantic Scholar client — arXiv-ID lookup for published-venue data."""

import os
import re
import time
import logging
from typing import Optional

import requests

from .provider import Provider, ProviderQuery, ProviderResult

logger = logging.getLogger(__name__)

_SS_FIELDS = (
    "title,authors,year,venue,journal,publicationVenue,externalIds,publicationTypes"
)
_ARXIV_VENUES = frozenset({"arxiv", "arxiv.org", "corr", "arxiv e-prints", ""})

# Semantic Scholar public API: ~1 req/sec without a key, higher with one.
_MIN_REQUEST_GAP = 3.0
_last_request_time: float = 0.0


def _throttle():
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < _MIN_REQUEST_GAP:
        time.sleep(_MIN_REQUEST_GAP - elapsed)
    _last_request_time = time.time()


def fetch_by_arxiv_id(arxiv_id: str, retries: int = 3) -> Optional[dict]:
    """Fetch paper metadata from Semantic Scholar using an arXiv ID.

    Set the S2_API_KEY environment variable to use a higher-rate-limit key.
    """
    clean_id = re.sub(r"^arxiv:", "", arxiv_id.strip(), flags=re.IGNORECASE)
    url = f"https://api.semanticscholar.org/graph/v1/paper/ARXIV:{clean_id}"
    params = {"fields": _SS_FIELDS}

    api_key = os.environ.get("S2_API_KEY")
    if not api_key:
        logger.warning("No Semantic Scholar API key found. Request failed.")
        return None
    headers = {"x-api-key": api_key}

    for attempt in range(retries):
        _throttle()
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 429:
                wait = 10 * (2**attempt)  # 10s, 20s, 40s
                logger.warning(f"Semantic Scholar rate-limited; retrying in {wait}s")
                time.sleep(wait)
            elif resp.status_code == 404:
                logger.debug(f"arXiv:{arxiv_id} not found in Semantic Scholar")
                break
            else:
                logger.warning(
                    f"Semantic Scholar HTTP {resp.status_code} for arXiv:{arxiv_id}"
                )
                break
        except requests.RequestException as exc:
            logger.warning(f"Semantic Scholar request failed: {exc}")
            break
    return None


def _is_published(paper: dict) -> bool:
    pub_types = [t.lower() for t in (paper.get("publicationTypes") or [])]
    if pub_types == ["preprint"]:
        return False

    venue = (
        ((paper.get("publicationVenue") or {}).get("name") or paper.get("venue") or "")
        .lower()
        .strip()
    )
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
            matched=True,
        )
