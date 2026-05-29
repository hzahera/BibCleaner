# BibCleaner

**Developed for researchers, by researchers.**

**A Python toolkit for automated BibTeX metadata enrichment and venue normalization**

[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

---

## Overview

BibCleaner automatically cleans and enriches BibTeX bibliographies. It detects arXiv preprint entries and replaces them with their published conference or journal metadata, expands incomplete author lists, and normalizes all venue names to a consistent full-name format — across the entire `.bib` file, not just the entries it enriched.

---

## Features

**Preprint → Published venue replacement**
- Detects arXiv entries from `eprint`, `archiveprefix`, or a `journal = {arXiv preprint arXiv:XXXX}` field
- Replaces them with the correct `@inproceedings` or `@article` entry including `booktitle`/`journal`, `year`, `pages`, `volume`, and `doi`
- Entries confirmed as still-unpublished are converted to clean `@misc` preprints with `eprint`, `archiveprefix`, `primaryclass`, and `url` fields

**Full author list expansion**
- Expands truncated lists (`et al.`, `others`) and silently incomplete lists using canonical author data
- arXiv API is used as the primary source for author names (exact as submitted by the authors)

**Venue name normalization**
- Runs on every entry in the file, including ones that were never arXiv preprints
- Maps all known abbreviations and source-specific variants to a single canonical full name

| Input (any format) | Canonical output |
|---|---|
| `NeurIPS` / `NIPS` / `neural inf process syst` | `Advances in Neural Information Processing Systems` |
| `ICLR` | `International Conference on Learning Representations` |
| `ICML` | `International Conference on Machine Learning` |
| `ACL` | `Annual Meeting of the Association for Computational Linguistics` |
| `TACL` | `Transactions of the Association for Computational Linguistics` |
| `CVPR` | `IEEE/CVF Conference on Computer Vision and Pattern Recognition` |

---

## Data Sources

BibCleaner queries four sources in order, stopping as soon as a published venue is found:

| Priority | Source | Used for |
|---|---|---|
| 1 | **arXiv API** | Canonical author names and `primaryclass` for every arXiv entry |
| 2 | **DBLP** | Published venue lookup — fast, no rate limits, authoritative for CS |
| 3 | **CrossRef** | Journal and proceedings metadata; covers ACM, IEEE, Springer |
| 4 | **Semantic Scholar** | Fallback arXiv ID lookup when DBLP and CrossRef find nothing |
| 5 | **OpenAlex** | Last-resort title search |

---

## Installation (uv)

### 1. Clone the repository

```bash
git clone https://github.com/hzahera/bib-cleaner.git
cd bib-cleaner
```

### 2. Install dependencies and create environment

```bash
uv sync
```

### 3. Run commands with uv

```bash
uv run bibcleaner input.bib -o output.bib
uv run uvicorn bibcleaner.web_api:app --reload
uv run pytest
```

### Optional: pip workflow

If you prefer pip/venv, the existing workflow still works:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

---

## Usage

### Command line

```bash
uv run bibcleaner input.bib -o output.bib
```

If `-o` is omitted the enriched file is saved as `enriched_<input>.bib` in the same directory.

### Python module

```bash
uv run python -m bibcleaner.cli input.bib -o output.bib
```

### Programmatic API

```python
from bibcleaner import process_bibliography, process_bibliography_content

process_bibliography("references.bib", "references_enriched.bib")

cleaned = process_bibliography_content("@article{demo,title={Example}}")
print(cleaned)
```

### Web API

Start the API locally:

```bash
uv run uvicorn bibcleaner.web_api:app --host 0.0.0.0 --port 8000 --reload
```

Health check:

```bash
curl http://localhost:8000/health
```

Clean a bibliography upload:

```bash
curl -X POST http://localhost:8000/clear-bib \
  -F "file=@references.bib" \
  -o cleaned_references.bib
```

The route `/clean-bib` is also available as an alias.

---

## Example

**Input**

```bibtex
@article{madaan2023selfrefine,
  title   = {Self-Refine: Iterative Refinement with Self-Feedback},
  author  = {Madaan, Aman and Tandon, Niket and others},
  journal = {arXiv preprint arXiv:2303.17651},
  year    = {2023}
}

@article{llmbar2024,
  title   = {RouterBench: A Benchmark for Multi-LLM Routing Systems},
  author  = {Hu, Qitian Jason and Bieker, Jacob and Li, Xiuyu},
  journal = {arXiv preprint arXiv:2403.12031},
  year    = {2024}
}

@inproceedings{existing,
  title     = {Attention Is All You Need},
  author    = {Vaswani, Ashish and others},
  booktitle = {NeurIPS},
  year      = {2017}
}
```

**Output**

```bibtex
@inproceedings{madaan2023selfrefine,
  title     = {Self-Refine: Iterative Refinement with Self-Feedback},
  author    = {Aman Madaan and Niket Tandon and Prakhar Gupta and ...},
  booktitle = {Advances in Neural Information Processing Systems},
  year      = {2023}
}

@misc{llmbar2024,
  title         = {RouterBench: A Benchmark for Multi-LLM Routing Systems},
  author        = {Qitian Jason Hu and Jacob Bieker and Xiuyu Li and Nan Jiang and ...},
  year          = {2024},
  eprint        = {2403.12031},
  archiveprefix = {arXiv},
  primaryclass  = {cs.LG},
  url           = {https://arxiv.org/abs/2403.12031}
}

@inproceedings{existing,
  title     = {Attention Is All You Need},
  author    = {Vaswani, Ashish and others},
  booktitle = {Advances in Neural Information Processing Systems},
  year      = {2017}
}
```

The third entry was never an arXiv preprint — BibCleaner normalized its `booktitle` from `NeurIPS` to the canonical full name automatically.

---

## Optional API keys

All data sources work without a key. Keys unlock higher rate limits for large bibliographies.

| Variable | Service | Where to apply |
|---|---|---|
| `S2_API_KEY` | Semantic Scholar | <https://www.semanticscholar.org/product/api#api-key-form> |
| `CROSSREF_MAILTO` | CrossRef polite pool | Any valid email address |

```bash
# macOS / Linux
export S2_API_KEY=your_key_here
export CROSSREF_MAILTO=you@example.com

# Windows Command Prompt
set S2_API_KEY=your_key_here
set CROSSREF_MAILTO=you@example.com
```

---
 (file + in-memory processing)
├── cli.py          Command-line interface
├── crossref.py     CrossRef title search client
├── dblp.py         DBLP title search client
├── enricher.py     Enrichment pipeline logic
├── openalex.py     OpenAlex title search client
├── venues.py       Venue name normalization table (~35 venues)
└── web_api.py      FastAPI service routes (/health, /clear-bib
│   ├─ Yes →  Step 1: arXiv API  (fetch canonical authors + primaryclass)
│   │         Step 2: DBLP       (find published venue — one request)
│   │         Step 3: CrossRef   (title search fallback)
│  Docker

Build and run the API image:

```bash
docker build -t bibcleaner-api .
docker run --rm -p 8000:8000 bibcleaner-api
```

Then test:

```bash
curl http://localhost:8000/health

```

Request example:

```bash
curl -X POST http://localhost:8000/clear-bib -F "file=@/path/to/file/file.bib" -o /path/to/output/file/output.bib
```

##  │         Step 4: Semantic Scholar (arXiv ID lookup)
│   │         Step 5: OpenAlex   (last-resort title search)
│   │         Step 6: If no venue found — normalize as clean @misc preprint
│   │
│   └─ No  →  Normalize booktitle / journal to canonical full name
│
└─ Write enriched .bib file
```

---

## Project structure

```
bibcleaner/
├── api.py          Semantic Scholar arXiv ID client
├── arxiv_api.py    arXiv Atom API client (canonical authors)
├── bibcleaner.py   Main orchestration
├── cli.py          Command-line interface
├── crossref.py     CrossRef title search client
├── dblp.py         DBLP title search client
├── enricher.py     Enrichment pipeline logic
├── openalex.py     OpenAlex title search client
└── venues.py       Venue name normalization table (~35 venues)
```

---

## Contributing

Contributions and feedback are welcome. Please open an issue or pull request on GitHub.

## License

MIT — see [LICENSE](LICENSE).
