"""Shared CLI scaffolding: argument parsing, change tracking, the update engine.

Every pipeline script follows the same shape:

    1. fetch candidate items,
    2. for each candidate, re-fetch the fresh item (current version token),
    3. compute field changes via a ``transform`` callback,
    4. print a per-item old -> new diff and (unless dry-run) write it back.

``transform`` mutates the freshly fetched item in place through a
:class:`Changes` recorder and returns that recorder; its ``.diffs`` drive the
printed old -> new diff. ``apply_updates`` then hands the mutated item (not the
return value) to ``zot.update_item``.
"""

from __future__ import annotations

import argparse
import time
from typing import Callable


class Changes:
    """Records field edits on an item's ``data`` dict and the resulting diff."""

    def __init__(self, data: dict):
        self.data = data
        self.diffs: list[tuple[str, object, object]] = []

    def set(self, field: str, value) -> None:
        """Set ``data[field] = value``, recording the change if it differs."""
        old = self.data.get(field)
        if old != value:
            self.diffs.append((field, old, value))
            self.data[field] = value

    def __bool__(self) -> bool:
        return bool(self.diffs)


# Signature: transform(zot, fresh_item) -> Changes
Transform = Callable[[object, dict], Changes]


def build_parser(description: str) -> argparse.ArgumentParser:
    """Return a parser preloaded with the flags common to every script."""
    parser = argparse.ArgumentParser(description=description)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Actually write changes to Zotero. Without this flag the script "
        "runs in dry-run mode and only previews the diff.",
    )
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without writing (the default; this flag just "
        "makes the intent explicit and cannot be combined with --apply).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Process at most N candidate items (useful for testing).",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Also log items that needed no change.",
    )
    return parser


def _title(item: dict, n: int = 70) -> str:
    return (item["data"].get("title") or "<untitled>")[:n]


def apply_updates(
    zot,
    candidates: list,
    transform: Transform,
    *,
    dry_run: bool,
    verbose: bool = False,
    limit: int | None = None,
    write_sleep: float = 0.0,
    label: str = "items",
) -> int:
    """Run ``transform`` over ``candidates``, previewing or writing each diff.

    Returns the number of items changed (or that *would* change in dry-run).
    """
    if limit is not None:
        candidates = candidates[:limit]

    total = len(candidates)
    mode = "DRY-RUN — no writes" if dry_run else "APPLYING changes"
    print(f"{mode}: {total} candidate {label}\n")

    n_changed = 0
    for i, cand in enumerate(candidates, 1):
        # Re-fetch (fresh version token) + compute changes. A transient Zotero
        # error (429/502/503) or a malformed item must skip this item, never
        # crash the whole stage.
        try:
            fresh = zot.item(cand["key"])
            changes = transform(zot, fresh)
        except Exception as exc:
            print(f"[{i}/{total}] ERROR  {_title(cand)}: {exc}")
            continue

        if not changes:
            if verbose:
                print(f"[{i}/{total}] ok     {_title(fresh)} (no change)")
            continue

        print(f"[{i}/{total}] change {_title(fresh)}")
        for field, old, new in changes.diffs:
            print(f"           {field}: {old!r} -> {new!r}")

        if not dry_run:
            try:
                zot.update_item(fresh)
            except Exception as exc:
                print(f"[{i}/{total}] ERROR writing {_title(fresh)}: {exc}")
                continue
            if write_sleep:
                time.sleep(write_sleep)
        n_changed += 1

    verb = "Would update" if dry_run else "Updated"
    print(f"\n{verb} {n_changed}/{total} {label}.")
    if dry_run and n_changed:
        print("Re-run with --apply to write these changes.")
    return n_changed
