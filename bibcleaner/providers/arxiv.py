"""arXiv API client — canonical source for preprint author names, categories,
and the author-declared published venue (journal_ref / doi)."""

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
_MIN_GAP = 3.0  # arXiv asks for >= 3 s between calls
_last_call: float = 0.0


def _throttle():
    global _last_call
    elapsed = time.time() - _last_call
    if elapsed < _MIN_GAP:
        time.sleep(_MIN_GAP - elapsed)
    _last_call = time.time()


def fetch(arxiv_id: str) -> Optional[dict]:
    """Return a dict with 'authors', 'year', 'primaryclass', 'journal_ref',
    and 'doi' for the given arXiv ID, or None on failure.

    'journal_ref' and 'doi' are populated only when the authors have marked the
    paper as published on arXiv — they are the most authoritative free signal
    that a preprint now has a real venue.
    """
    clean = re.sub(r"v\d+$", "", arxiv_id.strip())
    _throttle()
    try:
        resp = requests.get(
            _ARXIV_API,
            params={"id_list": clean},
            headers={
                "User-Agent": "bibcleaner/0.1 (https://github.com/hzahera/bib-cleaner)"
            },
            timeout=10,
        )
        if resp.status_code != 200:
            logger.warning(f"arXiv API HTTP {resp.status_code} for {arxiv_id}")
            return None

        root = ET.fromstring(resp.text)
        entries = root.findall("atom:entry", _NS)
        if not entries:
            return None

        entry = entries[0]

        # Abort if arXiv returned an error entry
        title_el = entry.find("atom:title", _NS)
        if title_el is None:
            return None
        if "Error" in (title_el.text or ""):
            return None

        authors = [
            a.find("atom:name", _NS).text.strip()
            for a in entry.findall("atom:author", _NS)
            if a.find("atom:name", _NS) is not None
        ]

        # published date -> year
        pub_el = entry.find("atom:published", _NS)
        year = pub_el.text[:4] if pub_el is not None and pub_el.text else None

        # primary category
        cat_el = entry.find("arxiv:primary_category", _NS)
        primaryclass = cat_el.attrib.get("term") if cat_el is not None else None

        # author-declared published venue
        jref_el = entry.find("arxiv:journal_ref", _NS)
        journal_ref = (jref_el.text or "").strip() if jref_el is not None else None
        journal_ref = journal_ref or None

        doi_el = entry.find("arxiv:doi", _NS)
        doi = (doi_el.text or "").strip() if doi_el is not None else None
        doi = doi or None

        return {
            "authors": authors,
            "year": year,
            "primaryclass": primaryclass,
            "journal_ref": journal_ref,
            "doi": doi,
        }

    except Exception as exc:
        logger.warning(f"arXiv API failed for {arxiv_id}: {exc}")
        return None


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
