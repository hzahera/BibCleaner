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
import httpx2
import asyncio

from .providers import (
    ProviderQuery,
    ProviderResult,
    ArxivProvider,
    DblpProvider,
    CrossrefProvider,
    SemanticScholarProvider,
    OpenAlexClient,
)
from .venues import normalize_or_keep, normalize_venue
from .cache import TTLCache

logger = logging.getLogger(__name__)

_ARXIV_FIELDS = {"eprint", "archiveprefix", "primaryclass"}


class ProviderRegistry:
    def __init__(self, client):
        self.arxiv = ArxivProvider(client)
        self.dblp = DblpProvider(client)
        self.crossref = CrossrefProvider(client)
        self.semanticscholar = SemanticScholarProvider(client)
        self.openalex = OpenAlexClient(
            client=client,
            mailto=os.environ.get("OPENALEX_MAILTO")
            or os.environ.get("CROSSREF_MAILTO"),
        )


# Shared cache so repeated arXiv IDs / DOIs / titles don't re-hit the APIs.
_lookup_cache = TTLCache(ttl=float(os.environ.get("BIBCLEANER_CACHE_TTL", 86400)))


def _cache_key(provider_name: str, q: ProviderQuery) -> tuple:
    return (
        provider_name,
        q.arxiv_id or "",
        (q.doi or "").strip().lower(),
        " ".join((q.title or "").lower().split()),
        str(q.year or ""),
    )


async def _lookup(provider, q: ProviderQuery) -> ProviderResult:
    """provider.lookup(q), memoized (including negative results)."""
    key = _cache_key(provider.name, q)
    cached = _lookup_cache.get(key)
    if cached is not None:
        return cached
    result = await provider.lookup(q)
    _lookup_cache.set(key, result)
    return result


# Canonical venues that are conference proceedings but whose names lack the
# usual hint words ("conference", "proceedings", ...).
_CONF_OVERRIDES = {
    "Advances in Neural Information Processing Systems (NeurIPS)",
    "Interspeech",
}
_CONF_HINTS = (
    "conference",
    "symposium",
    "workshop",
    "meeting",
    "proceedings",
    "congress",
)


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
    return len(
        [a for a in re.split(r"\band\b", author_str, flags=re.IGNORECASE) if a.strip()]
    )


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


def _normalize_preprint(
    entry: Entry, fields: dict, authors: list, primaryclass: Optional[str]
):
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


async def _resolve_by_doi(providers, doi: str) -> Optional[dict]:
    """Resolve a DOI to structured venue data via CrossRef, then OpenAlex."""
    doi_query = ProviderQuery(doi=doi)  # empty title => providers skip title search
    cr_task = _lookup(providers.crossref, doi_query)
    oa_task = _lookup(providers.openalex, doi_query)

    cr_res, oa_res = await asyncio.gather(cr_task, oa_task)
    return cr_res.published_data or oa_res.published_data


# Method-based confidence: *how* the venue was matched is the main reliability
# signal — an exact arXiv-ID / DOI match is trustworthy; a fuzzy title search
# (especially OpenAlex, the last resort) is less so.
_SOURCE_CONFIDENCE = {
    "doi": 1.0,  # exact DOI resolution
    "journal_ref": 0.97,  # author-declared venue on arXiv
    "semanticscholar": 0.95,  # exact arXiv-ID lookup
    "dblp": 0.85,  # title search (authoritative for CS)
    "crossref": 0.80,  # title search
    "openalex": 0.75,  # last-resort title search
}
# Matches below this are flagged for review rather than applied.
_MIN_CONFIDENCE = float(os.environ.get("BIBCLEANER_MIN_CONFIDENCE", "0.8"))


async def resolve_entry(
    client: httpx2.AsyncClient,
    fields: dict,
    provider_registry: ProviderRegistry = None,
) -> dict:
    """Resolve an entry's published venue, with a confidence score.

    Returns a dict with keys: arxiv_id, data (venue dict | None), confidence
    (0..1), source (which API matched it), canonical_authors, primaryclass,
    preprint_authors.  Used by both enrich_entry and the evaluation harness.
    """
    if provider_registry is None:
        provider_registry = ProviderRegistry(client)
    out = {
        "arxiv_id": extract_arxiv_id(fields),
        "data": None,
        "confidence": 0.0,
        "source": None,
        "canonical_authors": [],
        "primaryclass": None,
        "preprint_authors": [],
    }
    arxiv_id = out["arxiv_id"]
    if not arxiv_id:
        return out

    title = fields.get("title", "")
    raw_author = fields.get("author", "")
    authors = [
        a.strip()
        for a in re.split(r"\band\b", raw_author, flags=re.IGNORECASE)
        if a.strip()
    ]
    year = fields.get("year")

    # Step 1: arXiv API — canonical authors, category, declared venue.
    arxiv_res = await _lookup(
        provider_registry.arxiv,
        ProviderQuery(title=title, authors=authors, year=year, arxiv_id=arxiv_id),
    )
    out["canonical_authors"] = arxiv_res.canonical_authors
    out["primaryclass"] = arxiv_res.primaryclass
    doi = fields.get("doi") or arxiv_res.doi

    tquery = ProviderQuery(title=title, authors=authors, year=year, arxiv_id=arxiv_id)
    data: Optional[dict] = None
    source: Optional[str] = None

    # Step 2: DOI-first exact resolution.
    if doi:
        data = await _resolve_by_doi(provider_registry, doi)
        if data:
            source = "doi"

    dblp_res = ProviderResult()
    cr_res = ProviderResult()
    ss_res = ProviderResult()
    oa_res = ProviderResult()

    # Step 3: Title-based lookups — only if DOI didn't find a match.
    if data is None:
        dblp_task = _lookup(provider_registry.dblp, tquery)
        crossref_task = _lookup(provider_registry.crossref, tquery)
        dblp_res, cr_res = await asyncio.gather(dblp_task, crossref_task)

        if dblp_res.published_data:
            data, source = dblp_res.published_data, "dblp"
        elif cr_res.published_data:
            data, source = cr_res.published_data, "crossref"

    # Steps 4 & 5: SS + OpenAlex — only if no published venue yet and
    # DBLP/CrossRef didn't recognise the entry at all.
    if data is None and not (dblp_res.matched or cr_res.matched):
        ss_task = _lookup(provider_registry.semanticscholar, tquery)
        openalex_task = _lookup(provider_registry.openalex, tquery)
        ss_res, oa_res = await asyncio.gather(ss_task, openalex_task)

        if ss_res.published_data:
            data, source = ss_res.published_data, "semanticscholar"
        elif oa_res.published_data:
            data, source = oa_res.published_data, "openalex"

    # Step 6: arXiv journal_ref fallback (known venues only).
    if data is None and arxiv_res.journal_ref:
        jr = _data_from_journal_ref(
            arxiv_res.journal_ref, arxiv_res.year or year, arxiv_res.canonical_authors
        )
        if jr:
            data, source = jr, "journal_ref"

    if data is not None:
        _prefer_canonical(data, arxiv_res.canonical_authors)
        out["data"] = data
        out["source"] = source
        out["confidence"] = _SOURCE_CONFIDENCE.get(source, 0.0)

    out["preprint_authors"] = (
        arxiv_res.canonical_authors
        or dblp_res.preprint_authors
        or ss_res.preprint_authors
    )
    return out


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
sem = asyncio.Semaphore(20)


async def enrich_limited(client, entry, provider_registry=None):
    async with sem:
        return await enrich_entry(client, entry, provider_registry)


async def enrich_entry(
    client: httpx2.AsyncClient,
    entry: Entry,
    provider_registry: ProviderRegistry = None,
) -> bool:
    """Enrich an arXiv preprint entry with published venue and full author data.

    Confident matches are applied; low-confidence candidates are left as clean
    ``@misc`` preprints with a ``note`` flagging the possible venue, so a wrong
    venue is never written silently.  Returns True if the entry changed.
    """
    fields = {f.key: f.value for f in entry.fields}
    res = await resolve_entry(client, fields, provider_registry)

    arxiv_id = res["arxiv_id"]
    if not arxiv_id:
        return False

    data = res["data"]
    confidence = res["confidence"]

    # Confident published match -> apply it.
    if data is not None and confidence >= _MIN_CONFIDENCE:
        _apply(entry, data, fields)
        logger.info(f"[published:{res['source']} {confidence:.2f}] {entry.key}")
        return True

    # Otherwise leave a clean @misc preprint...
    _normalize_preprint(entry, fields, res["preprint_authors"], res["primaryclass"])

    # ...and if we *did* find a shaky candidate, flag it for manual review.
    if data is not None:
        venue = data.get("booktitle") or data.get("journal") or "?"
        _set_field(
            entry,
            "note",
            f"bibcleaner: possible match — {venue} ({data.get('year') or '?'}), "
            f"confidence {confidence:.2f} via {res['source']}; verify before using",
        )
        logger.info(f"[low-confidence:{res['source']} {confidence:.2f}] {entry.key}")
        return True

    changed = bool(res["preprint_authors"]) or "eprint" not in fields
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
