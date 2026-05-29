#!/usr/bin/env python3
"""Stage 04 — promote published preprints to ``journalArticle`` via Crossref.

Ported from ``pyzotero_journals_fromDOI.ipynb`` (the comprehensive version).
The most consequential stage — it changes item types and overwrites journal
metadata, so preview with a dry-run first. Two passes:

  Pass A: ``preprint`` items that now carry a real DOI -> look up Crossref and
          promote to ``journalArticle`` (journal name, abbreviation, volume,
          issue, page/article-number, date). DataCite arXiv DOIs are re-resolved
          via arXiv; ResearchGate DOIs are cleared.
  Pass B: backstop for ``journalArticle`` items with an empty publication title
          but a DOI — fill in the missing journal metadata.

Runs after stages 02-03 so DOIs are present and item types are settled.
"""

from __future__ import annotations

from zotcleanup import (
    Changes,
    apply_updates,
    arxiv_enrich_or_demote,
    arxiv_id_from_doi,
    build_parser,
    crossref_date,
    crossref_works,
    fetch_items,
    get_client,
    is_arxiv_placeholder_doi,
    is_researchgate_doi,
    prefetch_arxiv,
    retype,
)


def _apply_crossref_journal_fields(ch: Changes, info: dict) -> None:
    """Copy the journal metadata fields shared by both passes."""
    short = info.get("short-container-title") or []
    if short:
        ch.set("journalAbbreviation", short[0])
    if "volume" in info:
        ch.set("volume", info["volume"])
    if "issue" in info:
        ch.set("issue", info["issue"])
    if "article-number" in info:
        ch.set("pages", info["article-number"])
    elif "page" in info:
        ch.set("pages", info["page"])
    date = crossref_date(info)
    if date:
        ch.set("date", date)


def _handle_arxiv_placeholder(zot, ch: Changes, data: dict, doi: str) -> bool:
    """If *doi* is a DataCite arXiv placeholder, resolve and enrich-or-demote.

    Returns ``True`` when the doi was handled (caller should ``return ch``).
    """
    if not is_arxiv_placeholder_doi(doi):
        return False
    arxiv_id = arxiv_id_from_doi(doi)
    if arxiv_id:
        arxiv_enrich_or_demote(zot, ch, data, arxiv_id)
    return True


def promote_preprint(zot, item) -> Changes:
    data = item["data"]
    ch = Changes(data)
    doi = data.get("DOI") or ""

    if _handle_arxiv_placeholder(zot, ch, data, doi):
        return ch

    if is_researchgate_doi(doi):
        ch.set("DOI", "")
        return ch

    info = crossref_works(doi)
    container = (info or {}).get("container-title") or []
    if not container:
        return ch  # no journal name -> nothing to promote to

    retype(zot, ch, data, "journalArticle")
    ch.set("publicationTitle", container[0])
    _apply_crossref_journal_fields(ch, info)
    return ch


def fill_journal_metadata(zot, item) -> Changes:
    data = item["data"]
    ch = Changes(data)
    doi = data.get("DOI") or ""

    if _handle_arxiv_placeholder(zot, ch, data, doi):
        return ch

    info = crossref_works(doi)
    container = (info or {}).get("container-title") or []
    if container:
        ch.set("publicationTitle", container[0])
    if info:
        _apply_crossref_journal_fields(ch, info)
    return ch


def main() -> None:
    args = build_parser(__doc__.splitlines()[0]).parse_args()
    zot = get_client()
    dry_run = not args.apply

    print("=== Pass A: promote preprints with a DOI to journal articles ===")
    preprints = fetch_items(zot, "preprint")
    to_promote = [it for it in preprints if (it["data"].get("DOI") or "") != ""]
    # Batch-resolve the arXiv-placeholder DOIs (the only ones needing arXiv).
    prefetch_arxiv(
        arxiv_id_from_doi(it["data"].get("DOI") or "")
        for it in (to_promote[: args.limit] if args.limit else to_promote)
        if is_arxiv_placeholder_doi(it["data"].get("DOI") or "")
    )
    apply_updates(
        zot, to_promote, promote_preprint,
        dry_run=dry_run, verbose=args.verbose, limit=args.limit, label="preprints",
    )

    print("\n=== Pass B: fill metadata for journal articles missing a title ===")
    journals = fetch_items(zot, "journalArticle")
    to_fill = [
        it
        for it in journals
        if (it["data"].get("publicationTitle") or "") == ""
        and (it["data"].get("DOI") or "") != ""
    ]
    apply_updates(
        zot, to_fill, fill_journal_metadata,
        dry_run=dry_run, verbose=args.verbose, limit=args.limit, label="journal articles",
    )


if __name__ == "__main__":
    main()
