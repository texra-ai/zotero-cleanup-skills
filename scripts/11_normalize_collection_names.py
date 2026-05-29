#!/usr/bin/env python3
"""Stage 11 — normalize collection names under the live project/topic trees.

The library grew organically, so a collection's ordering prefix shows up glued
(``00Core``), dashed (``00-Core``) or spaced (``00 Core``) interchangeably, and
some numbers run straight into their label (``04GoogleTN``,
``13SequentiallyGeneratedTNs``). This stage canonicalizes a *leading numeric
prefix* to ``NN <rest>`` — a single, well-defined transformation:

    00Core               -> 00 Core
    00-Parallel Tempering-> 00 Parallel Tempering
    04GoogleTN           -> 04 GoogleTN
    00 Survey            -> 00 Survey   (unchanged)

Deliberately conservative — it does **not** touch:

* letter-prefixed codes (``R0-Max``, ``P0-...``, ``QuPCA``) — those are an
  intentional scheme, not a typo;
* casing — the library is full of acronyms (OTOC, MBL, QEC, SYK) that naive
  title-casing would mangle.

Scope is limited to the descendants of the two top-level trees named below;
``Mendeley Import 2021`` and anything else is left alone. Dry-run by default.
"""

from __future__ import annotations

import re

from zotcleanup import (
    Tree,
    all_collections,
    build_parser,
    get_client,
    rename_collection,
)

# Top-level trees whose descendants we normalize. Everything else is untouched.
TARGET_ROOTS = ("00 Project: Current", "01 Lib: Topics")

# digits + (separator OR glued letter) + remainder
_DIGITS_SEP = re.compile(r"^(\d+)[\s\-_]+(\S.*)$")
_DIGITS_GLUED = re.compile(r"^(\d+)([A-Za-z].*)$")


def normalize_name(name: str) -> str:
    """Canonicalize a leading numeric prefix to ``NN <rest>``; else unchanged."""
    m = _DIGITS_SEP.match(name) or _DIGITS_GLUED.match(name)
    if not m:
        return name
    return f"{m.group(1)} {m.group(2).strip()}"


def main() -> None:
    parser = build_parser(__doc__.splitlines()[0])
    args = parser.parse_args()
    zot = get_client()

    tree = Tree(all_collections(zot))

    # Gather every collection under a target root (excluding the roots).
    candidates: list[dict] = []
    for root_name in TARGET_ROOTS:
        root = tree.find_root(root_name)
        if root is None:
            print(f"WARNING: top-level collection {root_name!r} not found; skipping.")
            continue
        candidates.extend(tree.descendants(root["key"], include_self=False))

    if args.limit is not None:
        candidates = candidates[: args.limit]

    dry_run = not args.apply
    mode = "DRY-RUN — no writes" if dry_run else "APPLYING changes"
    print(f"{mode}: scanning {len(candidates)} collections\n")

    n = 0
    for c in candidates:
        old = c["data"]["name"]
        new = normalize_name(old)
        if old == new:
            if args.verbose:
                print(f"  ok     {tree.path(c['key'])}")
            continue
        n += 1
        print(f"  rename {tree.path(tree.parent(c['key']))} / {old!r} -> {new!r}")
        rename_collection(zot, c, new, dry_run=dry_run)

    verb = "Would rename" if dry_run else "Renamed"
    print(f"\n{verb} {n}/{len(candidates)} collections.")
    if dry_run and n:
        print("Re-run with --apply to write these changes.")


if __name__ == "__main__":
    main()
