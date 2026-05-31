"""Duplicate-entry detection and merging (no network).

Two entries are considered the same work when they share a DOI, an arXiv ID,
or a normalized title + year.  The richest entry (published over preprint, more
fields, has a DOI) is kept; missing fields are merged in from the duplicates.
"""

import re
import logging
from typing import Optional

from bibtexparser.model import Entry

from .enricher import extract_arxiv_id

logger = logging.getLogger(__name__)


def _fields(entry: Entry) -> dict:
    return {f.key.lower(): f.value for f in entry.fields}


def _norm_title(title: str) -> str:
    t = (title or "").lower()
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return " ".join(t.split())


def _doi(fields: dict) -> Optional[str]:
    doi = (fields.get("doi") or "").strip()
    doi = doi.replace("https://doi.org/", "").replace("http://doi.org/", "")
    doi = doi.replace("doi:", "").strip().lower()
    return doi or None


def _identity(entry: Entry):
    """Return a hashable dedup identity, or None if there's nothing to match on."""
    f = _fields(entry)
    doi = _doi(f)
    if doi:
        return ("doi", doi)
    arxiv = extract_arxiv_id(f)
    if arxiv:
        return ("arxiv", arxiv)
    title = _norm_title(f.get("title"))
    if title:
        return ("title", title, (f.get("year") or "").strip())
    return None


def _richness(entry: Entry) -> int:
    """Heuristic score — higher means 'keep this one'."""
    f = _fields(entry)
    score = len(entry.fields)
    if entry.entry_type.lower() != "misc":
        score += 100  # a published entry beats a preprint
    if _doi(f):
        score += 10
    journal = (f.get("journal") or "").lower()
    if f.get("booktitle") or (journal and "arxiv" not in journal):
        score += 20
    return score


def _merge_into(keep: Entry, drop: Entry) -> None:
    """Copy fields present in *drop* but missing in *keep*.

    Skips fields that would conflict with the keeper's entry type (a journal on
    an @inproceedings, a booktitle on an @article) and never imports an
    arXiv-preprint venue string.
    """
    have = {f.key.lower() for f in keep.fields}
    keep_type = keep.entry_type.lower()
    blocked = {"journal"} if keep_type == "inproceedings" else (
        {"booktitle"} if keep_type == "article" else set()
    )
    for f in drop.fields:
        key = f.key.lower()
        if key in have or key in blocked:
            continue
        if key in ("journal", "booktitle") and "arxiv" in (f.value or "").lower():
            continue
        keep.fields.append(f)
        have.add(key)


def deduplicate(entries: list) -> tuple:
    """Merge duplicate entries.

    Returns ``(kept_entries, remap)`` where *remap* maps each dropped citation
    key to the key of the entry it was merged into.  First-seen order of the
    surviving entries is preserved.
    """
    best: dict = {}      # identity -> kept Entry
    order: list = []     # surviving entries, in first-seen order
    remap: dict = {}     # dropped key -> surviving key

    for entry in entries:
        ident = _identity(entry)
        if ident is None or ident not in best:
            if ident is not None:
                best[ident] = entry
            order.append(entry)
            continue

        incumbent = best[ident]
        if _richness(entry) > _richness(incumbent):
            # The new entry wins: keep it, fold the incumbent's extras in.
            _merge_into(entry, incumbent)
            order[order.index(incumbent)] = entry
            best[ident] = entry
            remap[incumbent.key] = entry.key
            for old, new in list(remap.items()):
                if new == incumbent.key:
                    remap[old] = entry.key
        else:
            _merge_into(incumbent, entry)
            remap[entry.key] = incumbent.key

    return order, remap
