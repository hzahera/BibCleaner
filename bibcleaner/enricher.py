import re
import logging
from typing import Optional

from bibtexparser.model import Entry, Field

from . import dblp
from .api import fetch_by_arxiv_id
from .openalex import OpenAlexClient

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


# ---------------------------------------------------------------------------
# Apply enrichment data to entry
# ---------------------------------------------------------------------------

def _apply(entry: Entry, data: dict, fields: dict):
    """Write enrichment data dict onto a bibtexparser Entry in-place."""
    entry_type = data.get("entry_type")
    if entry_type:
        entry.entry_type = entry_type

    if entry_type == "inproceedings":
        if data.get("booktitle"):
            _set_field(entry, "booktitle", data["booktitle"])
        _remove_fields(entry, {"journal"})
    elif entry_type == "article":
        if data.get("journal"):
            _set_field(entry, "journal", data["journal"])
        _remove_fields(entry, {"booktitle"})

    if data.get("year"):
        _set_field(entry, "year", str(data["year"]))

    api_authors = data.get("authors") or []
    if api_authors and (_is_truncated(fields.get("author", "")) or not fields.get("author")):
        _set_field(entry, "author", _format_authors(api_authors))

    if data.get("doi"):
        _set_field(entry, "doi", data["doi"])
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


def _normalize_preprint(entry: Entry, fields: dict, authors: list):
    """For papers that are still preprints, clean up the entry in-place:
    convert the messy journal string to proper eprint fields and expand authors.
    """
    arxiv_id = extract_arxiv_id(fields)
    if not arxiv_id:
        return

    # Expand author list when the API source has more names than the current entry
    # (handles both explicit "et al." truncation and silently incomplete lists)
    current = [a.strip() for a in re.split(r"\band\b", fields.get("author", ""), flags=re.IGNORECASE) if a.strip()]
    if authors and (
        _is_truncated(fields.get("author", ""))
        or not fields.get("author")
        or len(authors) > len(current)
    ):
        _set_field(entry, "author", _format_authors(authors))

    # Replace messy journal field with clean eprint fields
    _remove_fields(entry, {"journal", "booktitle"} | _ARXIV_FIELDS)
    _set_field(entry, "eprint", arxiv_id)
    _set_field(entry, "archiveprefix", "arXiv")
    _set_field(entry, "url", f"https://arxiv.org/abs/{arxiv_id}")
    entry.entry_type = "misc"


# ---------------------------------------------------------------------------
# Semantic Scholar helpers
# ---------------------------------------------------------------------------

def _is_published_ss(paper: dict) -> bool:
    pub_types = [t.lower() for t in (paper.get("publicationTypes") or [])]
    if pub_types == ["preprint"]:
        return False
    venue_name = (
        (paper.get("publicationVenue") or {}).get("name")
        or paper.get("venue")
        or ""
    ).lower().strip()
    return venue_name not in _ARXIV_VENUES and "arxiv" not in venue_name


def _ss_to_data(paper: dict) -> Optional[dict]:
    """Convert a Semantic Scholar paper dict to the common enrichment format."""
    pub_venue = paper.get("publicationVenue") or {}
    venue_type = (pub_venue.get("type") or "").lower()
    venue_name = pub_venue.get("name") or paper.get("venue") or ""
    journal_obj = paper.get("journal") or {}
    journal_is_arxiv = "arxiv" in (journal_obj.get("name") or "").lower()

    _CONF_HINTS = {"proceedings", "conference", "symposium", "workshop", "meeting"}
    is_conf = "conference" in venue_type or any(h in venue_name.lower() for h in _CONF_HINTS)

    doi = (paper.get("externalIds") or {}).get("DOI") or ""
    if "arxiv" in doi.lower():
        doi = None

    data: dict = {
        "year": paper.get("year"),
        "doi": doi,
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
# Public API
# ---------------------------------------------------------------------------

def enrich_entry(entry: Entry) -> bool:
    """Replace an arXiv preprint entry with published venue metadata.

    Pipeline:  DBLP  →  Semantic Scholar  →  OpenAlex
    If no published venue is found, the preprint is normalized into a clean
    @misc entry with proper eprint/archiveprefix fields.

    Returns True if the entry was modified in any way.
    """
    fields = {f.key: f.value for f in entry.fields}

    arxiv_id = extract_arxiv_id(fields)
    if not arxiv_id:
        return False

    title = fields.get("title", "")
    raw_authors = fields.get("author", "")
    authors = [a.strip() for a in re.split(r"\band\b", raw_authors, flags=re.IGNORECASE) if a.strip()]
    year = fields.get("year")

    logger.debug(f"Processing {entry.key} (arXiv:{arxiv_id})")

    # ---- 1. DBLP (one request: fast, no rate limit, authoritative for CS) ----
    dblp_result = dblp.lookup(title, authors, year)
    dblp_pub = dblp_result["published"]
    dblp_pre = dblp_result["preprint"]

    if dblp_pub:
        data = dblp.normalize(dblp_pub)
        _apply(entry, data, fields)
        logger.info(f"[DBLP] Enriched: {entry.key} → {dblp_pub.get('venue')}")
        return True

    # If DBLP knows the paper (even as a preprint) we trust its author list
    # and skip the slow SS/OA network calls.
    dblp_knows_paper = dblp_pub is not None or dblp_pre is not None

    paper = None
    if not dblp_knows_paper:
        # ---- 2. Semantic Scholar (arXiv ID lookup) ----
        paper = fetch_by_arxiv_id(arxiv_id)
        if paper and _is_published_ss(paper):
            data = _ss_to_data(paper)
            if data:
                _apply(entry, data, fields)
                logger.info(f"[SS] Enriched: {entry.key}")
                return True

        # ---- 3. OpenAlex (title search) ----
        oa_work = _oa_client.best_match(title, authors, year)
        if oa_work:
            normalized = _oa_client.normalize_work(oa_work)
            data = _oa_to_data(normalized) if normalized else None
            if data:
                _apply(entry, data, fields)
                logger.info(f"[OA] Enriched: {entry.key}")
                return True

    # ---- 4. No published venue — normalize the preprint in-place ----
    fallback_authors = dblp.normalize(dblp_pre)["authors"] if dblp_pre else []
    if not fallback_authors and paper:
        fallback_authors = [a["name"] for a in (paper.get("authors") or []) if a.get("name")]

    _normalize_preprint(entry, fields, fallback_authors)
    changed = bool(fallback_authors) or "eprint" not in fields
    if changed:
        logger.info(f"[preprint] Normalized: {entry.key} (arXiv:{arxiv_id})")
    return changed
