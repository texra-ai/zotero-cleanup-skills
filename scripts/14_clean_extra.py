#!/usr/bin/env python3
"""Stage 14 — strip importer cruft out of the ``extra`` field.

Many items carry bookkeeping lines in ``extra`` left over from BetterBibTeX
(``Citation Key:``, ``tex.howpublished:``), ProQuest / dspace
(``Accepted: YYYY-MM-DDT…``), or odd Mendeley export quirks (``Issue: June``
when a month name leaked into the issue slot, ``Publication Title: Thesis``,
``Medium: COURSERA: …``).

These lines clutter exported bibliographies and never carry useful information
for citation. This stage drops them and leaves all other ``extra`` content
(arXiv IDs, arXiv categories, DOIs, notes) alone.

Included in ``run_pipeline.py`` as a hygiene stage (14–18).
"""

from __future__ import annotations

import re

from zotcleanup import (
    Changes,
    apply_updates,
    build_parser,
    fetch_items,
    get_client,
    strip_extra_lines,
)

# Prefixes whose entire line is cruft. Matched case-insensitively after
# left-stripping (strip_extra_lines handles that).
UNWANTED_PREFIXES = (
    "Citation Key:",
    "tex.howpublished:",
    "Accepted:",
    "Publication Title:",
    "Medium:",
)

# A "Volume: 2013" or "Issue: December"-style line where the value is just a
# year or a month name — these come from ProQuest/Mendeley exports putting
# the publication-month or year into the wrong slot.
_MONTHS = (
    "January|February|March|April|May|June|July|August|September|"
    "October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
)
_GARBLED = re.compile(
    rf"^\s*(Issue:\s*({_MONTHS})|Volume:\s*\d{{4}})\s*$",
    re.IGNORECASE | re.MULTILINE,
)
# _GARBLED.sub("", …) replaces each matched line with "" but leaves the
# surrounding newline in place — _BLANK_LINES below collapses the resulting
# blank run. These two steps are coupled; don't change the replacement to
# "\n" or drop the collapse without updating both.
_BLANK_LINES = re.compile(r"\n{2,}")


def _clean(extra: str) -> str:
    if not extra:
        return extra
    out = strip_extra_lines(extra, UNWANTED_PREFIXES)
    out = _GARBLED.sub("", out)
    out = _BLANK_LINES.sub("\n", out).strip()
    return out


def transform(zot, item) -> Changes:
    data = item["data"]
    ch = Changes(data)
    # Changes.set already records a diff only when the value actually changes.
    ch.set("extra", _clean(data.get("extra") or ""))
    return ch


def main() -> None:
    args = build_parser(__doc__.splitlines()[0]).parse_args()
    zot = get_client()
    # Fetch every non-attachment item type by passing None.
    items = fetch_items(zot, None)
    candidates = [it for it in items if (it["data"].get("extra") or "")]
    apply_updates(
        zot,
        candidates,
        transform,
        dry_run=not args.apply,
        verbose=args.verbose,
        limit=args.limit,
        label="items",
    )


if __name__ == "__main__":
    main()
