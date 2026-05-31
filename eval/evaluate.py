#!/usr/bin/env python3
"""Evaluate BibCleaner's arXiv -> published-venue matching against a labeled set.

Runs the real resolution pipeline on each paper in ``dataset.json`` and reports
precision / recall / accuracy plus a per-paper breakdown and confidence by
source.  Live runs (default) hit the APIs and record results to a fixture cache
so they can be replayed reproducibly with ``--offline``.

Usage:
    python eval/evaluate.py                  # live; records eval/results_cache.json
    python eval/evaluate.py --offline        # replay recorded results (no network)
    python eval/evaluate.py --limit 5        # only the first 5 papers
    python eval/evaluate.py --min-confidence 0.8

Tip: set S2_API_KEY for best coverage on the live run.
"""

import argparse
import json
import os
import sys
from pathlib import Path

# Allow running as a plain script (no install needed).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bibcleaner.enricher import resolve_entry  # noqa: E402
from bibcleaner.venues import normalize_or_keep  # noqa: E402

HERE = Path(__file__).resolve().parent
DATASET = HERE / "dataset.json"
CACHE = HERE / "results_cache.json"


def _resolved(paper: dict) -> dict:
    """Resolve one paper live -> {type, venue, year, confidence, source}."""
    fields = {
        "title": paper["title"],
        "eprint": paper["arxiv_id"],
        "archiveprefix": "arXiv",
    }
    res = resolve_entry(fields)
    data = res.get("data")
    venue = ""
    rtype = "misc"
    year = None
    if data:
        rtype = data.get("entry_type") or "misc"
        venue = data.get("booktitle") or data.get("journal") or ""
        venue = normalize_or_keep(venue) if venue else ""  # match what the tool writes
        year = data.get("year")
    return {
        "type": rtype,
        "venue": venue,
        "year": year,
        "confidence": round(res.get("confidence", 0.0), 2),
        "source": res.get("source"),
    }


def _score(paper: dict, r: dict, threshold: float) -> dict:
    """Classify a resolved result against the paper's ground truth."""
    applied = bool(r["venue"]) and r["confidence"] >= threshold
    expects_venue = paper["expected_type"] != "misc"

    if expects_venue:
        venue_ok = applied and paper["expected_venue"].lower() in r["venue"].lower()
        if venue_ok:
            outcome = "correct"          # resolved to the right venue
        elif applied:
            outcome = "wrong_venue"      # resolved, but to the wrong venue (false positive)
        else:
            outcome = "missed"           # left as preprint (false negative)
    else:
        # Genuinely unpublished: correct iff we did NOT assert a venue.
        outcome = "correct_preprint" if not applied else "false_positive"

    return {"applied": applied, "expects_venue": expects_venue, "outcome": outcome}


def main():
    ap = argparse.ArgumentParser(description="Evaluate BibCleaner venue matching.")
    ap.add_argument("--offline", action="store_true", help="Replay recorded results (no network)")
    ap.add_argument("--limit", type=int, default=None, help="Only evaluate the first N papers")
    ap.add_argument("--min-confidence", type=float,
                    default=float(os.environ.get("BIBCLEANER_MIN_CONFIDENCE", "0.8")),
                    help="Confidence at/above which a match counts as applied")
    args = ap.parse_args()

    papers = json.loads(DATASET.read_text())["papers"]
    if args.limit:
        papers = papers[: args.limit]

    cache = json.loads(CACHE.read_text()) if (args.offline and CACHE.exists()) else {}
    if args.offline and not cache:
        sys.exit("No results_cache.json to replay — run once live first.")

    results = {}
    rows = []
    counts = {"correct": 0, "wrong_venue": 0, "missed": 0, "correct_preprint": 0, "false_positive": 0}

    for p in papers:
        aid = p["arxiv_id"]
        r = cache[aid] if args.offline else _resolved(p)
        results[aid] = r
        s = _score(p, r, args.min_confidence)
        counts[s["outcome"]] += 1
        mark = {"correct": "OK", "correct_preprint": "OK", "wrong_venue": "X", "missed": "-", "false_positive": "X"}[s["outcome"]]
        rows.append((mark, aid, p.get("expected_venue") or "(preprint)",
                     (r["venue"] or "(none)")[:42], f"{r['confidence']:.2f}", r["source"] or "-"))

    if not args.offline:
        CACHE.write_text(json.dumps(results, indent=2))

    # ---- report ----
    print(f"\n{'':3} {'arXiv':12} {'expected':12} {'resolved venue':44} {'conf':5} source")
    print("-" * 92)
    for mark, aid, exp, got, conf, src in rows:
        print(f"{mark:3} {aid:12} {exp:12} {got:44} {conf:5} {src}")

    n = len(papers)
    published = counts["correct"] + counts["wrong_venue"] + counts["missed"]
    applied = counts["correct"] + counts["wrong_venue"] + counts["false_positive"]
    precision = counts["correct"] / applied if applied else float("nan")
    recall = counts["correct"] / published if published else float("nan")
    accuracy = (counts["correct"] + counts["correct_preprint"]) / n if n else float("nan")

    print("\n=== summary ===")
    print(f"  papers evaluated : {n}")
    print(f"  correct          : {counts['correct']}  (right venue)")
    print(f"  wrong venue      : {counts['wrong_venue']}")
    print(f"  missed (preprint): {counts['missed']}")
    print(f"  preprints kept   : {counts['correct_preprint']}  / false positives: {counts['false_positive']}")
    print(f"  precision        : {precision:.2f}   (of asserted venues, fraction correct)")
    print(f"  recall           : {recall:.2f}   (of published papers, fraction resolved correctly)")
    print(f"  accuracy         : {accuracy:.2f}   (correct venue OR correctly-left preprint)")
    print(f"  threshold        : {args.min_confidence}\n")


if __name__ == "__main__":
    main()
