#!/usr/bin/env python3
"""Stage 19 — recover identity of under-specified journal articles.

Two sub-actions (default ``all`` runs both, in this order):

  demote-shells : journalArticles with NEITHER DOI NOR publicationTitle are
                  not really journal articles. Try an arXiv title search; on a
                  confident match, capture archiveID + url + category + DOI
                  from arXiv. Either way, retype to ``preprint`` (more honest
                  than claiming "journal").
  fill-dois     : journalArticles with a publicationTitle but no DOI: search
                  DBLP by title and set the DOI on a confident name match.

Title matching is normalized (lowercase, punctuation-stripped); a hit must
exactly match or wholly contain the source title to be accepted, so we never
silently apply a wrong DOI.
"""

from __future__ import annotations

import re
import time

from zotcleanup import (
    Changes,
    apply_updates,
    arxiv_paper,
    build_parser,
    dblp_search,
    fetch_items,
    get_client,
    is_arxiv_placeholder_doi,
    is_researchgate_doi,
    retype,
)
from zotcleanup.helpers import _CROSSREF_SLEEP, _get_works


def _norm_title(t: str) -> str:
    t = re.sub(r"[^a-z0-9 ]+", " ", (t or "").lower())
    return re.sub(r"\s+", " ", t).strip()


def _titles_match(a: str, b: str) -> bool:
    """True when the normalized titles are equal or one contains the other."""
    na, nb = _norm_title(a), _norm_title(b)
    if not na or not nb:
        return False
    return na == nb or na in nb or nb in na


def _arxiv_search_title(title: str):
    """First arXiv result whose title confidently matches ``title``, or None."""
    import arxiv

    from zotcleanup.helpers import _get_arxiv_client  # cached, paced client

    search = arxiv.Search(query=title, max_results=3)
    try:
        for paper in _get_arxiv_client().results(search):
            if _titles_match(getattr(paper, "title", ""), title):
                return paper
    except Exception:
        pass
    return None


# --------------------------------------------------------------------------- #
# demote-shells
# --------------------------------------------------------------------------- #


def demote_shell(zot, item) -> Changes:
    data = item["data"]
    ch = Changes(data)
    title = data.get("title") or ""

    paper = _arxiv_search_title(title) if title else None
    if paper is not None:
        arxiv_id = paper.get_short_id()
        ch.set("archiveID", "arXiv: " + arxiv_id)
        ch.set("url", "http://arxiv.org/abs/" + arxiv_id)
        category = getattr(paper, "primary_category", None)
        extra = data.get("extra") or ""
        if category and category not in extra:
            ch.set("extra", f"{extra} [{category}]".strip())
        paper_doi = getattr(paper, "doi", None)
        if paper_doi and not is_researchgate_doi(paper_doi):
            ch.set("DOI", paper_doi)

    retype(zot, ch, data, "preprint")
    return ch


def run_demote_shells(zot, args, dry_run):
    print("=== demote-shells (empty-shell journalArticles -> preprint) ===")
    ja = fetch_items(zot, "journalArticle")
    candidates = [
        it for it in ja
        if not (it["data"].get("DOI") or "").strip()
        and not (it["data"].get("publicationTitle") or "").strip()
    ]
    apply_updates(
        zot, candidates, demote_shell,
        dry_run=dry_run, verbose=args.verbose, limit=args.limit,
        label="journal articles",
    )


# --------------------------------------------------------------------------- #
# fill-dois
# --------------------------------------------------------------------------- #


def _crossref_title_search(title: str):
    """Top Crossref hit by bibliographic title search, or ``None``."""
    works = _get_works()
    try:
        q = works.query(bibliographic=title).sort("relevance").order("desc").select(
            "DOI", "title"
        )
        for hit in q:
            time.sleep(_CROSSREF_SLEEP)
            return hit
    except Exception:
        return None
    return None


def fill_doi(zot, item) -> Changes:
    data = item["data"]
    ch = Changes(data)
    title = data.get("title") or ""
    if not title:
        return ch

    # 1. DBLP — curated for CS / theory venues.
    try:
        for hit in dblp_search(title, rows=3):
            if hit.get("doi") and _titles_match(hit.get("title", ""), title):
                ch.set("DOI", hit["doi"])
                return ch
    except Exception:
        pass  # DBLP throttled / down: fall through to Crossref.

    # 2. Crossref bibliographic search — broad authority for journals.
    hit = _crossref_title_search(title)
    if not hit:
        return ch
    cr_titles = hit.get("title") or []
    if not cr_titles or not _titles_match(cr_titles[0], title):
        return ch
    doi = (hit.get("DOI") or "").strip()
    if doi and not is_researchgate_doi(doi) and not is_arxiv_placeholder_doi(doi):
        ch.set("DOI", doi)
    return ch


def run_fill_dois(zot, args, dry_run):
    print("=== fill-dois (DBLP + Crossref title search for journalArticles missing DOI) ===")
    ja = fetch_items(zot, "journalArticle")
    candidates = [
        it for it in ja
        if not (it["data"].get("DOI") or "").strip()
        and (it["data"].get("publicationTitle") or "").strip()  # excludes shells
    ]
    apply_updates(
        zot, candidates, fill_doi,
        dry_run=dry_run, verbose=args.verbose, limit=args.limit,
        label="journal articles",
    )


def main() -> None:
    parser = build_parser(__doc__.splitlines()[0])
    parser.add_argument(
        "action", nargs="?", default="all",
        choices=["demote-shells", "fill-dois", "all"],
        help="Which sub-action to run (default: all, in order).",
    )
    args = parser.parse_args()
    zot = get_client()
    dry_run = not args.apply

    steps = {"demote-shells": run_demote_shells, "fill-dois": run_fill_dois}
    order = list(steps) if args.action == "all" else [args.action]
    for i, name in enumerate(order):
        if i:
            print()
        steps[name](zot, args, dry_run)


if __name__ == "__main__":
    main()
