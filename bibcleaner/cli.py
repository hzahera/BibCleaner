import argparse
import sys
import os
from .bibcleaner import process_bibliography

def main():
    parser = argparse.ArgumentParser(
        description="Automated BibTeX metadata enrichment using Semantic Scholar API."
    )
    parser.add_argument(
        "input",
        help="Path to the input .bib file"
    )
    parser.add_argument(
        "-o", "--output",
        help="Path to save the enriched .bib file (defaults to enriched_<input>)",
        default=None
    )
    
    args = parser.parse_args()
    
    input_file = args.input
    output_file = args.output
    
    if not output_file:
        dirname = os.path.dirname(input_file)
        basename = os.path.basename(input_file)
        output_file = os.path.join(dirname, f"enriched_{basename}")
        
    try:
        process_bibliography(input_file, output_file)
    except KeyboardInterrupt:
        print("\nProcess interrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\nAn error occurred: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()