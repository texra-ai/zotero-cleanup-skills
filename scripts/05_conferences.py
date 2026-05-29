#!/usr/bin/env python3
"""Stage 05 — conference paper cleanup (3 sub-actions, run in order by default).

Merges ``pyzotero_conference_duplicate.ipynb``, ``pyzotero_conference.ipynb`` and
``pyzotero_conference_neuralips.ipynb``:

  convert-duplicates : items tagged ``duplicate_conf`` that are journalArticles
                       -> retype to ``conferencePaper`` (clear archiveID/repository).
  fill-proceedings   : conferencePapers with an empty proceedingsTitle but a DOI
                       -> fill proceedingsTitle/publisher/place/date from Crossref.
  standardize-neurips : normalise the NeurIPS proceedings title to its abbreviation.

Default action ``all`` runs the three in the order above (duplicates must become
conference papers before the proceedings fill can see them).
"""

from __future__ import annotations

from zotcleanup import (
    Changes,
    apply_updates,
    build_parser,
    crossref_date,
    crossref_works,
    fetch_items,
    get_client,
    retype,
)

NEURIPS_FULL = "Advances in neural information processing systems"
NEURIPS_ABBR = "Adv. Neural inf. Process. Syst."


def convert_duplicate(zot, item) -> Changes:
    ch = Changes(item["data"])
    retype(zot, ch, item["data"], "conferencePaper")
    return ch


def fill_proceedings(zot, item) -> Changes:
    data = item["data"]
    ch = Changes(data)
    info = crossref_works(data.get("DOI") or "")
    if not info:
        return ch
    container = info.get("container-title") or []
    if container:
        ch.set("proceedingsTitle", container[0])
    if info.get("publisher"):
        ch.set("publisher", info["publisher"])
    event = info.get("event")
    if isinstance(event, dict) and event.get("location"):
        ch.set("place", event["location"])
    date = crossref_date(info)
    if date:
        ch.set("date", date)
    return ch


def standardize_neurips(zot, item) -> Changes:
    data = item["data"]
    ch = Changes(data)
    title = data.get("proceedingsTitle") or ""
    if title.startswith(NEURIPS_FULL):
        ch.set("proceedingsTitle", title.replace(NEURIPS_FULL, NEURIPS_ABBR))
    return ch


def run_convert_duplicates(zot, args, dry_run):
    print("=== convert-duplicates ===")
    tagged = zot.everything(zot.items(tag="duplicate_conf"))
    candidates = [it for it in tagged if it["data"].get("itemType") == "journalArticle"]
    apply_updates(
        zot, candidates, convert_duplicate,
        dry_run=dry_run, verbose=args.verbose, limit=args.limit, label="tagged items",
    )


def run_fill_proceedings(zot, args, dry_run):
    print("=== fill-proceedings ===")
    items = fetch_items(zot, "conferencePaper")
    candidates = [
        it
        for it in items
        if (it["data"].get("proceedingsTitle") or "") == ""
        and (it["data"].get("DOI") or "") != ""
    ]
    apply_updates(
        zot, candidates, fill_proceedings,
        dry_run=dry_run, verbose=args.verbose, limit=args.limit, label="conference papers",
    )


def run_standardize_neurips(zot, args, dry_run):
    print("=== standardize-neurips ===")
    items = fetch_items(zot, "conferencePaper")
    candidates = [it for it in items if NEURIPS_FULL in (it["data"].get("proceedingsTitle") or "")]
    apply_updates(
        zot, candidates, standardize_neurips,
        dry_run=dry_run, verbose=args.verbose, limit=args.limit, label="conference papers",
    )


def main() -> None:
    parser = build_parser(__doc__.splitlines()[0])
    parser.add_argument(
        "action",
        nargs="?",
        default="all",
        choices=["convert-duplicates", "fill-proceedings", "standardize-neurips", "all"],
        help="Which sub-action to run (default: all, in order).",
    )
    args = parser.parse_args()
    zot = get_client()
    dry_run = not args.apply

    steps = {
        "convert-duplicates": run_convert_duplicates,
        "fill-proceedings": run_fill_proceedings,
        "standardize-neurips": run_standardize_neurips,
    }
    order = list(steps) if args.action == "all" else [args.action]
    for i, name in enumerate(order):
        if i:
            print()
        steps[name](zot, args, dry_run)


if __name__ == "__main__":
    main()
