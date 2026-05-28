"""
Enrichment pipeline for arXiv preprint BibTeX entries.

Source priority
---------------
For published venue  : DBLP → CrossRef → Semantic Scholar → OpenAlex
For canonical authors: arXiv API  (always queried for any arXiv entry)

If no published venue is found the entry is normalised into a clean @misc
preprint with eprint / archiveprefix / url fields and the full author list
from the arXiv API.
"""

import re
import logging
from typing import Optional

from bibtexparser.model import Entry, Field

from providers import (
    ArxivProvider,
    CrossrefProvider,
    DblpProvider,
    OpenAlexClient,
    ProviderQuery,
    SemanticScholarProvider,
)

from .venues import normalize_or_keep

logger = logging.getLogger(__name__)

_ARXIV_FIELDS = {"eprint", "archiveprefix", "primaryclass"}

_arxiv_provider = ArxivProvider()
_dblp_provider = DblpProvider()
_crossref_provider = CrossrefProvider()
_ss_provider = SemanticScholarProvider()
_oa_provider = OpenAlexClient()


# ---------------------------------------------------------------------------
# arXiv ID extraction
# ---------------------------------------------------------------------------

def extract_arxiv_id(fields: dict) -> Optional[str]:
    """Return a bare arXiv ID (e.g. '2410.03834') from a BibTeX fields dict, or None."""
    if "eprint" in fields:
        raw = re.sub(r"^arxiv:", "", fields["eprint"].strip(), flags=re.IGNORECASE)
        raw = re.sub(r"v\d+$", "", raw)
        if re.match(r"^\d{4}\.\d{4,5}$", raw):
            return raw

    if "journal" in fields:
        m = re.search(r"arxiv[:\s]+(\d{4}\.\d{4,5})", fields["journal"], re.IGNORECASE)
        if m:
            return m.group(1)

    return None


# ---------------------------------------------------------------------------
# Field helpers
# ---------------------------------------------------------------------------

def _set_field(entry: Entry, key: str, value: str):
    for f in entry.fields:
        if f.key == key:
            f.value = value
            return
    entry.fields.append(Field(key=key, value=value))


def _remove_fields(entry: Entry, keys: set):
    entry.fields = [f for f in entry.fields if f.key not in keys]


def _format_authors(authors: list) -> str:
    return " and ".join(a.strip() for a in authors if a.strip())


def _is_truncated(author_str: str) -> bool:
    lower = (author_str or "").lower()
    return "et al" in lower or "others" in lower


def _count_authors(author_str: str) -> int:
    if not author_str:
        return 0
    return len([a for a in re.split(r"\band\b", author_str, flags=re.IGNORECASE) if a.strip()])


def _better_authors(candidate: list, current_str: str) -> bool:
    """True if candidate list is better than the current BibTeX author string."""
    if not candidate:
        return False
    if _is_truncated(current_str) or not current_str:
        return True
    return len(candidate) > _count_authors(current_str)


# ---------------------------------------------------------------------------
# Apply a data dict onto an Entry
# ---------------------------------------------------------------------------

def _apply(entry: Entry, data: dict, fields: dict):
    """Write enrichment data onto the entry in-place."""
    entry_type = data.get("entry_type")
    if entry_type:
        entry.entry_type = entry_type

    if entry_type == "inproceedings":
        if data.get("booktitle"):
            _set_field(entry, "booktitle", normalize_or_keep(data["booktitle"]))
        _remove_fields(entry, {"journal"})
    elif entry_type == "article":
        if data.get("journal"):
            _set_field(entry, "journal", normalize_or_keep(data["journal"]))
        _remove_fields(entry, {"booktitle"})

    if data.get("year"):
        _set_field(entry, "year", str(data["year"]))

    if _better_authors(data.get("authors", []), fields.get("author", "")):
        _set_field(entry, "author", _format_authors(data["authors"]))

    doi = data.get("doi") or ""
    if doi and "arxiv" not in doi.lower():
        _set_field(entry, "doi", doi)

    if data.get("pages"):
        pages = data["pages"]
        if "--" not in pages:
            pages = pages.replace("-", "--", 1)
        _set_field(entry, "pages", pages)
    if data.get("volume"):
        _set_field(entry, "volume", str(data["volume"]))
    if data.get("number"):
        _set_field(entry, "number", str(data["number"]))

    _remove_fields(entry, _ARXIV_FIELDS)


def _normalize_preprint(entry: Entry, fields: dict, authors: list, primaryclass: Optional[str]):
    """Convert a confirmed-preprint entry to a clean @misc with eprint fields."""
    arxiv_id = extract_arxiv_id(fields)
    if not arxiv_id:
        return

    if _better_authors(authors, fields.get("author", "")):
        _set_field(entry, "author", _format_authors(authors))

    _remove_fields(entry, {"journal", "booktitle"} | _ARXIV_FIELDS)
    _set_field(entry, "eprint", arxiv_id)
    _set_field(entry, "archiveprefix", "arXiv")
    if primaryclass:
        _set_field(entry, "primaryclass", primaryclass)
    _set_field(entry, "url", f"https://arxiv.org/abs/{arxiv_id}")
    entry.entry_type = "misc"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def enrich_entry(entry: Entry) -> bool:
    """Enrich an arXiv preprint entry with published venue and full author data.

    Pipeline
    --------
    1. arXiv API   — always called first; gives canonical author list + category
    2. DBLP        — one request; returns published venue *and* preprint authors
    3. CrossRef    — title search; covers journals and conference proceedings
    4. Semantic Scholar — arXiv ID lookup (rate-limited; used when 2+3 miss)
    5. OpenAlex    — title search last resort

    If no published venue is found the entry becomes a clean @misc with
    eprint / archiveprefix / primaryclass / url fields.

    Returns True if the entry was modified in any way.
    """
    fields = {f.key: f.value for f in entry.fields}

    arxiv_id = extract_arxiv_id(fields)
    if not arxiv_id:
        return False

    title = fields.get("title", "")
    raw_author = fields.get("author", "")
    authors = [a.strip() for a in re.split(r"\band\b", raw_author, flags=re.IGNORECASE) if a.strip()]
    year = fields.get("year")
    query = ProviderQuery(title=title, authors=authors, year=year, arxiv_id=arxiv_id)

    logger.debug(f"Processing {entry.key} (arXiv:{arxiv_id})")

    # ---- Step 1: arXiv API — canonical authors and category ----
    arxiv_result = _arxiv_provider.lookup(query)
    canonical_authors: list = arxiv_result.canonical_authors
    primaryclass: Optional[str] = arxiv_result.primaryclass

    # ---- Step 2: DBLP — one request, published + preprint split ----
    dblp_result = _dblp_provider.lookup(query)
    dblp_pub = dblp_result.published_data
    dblp_pre_authors = dblp_result.preprint_authors

    if dblp_pub:
        data = dict(dblp_pub)
        # Prefer canonical arXiv authors over DBLP if DBLP has fewer
        if _better_authors(canonical_authors, _format_authors(data.get("authors", []))):
            data["authors"] = canonical_authors
        _apply(entry, data, fields)
        logger.info(f"[DBLP] {entry.key}")
        return True

    # ---- Step 3: CrossRef — title search ----
    crossref_result = _crossref_provider.lookup(query)
    if crossref_result.published_data:
        data = dict(crossref_result.published_data)
        if _better_authors(canonical_authors, _format_authors(data.get("authors", []))):
            data["authors"] = canonical_authors
        _apply(entry, data, fields)
        logger.info(f"[CrossRef] {entry.key}")
        return True

    # ---- Step 4: Semantic Scholar — arXiv ID (skip when DBLP/CrossRef found no venue) ----
    dblp_or_cr_knows = bool(
        dblp_result.published_data
        or dblp_pre_authors
        or crossref_result.published_data
    )
    ss_result = None
    if not dblp_or_cr_knows:
        ss_result = _ss_provider.lookup(query)
        if ss_result.published_data:
            data = dict(ss_result.published_data)
            if _better_authors(canonical_authors, _format_authors(data.get("authors", []))):
                data["authors"] = canonical_authors
            _apply(entry, data, fields)
            logger.info(f"[SS] {entry.key}")
            return True

        # ---- Step 5: OpenAlex — title search ----
        oa_result = _oa_provider.lookup(query)
        if oa_result.published_data:
            data = dict(oa_result.published_data)
            if _better_authors(canonical_authors, _format_authors(data.get("authors", []))):
                data["authors"] = canonical_authors
            _apply(entry, data, fields)
            logger.info(f"[OA] {entry.key}")
            return True

    # ---- Step 6: Normalize preprint — best available author data ----
    # Priority: arXiv API > DBLP preprint > SS
    best_authors = canonical_authors
    if not best_authors and dblp_pre_authors:
        best_authors = dblp_pre_authors
    if not best_authors and ss_result and ss_result.preprint_authors:
        best_authors = ss_result.preprint_authors

    _normalize_preprint(entry, fields, best_authors, primaryclass)
    changed = bool(best_authors) or "eprint" not in fields
    if changed:
        logger.info(f"[preprint] {entry.key} (arXiv:{arxiv_id})")
    return changed


# ---------------------------------------------------------------------------
# Venue-only normalization (runs on every entry, including non-arXiv ones)
# ---------------------------------------------------------------------------

def normalize_venue_fields(entry: Entry) -> bool:
    """Normalize booktitle / journal to canonical full venue names.

    This pass runs on all entries regardless of whether they are arXiv
    preprints, so that existing entries with abbreviated venue names (e.g.
    'NeurIPS', 'ICLR') are unified with enriched ones.

    Returns True if any field was changed.
    """
    changed = False
    for f in entry.fields:
        if f.key in ("booktitle", "journal"):
            canonical = normalize_or_keep(f.value)
            if canonical != f.value:
                f.value = canonical
                changed = True
    return changed
