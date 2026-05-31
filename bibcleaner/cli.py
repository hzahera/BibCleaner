import argparse
import sys
import os

from .bibcleaner import process_bibliography
from .citations import collect_cited_keys


def main():
    parser = argparse.ArgumentParser(
        description="Clean and enrich BibTeX: replace arXiv preprints with their "
        "published venue, normalize venue names, and tidy entries for LaTeX."
    )
    parser.add_argument("input", help="Path to the input .bib file")
    parser.add_argument(
        "-o",
        "--output",
        help="Path to save the cleaned .bib file (defaults to enriched_<input>)",
        default=None,
    )
    parser.add_argument(
        "--no-enrich",
        action="store_true",
        help="Skip online enrichment; only clean, format, and normalize (offline)",
    )
    parser.add_argument(
        "--no-protect-caps",
        action="store_true",
        help="Do not brace-protect title capitalization (e.g. {BERT})",
    )
    parser.add_argument(
        "--dedup",
        action="store_true",
        help="Merge duplicate entries and print the citation-key remapping",
    )
    parser.add_argument(
        "--keep-cited",
        nargs="+",
        metavar="FILE",
        help="Keep only entries cited in the given .tex/.aux file(s)",
    )

    args = parser.parse_args()

    input_file = args.input
    output_file = args.output
    if not output_file:
        dirname = os.path.dirname(input_file)
        basename = os.path.basename(input_file)
        output_file = os.path.join(dirname, f"enriched_{basename}")

    cited_keys = collect_cited_keys(args.keep_cited) if args.keep_cited else None

    try:
        process_bibliography(
            input_file,
            output_file,
            enrich=not args.no_enrich,
            protect_caps=not args.no_protect_caps,
            dedup=args.dedup,
            cited_keys=cited_keys,
        )
    except KeyboardInterrupt:
        print("\nProcess interrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\nAn error occurred: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
