import bibtexparser


def load_bib(path):
    """Load a BibTeX database from a file path."""
    with open(path, encoding="utf-8") as f:
        return bibtexparser.load(f)


def save_bib(db, path):
    """Write a BibTeX database to a file path."""
    with open(path, "w", encoding="utf-8") as f:
        bibtexparser.dump(db, f)
