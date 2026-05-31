import bibtexparser
from tqdm import tqdm

from .enricher import enrich_entry, normalize_venue_fields, extract_arxiv_id
from .providers.arxiv import fetch_many as _arxiv_fetch_many
from .latex import protect_title_caps
from .dedup import deduplicate
from .citations import prune_unused, rewrite_tex as rewrite_tex_files
from .keys import normalize_keys as normalize_entry_keys


def _protect_caps(entry) -> bool:
    """Brace-protect capitalization in the entry's title. Returns True if changed."""
    for f in entry.fields:
        if f.key.lower() == "title":
            new = protect_title_caps(f.value)
            if new != f.value:
                f.value = new
                return True
    return False


def process_bibliography_content(
    content,
    *,
    enrich: bool = True,
    protect_caps: bool = True,
    dedup: bool = False,
    cited_keys=None,
    normalize_keys: bool = False,
    rewrite_tex=None,
    progress=None,
) -> str:
    """Parse, clean, and return a BibTeX string.

    Parameters
    ----------
    content        : UTF-8 bytes or str of BibTeX source.
    enrich         : query online sources to replace arXiv preprints (default on).
    protect_caps   : brace-protect title capitalization, e.g. {BERT} (default on).
    dedup          : merge duplicate entries; the key remap is printed.
    cited_keys     : if given (a set of keys), keep only entries cited there.
    normalize_keys : rewrite citation keys to a consistent surnameYYYYword form.
    rewrite_tex    : if given (a list of .tex paths), apply the resulting key
                     remap (dedup + normalization) to those files in place.
    progress       : optional callable(done, total) invoked per processed entry.
    """
    if isinstance(content, bytes):
        try:
            bibtex_str = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("Input file must be UTF-8 encoded") from exc
    else:
        bibtex_str = content

    if not bibtex_str.strip():
        raise ValueError("Input bibliography is empty")

    library = bibtexparser.parse_string(bibtex_str)
    entries = [b for b in library.blocks if isinstance(b, bibtexparser.model.Entry)]

    # ---- 0. Warm the arXiv cache in one batched request (avoids per-entry
    #         calls that trip arXiv's rate limit). ----
    if enrich:
        arxiv_ids = []
        for entry in entries:
            aid = extract_arxiv_id({f.key: f.value for f in entry.fields})
            if aid:
                arxiv_ids.append(aid)
        if arxiv_ids:
            try:
                _arxiv_fetch_many(arxiv_ids)
            except Exception as exc:  # never let prefetch block processing
                print(f"  Warning: arXiv prefetch failed: {exc}")

    # ---- 1. Enrich, normalize venues, protect capitalization ----
    enriched = venue_normalized = caps = 0
    total = len(entries)
    iterator = tqdm(entries, desc="Processing entries") if enrich else entries
    for i, entry in enumerate(iterator):
        try:
            if enrich and enrich_entry(entry):
                enriched += 1
            elif normalize_venue_fields(entry):
                venue_normalized += 1
        except Exception as exc:
            print(f"  Warning: could not process {entry.key}: {exc}")
        if protect_caps and _protect_caps(entry):
            caps += 1
        if progress is not None:
            try:
                progress(i + 1, total)
            except Exception:
                pass

    # Second venue pass so enriched entries also get the canonical form.
    for entry in entries:
        normalize_venue_fields(entry)

    print(
        f"Done: {enriched} arXiv entrie(s) enriched, "
        f"{venue_normalized} venue name(s) normalized, "
        f"{caps} title(s) capitalization-protected."
    )

    # The full key set before any merging/pruning — used to flag truly missing
    # citations (keys cited in LaTeX that exist in no entry at all).
    original_keys = {e.key for e in entries}

    # ---- 2. Deduplicate (before pruning, so merged entries can survive) ----
    remap = {}
    if dedup:
        entries, remap = deduplicate(entries)
        if remap:
            print(f"Merged {len(remap)} duplicate entrie(s); update your \\cite keys:")
            for old, new in sorted(remap.items()):
                print(f"  {old} -> {new}")

    # ---- 3. Prune to cited entries ----
    if cited_keys is not None:
        if "*" not in cited_keys:
            missing = sorted(k for k in cited_keys if k not in original_keys)
            if missing:
                print(
                    f"Warning: {len(missing)} cited key(s) missing from the .bib: "
                    f"{', '.join(missing)}"
                )
        # A \cite of a key that was merged away should keep its surviving entry.
        effective = set(cited_keys)
        for old in cited_keys:
            if old in remap:
                effective.add(remap[old])
        entries, dropped = prune_unused(entries, effective)
        if dropped:
            print(f"Pruned {len(dropped)} uncited entrie(s).")

    # ---- 4. Normalize citation keys ----
    key_remap = {}
    if normalize_keys:
        key_remap = normalize_entry_keys(entries)
        if key_remap:
            print(f"Normalized {len(key_remap)} citation key(s).")

    # ---- 5. Rewrite .tex citations with the full remap (dedup + normalization) ----
    if rewrite_tex:
        final_remap = dict(key_remap)
        for dropped_key, survivor in remap.items():  # remap = dedup result
            final_remap[dropped_key] = key_remap.get(survivor, survivor)
        counts = rewrite_tex_files(rewrite_tex, final_remap)
        total_refs = sum(counts.values())
        if total_refs:
            print(
                f"Rewrote {total_refs} citation reference(s) across "
                f"{len(counts)} file(s)."
            )

    # ---- 6. Rebuild the library if entry set changed ----
    if cited_keys is not None or dedup:
        out = bibtexparser.Library()
        for block in library.blocks:
            if not isinstance(block, bibtexparser.model.Entry):
                out.add(block)  # preserve @string / @preamble / comments
        out.add(entries)
        library = out

    return bibtexparser.write_string(library)


def process_bibliography(input_path: str, output_path: str, **options):
    """Parse, clean, and save the bibliography. See process_bibliography_content."""
    print(f"Reading {input_path}...")

    with open(input_path, "r", encoding="utf-8") as fh:
        bibtex_str = fh.read()

    print("Starting processing...")
    cleaned_bib = process_bibliography_content(bibtex_str, **options)
    print(f"Writing to {output_path}...")

    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(cleaned_bib)

    print(f"Saved to {output_path}")
