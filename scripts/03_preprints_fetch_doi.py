#!/usr/bin/env python3
"""Stage 03 — enrich preprints with arXiv DOI + category, then tidy categories.

Ported from ``pyzotero_preprint_get_doi.ipynb``. Two passes:

  Pass A: for ``preprint`` items with an arXiv URL and no DOI, set ``archiveID``,
          append the primary ``[category]`` to ``extra``, and record the DOI
          arXiv reports (skipping ResearchGate placeholders).
  Pass B: collapse duplicate category brackets (``[cs, stat] [cs.LG]`` ->
          ``[cs.LG]``) left behind by repeated enrichment runs.

Populates the DOIs that stage 04 keys off of, so it must run before stage 04.
"""

from __future__ import annotations

from zotcleanup import (
    Changes,
    apply_updates,
    arxiv_id_from_extra,
    arxiv_id_from_url,
    arxiv_paper,
    build_parser,
    clean_arxiv_categories,
    fetch_items,
    get_client,
    is_researchgate_doi,
    prefetch_arxiv,
)


def enrich(zot, item) -> Changes:
    data = item["data"]
    ch = Changes(data)
    if (data.get("DOI") or "") != "":
        return ch

    url = data.get("url") or ""
    arxiv_id = arxiv_id_from_url(url) or arxiv_id_from_extra(data.get("extra", ""))
    if not arxiv_id:
        return ch

    ch.set("archiveID", "arXiv: " + arxiv_id)
    if not url:
        ch.set("url", "http://arxiv.org/abs/" + arxiv_id)

    paper = arxiv_paper(arxiv_id)
    category = getattr(paper, "primary_category", None)
    extra = data.get("extra") or ""
    if category and category not in extra:
        ch.set("extra", f"{extra} [{category}]".strip())

    doi = getattr(paper, "doi", None)
    if doi and not is_researchgate_doi(doi):
        ch.set("DOI", doi)
    return ch


def tidy_categories(zot, item) -> Changes:
    data = item["data"]
    ch = Changes(data)
    extra = data.get("extra") or ""
    ch.set("extra", clean_arxiv_categories(extra))
    return ch


def main() -> None:
    args = build_parser(__doc__.splitlines()[0]).parse_args()
    zot = get_client()
    dry_run = not args.apply

    preprints = fetch_items(zot, "preprint")

    print("=== Pass A: fetch arXiv DOI + category ===")
    to_enrich = [
        it
        for it in preprints
        if "arxiv" in (it["data"].get("url") or "").lower()
        and (it["data"].get("DOI") or "") == ""
    ]
    # Resolve all the arXiv ids up front in a few batched requests (avoids 429s).
    batch = to_enrich[: args.limit] if args.limit else to_enrich
    prefetch_arxiv(
        arxiv_id_from_url(it["data"].get("url") or "")
        or arxiv_id_from_extra(it["data"].get("extra") or "")
        for it in batch
    )
    apply_updates(
        zot, to_enrich, enrich,
        dry_run=dry_run, verbose=args.verbose, limit=args.limit, label="preprints",
    )

    print("\n=== Pass B: tidy duplicate category brackets ===")
    # Re-fetch so Pass B sees Pass A's writes (in --apply mode).
    preprints = fetch_items(zot, "preprint")
    to_tidy = [it for it in preprints if "] [" in (it["data"].get("extra") or "")]
    apply_updates(
        zot, to_tidy, tidy_categories,
        dry_run=dry_run, verbose=args.verbose, limit=args.limit, label="preprints",
    )


if __name__ == "__main__":
    main()
