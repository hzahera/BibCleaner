# BibCleaner

**Developed for researchers, by researchers.**

**A Python toolkit for automated BibTeX metadata enrichment and validation**

[![Python 3.8+](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

#research #bibtex #bibliography #metadata #academic #citation #python-tool

## Overview

BibCleaner is a lightweight Python toolkit designed for researchers and academics to automatically clean, validate, and enrich BibTeX bibliographies. It leverages the Semantic Scholar API to replace incomplete arXiv references with published venue metadata and expand author attribution information.

## Key Features

✨ **Automated Metadata Enrichment**
- Intelligently replace arXiv preprint entries with their published venue information
- Expand truncated author lists using Semantic Scholar author metadata
- Validate and standardize citation formatting

🔄 **Seamless Integration**
- Read and write `.bib` files using industry-standard `bibtexparser`
- Graceful error handling—skips unavailable metadata without disrupting workflow
- CLI and programmatic Python API support

⚙️ **Research-Ready**
- Batch processing for large bibliography collections
- Built-in progress tracking with `tqdm`
- HTTP request handling with automatic retry logic

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/hzahera/bib-cleaner.git
cd bib-cleaner
```

### 2. Create and activate a virtual environment

```bash
python3 -m venv venv
```

Activate it:

- **macOS / Linux**
  ```bash
  source venv/bin/activate
  ```
- **Windows (Command Prompt)**
  ```bat
  venv\Scripts\activate.bat
  ```
- **Windows (PowerShell)**
  ```powershell
  venv\Scripts\Activate.ps1
  ```

Your prompt should now be prefixed with `(venv)`.

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

This installs:

| Package | Purpose |
|---|---|
| `bibtexparser>=2.0.0` | Parse and write `.bib` files |
| `requests>=2.25.0` | HTTP client for API calls |
| `tqdm>=4.65.0` | Progress bar during enrichment |

### 4. Install the package (editable mode)

```bash
pip install -e .
```

Editable mode means any changes you make to the source files take effect immediately — no reinstall needed.

### Optional: Semantic Scholar API key

By default, BibCleaner uses the public Semantic Scholar API (rate-limited to ~1 request/3 seconds). For larger bibliographies you can apply for a free API key and set it as an environment variable:

```bash
export S2_API_KEY=your_key_here   # macOS / Linux
set S2_API_KEY=your_key_here      # Windows Command Prompt
```

Apply for a key at <https://www.semanticscholar.org/product/api#api-key-form>.

---

## Usage

### Command-Line Interface

```bash
bibcleaner input.bib -o output.bib
```

If `-o` is omitted, the enriched file is saved as `enriched_<input>.bib` in the same directory.

### Python module

```bash
python -m bibcleaner.cli input.bib -o output.bib
```

### Programmatic API

```python
from bibcleaner import process_bibliography

process_bibliography("references.bib", "references_enriched.bib")
```

## How It Works

1. **Parse** — Loads BibTeX entries using bibtexparser
2. **Identify** — Detects arXiv preprints and incomplete author lists
3. **Enrich** — Queries Semantic Scholar for published metadata
4. **Validate** — Cross-references and standardizes entries
5. **Export** — Writes cleaned bibliography to output file

## Use Cases

- 📚 Preparing bibliographies for academic publications
- 🔍 Standardizing citation formats across large research projects
- 📊 Maintaining up-to-date reference collections
- 🏢 Batch processing institutional bibliography databases

## Contributing

Contributions and feedback are welcome! Please feel free to submit issues or pull requests.

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

## Support

For issues, feature requests, or questions, please [open an issue](https://github.com/hzahera/bib-cleaner/issues) on GitHub.
