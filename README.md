<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="logo-dark.png">
  <img src="logo.png" alt="BibCleaner" width="440">
</picture>

### A tool that you run before every submission.

**A Python toolkit for automated BibTeX metadata enrichment and venue normalization**

_Developed by researchers, to researchers._

[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

</div>

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
| `NeurIPS` / `NIPS` / `neural inf process syst` | `Advances in Neural Information Processing Systems (NeurIPS)` |
| `ICLR` | `International Conference on Learning Representations (ICLR)` |
| `ICML` | `International Conference on Machine Learning (ICML)` |
| `ACL` | `Annual Meeting of the Association for Computational Linguistics (ACL)` |
| `TACL` | `Transactions of the Association for Computational Linguistics (TACL)` |
| `CVPR` | `IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR)` |

**LaTeX-friendly cleaning** (all offline — no network needed)
- **Title capitalization protection** — brace-protects acronyms and inter-capped words so sentence-casing styles can't mangle them: `BERT: ... for ImageNet` → `{BERT}: ... for {ImageNet}`. Ordinary Title-Case words are left for the bib style; already-braced text and math (`$...$`) are untouched.
- **Duplicate merging** (`--dedup`) — collapses entries that share a DOI, arXiv ID, or title+year. Keeps the richest (published beats preprint), folds in any missing fields, and prints the `old → new` citation-key remap.
- **Used-citation pruning** (`--keep-cited`) — keeps only entries actually `\cite`d in your `.tex`/`.aux`, and warns about cited keys that have no entry (the dreaded `[?]`). Honours `\nocite{*}`.

---

## Data Sources

Each source is a self-contained `Provider` (in the `providers/` package) exposing a uniform `lookup()`. BibCleaner queries them in order, stopping as soon as a published venue is found:

| Priority | Source | Used for |
|---|---|---|
| 1 | **arXiv API** | Canonical author names, `primaryclass`, and the author-declared venue (`journal_ref` / `doi`) |
| 2 | **DOI lookup** | Exact resolution via CrossRef → OpenAlex when a DOI is known — no fuzzy matching |
| 3 | **DBLP** | Title search — fast, no rate limits, authoritative for CS |
| 4 | **CrossRef** | Title search; journal and proceedings metadata (ACM, IEEE, Springer) |
| 5 | **Semantic Scholar** | Fallback arXiv-ID lookup when DBLP and CrossRef find nothing |
| 6 | **OpenAlex** | Last-resort title search |

When no published venue is found but the authors have declared one on arXiv (`journal_ref`), BibCleaner uses it — but only if it maps to a known canonical venue, so no noisy metadata is ever written.

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

**Options**

| Flag | Effect |
|---|---|
| `-o`, `--output FILE` | Output path (default `enriched_<input>.bib`) |
| `--no-enrich` | Skip online lookups; only clean, format, and normalize (fully offline) |
| `--no-protect-caps` | Disable title capitalization brace-protection |
| `--dedup` | Merge duplicate entries and print the citation-key remapping |
| `--keep-cited FILE ...` | Keep only entries cited in the given `.tex`/`.aux` file(s) |

```bash
# Offline tidy: dedup, prune to what the paper cites, protect capitalization
uv run bibcleaner refs.bib -o refs_clean.bib --no-enrich --dedup --keep-cited paper.tex paper.aux
```

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

Because enrichment is rate-limited and can take a while, uploads are processed
as **background jobs** — submit, poll, then download:

| Method & path | Purpose |
|---|---|
| `GET /health` | Liveness + active-job count |
| `POST /jobs` | Upload a `.bib` (`file=@...`); returns `{ "job_id": ... }`. Optional form fields: `enrich`, `dedup`, `protect_caps` |
| `GET /jobs/{id}` | Job status: `queued` / `processing` / `done` / `error`, with `done`/`total` progress |
| `GET /jobs/{id}/result` | The cleaned `.bib` once status is `done` |
| `POST /clean-bib` | Synchronous convenience endpoint for small uploads (alias `/clear-bib`) |

```bash
# Submit
JOB=$(curl -s -X POST http://localhost:8000/jobs -F "file=@references.bib" | jq -r .job_id)
# Poll
curl -s http://localhost:8000/jobs/$JOB
# Download when done
curl -s http://localhost:8000/jobs/$JOB/result -o cleaned_references.bib
```

**Configuration** (environment variables):

| Variable | Default | Effect |
|---|---|---|
| `ALLOWED_ORIGINS` | `*` | Comma-separated CORS origins (set to your frontend URL in prod) |
| `BIBCLEANER_MAX_ENTRIES` | `500` | Reject uploads with more entries |
| `BIBCLEANER_MAX_BYTES` | `10485760` | Max upload size |
| `BIBCLEANER_RATE_LIMIT` | `30` | Requests per minute per IP |
| `BIBCLEANER_WORKERS` | `2` | Concurrent processing jobs |
| `BIBCLEANER_JOB_TTL` | `3600` | Seconds a finished job (and its result) is kept |
| `BIBCLEANER_CACHE_TTL` | `86400` | Lookup-cache lifetime (repeat arXiv IDs/DOIs are served instantly) |
| `CROSSREF_MAILTO`, `S2_API_KEY` | — | Polite-pool email / API key for upstream sources |

### Deploy to Render

A [`render.yaml`](render.yaml) blueprint is included. Push to GitHub, create a
new **Blueprint** in Render pointing at the repo, then set `CROSSREF_MAILTO`
(and optionally `S2_API_KEY`) in the dashboard. The Dockerfile honours Render's
`$PORT`, and `/health` is wired as the health check.

### Frontend with Docker Compose

Start the full stack from the repository root:

```bash
make compose-up
```

This launches the API container on `http://localhost:8000` and the frontend on `http://localhost:8080`.
The browser-facing frontend sends same-origin requests to `http://localhost:8080/api/clean-bib`, which nginx proxies to the API container.

If you prefer the raw Docker command, use:

```bash
docker compose up --build
```

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
  booktitle = {Advances in Neural Information Processing Systems (NeurIPS)},
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
  booktitle = {Advances in Neural Information Processing Systems (NeurIPS)},
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

## Docker

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
curl -X POST http://localhost:8000/clear-bib \
  -F "file=@/path/to/references.bib" \
  -o cleaned_references.bib
```

---

## How it works

```
For every entry in the .bib file
│
├─ Does it contain an arXiv ID?
│   ├─ Yes →  Step 1: arXiv API  (authors + category + declared journal_ref / doi)
│   │         Step 2: DOI lookup  (CrossRef → OpenAlex, exact — if a DOI is known)
│   │         Step 3: DBLP        (title search — published venue, one request)
│   │         Step 4: CrossRef    (title search)
│   │         Step 5: Semantic Scholar (arXiv-ID lookup)
│   │         Step 6: OpenAlex    (last-resort title search)
│   │         Step 7: journal_ref (author-declared venue, known venues only)
│   │         else → normalize as clean @misc preprint
│   │
│   └─ No  →  Normalize booktitle / journal to canonical full name
│
└─ Write enriched .bib file
```

---

## Project structure

```
bibcleaner/
├── bibcleaner.py       Orchestration (parse → enrich → write; file + in-memory)
├── cli.py              Command-line interface
├── enricher.py         Enrichment pipeline (drives the providers)
├── venues.py           Venue name normalization table (~40 venues)
├── latex.py            Title capitalization brace-protection
├── dedup.py            Duplicate detection + merging
├── citations.py        .tex/.aux citation parsing + pruning
├── cache.py            Thread-safe TTL cache for provider lookups
├── web_api.py          FastAPI service (jobs, rate limiting, CORS)
└── providers/          One module per data source, uniform Provider interface
    ├── provider.py         Provider ABC + ProviderQuery / ProviderResult
    ├── arxiv.py            arXiv Atom API (authors, category, journal_ref, doi)
    ├── dblp.py             DBLP title search
    ├── crossref.py         CrossRef DOI + title search
    ├── semanticscholar.py  Semantic Scholar arXiv-ID lookup
    └── openalex.py         OpenAlex DOI + title search

frontend/               Vite + TypeScript web UI (submit → poll → download)
```

---

## Contributing

Contributions and feedback are welcome. Please open an issue or pull request on GitHub.

## License

MIT — see [LICENSE](LICENSE).
