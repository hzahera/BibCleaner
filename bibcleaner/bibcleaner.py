import bibtexparser
from tqdm import tqdm
from .enricher import enrich_entry


def process_bibliography(input_path: str, output_path: str):
    """Parse, enrich, and save the bibliography."""
    print(f"Reading {input_path}...")

    with open(input_path, "r", encoding="utf-8") as fh:
        bibtex_str = fh.read()

    library = bibtexparser.parse_string(bibtex_str)
    entries = [b for b in library.blocks if isinstance(b, bibtexparser.model.Entry)]
    print(f"Loaded {len(entries)} entries. Starting enrichment...")

    enriched = 0
    for entry in tqdm(entries, desc="Enriching entries"):
        try:
            if enrich_entry(entry):
                enriched += 1
        except Exception as exc:
            print(f"  Warning: could not enrich {entry.key}: {exc}")

    print(f"Enriched {enriched}/{len(entries)} arXiv preprint(s).")
    print(f"Writing to {output_path}...")

    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(bibtexparser.write_string(library))

    print(f"Done — saved to {output_path}")
