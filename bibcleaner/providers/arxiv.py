"""arXiv API client — canonical source for preprint author names, categories,
and the author-declared published venue (journal_ref / doi).

arXiv throttles per-IP, and BibCleaner needs one lookup per arXiv entry, so we
**batch**: ``fetch_many`` resolves many IDs in a single request and caches them,
turning N per-entry calls into ceil(N / batch) network calls.
"""

import re
import time
import logging
from typing import Optional
from xml.etree import ElementTree as ET

import requests

from .provider import Provider, ProviderQuery, ProviderResult

logger = logging.getLogger(__name__)

_ARXIV_API = "https://export.arxiv.org/api/query"
_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}
_HEADERS = {"User-Agent": "bibcleaner/0.1 (https://github.com/hzahera/bib-cleaner)"}
_MIN_GAP = 3.0          # arXiv asks for >= 3 s between calls
_BATCH_SIZE = 100       # IDs per batched request
_CACHE_CAP = 10000      # bound the per-process cache

_last_call: float = 0.0
_cache: dict = {}       # bare arXiv id -> meta dict | None (None = not found)


def _throttle():
    global _last_call
    elapsed = time.time() - _last_call
    if elapsed < _MIN_GAP:
        time.sleep(_MIN_GAP - elapsed)
    _last_call = time.time()


def _norm_id(raw: str) -> str:
    return re.sub(r"v\d+$", "", (raw or "").strip())


def _cache_put(key: str, value):
    if len(_cache) >= _CACHE_CAP and key not in _cache:
        _cache.clear()
    _cache[key] = value


def _request(params: dict) -> Optional[str]:
    """GET the arXiv API with throttle + retry on timeout/5xx/429. Text or None."""
    for attempt in range(3):
        _throttle()
        try:
            resp = requests.get(_ARXIV_API, params=params, headers=_HEADERS, timeout=20)
            if resp.status_code == 200:
                return resp.text
            if resp.status_code == 429 or 500 <= resp.status_code < 600:
                retry_after = resp.headers.get("Retry-After")
                wait = int(retry_after) if (retry_after or "").isdigit() else 2 * (attempt + 1)
                logger.debug(f"arXiv API HTTP {resp.status_code} (attempt {attempt + 1})")
                if attempt < 2:
                    time.sleep(wait)
                continue
            logger.warning(f"arXiv API HTTP {resp.status_code}")
            return None
        except requests.exceptions.RequestException as exc:
            logger.debug(f"arXiv API request error (attempt {attempt + 1}): {exc}")
            if attempt < 2:
                time.sleep(2 * (attempt + 1))  # 2s, 4s
    return None


def _id_from_entry(entry) -> Optional[str]:
    el = entry.find("atom:id", _NS)
    if el is None or not el.text:
        return None
    tail = el.text.strip().split("/abs/")[-1]
    return _norm_id(tail)


def _parse_entry(entry) -> Optional[dict]:
    """Extract metadata from one <entry>, or None if it's an error entry."""
    title_el = entry.find("atom:title", _NS)
    if title_el is None or "Error" in (title_el.text or ""):
        return None

    authors = [
        a.find("atom:name", _NS).text.strip()
        for a in entry.findall("atom:author", _NS)
        if a.find("atom:name", _NS) is not None
    ]

    pub_el = entry.find("atom:published", _NS)
    year = pub_el.text[:4] if pub_el is not None and pub_el.text else None

    cat_el = entry.find("arxiv:primary_category", _NS)
    primaryclass = cat_el.attrib.get("term") if cat_el is not None else None

    jref_el = entry.find("arxiv:journal_ref", _NS)
    journal_ref = (jref_el.text or "").strip() if jref_el is not None else None

    doi_el = entry.find("arxiv:doi", _NS)
    doi = (doi_el.text or "").strip() if doi_el is not None else None

    return {
        "authors": authors,
        "year": year,
        "primaryclass": primaryclass,
        "journal_ref": journal_ref or None,
        "doi": doi or None,
    }


def fetch_many(arxiv_ids) -> dict:
    """Resolve many arXiv IDs in batched requests; populates the cache.

    Returns a mapping of bare id -> meta dict for the ones that were found.
    Used to warm the cache before per-entry processing so arXiv is hit just a
    few times instead of once per entry.
    """
    ids = []
    seen = set()
    for raw in arxiv_ids:
        key = _norm_id(raw)
        if key and key not in seen and key not in _cache:
            seen.add(key)
            ids.append(key)

    found: dict = {}
    for start in range(0, len(ids), _BATCH_SIZE):
        chunk = ids[start:start + _BATCH_SIZE]
        text = _request({"id_list": ",".join(chunk), "max_results": len(chunk)})
        if text is None:
            continue  # leave these uncached so per-entry fetch can retry
        try:
            root = ET.fromstring(text)
        except Exception as exc:
            logger.warning(f"arXiv batch parse failed: {exc}")
            continue
        returned = set()
        for entry in root.findall("atom:entry", _NS):
            eid = _id_from_entry(entry)
            if not eid:
                continue
            meta = _parse_entry(entry)
            _cache_put(eid, meta)
            returned.add(eid)
            if meta:
                found[eid] = meta
        # IDs requested but absent from the response → genuinely not found
        for eid in chunk:
            if eid not in returned:
                _cache_put(eid, None)
    return found


def fetch(arxiv_id: str) -> Optional[dict]:
    """Return metadata for a single arXiv ID (cache-first), or None."""
    key = _norm_id(arxiv_id)
    if key in _cache:
        return _cache[key]

    text = _request({"id_list": key})
    if text is None:
        logger.warning(f"arXiv API unavailable for {arxiv_id} after retries")
        return None  # don't cache transient failures

    meta = None
    try:
        entries = ET.fromstring(text).findall("atom:entry", _NS)
        if entries:
            meta = _parse_entry(entries[0])
    except Exception as exc:
        logger.warning(f"arXiv API parse failed for {arxiv_id}: {exc}")
        return None

    _cache_put(key, meta)
    return meta


class ArxivProvider(Provider):
    name = "arxiv"

    def lookup(self, query: ProviderQuery) -> ProviderResult:
        if not query.arxiv_id:
            return ProviderResult()

        meta = fetch(query.arxiv_id)
        if not meta:
            return ProviderResult()

        return ProviderResult(
            canonical_authors=meta.get("authors") or [],
            primaryclass=meta.get("primaryclass"),
            year=meta.get("year"),
            doi=meta.get("doi"),
            journal_ref=meta.get("journal_ref"),
            matched=True,
        )
