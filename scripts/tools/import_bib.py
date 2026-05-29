#!/usr/bin/env python3
"""Tool — import a BibTeX file into Zotero.

Parses a small, well-formed ``.bib`` (the kind Better BibTeX exports) and creates
Zotero items, mapping ``@article``/``@inproceedings``/``@unpublished``/``@misc``
to the appropriate Zotero ``itemType`` and translating LaTeX accents + BBT
braces via the project's existing helpers.

Skips entries whose title already exists in the library (case-insensitive,
punctuation-stripped) so re-runs are idempotent.

    uv run scripts/tools/import_bib.py path/to/file.bib            # dry run
    uv run scripts/tools/import_bib.py path/to/file.bib --apply    # actually create
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from zotcleanup import fetch_items, get_client
from zotcleanup.helpers import latex_to_unicode, strip_bbt_braces

_MONTHS = {
    "jan": "01", "feb": "02", "mar": "03", "apr": "04", "may": "05", "jun": "06",
    "jul": "07", "aug": "08", "sep": "09", "oct": "10", "nov": "11", "dec": "12",
}

# Map BibTeX entry type -> Zotero itemType. arXiv-eprint entries override
# to ``preprint`` (handled in build_item below).
TYPE_MAP = {
    "article": "journalArticle",
    "inproceedings": "conferencePaper",
    "incollection": "bookSection",
    "book": "book",
    "unpublished": "preprint",
    "misc": "preprint",  # most @misc entries here are arXiv preprints
    "techreport": "report",
    "phdthesis": "thesis",
    "mastersthesis": "thesis",
}


# --------------------------------------------------------------------------- #
# BibTeX parsing — brace-balanced, robust enough for well-formed exports
# --------------------------------------------------------------------------- #


def parse_bib(text: str) -> list[dict]:
    """Return a list of ``{type, key, <fields>...}`` dicts."""
    entries: list[dict] = []
    i = 0
    while True:
        m = re.search(r"@(\w+)\s*\{\s*([^,\s]+)\s*,", text[i:])
        if not m:
            break
        entry_type, citekey = m.group(1).lower(), m.group(2)
        body_start = i + m.end()
        # Find the matching closing brace of the entry.
        depth = 1
        j = body_start
        while j < len(text) and depth > 0:
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
            j += 1
        body = text[body_start : j - 1]
        i = j

        fields: dict[str, str] = {}
        pos = 0
        while pos < len(body):
            fm = re.match(r"\s*(\w+)\s*=\s*", body[pos:])
            if not fm:
                break
            name = fm.group(1).lower()
            pos += fm.end()
            if pos >= len(body):
                break
            ch = body[pos]
            if ch == "{":
                depth = 1
                vstart = pos + 1
                pos += 1
                while pos < len(body) and depth > 0:
                    if body[pos] == "{":
                        depth += 1
                    elif body[pos] == "}":
                        depth -= 1
                    pos += 1
                value = body[vstart : pos - 1]
            elif ch == '"':
                vstart = pos + 1
                pos += 1
                while pos < len(body) and body[pos] != '"':
                    pos += 1
                value = body[vstart:pos]
                pos = min(pos + 1, len(body))
            else:
                vm = re.match(r"([^,]+)", body[pos:])
                value = (vm.group(1) if vm else "").strip()
                pos += len(vm.group(1)) if vm else 0
            fields[name] = value.strip()
            cm = re.match(r"\s*,\s*", body[pos:])
            if cm:
                pos += cm.end()
        entries.append({"type": entry_type, "key": citekey, **fields})
    return entries


# --------------------------------------------------------------------------- #
# Field translation
# --------------------------------------------------------------------------- #


def _clean(s: str) -> str:
    """Strip BBT braces (incl. single-letter case-protection) and convert
    LaTeX accents to Unicode. Suitable for Zotero plain-text fields."""
    s = latex_to_unicode(strip_bbt_braces(s or ""))
    # ``strip_bbt_braces`` keeps single ``{X}`` for .bst case-protection, but
    # Zotero stores plain text — strip those too. Iterate for nested forms.
    while re.search(r"\{([^{}]*)\}", s):
        s = re.sub(r"\{([^{}]*)\}", r"\1", s)
    return s.strip()


def _parse_authors(raw: str) -> list[dict]:
    """``"Polu, Stanislas and Sutskever, Ilya"`` -> list of creator dicts."""
    if not raw:
        return []
    creators = []
    for name in re.split(r"\s+and\s+", raw):
        name = _clean(name)
        if not name:
            continue
        if "," in name:
            last, _, first = name.partition(",")
            creators.append(
                {"creatorType": "author", "lastName": last.strip(), "firstName": first.strip()}
            )
        else:
            parts = name.rsplit(" ", 1)
            if len(parts) == 2:
                creators.append(
                    {"creatorType": "author", "firstName": parts[0].strip(),
                     "lastName": parts[1].strip()}
                )
            else:
                creators.append({"creatorType": "author", "name": name})
    return creators


def _date(entry: dict) -> str:
    year = entry.get("year", "").strip()
    month = entry.get("month", "").strip().lower()[:3]
    if year and month in _MONTHS:
        return f"{year}-{_MONTHS[month]}"
    return year


def build_item(zot, entry: dict) -> dict:
    """Build a Zotero item dict (using the type template) from a parsed entry."""
    # arXiv eprint entries are preprints regardless of @type.
    et = entry["type"]
    if entry.get("eprinttype", "").lower() == "arxiv" or entry.get("archiveprefix", "").lower() == "arxiv":
        item_type = "preprint"
    else:
        item_type = TYPE_MAP.get(et, "document")

    item = zot.item_template(item_type)
    if entry.get("title"):
        item["title"] = _clean(entry["title"])
    if entry.get("author"):
        item["creators"] = _parse_authors(entry["author"])
    date = _date(entry)
    if date and "date" in item:
        item["date"] = date

    if "DOI" in item and entry.get("doi"):
        item["DOI"] = entry["doi"]
    if "url" in item and entry.get("url"):
        item["url"] = entry["url"]

    # type-specific mappings
    if item_type == "journalArticle":
        item["publicationTitle"] = _clean(entry.get("journal", ""))
        item["volume"] = entry.get("volume", "")
        item["issue"] = entry.get("number", "")
        item["pages"] = entry.get("pages", "").replace("--", "-")
    elif item_type == "conferencePaper":
        item["proceedingsTitle"] = _clean(entry.get("booktitle", ""))
        item["publisher"] = entry.get("publisher", "")
        item["pages"] = entry.get("pages", "").replace("--", "-")
    elif item_type == "bookSection":
        item["bookTitle"] = _clean(entry.get("booktitle", ""))
        item["publisher"] = entry.get("publisher", "")
        item["pages"] = entry.get("pages", "").replace("--", "-")
    elif item_type == "preprint":
        eprint = entry.get("eprint", "").strip()
        if eprint:
            item["archiveID"] = "arXiv: " + eprint
            if not item.get("url"):
                item["url"] = "http://arxiv.org/abs/" + eprint
            item["repository"] = "arXiv"
        primary = entry.get("primaryclass", "").strip()
        if primary:
            extra = item.get("extra", "")
            item["extra"] = f"{extra} [{primary}]".strip()

    # drop empty fields to keep the create payload small
    return {k: v for k, v in item.items() if v not in ("", [], {}, None)} | {
        "itemType": item["itemType"],
        "creators": item.get("creators", []),
        "tags": item.get("tags", []),
        "collections": item.get("collections", []),
        "relations": item.get("relations", {}),
    }


# --------------------------------------------------------------------------- #
# Duplicate check + driver
# --------------------------------------------------------------------------- #


def _norm_title(t: str) -> str:
    t = re.sub(r"[^a-z0-9 ]+", " ", (t or "").lower())
    return re.sub(r"\s+", " ", t).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("path", type=Path, help="Path to the .bib file")
    parser.add_argument("--apply", action="store_true", help="Actually create items (default: dry run)")
    args = parser.parse_args()

    text = args.path.read_text()
    entries = parse_bib(text)
    print(f"Parsed {len(entries)} entries from {args.path}")

    zot = get_client()
    library = fetch_items(zot)
    seen_titles = {_norm_title(it["data"].get("title", "")) for it in library}

    new_items, skipped = [], []
    for e in entries:
        title = _clean(e.get("title", ""))
        if _norm_title(title) in seen_titles:
            skipped.append(title)
            continue
        new_items.append(build_item(zot, e))

    print(f"\n{len(new_items)} new · {len(skipped)} already in library")
    for it in new_items:
        creators = it.get("creators") or []
        first = creators[0] if creators else {}
        author = first.get("lastName") or first.get("name") or ""
        print(
            f"  [{it['itemType']:14}] {it.get('title', '<no title>')[:75]}"
            f"  ({author}, {it.get('date', '')})"
        )
    for t in skipped:
        print(f"  [skip-existing]  {t[:75]}")

    if not args.apply:
        print("\nDry run — re-run with --apply to create these items.")
        return

    # Zotero create_items takes <=50 per request.
    created = 0
    for i in range(0, len(new_items), 50):
        chunk = new_items[i : i + 50]
        resp = zot.create_items(chunk)
        created += len(resp.get("successful", {}))
    print(f"\nCreated {created}/{len(new_items)} items.")


if __name__ == "__main__":
    main()
