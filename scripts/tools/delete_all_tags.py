#!/usr/bin/env python3
"""Tool — bulk-delete EVERY tag in the library. Destructive, opt-in, irreversible.

Ported from ``pyzotero.ipynb``. NOT part of the cleanup pipeline. Without
``--yes`` it only reports how many tags exist; with ``--yes`` it deletes them all
in batches of 50 (the Zotero server limit).
"""

from __future__ import annotations

import argparse

from zotcleanup import get_client, split_list


def load_all_tags(zot, verbose: bool = True) -> list[str]:
    tagiter = zot.makeiter(zot.tags())
    seen = 0
    all_tags: list[str] = []
    for tags in tagiter:
        seen += len(tags)
        if verbose and tags:
            print(f"{seen:05d} {tags[-1]}")
        all_tags.extend(tags)
    return all_tags


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm deletion of ALL tags. Without it, only the count is shown.",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="List tags as they load.")
    args = parser.parse_args()

    zot = get_client()
    tags = load_all_tags(zot, verbose=args.verbose)
    print(f"\n{len(tags)} tags in the library.")

    if not args.yes:
        print("Dry run: pass --yes to delete ALL of them (irreversible).")
        return

    n_batches = (len(tags) + 49) // 50
    for n, chunk in enumerate(split_list(tags, 50), 1):
        print(f"Deleting batch {n}/{n_batches} ({len(chunk)} tags)...")
        zot.delete_tags(*chunk)
    print(f"Deleted {len(tags)} tags.")


if __name__ == "__main__":
    main()
