#!/usr/bin/env python3
"""Stage 15 — strip BetterBibTeX braces and HTML entities from titles.

Targets the mechanical title-field artifacts left by import tools:

* BetterBibTeX brace-protection: ``{{Quantum}}`` → ``Quantum``
* HTML entities leaked from web imports: ``&amp;`` → ``&``, ``&lt;`` → ``<``,
  ``&gt;`` → ``>``, ``&nbsp;`` → space, ``&#39;`` / ``&apos;`` → ``'``,
  ``&quot;`` → ``"``
* Doubled / leading / trailing whitespace.

Deliberately conservative: leaves ``<sup>``/``<sub>`` tags and ``$math$``
intact — those carry semantic content the user may want to preserve in their
own rendering pipeline. LaTeX accent escapes in titles are handled by the
author-name stage when they're in creator fields; titles rarely need them.

Included in ``run_pipeline.py`` as a hygiene stage (14–18).
"""

from __future__ import annotations

import html
import re

from zotcleanup import (
    Changes,
    apply_updates,
    build_parser,
    fetch_items,
    get_client,
    strip_bbt_braces,
)

# Conservative whitelist of HTML entities to decode in titles. Note: this
# whitelist only gates whether html.unescape() runs; once triggered, unescape
# decodes ALL entities including numeric ones (&#8209; non-breaking hyphen,
# &#x2212; minus sign, etc.). Widen with care.
_SAFE_ENTITIES = ("&amp;", "&lt;", "&gt;", "&nbsp;", "&#39;", "&apos;", "&quot;")
_WS = re.compile(r"[ \t]+")


def _has_safe_entity(s: str) -> bool:
    return any(e in s for e in _SAFE_ENTITIES)


def _clean(title: str) -> str:
    out = strip_bbt_braces(title)
    if _has_safe_entity(out):
        out = html.unescape(out)
    out = _WS.sub(" ", out).strip()
    return out


def transform(zot, item) -> Changes:
    data = item["data"]
    ch = Changes(data)
    title = data.get("title") or ""
    if title:
        ch.set("title", _clean(title))  # Changes.set no-ops when unchanged
    return ch


def main() -> None:
    args = build_parser(__doc__.splitlines()[0]).parse_args()
    zot = get_client()
    items = fetch_items(zot, None)
    # Cheap pre-filter so the dry-run output isn't noisy with no-ops.
    cand = [
        it
        for it in items
        if "{{" in (it["data"].get("title") or "")
        or _has_safe_entity(it["data"].get("title") or "")
    ]
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
