#!/usr/bin/env python3
"""Stage 01 — convert ``document`` items with an arXiv URL or id into ``preprint``.

Ported from ``pyzoter_document2preprint.ipynb`` (the document->preprint block).
Must run first: later stages only scan ``itemType=preprint``, so any arXiv paper
still mislabelled as a ``document`` would otherwise be invisible to them.
"""

from __future__ import annotations

from zotcleanup import (
    Changes,
    apply_updates,
    arxiv_id_from_extra,
    arxiv_id_from_url,
    build_parser,
    fetch_items,
    get_client,
    retype,
    strip_extra_lines,
)


def find_arxiv_id(data: dict):
    """The arXiv id from the URL, falling back to the ``extra`` field."""
    return arxiv_id_from_url(data.get("url", "")) or arxiv_id_from_extra(data.get("extra", ""))


def is_candidate(item) -> bool:
    data = item["data"]
    return "arxiv" in (data.get("url") or "").lower() or arxiv_id_from_extra(data.get("extra", "")) is not None


def transform(zot, item) -> Changes:
    data = item["data"]
    ch = Changes(data)
    arxiv_id = find_arxiv_id(data)

    retype(zot, ch, data, "preprint")
    ch.set("repository", "arXiv")
    # Drop the (now stale) Better BibTeX citation key so it can be regenerated.
    ch.set("extra", strip_extra_lines(data.get("extra") or "", ["Citation Key:"]))
    if arxiv_id:
        ch.set("archiveID", "arXiv: " + arxiv_id)
        if not (data.get("url") or ""):  # id came from extra; give it a URL
            ch.set("url", "http://arxiv.org/abs/" + arxiv_id)
    return ch


def main() -> None:
    args = build_parser(__doc__.splitlines()[0]).parse_args()
    zot = get_client()

    items = fetch_items(zot, "document")
    candidates = [it for it in items if is_candidate(it)]

    apply_updates(
        zot,
        candidates,
        transform,
        dry_run=not args.apply,
        verbose=args.verbose,
        limit=args.limit,
        label="documents",
    )


if __name__ == "__main__":
    main()
