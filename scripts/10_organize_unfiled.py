#!/usr/bin/env python3
"""Stage 10 — file unfiled references into collections.

"Unfiled" means a top-level item in *no* collection. Orphaned PDF
``annotation`` items (the bulk of the raw count) are ignored — only real
references are candidates.

The interesting part — deciding *which* collection a paper belongs in — is a
judgement call, so this script splits cleanly into two phases:

* ``--export PATH``  Dump every unfiled reference (key, type, title, abstract,
  tags, publication) to JSON, plus a flat catalog of assignable collections.
  An agent (or you) reads this and writes an assignment map.
* ``--map PATH``     Read an assignment map ``{item_key: [collection_key, ...]}``
  and add each item to those collections, batched 50/write. Dry-run unless
  ``--apply``. Unknown keys are reported and skipped; items are never removed
  from anywhere, only added.

    uv run scripts/10_organize_unfiled.py --export unfiled.json
    uv run scripts/10_organize_unfiled.py --map assignments.json          # preview
    uv run scripts/10_organize_unfiled.py --map assignments.json --apply
"""

from __future__ import annotations

import json
import sys

from zotcleanup import (
    Tree,
    add_items_to_collection,
    all_collections,
    build_parser,
    get_client,
    split_list,
)

SKIP_TYPES = {"attachment", "note", "annotation"}
# Where unfiled references should land. Per the user's intent, topics — not
# individual projects — are the default home, but the catalog lists everything.
CATALOG_ROOTS = ("01 Lib: Topics", "00 Project: Current")


def iter_unfiled(zot):
    """Yield top-level reference items that belong to no collection."""
    start = 0
    while True:
        batch = zot.items(top=True, start=start, limit=100)
        if not batch:
            break
        for it in batch:
            d = it["data"]
            if d.get("itemType") in SKIP_TYPES:
                continue
            if not d.get("collections"):
                yield it
        start += len(batch)
        sys.stderr.write(f"\r  fetched {start}")
        sys.stderr.flush()
    sys.stderr.write("\n")


def export(zot, tree: Tree, path: str) -> None:
    items = list(iter_unfiled(zot))
    records = []
    for it in items:
        d = it["data"]
        records.append(
            {
                "key": it["key"],
                "type": d.get("itemType"),
                "title": d.get("title"),
                "abstract": (d.get("abstractNote") or "")[:600],
                "publication": d.get("publicationTitle") or d.get("proceedingsTitle"),
                "tags": [t["tag"] for t in d.get("tags", [])],
                "date": d.get("date"),
            }
        )

    catalog = []
    for root_name in CATALOG_ROOTS:
        root = tree.find_root(root_name)
        if root is None:
            continue
        for c in tree.descendants(root["key"], include_self=True):
            catalog.append({"key": c["key"], "path": tree.path(c["key"])})

    with open(path, "w") as fh:
        json.dump({"items": records, "collections": catalog}, fh, indent=2)
    print(f"Exported {len(records)} unfiled references and {len(catalog)} "
          f"collections to {path}")


def apply_map(zot, tree: Tree, path: str, *, dry_run: bool, limit: int | None) -> None:
    with open(path) as fh:
        mapping: dict[str, list[str]] = json.load(fh)

    # Validate collection keys up front.
    bad = {ck for cks in mapping.values() for ck in cks if ck not in tree.by_key}
    if bad:
        print(f"WARNING: {len(bad)} unknown collection keys will be skipped: {sorted(bad)}\n")

    pairs = list(mapping.items())
    if limit is not None:
        pairs = pairs[:limit]

    mode = "DRY-RUN — no writes" if dry_run else "APPLYING changes"
    print(f"{mode}: filing {len(pairs)} items\n")

    # Group by target collection so each collection is one batched write.
    by_collection: dict[str, list[str]] = {}
    for item_key, col_keys in pairs:
        for ck in col_keys:
            if ck in tree.by_key:
                by_collection.setdefault(ck, []).append(item_key)

    # Pre-fetch every unique item in batches of 50. One GET per item would be
    # N+1, and an item assigned to several collections would be fetched once per
    # collection; caching avoids both.
    all_keys = list({k for ks in by_collection.values() for k in ks})
    item_cache: dict[str, dict] = {}
    for chunk in split_list(all_keys, 50):
        for it in zot.items(itemKey=",".join(chunk), limit=50):
            item_cache[it["key"]] = it

    n_moves = 0
    for ck, item_keys in by_collection.items():
        items = [item_cache[k] for k in item_keys if k in item_cache]
        moved = add_items_to_collection(zot, ck, items, dry_run=dry_run)
        n_moves += moved
        print(f"  {tree.path(ck)}  <- {moved} item(s)")
        for it in items:
            print(f"      {(it['data'].get('title') or '<untitled>')[:80]}")

    verb = "Would file" if dry_run else "Filed"
    print(f"\n{verb} {n_moves} item-placements across {len(by_collection)} collections.")
    if dry_run and n_moves:
        print("Re-run with --apply to write these changes.")


def main() -> None:
    parser = build_parser(__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--export", metavar="PATH", help="Dump unfiled items + catalog to JSON.")
    group.add_argument("--map", metavar="PATH", help="Apply an assignment map JSON.")
    args = parser.parse_args()

    zot = get_client()
    tree = Tree(all_collections(zot))

    if args.export:
        export(zot, tree, args.export)
    else:
        apply_map(zot, tree, args.map, dry_run=not args.apply, limit=args.limit)


if __name__ == "__main__":
    main()
