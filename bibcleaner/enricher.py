"""
Enrichment pipeline for arXiv preprint BibTeX entries.

Every external source is a :class:`providers.Provider` exposing a uniform
``lookup(ProviderQuery) -> ProviderResult``.  This module only orchestrates
them; all HTTP and parsing logic lives in the ``providers`` package.

Resolution order
----------------
1. arXiv API   — canonical authors, category, and the author-declared venue
                 (``journal_ref`` / ``doi``) when the paper is marked published.
2. DOI lookup  — exact resolution via CrossRef then OpenAlex (no fuzzy matching).
3. DBLP        — title search; published venue + preprint authors.
4. CrossRef    — title search.
5. Semantic Scholar — arXiv-ID lookup (only if DBLP/CrossRef don't recognise it).
6. OpenAlex    — title search (last resort).
7. journal_ref — author-declared venue, used only when it maps to a known venue.

If no published venue is found the entry becomes a clean ``@misc`` preprint with
the fullest available author list.
"""

import os
import re
import logging
from typing import Optional

from bibtexparser.model import Entry, Field

from providers import (
    ProviderQuery,
    ProviderResult,
    ArxivProvider,
    DblpProvider,
    CrossrefProvider,
    SemanticScholarProvider,
    OpenAlexClient,
)
from .venues import normalize_or_keep, normalize_venue

logger = logging.getLogger(__name__)

_ARXIV_FIELDS = {"eprint", "archiveprefix", "primaryclass"}

# Provider instances (stateful: throttling, OpenAlex cache).
_arxiv = ArxivProvider()
_dblp = DblpProvider()
_crossref = CrossrefProvider()
_ss = SemanticScholarProvider()
_openalex = OpenAlexClient(
    mailto=os.environ.get("OPENALEX_MAILTO") or os.environ.get("CROSSREF_MAILTO")
)

# Canonical venues that are conference proceedings but whose names lack the
# usual hint words ("conference", "proceedings", ...).
_CONF_OVERRIDES = {
    "Advances in Neural Information Processing Systems (NeurIPS)",
    "Interspeech",
}
_CONF_HINTS = ("conference", "symposium", "workshop", "meeting", "proceedings", "congress")


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
# Author preference + apply
# ---------------------------------------------------------------------------

def _prefer_canonical(data: dict, canonical_authors: list):
    """Replace data['authors'] with the arXiv canonical list when it is richer."""
    if _better_authors(canonical_authors, _format_authors(data.get("authors", []))):
        data["authors"] = canonical_authors


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
# arXiv journal_ref → venue data
# ---------------------------------------------------------------------------

def _venue_core(journal_ref: str) -> str:
    """Extract the bare venue name from a free-text arXiv journal_ref."""
    s = re.sub(
        r"^(?:to appear in|accepted (?:at|to|for)|published in|"
        r"in proceedings of|proceedings of|proc\.?\s+of|in)\s+",
        "",
        journal_ref.strip(),
        flags=re.IGNORECASE,
    )
    # Venue name is the leading run of letters before any volume/year/comma.
    m = re.match(r"^([A-Za-z][A-Za-z&/.'\- ]+?)(?=[\s,]+\d|\s*\(|,|$)", s)
    return (m.group(1) if m else s).strip(" ,.-")


def _is_conference_venue(canonical: str) -> bool:
    if canonical in _CONF_OVERRIDES:
        return True
    low = canonical.lower()
    return any(h in low for h in _CONF_HINTS)


def _data_from_journal_ref(journal_ref: str, year, authors: list) -> Optional[dict]:
    """Build venue data from an arXiv journal_ref, only if it maps to a known venue.

    Returns None for unrecognised venue strings so we never insert noisy
    metadata — the entry then falls through to clean @misc normalization.
    """
    canonical = normalize_venue(_venue_core(journal_ref))
    if not canonical:
        return None

    is_conf = _is_conference_venue(canonical)
    data = {
        "entry_type": "inproceedings" if is_conf else "article",
        "year": str(year) if year else None,
        "authors": authors or [],
    }
    if is_conf:
        data["booktitle"] = canonical
    else:
        data["journal"] = canonical
    return data


# ---------------------------------------------------------------------------
# DOI-first exact resolution
# ---------------------------------------------------------------------------

def _resolve_by_doi(doi: str) -> Optional[dict]:
    """Resolve a DOI to structured venue data via CrossRef, then OpenAlex."""
    doi_query = ProviderQuery(doi=doi)  # empty title => providers skip title search
    for provider in (_crossref, _openalex):
        result = provider.lookup(doi_query)
        if result.published_data:
            return result.published_data
    return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def enrich_entry(entry: Entry) -> bool:
    """Enrich an arXiv preprint entry with published venue and full author data.

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

    logger.debug(f"Processing {entry.key} (arXiv:{arxiv_id})")

    # ---- Step 1: arXiv API — canonical authors, category, declared venue ----
    arxiv_res = _arxiv.lookup(
        ProviderQuery(title=title, authors=authors, year=year, arxiv_id=arxiv_id)
    )
    canonical_authors = arxiv_res.canonical_authors
    primaryclass = arxiv_res.primaryclass
    doi = fields.get("doi") or arxiv_res.doi  # prefer the entry's own DOI, else arXiv's

    # Title-only query reused for the fuzzy-search providers.
    tquery = ProviderQuery(title=title, authors=authors, year=year, arxiv_id=arxiv_id)

    data: Optional[dict] = None

    # ---- Step 2: DOI-first exact resolution ----
    if doi:
        data = _resolve_by_doi(doi)

    # ---- Step 3: DBLP title search ----
    dblp_res = ProviderResult()
    if data is None:
        dblp_res = _dblp.lookup(tquery)
        data = dblp_res.published_data

    # ---- Step 4: CrossRef title search ----
    cr_res = ProviderResult()
    if data is None:
        cr_res = _crossref.lookup(tquery)
        data = cr_res.published_data

    # ---- Steps 5 & 6: SS + OpenAlex, only if DBLP/CrossRef didn't recognise it ----
    ss_res = ProviderResult()
    if data is None and not (dblp_res.matched or cr_res.matched):
        ss_res = _ss.lookup(tquery)
        data = ss_res.published_data
        if data is None:
            data = _openalex.lookup(tquery).published_data

    # ---- Step 7: arXiv journal_ref fallback (known venues only) ----
    if data is None and arxiv_res.journal_ref:
        data = _data_from_journal_ref(
            arxiv_res.journal_ref, arxiv_res.year or year, canonical_authors
        )

    # ---- Apply published data if we found any ----
    if data:
        _prefer_canonical(data, canonical_authors)
        _apply(entry, data, fields)
        logger.info(f"[published] {entry.key}")
        return True

    # ---- Step 8: clean @misc preprint with the fullest author list ----
    best_authors = canonical_authors
    if not best_authors:
        best_authors = dblp_res.preprint_authors or ss_res.preprint_authors

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

    Runs on all entries regardless of whether they are arXiv preprints, so that
    existing entries with abbreviated venue names (e.g. 'NeurIPS', 'ICLR') are
    unified with enriched ones.  Returns True if any field was changed.
    """
    changed = False
    for f in entry.fields:
        if f.key in ("booktitle", "journal"):
            canonical = normalize_or_keep(f.value)
            if canonical != f.value:
                f.value = canonical
                changed = True
    return changed
