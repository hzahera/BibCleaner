# BibCleaner

BibCleaner is a lightweight Python toolkit for cleaning and enriching BibTeX files.

## Features

- Replace arXiv entries with published venue metadata when available
- Expand author lists using Semantic Scholar author metadata
- Read and write ".bib" files using `bibtexparser`
- Gracefully skip entries when metadata is unavailable
- Command-line interface for batch BibTeX cleaning

## Install

```bash
pip install -r requirements.txt
pip install -e .
```

## Usage

```bash
bibcleaner input.bib output.bib
```

Or run directly with Python:

```bash
python -m bibcleaner.cli input.bib output.bib
```

## Requirements

- `bibtexparser`
- `requests`
- `tqdm`

## Notes

BibCleaner is intended for BibTeX collections with arXiv entries and can improve citation metadata by leveraging Semantic Scholar lookup results.
