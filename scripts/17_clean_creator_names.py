#!/usr/bin/env python3
"""Stage 17 — clean author / editor names: Unicode, casing, BBT braces, junk.

Zotero stores creator fields as native Unicode, so we restore proper diacritics
on every name and strip mechanical artefacts:

* LaTeX accent escapes → Unicode: ``\\"o`` → ``ö``, ``\\'e`` → ``é``,
  ``\\v{c}`` → ``č``, ``\\c{c}`` → ``ç``, ``\\l`` → ``ł``, etc.
* BetterBibTeX brace-protection in name fields: ``{{Smith}}`` → ``Smith``.
* ALL-CAPS surnames from ProQuest exports: ``SMITH`` → ``Smith`` (only when
  the surname is all alphabetic and length ≥ 4, to avoid touching valid
  acronyms / initials).
* Trailing junk on a name: ``Smith,``, ``Smith.``, ``et al.`` swallowed
  into a lastName.

Deliberately conservative — items needing a real human eye (single-author
records on multi-author papers, swapped first/last, fully missing names)
are left for the agent-assisted creator-fix pass; this script only flips
unambiguous mechanical transforms.

Included in ``run_pipeline.py`` as a hygiene stage (14–18).
"""

from __future__ import annotations

import re

from zotcleanup import (
    Changes,
    apply_updates,
    build_parser,
    fetch_items,
    get_client,
    latex_to_unicode,
    strip_bbt_braces,
)

# --- mechanical name fixes -------------------------------------------------- #

# ≥4 consecutive caps; hyphenated segments must each be ≥2 caps. The 4-char
# floor protects valid 3-letter acronym surnames (MIT, IBM, WHO) from being
# mangled into Mit/Ibm/Who by str.title().
_ALLCAPS_SURNAME = re.compile(r"^[A-Z]{4,}(?:-[A-Z]{2,})*$")
_TRAIL_JUNK = re.compile(r"[,\s]+$")                   # commas/whitespace only; periods are valid on initials
_ET_AL = re.compile(r"\b(et\.?\s*al\.?|and\s+others)\b\.?", re.IGNORECASE)
# A standalone creator entry whose only content is "et al." / "Others" /
# similar — these are import-pollution and should be dropped from the
# creators list entirely.
_STANDALONE_ETAL = re.compile(r"^(others?|et\.?\s*al\.?|and\s+others)\.?$", re.IGNORECASE)


def _clean_name_field(s: str | None) -> str | None:
    if not s:
        return s
    # Strip BBT double-braces BEFORE LaTeX decoding: the diacritic regex's
    # trailing `\}?` greedily consumes a closing brace, so `{{\'e}}` would
    # decode to `{{é}` (one closing brace lost), leaving the wrapper for
    # strip_bbt_braces to fail on. Brace-strip first, then decode.
    new = latex_to_unicode(strip_bbt_braces(s))
    new = _ET_AL.sub("", new).strip()
    new = _TRAIL_JUNK.sub("", new)
    # str.title() is safe only because _ALLCAPS_SURNAME restricts to
    # [A-Z] + hyphens — no apostrophes (the known str.title quirk on
    # ``O'CONNOR``) and no dotless letters can reach this branch.
    if _ALLCAPS_SURNAME.match(new):
        new = new.title()
    return new


def _is_standalone_etal(cr: dict) -> bool:
    """True if ``cr`` is a creator entry whose only payload is 'others' / 'et al.'."""
    parts = [cr.get(k) for k in ("name", "lastName", "firstName") if cr.get(k)]
    return bool(parts) and all(_STANDALONE_ETAL.match(p.strip()) for p in parts)


def _clean_creator(cr: dict) -> dict | None:
    """Return a corrected copy of ``cr``, or ``None`` if unchanged."""
    new = dict(cr)
    changed = False
    for k in ("lastName", "firstName", "name"):
        if k in cr and cr[k]:
            v = _clean_name_field(cr[k])
            if v != cr[k]:
                new[k] = v
                changed = True
    return new if changed else None


def transform(zot, item) -> Changes:
    data = item["data"]
    ch = Changes(data)
    creators = data.get("creators") or []
    new_list = []
    any_change = False
    for cr in creators:
        if _is_standalone_etal(cr):
            any_change = True       # dropping the entry counts as a change
            continue
        fixed = _clean_creator(cr)
        if fixed:
            new_list.append(fixed)
            any_change = True
        else:
            new_list.append(cr)
    if any_change:
        ch.set("creators", new_list)
    return ch


def _is_candidate(item) -> bool:
    for cr in item["data"].get("creators") or []:
        if _is_standalone_etal(cr):
            return True
        for k in ("lastName", "firstName", "name"):
            v = cr.get(k) or ""
            if "\\" in v or "{{" in v or _ALLCAPS_SURNAME.match(v) or _ET_AL.search(v):
                return True
    return False


def main() -> None:
    args = build_parser(__doc__.splitlines()[0]).parse_args()
    zot = get_client()
    items = fetch_items(zot, None)
    cand = [it for it in items if _is_candidate(it)]
    apply_updates(
        zot,
        cand,
        transform,
        dry_run=not args.apply,
        verbose=args.verbose,
        limit=args.limit,
        label="items",
    )


if __name__ == "__main__":
    main()
