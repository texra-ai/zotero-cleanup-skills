#!/usr/bin/env python3
"""Stage 06 — repair journal article issue numbers, page numbers and extra fields.

Merges ``journal-issues.ipynb`` and ``pyzotero-journal-pages.ipynb``. Two actions:

  fix-issues : articles whose ``issue`` equals a suspicious value (default "2",
               often a mis-scrape of "1") -> if Crossref reports a different
               issue, correct it (and the page range if Crossref has one).
  fix-pages  : articles with telltale bad page strings ("1-1234", a dash-less
               Nature page, or a too-short page number in a Physical-Review-style
               journal) -> replace with Crossref's article-number/page, fill an
               empty issue, and strip PMID/ISBN lines from ``extra``.

All Crossref-driven, so it runs after stage 04 (so freshly-promoted journal
articles are included). Default action ``all`` runs both.
"""

from __future__ import annotations

import re

from zotcleanup import (
    Changes,
    apply_updates,
    build_parser,
    crossref_works,
    fetch_items,
    get_client,
    strip_extra_lines,
)

# Journals where the "page" is really an article number (from journal-pages cell 10).
ARTICLE_NUMBER_JOURNALS = (
    "Physical Review", "Phys. Rev.", "New J. Phys.", "New Journal of Physics",
    "Nature", "Journal of Mathematical Physics", "Reviews of Modern Physics",
    "npj", "Science",
)


def _crossref_pages(info: dict):
    if "article-number" in info:
        return info["article-number"]
    if "page" in info:
        return info["page"]
    return None


# --------------------------------------------------------------------------- #
# fix-issues
# --------------------------------------------------------------------------- #


def make_fix_issue(suspicious: str):
    def fix_issue(zot, item) -> Changes:
        data = item["data"]
        ch = Changes(data)
        info = crossref_works(data.get("DOI") or "")
        if info and "issue" in info and info["issue"] != suspicious:
            ch.set("issue", info["issue"])
            if "page" in info:
                ch.set("pages", info["page"])
        return ch

    return fix_issue


def run_fix_issues(zot, args, dry_run):
    suspicious = args.suspicious_issue
    print(f"=== fix-issues (suspicious issue = {suspicious!r}) ===")
    items = fetch_items(zot, "journalArticle")
    candidates = [
        it
        for it in items
        if (it["data"].get("issue") or "") == suspicious and (it["data"].get("DOI") or "") != ""
    ]
    apply_updates(
        zot, candidates, make_fix_issue(suspicious),
        dry_run=dry_run, verbose=args.verbose, limit=args.limit, label="journal articles",
    )


# --------------------------------------------------------------------------- #
# fix-pages
# --------------------------------------------------------------------------- #


def _needs_page_fix(data: dict) -> bool:
    pages = data.get("pages") or ""
    journal = data.get("publicationTitle") or ""
    if re.match(r"^1\-\d+$", pages):
        return True
    if journal.lower() == "nature" and "-" not in pages and pages != "":
        return True
    if any(j in journal for j in ARTICLE_NUMBER_JOURNALS):
        if pages and len(pages.replace("-", "").strip()) < 5:
            return True
    return False


def _has_extra_noise(data: dict) -> bool:
    extra = data.get("extra") or ""
    return "PMID:" in extra or "ISBN:" in extra


def fix_pages(zot, item) -> Changes:
    data = item["data"]
    ch = Changes(data)

    if _needs_page_fix(data) and (data.get("DOI") or ""):
        info = crossref_works(data["DOI"])
        if info:
            new_pages = _crossref_pages(info)
            if new_pages is not None:
                ch.set("pages", new_pages)
            if "issue" in info and (data.get("issue") or "") == "":
                ch.set("issue", info["issue"])

    extra = data.get("extra") or ""
    if extra:
        ch.set("extra", strip_extra_lines(extra, ["PMID:", "ISBN:"]))
    return ch


def run_fix_pages(zot, args, dry_run):
    print("=== fix-pages ===")
    items = fetch_items(zot, "journalArticle")
    candidates = [it for it in items if _needs_page_fix(it["data"]) or _has_extra_noise(it["data"])]
    apply_updates(
        zot, candidates, fix_pages,
        dry_run=dry_run, verbose=args.verbose, limit=args.limit, label="journal articles",
    )


def main() -> None:
    parser = build_parser(__doc__.splitlines()[0])
    parser.add_argument(
        "action", nargs="?", default="all",
        choices=["fix-issues", "fix-pages", "all"],
        help="Which fix to run (default: all).",
    )
    parser.add_argument(
        "--suspicious-issue", default="2", metavar="N",
        help="Issue value treated as suspicious for fix-issues (default: 2).",
    )
    args = parser.parse_args()
    zot = get_client()
    dry_run = not args.apply

    steps = {"fix-issues": run_fix_issues, "fix-pages": run_fix_pages}
    order = list(steps) if args.action == "all" else [args.action]
    for i, name in enumerate(order):
        if i:
            print()
        steps[name](zot, args, dry_run)


if __name__ == "__main__":
    main()
