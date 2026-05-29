import bibtexparser
from tqdm import tqdm
from .enricher import enrich_entry, normalize_venue_fields


def process_bibliography_content(content: str | bytes) -> str:
    """Parse, enrich, and return a BibTeX string.

    Accepts UTF-8 encoded bytes or a plain text string.
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

    enriched = venue_normalized = 0
    for entry in tqdm(entries, desc="Processing entries"):
        try:
            if enrich_entry(entry):
                enriched += 1
            elif normalize_venue_fields(entry):
                # Non-arXiv entry: just normalize the venue name
                venue_normalized += 1
        except Exception as exc:
            print(f"  Warning: could not process {entry.key}: {exc}")

    # Venue normalization also runs on freshly enriched entries
    # (already applied inside _apply), but run a second pass on everything
    # to catch entries that were enriched but whose venue came from the
    # user's original data rather than the API.
    for entry in entries:
        normalize_venue_fields(entry)

    total_changed = enriched + venue_normalized
    print(
        f"Done: {enriched} arXiv entrie(s) enriched, "
        f"{venue_normalized} additional venue name(s) normalized "
        f"({total_changed} total changes)."
    )

    return bibtexparser.write_string(library)


def process_bibliography(input_path: str, output_path: str):
    """Parse, enrich, and save the bibliography."""
    print(f"Reading {input_path}...")

    with open(input_path, "r", encoding="utf-8") as fh:
        bibtex_str = fh.read()

    print("Starting enrichment...")
    cleaned_bib = process_bibliography_content(bibtex_str)
    print(f"Writing to {output_path}...")

    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(cleaned_bib)

    print(f"Saved to {output_path}")
