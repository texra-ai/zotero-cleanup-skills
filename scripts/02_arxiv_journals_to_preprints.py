#!/usr/bin/env python3
"""Stage 02 — fix journal articles that are really arXiv preprints.

Ported from ``pyzotero_arXiv_new.ipynb`` (the journalArticle handling; the dead
``document`` blocks are dropped — stage 01 owns documents). Targets items whose
``publicationTitle`` says arXiv/CoRR, or whose DOI is a DataCite arXiv DOI
(``10.48550/arxiv.*``), or that have an empty title+DOI but an arXiv URL.

For each, the real publisher DOI (if arXiv now reports one) is recorded;
otherwise the item is demoted to a ``preprint`` and journal-only fields cleared.
Runs before stage 04 so genuinely-unpublished items are parked as preprints and
newly-found real DOIs flow forward.
"""

from __future__ import annotations

from zotcleanup import (
    Changes,
    apply_updates,
    arxiv_enrich_or_demote,
    arxiv_id_from_doi,
    arxiv_id_from_extra,
    arxiv_id_from_url,
    build_parser,
    fetch_items,
    get_client,
    is_arxiv_placeholder_doi,
    prefetch_arxiv,
    strip_extra_lines,
)


def is_candidate(item) -> bool:
    d = item["data"]
    title = d.get("publicationTitle") or ""
    doi = d.get("DOI") or ""
    url = d.get("url") or ""
    if ("arXiv" in title or "CoRR" in title) and "[" not in title:
        return True
    if is_arxiv_placeholder_doi(doi):
        return True
    if title == "" and doi == "" and "arxiv" in url.lower():
        return True
    return False


def resolve_arxiv_id(data: dict):
    """Find an arXiv id from the DOI, then title, then URL, then extra."""
    doi = data.get("DOI") or ""
    if is_arxiv_placeholder_doi(doi):
        return arxiv_id_from_doi(doi)

    title = data.get("publicationTitle") or ""
    if "arXiv preprint arXiv:" in title:
        return title[title.find("arXiv:") + 7 :].strip() or None

    return arxiv_id_from_url(data.get("url", "")) or arxiv_id_from_extra(data.get("extra", ""))


def transform(zot, item) -> Changes:
    data = item["data"]
    ch = Changes(data)
    # Drop the (now stale) Better BibTeX citation key before re-typing/enriching.
    ch.set("extra", strip_extra_lines(data.get("extra") or "", ["Citation Key:"]))
    arxiv_id = resolve_arxiv_id(data)
    if arxiv_id:
        arxiv_enrich_or_demote(zot, ch, data, arxiv_id)
    return ch


def main() -> None:
    args = build_parser(__doc__.splitlines()[0]).parse_args()
    zot = get_client()

    items = fetch_items(zot, "journalArticle")
    candidates = [it for it in items if is_candidate(it)]

    batch = candidates[: args.limit] if args.limit else candidates
    prefetch_arxiv(resolve_arxiv_id(it["data"]) for it in batch)

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
