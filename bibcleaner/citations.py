"""Cross-reference a .bib against the LaTeX sources that cite it (no network).

Lets you keep only the entries actually cited in a project (``\\cite`` etc.)
and warn about citation keys that have no matching .bib entry.
"""

import re
import logging

logger = logging.getLogger(__name__)

# Any \...cite... command: \cite, \citep, \citet, \autocite, \parencite,
# \textcite, \nocite, \citeauthor, \citeyear, starred variants, and the
# optional [prenote]/[postnote] arguments biblatex allows.
_TEX_CITE = re.compile(r"\\[a-zA-Z]*cite[a-zA-Z]*\*?\s*(?:\[[^\]]*\]\s*)*\{([^}]*)\}")

# .aux entries: BibTeX's \citation{key} and biblatex's \abx@aux@cite{...}{key}.
_AUX_CITE = re.compile(
    r"\\(?:citation|abx@aux@cite(?:@innote)?)\s*(?:\{[^}]*\}\s*)*\{([^}]*)\}"
)


def _split_keys(group: str) -> list:
    return [k.strip() for k in group.split(",") if k.strip()]


def collect_cited_keys(paths) -> set:
    """Return the set of citation keys referenced across .tex / .aux files.

    A ``\\nocite{*}`` anywhere yields the sentinel ``{'*'}`` meaning "keep all".
    """
    keys: set = set()
    for path in paths:
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                text = fh.read()
        except OSError as exc:
            logger.warning(f"Could not read {path}: {exc}")
            continue
        pattern = _AUX_CITE if path.lower().endswith(".aux") else _TEX_CITE
        for group in pattern.findall(text):
            keys.update(_split_keys(group))
    return keys


def prune_unused(entries: list, cited: set) -> tuple:
    """Keep only entries whose key is in *cited*.

    ``'*'`` in *cited* (from ``\\nocite{*}``) keeps everything.
    Returns ``(kept_entries, dropped_keys)``.
    """
    if "*" in cited:
        return entries, []
    kept, dropped = [], []
    for entry in entries:
        (kept if entry.key in cited else dropped).append(entry)
    return kept, [e.key for e in dropped]


def missing_citations(entries: list, cited: set) -> list:
    """Citation keys referenced in LaTeX but absent from the .bib (sorted)."""
    if "*" in cited:
        return []
    have = {e.key for e in entries}
    return sorted(k for k in cited if k not in have)
