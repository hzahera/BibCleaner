import re
import logging
from difflib import SequenceMatcher
from typing import Optional

import requests

logger = logging.getLogger(__name__)

DBLP_SEARCH = "https://dblp.org/search/publ/api"

_STOP_WORDS = frozenset(
    "a an the for of in on at to is are with and or by from this that via "
    "its their it as we our be has have been using towards toward towards "
    "how what when where which who why do does did not no can could would "
    "should may might will shall".split()
)

# DBLP type strings that indicate a real publication (not a preprint)
_PUBLISHED_TYPES = {
    "Conference and Workshop Papers": "inproceedings",
    "Journal Articles": "article",
    "Parts in Books or Collections": "incollection",
    "Books and Theses": "book",
}
_PREPRINT_TYPE = "Informal and Other Publications"


def _normalize_text(text: str) -> str:
    return " ".join((text or "").lower().split())


def _clean_author_name(name: str) -> str:
    """Strip DBLP disambiguation suffixes like '0002' from author names."""
    return re.sub(r"\s+\d{4}$", "", name).strip()


def _surname_set(authors: list) -> set:
    out = set()
    for a in authors or []:
        a = (a or "").strip()
        if not a:
            continue
        if "," in a:
            out.add(a.split(",", 1)[0].strip().lower())
        else:
            parts = a.split()
            if parts:
                out.add(parts[-1].strip().lower())
    return out


def _extract_authors(hit_info: dict) -> list:
    raw = (hit_info.get("authors") or {}).get("author", [])
    if isinstance(raw, dict):
        raw = [raw]
    return [_clean_author_name(a["text"]) for a in raw if a.get("text")]


def _title_keywords(title: str, max_words: int = 6) -> str:
    """Extract the first max_words significant keywords from a title for DBLP.

    DBLP uses AND-semantics: every term must appear.  Stop words and trailing
    words with plural/variant forms are the most common sources of zero hits,
    so we keep only distinctive leading tokens.
    """
    tokens = re.findall(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*", title)
    keywords = [t for t in tokens if t.lower() not in _STOP_WORDS]
    return " ".join(keywords[:max_words])


_HEADERS = {
    "User-Agent": "bibcleaner/0.1 (https://github.com/hzahera/bib-cleaner)",
    "Connection": "close",  # avoid keep-alive issues with DBLP
}


def _fetch(query: str, max_results: int) -> list:
    """Single DBLP HTTP call; returns list of info dicts or []."""
    for attempt in range(3):
        try:
            resp = requests.get(
                DBLP_SEARCH,
                params={"q": query, "format": "json", "h": max_results},
                headers=_HEADERS,
                timeout=10,
            )
            if resp.status_code != 200:
                logger.warning(f"DBLP HTTP {resp.status_code}")
                return []
            data = resp.json()
            hits = data.get("result", {}).get("hits", {}).get("hit", [])
            if isinstance(hits, dict):
                hits = [hits]
            return [h["info"] for h in hits if "info" in h]
        except requests.exceptions.ConnectionError as exc:
            logger.debug(f"DBLP connection error (attempt {attempt + 1}): {exc}")
            import time

            time.sleep(1 + attempt)
        except Exception as exc:
            logger.warning(f"DBLP request failed: {exc}")
            break
    return []


def search(title: str, max_results: int = 10) -> list:
    """Return up to max_results DBLP hit dicts for the given title.

    Tries progressively shorter keyword queries (6 → 4 → 3 keywords) so
    minor plural/variant mismatches don't block the lookup.
    """
    if not title:
        return []
    for n_words in (6, 4, 3):
        query = _title_keywords(title, max_words=n_words)
        if not query:
            continue
        hits = _fetch(query, max_results)
        if hits:
            return hits
    return []


def lookup(
    title: str,
    authors: Optional[list] = None,
    year: Optional[str] = None,
) -> dict:
    """Search DBLP once and return {'published': info | None, 'preprint': info | None}.

    Callers use 'published' to replace an arXiv entry and 'preprint' to
    expand the author list when no published version exists.
    """
    hits = search(title, max_results=10)
    result = {"published": None, "preprint": None}
    if not hits:
        return result

    title_norm = _normalize_text(title)
    input_surnames = _surname_set(authors or [])
    year_str = str(year).strip() if year else ""

    published, preprints = [], []

    for info in hits:
        hit_title = _normalize_text(info.get("title", ""))
        sim = SequenceMatcher(None, title_norm, hit_title).ratio()
        if sim < 0.80:
            continue

        hit_year = str(info.get("year", ""))
        year_ok = (
            not year_str
            or hit_year == year_str
            or (
                hit_year.isdigit()
                and year_str.isdigit()
                and abs(int(hit_year) - int(year_str)) <= 1
            )
        )
        if not year_ok:
            continue

        hit_authors = _extract_authors(info)
        overlap = len(input_surnames & _surname_set(hit_authors))
        author_ok = not input_surnames or overlap > 0
        if not author_ok:
            continue

        score = 0.7 * sim + 0.3 * (1.0 if hit_year == year_str else 0.5)
        bucket = preprints if info.get("type") == _PREPRINT_TYPE else published
        bucket.append((score, info))

    if published:
        result["published"] = max(published, key=lambda x: x[0])[1]
    if preprints:
        result["preprint"] = max(preprints, key=lambda x: x[0])[1]
    return result


def best_match(
    title: str,
    authors: Optional[list] = None,
    year: Optional[str] = None,
    require_published: bool = True,
) -> Optional[dict]:
    """Convenience wrapper around lookup() kept for compatibility."""
    r = lookup(title, authors, year)
    if require_published:
        return r["published"]
    return r["published"] or r["preprint"]


def normalize(info: dict) -> dict:
    """Convert a raw DBLP hit info dict into a flat enrichment dict."""
    hit_type = info.get("type", "")
    is_preprint = hit_type == _PREPRINT_TYPE

    entry_type = _PUBLISHED_TYPES.get(hit_type)
    venue = info.get("venue", "")
    doi = info.get("doi", "")

    booktitle = venue if entry_type == "inproceedings" else None
    journal = venue if entry_type == "article" else None

    # Reject arXiv DOIs
    if doi and "arxiv" in doi.lower():
        doi = None

    return {
        "entry_type": entry_type,
        "authors": _extract_authors(info),
        "year": info.get("year"),
        "doi": doi or None,
        "journal": journal,
        "booktitle": booktitle,
        "volume": info.get("volume"),
        "is_preprint": is_preprint,
        "dblp_key": info.get("key", ""),
    }
