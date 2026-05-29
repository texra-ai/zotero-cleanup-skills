#!/usr/bin/env python3
"""Stage 20 — clear leftover preprint-server URLs on journal articles.

For journalArticles with a URL pointing to arXiv / bioRxiv / etc.:

  - **Legit case** (item has both a real DOI AND a publicationTitle): the URL
    is just a surviving preprint link. The DOI is the canonical identifier, so
    capture the arXiv id in ``archiveID`` (if missing) and clear ``url`` —
    Zotero resolves the canonical link from the DOI.
  - **Mis-typed case** (no DOI or no publicationTitle): the item really is a
    preprint that slipped past stage 02. Demote to ``preprint`` (keeping
    ``url``), stripping any stale Better-BibTeX citation key.

Resolves the bulk of ``no-journal-preprint`` warnings. Runs after stage 02 so
items stage 02 already correctly demoted aren't touched again, and before stage
03 so newly-demoted preprints can have their DOI fetched on the same run.
"""

from __future__ import annotations

from zotcleanup import (
    Changes,
    apply_updates,
    build_parser,
    fetch_items,
    get_client,
    retype,
    strip_extra_lines,
)

# Preprint-server URL hosts the linter (and we) treat as "not a journal URL".
PREPRINT_HOSTS = (
    "arxiv.org",
    "biorxiv",
    "medrxiv",
    "chemrxiv",
    "researchsquare",
    "osf.io",
    "ssrn.com",
)


def has_preprint_url(item) -> bool:
    url = (item["data"].get("url") or "").lower()
    return any(host in url for host in PREPRINT_HOSTS)


def transform(zot, item) -> Changes:
    data = item["data"]
    ch = Changes(data)
    has_doi = bool(data.get("DOI"))
    has_title = bool(data.get("publicationTitle"))

    if has_doi and has_title:
        # Legit journalArticle — DOI is canonical, so just clear the leftover
        # preprint URL. (``archiveID`` is not a valid field on journalArticle,
        # and the arxiv id is typically already preserved in ``extra`` anyway.)
        ch.set("url", "")
    else:
        # Genuinely a preprint that escaped stage 02. Demote, drop stale BBT key.
        ch.set("extra", strip_extra_lines(data.get("extra") or "", ["Citation Key:"]))
        retype(zot, ch, data, "preprint")
    return ch


def main() -> None:
    args = build_parser(__doc__.splitlines()[0]).parse_args()
    zot = get_client()
    items = fetch_items(zot, "journalArticle")
    candidates = [it for it in items if has_preprint_url(it)]
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
