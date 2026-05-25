import argparse
from .parser import load_bib, save_bib
from .enrich import process_entries

def main():
    parser = argparse.ArgumentParser(description="Clean and upgrade BibTeX files")
    parser.add_argument("input", help="Input .bib file")
    parser.add_argument("output", help="Output .bib file")

    args = parser.parse_args()

    db = load_bib(args.input)
    db = process_entries(db)
    save_bib(db, args.output)

    print("Done cleaning BibTeX ✔")

if __name__ == "__main__":
    main()