#!/usr/bin/env python3
"""Run the metadata + hygiene cleanup stages in order, forwarding common flags.

Runs, in order: 01, 02, 20 (clean preprint URLs), 03-09, then the hygiene block
14-18. The collection stages (10-12), DBLP enrichment (13) and DOI backfill (19)
are standalone, and the utilities in ``scripts/tools/`` are NOT run.

By default everything is a dry run. Add ``--apply`` to write.

    uv run run_pipeline.py --dry-run --limit 5      # preview a few items per stage
    uv run run_pipeline.py --apply                  # run the whole pipeline for real
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent / "scripts"
STAGES = [
    # Data stages — type conversion, preprint-URL cleanup, DOI/Crossref enrichment.
    "01_documents_to_preprints.py",
    "02_arxiv_journals_to_preprints.py",
    "20_clean_journal_preprint_urls.py",
    "03_preprints_fetch_doi.py",
    "04_preprints_to_journals.py",
    "05_conferences.py",
    "06_journal_metadata_fixes.py",
    "07_strip_arxiv_from_journals.py",
    "08_standardize_journal_titles.py",
    "09_tag_arxiv_categories.py",
    # Hygiene stages — extra/title/creator/DOI scrub. Safe to run last.
    "14_clean_extra.py",
    "15_clean_titles.py",
    "16_resolve_placeholder_dois.py",
    "17_clean_creator_names.py",
    "18_capitalize_proper_nouns.py",
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="Write changes (default: dry run).")
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview without writing (the default; explicit, excludes --apply).",
    )
    parser.add_argument("--limit", type=int, default=None, help="Per-stage item cap.")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    common: list[str] = []
    if args.apply:
        common.append("--apply")
    if args.limit is not None:
        common += ["--limit", str(args.limit)]
    if args.verbose:
        common.append("--verbose")

    missing = [s for s in STAGES if not (SCRIPTS_DIR / s).exists()]
    if missing:
        sys.exit("Missing stage scripts: " + ", ".join(missing))

    for stage in STAGES:
        print(f"\n{'=' * 70}\n# {stage}\n{'=' * 70}")
        result = subprocess.run([sys.executable, str(SCRIPTS_DIR / stage), *common])
        if result.returncode != 0:
            print(f"\nStage {stage} exited with code {result.returncode}; stopping.")
            sys.exit(result.returncode)

    print("\nPipeline complete.")


if __name__ == "__main__":
    main()
