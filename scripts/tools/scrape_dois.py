#!/usr/bin/env python3
"""Tool — recover DOIs by scraping ``citation_doi`` meta tags from arXiv pages.

Ported from ``pyzotero-doi-retriever.ipynb``. A slow, HTML-scraping fallback for
arXiv-flavoured journal articles whose DOI the arXiv/Crossref API path missed.
NOT a default pipeline stage; run on demand (logically before stage 04).
"""

from __future__ import annotations

import re
import time

import requests

from zotcleanup import Changes, apply_updates, build_parser, fetch_items, get_client

_CITATION_DOI = re.compile(r'name="citation_doi" content=(.*?)/>')
_SCRAPE_SLEEP = 1.0


def transform(zot, item) -> Changes:
    data = item["data"]
    ch = Changes(data)
    url = data.get("url") or ""
    if not url:
        return ch
    response = requests.get(url, timeout=30)
    time.sleep(_SCRAPE_SLEEP)
    match = _CITATION_DOI.search(response.text)
    if match:
        ch.set("DOI", match.group(1).replace('"', "").strip())
    return ch


def is_candidate(item) -> bool:
    d = item["data"]
    if "publicationTitle" not in d:
        return False
    url = (d.get("url") or "").lower()
    title = (d.get("publicationTitle") or "").lower()
    return ("arxiv" in title or "arxiv" in url) and " " not in url and url != ""


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
