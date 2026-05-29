#!/usr/bin/env python3
"""Stage 09 — tag the arXiv primary category into ``extra`` for any item.

Ported and generalized from ``pyzotero_arXiv_category.ipynb`` (which only
handled journalArticle and conferencePaper). For any item that mentions an
arXiv id in ``extra`` but has no ``[category]`` bracket yet, look the paper up
and append ``[<primary_category>]``.

Network-bound (one arXiv lookup per candidate), so it is the last pipeline
stage. Idempotent: items that already carry their category are skipped.
"""

from __future__ import annotations

from zotcleanup import (
    Changes,
    apply_updates,
    arxiv_id_from_extra,
    arxiv_paper,
    build_parser,
    fetch_items,
    get_client,
    prefetch_arxiv,
)


def transform(zot, item) -> Changes:
    data = item["data"]
    ch = Changes(data)
    extra = data.get("extra") or ""
    arxiv_id = arxiv_id_from_extra(extra)
    if not arxiv_id:
        return ch
    paper = arxiv_paper(arxiv_id)
    category = getattr(paper, "primary_category", None)
    if category and category not in extra:
        ch.set("extra", f"{extra} [{category}]".strip())
    return ch


def is_candidate(item) -> bool:
    extra = item["data"].get("extra") or ""
    # Has an arXiv id but no category bracket yet (avoids needless API calls).
    return "[" not in extra and arxiv_id_from_extra(extra) is not None


def main() -> None:
    args = build_parser(__doc__.splitlines()[0]).parse_args()
    zot = get_client()

    items = fetch_items(zot)  # all item types
    candidates = [it for it in items if is_candidate(it)]

    batch = candidates[: args.limit] if args.limit else candidates
    prefetch_arxiv(arxiv_id_from_extra(it["data"].get("extra") or "") for it in batch)

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
