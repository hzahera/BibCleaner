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


def _rewrite_text(text: str, remap: dict) -> tuple:
    """Rewrite cite-command keys in *text* using *remap*. Returns (new_text, count)."""
    changed = 0

    def _sub(match: "re.Match") -> str:
        nonlocal changed
        full = match.group(0)
        group_start = match.start(1) - match.start(0)
        group_end = match.end(1) - match.start(0)
        pieces = match.group(1).split(",")
        out = []
        for piece in pieces:
            key = piece.strip()
            if key in remap:
                out.append(piece.replace(key, remap[key], 1))
                changed += 1
            else:
                out.append(piece)
        return full[:group_start] + ",".join(out) + full[group_end:]

    return _TEX_CITE.sub(_sub, text), changed


def rewrite_tex(paths, remap: dict) -> dict:
    """Rewrite \\cite-style keys in the given .tex files in place.

    Returns ``{path: n_keys_rewritten}`` for files that were modified.
    """
    if not remap:
        return {}
    counts: dict = {}
    for path in paths:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read()
        except OSError as exc:
            logger.warning(f"Could not read {path}: {exc}")
            continue
        new_text, n = _rewrite_text(text, remap)
        if n:
            try:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(new_text)
                counts[path] = n
            except OSError as exc:
                logger.warning(f"Could not write {path}: {exc}")
    return counts
