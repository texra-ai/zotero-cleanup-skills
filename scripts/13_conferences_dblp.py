#!/usr/bin/env python3
"""Stage 13 — verify & enrich conference papers against DBLP.

DBLP (dblp.org) is the curated authority for CS / ML / theory bibliography:
canonical venue names, correct years, pages, and DOIs. This stage looks each
``conferencePaper`` up there by title and, crucially, *verifies the match*
before trusting it — a DBLP record is only believed when

  * its title is a near-match to ours (fuzzy ratio >= TITLE_MIN), AND
  * its year agrees (exactly, or off by one — proceedings vs. arXiv year), AND
  * its authors overlap with ours (surname overlap, or first author matches).

Only a verified ("CONFIRMED") match is used to fill **missing** fields — DOI,
proceedings title (canonical venue), date, pages, volume. Anything where the
title matches but the year or authors *disagree* is reported as **SUSPECT** and
left untouched, because that is exactly the signal of a wrong/duplicated record.
Papers with no confident hit are **NOT FOUND** and also left alone.

Network-bound (one DBLP query per paper), so run it on demand, not in the
default pipeline. After it fills DOIs, stage 05 ``fill-proceedings`` can use
those DOIs to add publisher/place from Crossref.

    uv run scripts/13_conferences_dblp.py --limit 10        # preview verification
    uv run scripts/13_conferences_dblp.py --only-missing    # skip complete papers
    uv run scripts/13_conferences_dblp.py --apply
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from zotcleanup import (
    Changes,
    DBLPThrottled,
    build_parser,
    dblp_authors,
    dblp_search,
    fetch_items,
    get_client,
    is_arxiv_placeholder_doi,
)

TITLE_MIN = 0.90  # fuzzy-title ratio below which we don't even consider a hit
FILL_FIELDS = ("DOI", "proceedingsTitle", "date", "pages", "volume")


def _norm_title(s: str) -> str:
    s = (s or "").lower().strip().rstrip(".")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", s)).strip()


def _year(s: str) -> int | None:
    m = re.search(r"(19|20)\d{2}", s or "")
    return int(m.group(0)) if m else None


def _surnames(names: list[str]) -> set[str]:
    """Last token of each name, lowercased — a rough but robust surname key."""
    return {n.split()[-1].lower() for n in names if n.split()}


def _item_surnames(data: dict) -> set[str]:
    names = []
    for c in data.get("creators", []):
        if c.get("lastName"):
            names.append(c["lastName"])
        elif c.get("name"):
            names.append(c["name"])
    return _surnames(names)


def _venue(info: dict) -> str | None:
    v = info.get("venue")
    if isinstance(v, list):
        v = v[0] if v else None
    return v or None


def _is_published(info: dict) -> bool:
    """True for a real published record; False for DBLP's arXiv/CoRR twin.

    A conference paper has both a ``conf/...`` entry and a ``journals/corr/...``
    (arXiv) entry in DBLP; the latter carries an arXiv-placeholder DOI and an
    ``abs/<id>`` "volume", which we must not copy onto the published item.
    """
    return (
        "informal" not in (info.get("type") or "").lower()
        and (_venue(info) or "").lower() != "corr"
    )


def best_match(title: str, hits: list[dict]) -> tuple[dict | None, float]:
    """Pick the closest-title DBLP hit, preferring a published entry over CoRR.

    Among hits above the title threshold, a real published record wins even at a
    slightly lower title ratio than its arXiv twin; only if none is published do
    we fall back to the best raw match.
    """
    want = _norm_title(title)
    scored = sorted(
        ((SequenceMatcher(None, want, _norm_title(i.get("title", ""))).ratio(), i)
         for i in hits),
        key=lambda x: x[0],
        reverse=True,
    )
    above = [(r, i) for r, i in scored if r >= TITLE_MIN]
    published = [(r, i) for r, i in above if _is_published(i)]
    for pool in (published, above, scored):
        if pool:
            ratio, info = pool[0]
            return info, ratio
    return None, 0.0


def classify(data: dict, info: dict) -> tuple[str, list[str]]:
    """Return ('confirmed'|'suspect', reasons) for a title-matched DBLP hit."""
    reasons = []

    our_year, their_year = _year(data.get("date", "")), _year(info.get("year", ""))
    if our_year and their_year:
        delta = abs(our_year - their_year)
        if delta == 0:
            pass
        elif delta == 1:
            reasons.append(f"year off by 1 (ours {our_year}, dblp {their_year})")
        else:
            return "suspect", [f"year mismatch (ours {our_year}, dblp {their_year})"]

    our_auth, their_auth = _item_surnames(data), _surnames(dblp_authors(info))
    if our_auth and their_auth:
        overlap = our_auth & their_auth
        if not overlap:
            return "suspect", reasons + ["no shared authors with dblp"]
        if len(overlap) / min(len(our_auth), len(their_auth)) < 0.5:
            reasons.append("weak author overlap")
    return "confirmed", reasons


def enrich(data: dict, info: dict, *, canonical_venue: bool) -> Changes:
    ch = Changes(data)
    doi = info.get("doi")
    # Never write an arXiv-placeholder DOI onto a published conference paper.
    if doi and not is_arxiv_placeholder_doi(doi) and not (data.get("DOI") or "").strip():
        ch.set("DOI", doi)

    venue = _venue(info)
    if (
        venue
        and venue.lower() != "corr"
        and (canonical_venue or not (data.get("proceedingsTitle") or "").strip())
    ):
        ch.set("proceedingsTitle", venue)

    year = info.get("year")
    if year and not (data.get("date") or "").strip():
        ch.set("date", str(year))

    if info.get("pages") and not (data.get("pages") or "").strip():
        ch.set("pages", info["pages"])

    volume = info.get("volume")
    # DBLP stores arXiv ids ("abs/1904.09237") in 'volume' — not a real volume.
    if volume and not volume.lower().startswith("abs/") and not (data.get("volume") or "").strip():
        ch.set("volume", volume)
    return ch


def _title(data: dict, n: int = 70) -> str:
    return (data.get("title") or "<untitled>")[:n]


def main() -> None:
    parser = build_parser(__doc__.splitlines()[0])
    parser.add_argument(
        "--only-missing",
        action="store_true",
        help="Only check papers missing at least one fillable field "
        "(DOI/proceedingsTitle/pages/volume) — faster.",
    )
    parser.add_argument(
        "--canonical-venue",
        action="store_true",
        help="Overwrite proceedingsTitle with DBLP's canonical venue even when "
        "one is already set (default: only fill when empty).",
    )
    args = parser.parse_args()
    zot = get_client()
    dry_run = not args.apply

    papers = fetch_items(zot, "conferencePaper")
    if args.only_missing:
        papers = [
            it
            for it in papers
            if any(not (it["data"].get(f) or "").strip() for f in
                   ("DOI", "proceedingsTitle", "pages", "volume"))
        ]
    if args.limit is not None:
        papers = papers[: args.limit]

    mode = "DRY-RUN — no writes" if dry_run else "APPLYING changes"
    print(f"{mode}: verifying {len(papers)} conference papers against DBLP\n")

    counts = {"confirmed": 0, "filled": 0, "suspect": 0, "not_found": 0, "throttled": 0}
    consecutive_throttle = 0
    for i, item in enumerate(papers, 1):
        data = item["data"]
        title = data.get("title") or ""
        if not title:
            counts["not_found"] += 1
            continue

        try:
            hits = dblp_search(title)
            consecutive_throttle = 0
        except DBLPThrottled:
            counts["throttled"] += 1
            consecutive_throttle += 1
            print(f"[{i}/{len(papers)}] THROTTLED  {_title(data)} (left unverified)")
            if consecutive_throttle >= 10:
                print("\nDBLP is rate-limiting persistently (10 in a row); stopping "
                      "early. Re-run later to cover the rest.")
                break
            continue

        info, ratio = best_match(title, hits)
        if not info or ratio < TITLE_MIN:
            counts["not_found"] += 1
            if args.verbose:
                print(f"[{i}/{len(papers)}] NOT FOUND  {_title(data)} (best ratio {ratio:.2f})")
            continue

        verdict, reasons = classify(data, info)
        if verdict == "suspect":
            counts["suspect"] += 1
            print(f"[{i}/{len(papers)}] SUSPECT    {_title(data)}")
            print(f"             dblp: {info.get('title','')[:70]!r} ({info.get('year')})")
            print(f"             why : {'; '.join(reasons)}")
            continue

        counts["confirmed"] += 1
        ch = enrich(data, info, canonical_venue=args.canonical_venue)
        note = f" [{'; '.join(reasons)}]" if reasons else ""
        if not ch:
            if args.verbose:
                print(f"[{i}/{len(papers)}] ok         {_title(data)}{note}")
            continue
        counts["filled"] += 1
        print(f"[{i}/{len(papers)}] CONFIRMED  {_title(data)}{note}")
        for field, old, new in ch.diffs:
            print(f"             {field}: {old!r} -> {new!r}")
        if not dry_run:
            try:
                zot.update_item(item)
            except Exception as exc:
                # 412 "modified since" — our fetched version is stale because
                # the item was touched elsewhere in this session. Refetch and
                # retry once, only filling what is *still* empty on the server.
                if "modified since" not in str(exc):
                    print(f"             ERROR (will skip): {exc}")
                    counts["filled"] -= 1
                    continue
                try:
                    fresh = zot.item(item["key"])
                    ch2 = enrich(fresh["data"], info,
                                 canonical_venue=args.canonical_venue)
                    if ch2:
                        zot.update_item(fresh)
                    else:
                        print(f"             (already filled on server; skipped)")
                        counts["filled"] -= 1
                except Exception as exc2:
                    print(f"             ERROR after refetch (skip): {exc2}")
                    counts["filled"] -= 1

    print(
        f"\nConfirmed {counts['confirmed']} "
        f"({counts['filled']} {'would be ' if dry_run else ''}filled), "
        f"suspect {counts['suspect']}, not found {counts['not_found']}, "
        f"throttled {counts['throttled']}."
    )
    if counts["throttled"]:
        print(f"{counts['throttled']} papers were left UNVERIFIED due to DBLP "
              "rate-limiting — re-run later to cover them.")
    if dry_run and counts["filled"]:
        print("Re-run with --apply to write these changes.")


if __name__ == "__main__":
    main()
