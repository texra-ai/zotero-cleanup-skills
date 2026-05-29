#!/usr/bin/env python3
"""Tool — detect items whose DOI returns 404 at doi.org.

Scans every item with a non-arXiv-placeholder DOI and ``HEAD``s
``https://doi.org/<doi>`` (in parallel). A 404 means the DOI doesn't resolve —
the case the CSL linter flags as ``correct-doi-long``. With ``--apply``, clears
the DOI field on the confirmed-dead ones (the rest of the metadata is kept).

    uv run scripts/tools/detect_dead_dois.py                    # scan only
    uv run scripts/tools/detect_dead_dois.py --apply            # clear dead DOIs
    uv run scripts/tools/detect_dead_dois.py --limit 200        # quick sample
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import re

import requests

from zotcleanup import fetch_items, get_client, is_arxiv_placeholder_doi


_SESSION = requests.Session()
_SESSION.headers["User-Agent"] = "zotcleanup-dead-doi-check/0.1"


def _status(doi: str) -> int | None:
    """HTTP status for ``https://doi.org/<doi>``, or ``None`` on network error."""
    try:
        r = _SESSION.head(
            f"https://doi.org/{doi}", timeout=15, allow_redirects=True
        )
        return r.status_code
    except Exception:
        return None


def _candidate_fixes(doi: str) -> list[str]:
    """A small set of safe DOI repairs to try when ``doi`` 404s."""
    fixes: list[str] = []

    # 1. Unescape LaTeX backslash-escapes (``\_`` → ``_`` etc.).
    if "\\" in doi:
        unescaped = doi
        for esc in ("_", "&", "#", "$", "%", "{", "}"):
            unescaped = unescaped.replace("\\" + esc, esc)
        if unescaped != doi:
            fixes.append(unescaped)

    # 2. Springer book chapter style: ``10.1007/978-…-N`` → ``…_N``
    #    (final dash before a digit run should be an underscore for chapters).
    m = re.match(r"^(10\.\d+/978[-\d]+?)-(\d+)$", doi)
    if m and "_" not in doi.split("/", 1)[1]:
        fixes.append(f"{m.group(1)}_{m.group(2)}")

    # 3. Physical-Review-style missing-zero (e.g. ``…89.15001`` → ``…89.015001``).
    m = re.match(r"^(10\.1103/[A-Za-z.]+\.\d+)\.(\d{5})$", doi)
    if m:
        fixes.append(f"{m.group(1)}.0{m.group(2)}")

    return fixes


def _attempt_fix(doi: str) -> str | None:
    """First repaired DOI that resolves, or ``None``."""
    for fix in _candidate_fixes(doi):
        if _status(fix) == 200:
            return fix
    return None


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--apply", action="store_true", help="Clear the DOI on confirmed-dead items.")
    p.add_argument("--limit", type=int, default=None, help="Check at most N candidates.")
    p.add_argument("--workers", type=int, default=10, help="Parallel HEAD requests (default 10).")
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args()

    zot = get_client()
    items = fetch_items(zot)
    candidates = [
        it for it in items
        if (it["data"].get("DOI") or "").strip()
        and not is_arxiv_placeholder_doi(it["data"]["DOI"])
    ]
    if args.limit is not None:
        candidates = candidates[: args.limit]

    print(f"Checking {len(candidates)} DOIs at doi.org with {args.workers} workers...\n")

    dead: list[dict] = []
    n_done = 0
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(_status, it["data"]["DOI"]): it for it in candidates}
        for fut in cf.as_completed(futures):
            it = futures[fut]
            status = fut.result()
            n_done += 1
            if status == 404:
                dead.append(it)
                title = (it["data"].get("title") or "<no title>")[:65]
                print(f"  [404] {title}  DOI={it['data']['DOI']}")
            elif args.verbose and status not in (None, 200, 301, 302, 303):
                title = (it["data"].get("title") or "")[:60]
                print(f"  [{status}] {title}  DOI={it['data']['DOI']}")
            if n_done % 500 == 0:
                print(f"  ... checked {n_done}/{len(candidates)}")

    print(f"\n{len(dead)} dead DOIs found out of {len(candidates)} checked.\n")
    if not dead:
        return

    # For each dead DOI, see if a safe repair makes it resolve.
    print("Attempting auto-fixes for dead DOIs...")
    plan: list[tuple[dict, str | None]] = []  # (item, new_doi_or_None_for_clear)
    for it in dead:
        bad = it["data"]["DOI"]
        fix = _attempt_fix(bad)
        plan.append((it, fix))
        title = (it["data"].get("title") or "")[:55]
        if fix:
            print(f"  FIX   {title}\n        {bad!r} -> {fix!r}")
        else:
            print(f"  CLEAR {title}\n        {bad!r}")

    n_fix = sum(1 for _, f in plan if f)
    n_clear = len(plan) - n_fix
    print(f"\n{n_fix} fixable · {n_clear} to clear")

    if not args.apply:
        print("Dry run — re-run with --apply to apply fixes and clear the rest.")
        return

    fixed = cleared = 0
    for it, fix in plan:
        try:
            fresh = zot.item(it["key"])
            fresh["data"]["DOI"] = fix if fix else ""
            zot.update_item(fresh)
            if fix:
                fixed += 1
            else:
                cleared += 1
        except Exception as exc:
            print(f"  ERROR updating {it['key']}: {exc}")
    print(f"Fixed {fixed}, cleared {cleared}.")


if __name__ == "__main__":
    main()
