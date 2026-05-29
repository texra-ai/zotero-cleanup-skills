#!/usr/bin/env python3
"""Stage 12 — find collision-named collections and merge a chosen pair.

A scan of this library turned up *no* true duplicate siblings (collections with
the same name under the same parent). The repeated names that exist — ``00Survey``,
``Others``, ``Gibbs state`` — live under different parents and are genuinely
different topics, so merging them automatically would be wrong.

This stage therefore does two things, neither destructive by default:

1. **report** (default): list every name that appears in more than one place
   under the target trees, with each location's path, item count and key — so
   you can eyeball real duplicates.
2. **merge** (``--merge SRC_KEY DST_KEY``): fold one specific collection into
   another — move SRC's items into DST, reparent SRC's subcollections under
   DST, then delete SRC. Dry-run unless ``--apply`` is given.

    uv run scripts/12_merge_collections.py                       # report collisions
    uv run scripts/12_merge_collections.py --merge AAA BBB       # preview a merge
    uv run scripts/12_merge_collections.py --merge AAA BBB --apply
"""

from __future__ import annotations

from collections import defaultdict

from zotcleanup import (
    Tree,
    all_collections,
    build_parser,
    get_client,
    merge_collection,
)

TARGET_ROOTS = ("00 Project: Current", "01 Lib: Topics")


def target_keys(tree: Tree) -> set[str]:
    keys: set[str] = set()
    for root_name in TARGET_ROOTS:
        root = tree.find_root(root_name)
        if root is not None:
            keys.update(c["key"] for c in tree.descendants(root["key"], include_self=True))
    return keys


def report(tree: Tree) -> None:
    keys = target_keys(tree)
    by_name: dict[str, list[str]] = defaultdict(list)
    for k in keys:
        by_name[tree.name(k).strip().lower()].append(k)

    collisions = {n: ks for n, ks in by_name.items() if len(ks) > 1}
    print(f"{len(collisions)} names appear in more than one place:\n")
    for _, ks in sorted(collisions.items(), key=lambda x: -len(x[1])):
        print(f"  {tree.name(ks[0])!r}  (x{len(ks)})")
        for k in ks:
            print(f"      [{tree.num_items(k):4}] {tree.path(k)}   key={k}")
    print("\nNothing was changed. To fold one into another:")
    print("  uv run scripts/12_merge_collections.py --merge <SRC_KEY> <DST_KEY> [--apply]")


def main() -> None:
    parser = build_parser(__doc__.splitlines()[0])
    parser.add_argument(
        "--merge",
        nargs=2,
        metavar=("SRC_KEY", "DST_KEY"),
        help="Merge SRC collection into DST, then delete SRC.",
    )
    args = parser.parse_args()
    zot = get_client()
    tree = Tree(all_collections(zot))

    if not args.merge:
        report(tree)
        return

    src_key, dst_key = args.merge
    for k in (src_key, dst_key):
        if k not in tree.by_key:
            raise SystemExit(f"Collection key {k!r} not found.")
    # Guard against folding a collection into its own descendant.
    if dst_key in {c["key"] for c in tree.descendants(src_key, include_self=False)}:
        raise SystemExit("DST is a descendant of SRC — that would create a cycle.")

    dry_run = not args.apply
    mode = "DRY-RUN — no writes" if dry_run else "APPLYING changes"
    print(f"{mode}")
    print(f"  SRC: {tree.path(src_key)}")
    print(f"  DST: {tree.path(dst_key)}")
    summary = merge_collection(zot, tree, src_key, dst_key, dry_run=dry_run)
    verb = "Would move" if dry_run else "Moved"
    print(
        f"\n{verb} {summary['moved_items']} items and "
        f"{summary['moved_subcollections']} subcollections; "
        f"{'would delete' if dry_run else 'deleted'} SRC."
    )
    if dry_run:
        print("Re-run with --apply to perform the merge.")


if __name__ == "__main__":
    main()
