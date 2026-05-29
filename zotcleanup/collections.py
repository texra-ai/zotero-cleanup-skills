"""Reusable collection (folder) operations for a large Zotero library.

The metadata pipeline (scripts 01-09) edits *items*. This module edits the
*collection tree* and item-collection *membership* — the raw material for
organizing unfiled items, renaming folders consistently, and merging
duplicates.

Two design goals, because the library is big (~900 collections, ~16k items):

* **Cheap to read.** Fetch the whole collection tree once into a :class:`Tree`
  and answer parent/child/path/lookup questions in memory.
* **Cheap to write.** Membership changes go through ``update_items`` in batches
  of 50 (the Zotero API ceiling) rather than one request per item.

Every mutating function takes ``dry_run`` and, when true, performs no writes —
it only returns what it *would* do, so callers can print a diff first.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterator

from .helpers import split_list


# --------------------------------------------------------------------------- #
# Reading the tree
# --------------------------------------------------------------------------- #


def all_collections(zot) -> list[dict]:
    """Fetch every collection in the library (paged for you)."""
    return zot.everything(zot.collections())


class Tree:
    """In-memory view of the collection hierarchy.

    Build once from :func:`all_collections`; all lookups are then local.
    """

    def __init__(self, collections: list[dict]):
        self.collections = collections
        self.by_key: dict[str, dict] = {c["key"]: c for c in collections}
        self.children: dict[str | None, list[dict]] = defaultdict(list)
        for c in collections:
            self.children[c["data"].get("parentCollection") or None].append(c)

    # -- basic accessors --------------------------------------------------- #

    def name(self, key: str) -> str:
        return self.by_key[key]["data"]["name"]

    def parent(self, key: str) -> str | None:
        return self.by_key[key]["data"].get("parentCollection") or None

    def num_items(self, key: str) -> int:
        """Items directly in this collection (not counting subcollections)."""
        return self.by_key[key]["meta"].get("numItems", 0)

    def roots(self) -> list[dict]:
        return self.child_collections(None)

    def child_collections(self, key: str | None) -> list[dict]:
        return list(self.children[key])

    def path(self, key: str, sep: str = " / ") -> str:
        """Human-readable path from the root, e.g. ``01 Lib: Topics / QEC``."""
        parts: list[str] = []
        cur: str | None = key
        while cur is not None and cur in self.by_key:
            parts.append(self.by_key[cur]["data"]["name"])
            cur = self.parent(cur)
        return sep.join(reversed(parts))

    # -- navigation -------------------------------------------------------- #

    def find_root(self, name: str) -> dict | None:
        """Top-level collection with this exact name, or ``None``."""
        for c in self.children[None]:
            if c["data"]["name"] == name:
                return c
        return None

    def descendants(self, key: str, include_self: bool = False) -> list[dict]:
        """All collections beneath ``key`` (depth-first)."""
        out: list[dict] = [self.by_key[key]] if include_self else []
        stack = list(self.children[key])
        while stack:
            c = stack.pop()
            out.append(c)
            stack.extend(self.children[c["key"]])
        return out

    def walk(self, key: str | None = None, depth: int = 0) -> Iterator[tuple[dict, int]]:
        """Yield ``(collection, depth)`` in sorted, indented tree order."""
        for c in sorted(self.children[key], key=lambda x: x["data"]["name"].lower()):
            yield c, depth
            yield from self.walk(c["key"], depth + 1)

    def duplicate_siblings(
        self, key: str | None, normalize=lambda s: s.strip().lower()
    ) -> dict[str, list[dict]]:
        """Group a node's direct children by normalized name.

        Returns only the groups with more than one member — i.e. sibling
        collections that collide under ``normalize`` and are merge candidates.
        """
        groups: dict[str, list[dict]] = defaultdict(list)
        for c in self.children[key]:
            groups[normalize(c["data"]["name"])].append(c)
        return {k: v for k, v in groups.items() if len(v) > 1}


# --------------------------------------------------------------------------- #
# Writing — every function is dry-run aware
# --------------------------------------------------------------------------- #

# Item types that are never moved between collections (PDF annotations etc.).
_SKIP_ITEM_TYPES = frozenset({"attachment", "note", "annotation"})


def create_collection(zot, name: str, parent_key: str | None, *, dry_run: bool) -> str | None:
    """Create a collection ``name`` under ``parent_key`` (or top-level if None).

    Returns the new collection's key, or ``None`` in dry-run. The Zotero write
    API returns created keys under ``successful``.
    """
    if dry_run:
        return None
    payload = {"name": name}
    if parent_key:
        payload["parentCollection"] = parent_key
    resp = zot.create_collections([payload])
    return resp["successful"]["0"]["key"]


def rename_collection(zot, collection: dict, new_name: str, *, dry_run: bool) -> bool:
    """Rename ``collection`` to ``new_name``. Returns True if it changed."""
    if collection["data"]["name"] == new_name:
        return False
    if not dry_run:
        # update_collection does a full replace — we MUST echo parentCollection,
        # or the collection is detached to the top level.
        payload = {
            "key": collection["key"],
            "version": collection["version"],
            "name": new_name,
            "parentCollection": collection["data"].get("parentCollection") or False,
        }
        zot.update_collection(payload)
        collection["data"]["name"] = new_name
        collection["version"] += 1
    return True


def add_items_to_collection(
    zot, collection_key: str, items: list[dict], *, dry_run: bool
) -> int:
    """Add ``collection_key`` to each item's membership, batched (<=50/write).

    ``items`` are full item dicts (with ``version``). Items already in the
    collection are skipped. Returns the number actually (or notionally) moved.
    """
    pending = [
        it
        for it in items
        if collection_key not in (it["data"].get("collections") or [])
    ]
    if not pending:
        return 0
    if not dry_run:
        for chunk in split_list(pending, 50):
            payload = []
            for it in chunk:
                cols = list(it["data"].get("collections") or [])
                cols.append(collection_key)
                it["data"]["collections"] = cols
                payload.append(it["data"])
            zot.update_items(payload)
    return len(pending)


def merge_collection(zot, tree: Tree, src_key: str, dst_key: str, *, dry_run: bool) -> dict:
    """Merge collection ``src`` into ``dst`` and delete ``src``.

    Moves ``src``'s directly-held items into ``dst`` (adds ``dst`` to their
    membership, removes ``src``), reparents ``src``'s subcollections under
    ``dst``, then deletes the now-empty ``src``. Returns a summary dict.
    Caller is responsible for not creating a cycle (``dst`` not under ``src``).
    """
    moved_subcols = [c["key"] for c in tree.child_collections(src_key)]

    # 1. Move items out of src into dst.
    items = zot.everything(zot.collection_items(src_key))
    items = [it for it in items if it["data"].get("itemType") not in _SKIP_ITEM_TYPES]
    if not dry_run:
        for chunk in split_list(items, 50):
            payload = []
            for it in chunk:
                cols = list(it["data"].get("collections") or [])
                if src_key in cols:
                    cols.remove(src_key)
                if dst_key not in cols:
                    cols.append(dst_key)
                it["data"]["collections"] = cols
                payload.append(it["data"])
            zot.update_items(payload)
    moved_items = len(items)

    # 2. Reparent src's subcollections under dst, then 3. delete the empty src.
    if not dry_run:
        for sub_key in moved_subcols:
            sub = tree.by_key[sub_key]
            zot.update_collection(
                {
                    "key": sub["key"],
                    "version": sub["version"],
                    "name": sub["data"]["name"],
                    "parentCollection": dst_key,
                }
            )
        fresh = zot.collection(src_key)
        zot.delete_collection(fresh)

    return {
        "src": tree.path(src_key),
        "dst": tree.path(dst_key),
        "moved_items": moved_items,
        "moved_subcollections": len(moved_subcols),
    }
