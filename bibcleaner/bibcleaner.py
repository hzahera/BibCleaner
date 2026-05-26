import bibtexparser
from tqdm import tqdm
from .enricher import enrich_entry

def process_bibliography(input_path, output_path):
    """Parse, enrich, and save the bibliography."""
    print(f"Reading {input_path}...")
    
    with open(input_path, 'r', encoding='utf-8') as bibtex_file:
        bibtex_str = bibtex_file.read()
        
    library = bibtexparser.parse_string(bibtex_str)
    
    entries = [b for b in library.blocks if isinstance(b, bibtexparser.model.Entry)]
    print(f"Loaded {len(entries)} entries. Starting enrichment...")
    
    # Process only the entries
    for block in tqdm(entries, desc="Enriching entries"):
        try:
            # enrich_entry modifies the block in-place
            enrich_entry(block)
        except Exception as e:
            print(f"Error processing entry {block.key}: {e}")
            
    print(f"Writing to {output_path}...")
    with open(output_path, 'w', encoding='utf-8') as bibtex_file:
        bibtex_file.write(bibtexparser.write_string(library))
        
    print(f"Successfully saved enriched bibliography to {output_path}")