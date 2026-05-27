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

from . import dblp, crossref
from .api import fetch_by_arxiv_id
from .arxiv_api import fetch as fetch_arxiv
from .openalex import OpenAlexClient
from .venues import normalize_or_keep

logger = logging.getLogger(__name__)

_ARXIV_VENUES = frozenset({"arxiv", "arxiv.org", "corr", "arxiv e-prints", ""})
_ARXIV_FIELDS = {"eprint", "archiveprefix", "primaryclass"}

_oa_client = OpenAlexClient()


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
# Per-source helpers
# ---------------------------------------------------------------------------

def _is_published_ss(paper: dict) -> bool:
    pub_types = [t.lower() for t in (paper.get("publicationTypes") or [])]
    if pub_types == ["preprint"]:
        return False
    venue = (
        (paper.get("publicationVenue") or {}).get("name")
        or paper.get("venue")
        or ""
    ).lower().strip()
    return venue not in _ARXIV_VENUES and "arxiv" not in venue


def _ss_to_data(paper: dict) -> Optional[dict]:
    pub_venue = paper.get("publicationVenue") or {}
    venue_type = (pub_venue.get("type") or "").lower()
    venue_name = pub_venue.get("name") or paper.get("venue") or ""
    journal_obj = paper.get("journal") or {}
    journal_is_arxiv = "arxiv" in (journal_obj.get("name") or "").lower()

    _CONF = {"proceedings", "conference", "symposium", "workshop", "meeting"}
    is_conf = "conference" in venue_type or any(h in venue_name.lower() for h in _CONF)

    doi = (paper.get("externalIds") or {}).get("DOI") or ""
    if "arxiv" in doi.lower():
        doi = None

    data: dict = {
        "year": paper.get("year"),
        "doi": doi or None,
        "authors": [a["name"] for a in (paper.get("authors") or []) if a.get("name")],
        "pages": journal_obj.get("pages") if not journal_is_arxiv else None,
        "volume": str(journal_obj["volume"]) if journal_obj.get("volume") and not journal_is_arxiv else None,
    }
    if is_conf:
        data["entry_type"] = "inproceedings"
        data["booktitle"] = venue_name
    else:
        data["entry_type"] = "article"
        data["journal"] = journal_obj.get("name") or venue_name

    return data


def _oa_to_data(normalized: dict) -> Optional[dict]:
    venue = normalized.get("journal") or normalized.get("booktitle") or ""
    if "arxiv" in venue.lower():
        return None
    return normalized


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

    logger.debug(f"Processing {entry.key} (arXiv:{arxiv_id})")

    # ---- Step 1: arXiv API — canonical authors and category ----
    arxiv_meta = fetch_arxiv(arxiv_id)
    canonical_authors: list = (arxiv_meta or {}).get("authors", [])
    primaryclass: Optional[str] = (arxiv_meta or {}).get("primaryclass")

    # ---- Step 2: DBLP — one request, published + preprint split ----
    dblp_result = dblp.lookup(title, authors, year)
    dblp_pub = dblp_result["published"]
    dblp_pre = dblp_result["preprint"]

    if dblp_pub:
        data = dblp.normalize(dblp_pub)
        # Prefer canonical arXiv authors over DBLP if DBLP has fewer
        if _better_authors(canonical_authors, _format_authors(data.get("authors", []))):
            data["authors"] = canonical_authors
        _apply(entry, data, fields)
        logger.info(f"[DBLP] {entry.key} → {dblp_pub.get('venue')}")
        return True

    # ---- Step 3: CrossRef — title search ----
    cr_item = crossref.best_match(title, authors, year)
    if cr_item:
        data = crossref.normalize(cr_item)
        if data:
            if _better_authors(canonical_authors, _format_authors(data.get("authors", []))):
                data["authors"] = canonical_authors
            _apply(entry, data, fields)
            logger.info(f"[CrossRef] {entry.key} → {cr_item.get('container-title', ['?'])[0]}")
            return True

    # ---- Step 4: Semantic Scholar — arXiv ID (skip when DBLP/CrossRef found no venue) ----
    dblp_or_cr_knows = dblp_pub is not None or dblp_pre is not None or cr_item is not None
    paper = None
    if not dblp_or_cr_knows:
        paper = fetch_by_arxiv_id(arxiv_id)
        if paper and _is_published_ss(paper):
            data = _ss_to_data(paper)
            if data:
                if _better_authors(canonical_authors, _format_authors(data.get("authors", []))):
                    data["authors"] = canonical_authors
                _apply(entry, data, fields)
                logger.info(f"[SS] {entry.key}")
                return True

        # ---- Step 5: OpenAlex — title search ----
        oa_work = _oa_client.best_match(title, authors, year)
        if oa_work:
            normalized = _oa_client.normalize_work(oa_work)
            data = _oa_to_data(normalized) if normalized else None
            if data:
                if _better_authors(canonical_authors, _format_authors(data.get("authors", []))):
                    data["authors"] = canonical_authors
                _apply(entry, data, fields)
                logger.info(f"[OA] {entry.key}")
                return True

    # ---- Step 6: Normalize preprint — best available author data ----
    # Priority: arXiv API > DBLP preprint > SS
    best_authors = canonical_authors
    if not best_authors and dblp_pre:
        best_authors = dblp.normalize(dblp_pre).get("authors", [])
    if not best_authors and paper:
        best_authors = [a["name"] for a in (paper.get("authors") or []) if a.get("name")]

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
