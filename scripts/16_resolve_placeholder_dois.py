#!/usr/bin/env python3
"""Stage 16 — replace placeholder DOIs with the real publisher DOI.

Items whose ``DOI`` field is a ResearchGate placeholder (``10.13140/RG.…``)
or a DataCite-issued arXiv stand-in (``10.48550/arxiv.…``) usually have a
real publisher DOI that Crossref knows about, keyed by title + first-author
surname.

This stage queries Crossref Works for each such item, accepts the top hit
only when (a) the result's title fuzzy-matches the item's title with ratio
≥ 0.85, (b) at least one of the item's author surnames appears in the
Crossref author list, and (c) the returned DOI itself is NOT a placeholder.
On a confirmed match it overwrites the placeholder DOI; otherwise it leaves
the item alone.

Network-bound (one Crossref query per candidate). Set ``CROSSREF_MAILTO``
to join the polite pool for stabler rate limits.

Included in ``run_pipeline.py`` as a hygiene stage (14–18).
"""

from __future__ import annotations

import time
from difflib import SequenceMatcher

from zotcleanup import (
    Changes,
    apply_updates,
    build_parser,
    fetch_items,
    get_client,
    is_arxiv_placeholder_doi,
    is_researchgate_doi,
)
# `crossref_works` (the public wrapper) is a DOI lookup only; this stage needs
# a bibliographic title+author query, so we reach for the underlying shared
# Works client. Keep the noqa.
from zotcleanup.helpers import _get_works  # noqa: PLC2701

_TITLE_THRESHOLD = 0.85
_CROSSREF_SLEEP = 0.2


def _norm(s: str) -> str:
    return " ".join((s or "").lower().split())


def _title_match(a: str, b: str) -> float:
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def _author_surnames(item_data: dict) -> set[str]:
    out = set()
    for cr in item_data.get("creators", []):
        ln = (cr.get("lastName") or cr.get("name") or "").strip().lower()
        if ln:
            out.add(ln.split()[-1])   # last token of surname
    return out


def _crossref_authors(info: dict) -> set[str]:
    out = set()
    for a in info.get("author") or []:
        fam = (a.get("family") or "").strip().lower()
        if fam:
            out.add(fam.split()[-1])
    return out


def _crossref_title(info: dict) -> str:
    titles = info.get("title") or []
    return titles[0] if titles else ""


def _crossref_search(title: str, author: str) -> dict | None:
    """Return Crossref top hit for (title, author) or ``None``."""
    works = _get_works()
    try:
        q = works.query(bibliographic=title)
        if author:
            q = q.query(author=author)
        for hit in q.sort("relevance").order("desc").select(
            "DOI", "title", "author"
        ):
            time.sleep(_CROSSREF_SLEEP)
            return hit
    except Exception:
        return None
    return None


def _candidate_doi(
    info: dict, item_data: dict, surnames: set[str] | None = None
) -> str | None:
    # Don't lowercase here: ``is_researchgate_doi`` tests for the literal
    # uppercase ``"RG."`` substring (``10.13140/RG.…``), so pre-lowercasing
    # would silently make every ResearchGate placeholder a false negative.
    doi = (info.get("DOI") or "").strip()
    if not doi or is_researchgate_doi(doi) or is_arxiv_placeholder_doi(doi):
        return None
    t_item = item_data.get("title") or ""
    if _title_match(t_item, _crossref_title(info)) < _TITLE_THRESHOLD:
        return None
    if surnames is None:
        surnames = _author_surnames(item_data)
    if not (surnames & _crossref_authors(info)):
        return None
    return doi


def transform(zot, item) -> Changes:
    data = item["data"]
    ch = Changes(data)
    title = data.get("title") or ""
    if not title:
        return ch
    # Compute the surname set once; reuse for the query and the author check.
    surnames = _author_surnames(data)
    first_surname = next(iter(surnames), "")
    hit = _crossref_search(title, first_surname)
    if not hit:
        return ch
    new_doi = _candidate_doi(hit, data, surnames)
    if new_doi:
        ch.set("DOI", new_doi)
    return ch


def _is_candidate(item) -> bool:
    # See _candidate_doi for why we don't lowercase before is_researchgate_doi.
    doi = item["data"].get("DOI") or ""
    return is_researchgate_doi(doi) or is_arxiv_placeholder_doi(doi)


def main() -> None:
    args = build_parser(__doc__.splitlines()[0]).parse_args()
    zot = get_client()
    items = fetch_items(zot, None)
    cand = [it for it in items if _is_candidate(it)]
    apply_updates(
        zot,
        cand,
        transform,
        dry_run=not args.apply,
        verbose=args.verbose,
        limit=args.limit,
        label="items",
        write_sleep=_CROSSREF_SLEEP,
    )


if __name__ == "__main__":
    main()
