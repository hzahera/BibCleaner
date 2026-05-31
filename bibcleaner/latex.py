"""LaTeX-aware cleaning helpers (no network)."""

import re

# lead punctuation | core word | trailing punctuation
_TOKEN = re.compile(r"^(\W*)(.*?)(\W*)$", re.UNICODE)
# Tokens containing these are left untouched (already braced, math, macros).
_SKIP_CHARS = ("$", "{", "}", "\\")


def _needs_protection(core: str) -> bool:
    """True if the token has casing a sentence-casing BibTeX style would destroy.

    Protect acronyms and inter-capped words (BERT, GANs, ImageNet, LaTeX,
    GPT-4) while leaving ordinary Title-Case words (Deep, Learning) for the
    bibliography style to handle.
    """
    if len(core) < 2:
        return False
    return any(c.isupper() for c in core[1:])


def protect_title_caps(title: str) -> str:
    """Brace-protect significant capitalization in a title.

    Example::

        'BERT: Pre-training for ImageNet' -> '{BERT}: Pre-training for {ImageNet}'

    Idempotent — tokens that already contain braces (or math/macros) are left
    untouched, so it is safe to run repeatedly.
    """
    if not title:
        return title

    out = []
    for tok in title.split(" "):
        if not tok or any(ch in tok for ch in _SKIP_CHARS):
            out.append(tok)
            continue
        lead, core, trail = _TOKEN.match(tok).groups()
        if core and _needs_protection(core):
            out.append(f"{lead}{{{core}}}{trail}")
        else:
            out.append(tok)
    return " ".join(out)
