#!/usr/bin/env python3
"""Stage 07 — strip arXiv provenance from the ``extra`` of published articles.

Ported from ``pyzotero_journal_arxivRemover.ipynb``. Targets ``journalArticle``
items that have a real (non-ResearchGate) DOI and still carry an ``arXiv:`` line
in ``extra``, removing just that line while keeping the rest of ``extra``.

Runs last among the data stages: only once an item is confirmed as a published
journal article with a real DOI is it safe to delete its arXiv identifier
(earlier stages still need it).
"""

from __future__ import annotations

import re

from zotcleanup import (
    Changes,
    apply_updates,
    build_parser,
    fetch_items,
    get_client,
    is_researchgate_doi,
)


def transform(zot, item) -> Changes:
    data = item["data"]
    ch = Changes(data)
    extra = data.get("extra") or ""
    ch.set("extra", re.sub(r"arXiv:.*?(\n|$)", "", extra))
    return ch


def is_candidate(item) -> bool:
    d = item["data"]
    doi = d.get("DOI") or ""
    extra = d.get("extra") or ""
    return "arXiv" in extra and doi != "" and not is_researchgate_doi(doi)


def main() -> None:
    args = build_parser(__doc__.splitlines()[0]).parse_args()
    zot = get_client()

    items = fetch_items(zot, "journalArticle")
    candidates = [it for it in items if is_candidate(it)]

    apply_updates(
        zot,
        candidates,
        transform,
        dry_run=not args.apply,
        verbose=args.verbose,
        limit=args.limit,
        label="journal articles",
    )


if __name__ == "__main__":
    main()
