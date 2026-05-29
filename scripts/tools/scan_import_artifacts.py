"""Read-only scan for bad-metadata-import artifacts across the whole library.

Detects a family of bad-metadata-import problems:
  - arXiv IDs / identifiers stuffed into the Volume (or Issue/Pages) field
  - fake "E. Al." authors (mangled "et al.")
  - other "et al." / "and others" literals living in a creator slot
  - arXiv IDs leaking into journal/publication-title text fields

Fetches every top-level item once, caches to scan_cache.json, then reports.
Nothing is written back. Run again with --refresh to re-pull from the API.
"""

from __future__ import annotations

import json
import os
import re
import sys

from zotcleanup import ARXIV_NEW_RE, ARXIV_OLD_RE, get_client

CACHE = os.path.join(os.path.dirname(__file__), "scan_cache.json")

# arXiv-id detectors (new-style 2009.03393, old-style cs.LG/0309044) come from
# the shared package, so "what an arXiv id looks like" has one definition.
# These two are specific to the scanner's free-text search:
ARXIV_WORD = re.compile(r"arxiv", re.I)
CATEGORY = re.compile(r"\[(?:[a-z\-]+\.[A-Z]{2}|math\.[A-Z]{2}|cs\.[A-Z]{2})\]", re.I)

# "et al." mangled into an author name slot
ETAL = re.compile(r"^\s*(e\.?\s*al\.?|et\.?\s*al\.?|and\s+others|others)\s*$", re.I)


def load_items() -> list:
    refresh = "--refresh" in sys.argv
    if not refresh and os.path.exists(CACHE):
        with open(CACHE) as f:
            return json.load(f)
    zot = get_client()
    print("Fetching all top-level items (this is slow)…", file=sys.stderr)
    items = zot.everything(zot.top())
    with open(CACHE, "w") as f:
        json.dump(items, f)
    print(f"Cached {len(items)} items to {CACHE}", file=sys.stderr)
    return items


def arxiv_like(val: str) -> str | None:
    if not val:
        return None
    if ARXIV_WORD.search(val):
        return "contains 'arxiv'"
    if ARXIV_NEW_RE.search(val):
        return "arXiv new-style id"
    if ARXIV_OLD_RE.search(val):
        return "arXiv old-style id"
    if CATEGORY.search(val):
        return "arXiv category tag"
    return None


def main() -> None:
    items = load_items()
    findings: dict[str, list] = {
        "id_in_volume": [],
        "id_in_issue": [],
        "id_in_pages": [],
        "id_in_pubtitle": [],
        "etal_author": [],
    }

    for it in items:
        d = it.get("data", {})
        key = d.get("key", "?")
        title = (d.get("title") or "")[:70]
        itype = d.get("itemType", "")
        ref = f"{key}  [{itype}]  {title}"

        for field, bucket in (
            ("volume", "id_in_volume"),
            ("issue", "id_in_issue"),
            ("pages", "id_in_pages"),
        ):
            val = d.get(field, "")
            why = arxiv_like(val)
            if why:
                findings[bucket].append((ref, f"{field}={val!r}  ({why})"))

        for field in ("publicationTitle", "journalAbbreviation", "proceedingsTitle"):
            val = d.get(field, "")
            why = arxiv_like(val)
            if why:
                findings["id_in_pubtitle"].append((ref, f"{field}={val!r}  ({why})"))

        for c in d.get("creators", []):
            last = c.get("lastName", "") or ""
            first = c.get("firstName", "") or ""
            name = c.get("name", "") or ""
            combined = f"{first} {last}".strip() or name
            if ETAL.match(last) or ETAL.match(name) or ETAL.match(combined):
                findings["etal_author"].append(
                    (ref, f"creator={c!r}")
                )

    total = sum(len(v) for v in findings.values())
    labels = {
        "id_in_volume": "arXiv/identifier in VOLUME field",
        "id_in_issue": "arXiv/identifier in ISSUE field",
        "id_in_pages": "arXiv/identifier in PAGES field",
        "id_in_pubtitle": "arXiv/identifier in PUBLICATION-TITLE field",
        "etal_author": "fake 'et al.' / 'E. Al.' author slot",
    }
    print(f"\nScanned {len(items)} items. {total} suspect findings.\n")
    for bucket, rows in findings.items():
        print(f"### {labels[bucket]}  —  {len(rows)} hit(s)")
        for ref, detail in rows:
            print(f"  {ref}")
            print(f"      {detail}")
        print()


if __name__ == "__main__":
    main()
