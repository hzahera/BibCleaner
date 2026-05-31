"""Consistent citation-key generation (no network).

Produces keys of the form ``<surname><year><firstTitleWord>`` — e.g.
``vaswani2017attention`` — with deterministic ``a``/``b``/... suffixes on
collision.  Entries that lack an author or year keep their original key.
"""

import re
import string
import itertools
import unicodedata
from typing import Optional

from bibtexparser.model import Entry

_STOP = frozenset(
    "a an the of for and or to in on at with from by via is are be this that "
    "towards toward using how what when where which who why no not".split()
)


def _ascii(text: str) -> str:
    """Lowercase, strip accents, keep only [a-z0-9]."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    folded = decomposed.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]", "", folded.lower())


def _first_surname(author_field: str) -> str:
    first = re.split(r"\band\b", author_field or "", flags=re.IGNORECASE)[0].strip()
    if not first:
        return ""
    if "," in first:
        family = first.split(",", 1)[0]
    else:
        parts = first.split()
        family = parts[-1] if parts else ""
    return _ascii(family)


def _title_word(title: str) -> str:
    for token in re.findall(r"[A-Za-z][A-Za-z0-9-]*", title or ""):
        if token.lower() in _STOP:
            continue
        word = _ascii(token)
        if len(word) >= 3:
            return word
    return ""


def generate_key(entry: Entry) -> Optional[str]:
    """Return a normalized citation key for *entry*, or None if not enough data."""
    fields = {f.key.lower(): f.value for f in entry.fields}
    surname = _first_surname(fields.get("author", ""))
    year_match = re.search(r"\d{4}", fields.get("year", "") or "")
    if not surname or not year_match:
        return None
    return f"{surname}{year_match.group(0)}{_title_word(fields.get('title', ''))}"


def _suffixes():
    """Yield 'a','b',...,'z','aa','ab',... forever."""
    for n in itertools.count(1):
        for combo in itertools.product(string.ascii_lowercase, repeat=n):
            yield "".join(combo)


def _unique(base: str, used: set) -> str:
    if base not in used:
        return base
    for suffix in _suffixes():
        candidate = base + suffix
        if candidate not in used:
            return candidate
    raise RuntimeError("unreachable")  # pragma: no cover


def normalize_keys(entries: list) -> dict:
    """Rekey *entries* in place to consistent keys.

    Returns ``{old_key: new_key}`` for every entry whose key changed.  Entries
    without a generatable key keep their original key (and reserve it so no
    generated key collides with it).
    """
    bases = {id(e): generate_key(e) for e in entries}

    # Reserve the keys of entries we are not going to rekey.
    used = {e.key for e in entries if bases[id(e)] is None}

    remap: dict = {}
    for entry in entries:
        base = bases[id(entry)]
        if base is None:
            continue
        new_key = _unique(base, used)
        used.add(new_key)
        if new_key != entry.key:
            remap[entry.key] = new_key
            entry.key = new_key
    return remap
