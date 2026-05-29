"""Shared helpers extracted from the original cleanup notebooks.

Covers: fetching items, parsing arXiv identifiers out of the various places
they hide, querying the arXiv and Crossref APIs, normalising Crossref dates,
and a couple of pure string utilities.
"""

from __future__ import annotations

import os
import re
import time
from typing import Callable, Iterable, Iterator, Optional

import requests

# --------------------------------------------------------------------------- #
# Zotero item fetching
# --------------------------------------------------------------------------- #


def fetch_items(zot, item_type: Optional[str] = None) -> list:
    """Fetch library items of ``item_type`` (or all top-level items).

    Wraps the ``zot.everything(...)`` idiom repeated in every notebook. With
    ``item_type=None`` it returns only top-level items (``zot.top()``) — never
    child attachments or notes, which the cleanup never touches.
    """
    if item_type is None:
        return zot.everything(zot.top())
    return zot.everything(zot.items(itemType=item_type, limit=None))


# --------------------------------------------------------------------------- #
# arXiv identifier parsing
# --------------------------------------------------------------------------- #


def arxiv_id_from_url(url: str) -> Optional[str]:
    """Extract an arXiv id from a URL like ``http://arxiv.org/abs/1605.08386``."""
    if not url:
        return None
    ind = url.find("abs")
    if ind == -1:
        return None
    return url[ind + 4 :].strip() or None


# Match only well-formed arXiv ids after "arXiv:" — new style (2503.03205[v2])
# or old style (cond-mat/0407066[v1]) — so stray text in a BibTeX-laden `extra`
# isn't mistaken for an id.
_ARXIV_NEW = r"\d{4}\.\d{4,5}(?:v\d+)?"
_ARXIV_OLD = r"[a-z-]+(?:\.[A-Za-z-]+)?/\d{7}(?:v\d+)?"
_ARXIV_EXTRA_RE = re.compile(rf"arxiv:\s*({_ARXIV_NEW}|{_ARXIV_OLD})", re.IGNORECASE)

# Standalone, word-boundary-anchored detectors built from the same fragments —
# for *scanning* free text where a bare arXiv id might be lurking (e.g. an id
# stuffed into a Volume/Pages field), as opposed to the ``arXiv:``-prefixed
# extraction `_ARXIV_EXTRA_RE` performs. Shared so "what an arXiv id looks
# like" has a single definition across the package and its tools.
ARXIV_NEW_RE = re.compile(rf"\b{_ARXIV_NEW}\b")
ARXIV_OLD_RE = re.compile(rf"\b{_ARXIV_OLD}\b")


def arxiv_id_from_extra(extra: str) -> Optional[str]:
    """Extract an arXiv id from an ``extra`` field mentioning ``arXiv: <id>``.

    Captures just the id token, so a trailing category bracket or a following
    line (e.g. ``arXiv: 2503.03205 [quant-ph]``) doesn't leak into the id, and
    only well-formed ids match (stray ``arXiv:``-prefixed text is ignored).
    """
    if not extra:
        return None
    match = _ARXIV_EXTRA_RE.search(extra)
    return match.group(1).strip() if match else None


def arxiv_id_from_doi(doi: str) -> Optional[str]:
    """Extract an arXiv id from a DataCite arXiv DOI (``10.48550/arxiv.<id>``)."""
    if not doi:
        return None
    low = doi.lower()
    if "10.48550/arxiv." not in low:
        return None
    return low[low.find("arxiv.") + 6 :].strip() or None


# --------------------------------------------------------------------------- #
# External API lookups (with light rate limiting)
# --------------------------------------------------------------------------- #

_CROSSREF_SLEEP = 0.1
_arxiv_client = None


def _get_arxiv_client():
    """A single shared arXiv client so its rate limiting/retries actually apply.

    arXiv asks for ~3s between requests; reusing one client lets it pace and
    retry (on 429/503) across calls instead of resetting state every time.
    """
    global _arxiv_client
    if _arxiv_client is None:
        import arxiv

        _arxiv_client = arxiv.Client(page_size=100, delay_seconds=3.0, num_retries=3)
    return _arxiv_client


_arxiv_cache: dict[str, object] = {}


_ARXIV_VERSION_RE = re.compile(r"v\d+$")


def _norm_arxiv_id(arxiv_id: str) -> str:
    """Normalize an id for cache keys: lowercase, no trailing version (``v2``)."""
    return _ARXIV_VERSION_RE.sub("", (arxiv_id or "").strip().lower())


def prefetch_arxiv(ids: Iterable[str], batch_size: int = 50) -> None:
    """Resolve many arXiv ids in a few batched requests, into ``_arxiv_cache``.

    arXiv accepts many ids per ``id_list`` query, so this turns N per-item
    lookups into ~N/50 requests — the difference between sailing through and
    getting 429-throttled. Call it once with all the ids a stage will need;
    :func:`arxiv_paper` then serves them from cache (falling back to a single
    lookup for anything a batch didn't return, e.g. a withdrawn id).
    """
    import arxiv

    client = _get_arxiv_client()
    todo, seen = [], set()
    for raw in ids:
        key = _norm_arxiv_id(raw)
        if not key or key in _arxiv_cache or key in seen:
            continue
        seen.add(key)
        todo.append(raw)

    for batch in split_list(todo, batch_size):
        try:
            for paper in client.results(arxiv.Search(id_list=list(batch))):
                _arxiv_cache[_norm_arxiv_id(paper.get_short_id())] = paper
        except Exception:
            continue  # leave this batch's ids for the per-item fallback


def arxiv_paper(arxiv_id: str):
    """Return the arXiv result for ``arxiv_id`` (cached; batched via prefetch).

    Raises ``StopIteration`` if arXiv has no such id; callers run inside
    ``apply_updates``, which logs and skips on any exception.
    """
    key = _norm_arxiv_id(arxiv_id)
    if key in _arxiv_cache:
        return _arxiv_cache[key]
    import arxiv

    paper = next(_get_arxiv_client().results(arxiv.Search(id_list=[arxiv_id])))
    _arxiv_cache[key] = paper
    return paper


_works = None


def _get_works():
    """A shared Crossref ``Works`` client, in the polite pool when possible.

    Setting ``CROSSREF_MAILTO`` (a contact email) joins Crossref's "polite
    pool" — they identify your traffic and give it better, more stable service.
    Without it, requests still work but use the anonymous pool.
    """
    global _works
    if _works is None:
        from crossref.restful import Works

        mailto = os.environ.get("CROSSREF_MAILTO", "").strip()
        if mailto:
            from crossref.restful import Etiquette

            etiquette = Etiquette(
                "zotcleanup", "0.1.0",
                "https://github.com/texra-ai/zotero-cleanup-skills", mailto
            )
            _works = Works(etiquette=etiquette)
        else:
            _works = Works()
    return _works


def crossref_works(doi: str, retries: int = 2):
    """Return Crossref metadata for ``doi`` (or ``None`` on failure).

    Retries transient failures with a short backoff before giving up.
    """
    works = _get_works()
    for attempt in range(retries + 1):
        try:
            info = works.doi(doi)
            time.sleep(_CROSSREF_SLEEP)
            return info
        except Exception:
            if attempt == retries:
                return None
            time.sleep(_CROSSREF_SLEEP * (attempt + 2))


def crossref_date(info: dict, order: Iterable[str] = (
    "published-online",
    "published-print",
    "issued",
    "indexed",
)) -> Optional[str]:
    """Pull a ``YYYY-MM-DD`` (or shorter) date from Crossref metadata.

    Tries each key in ``order`` and returns the first that parses. Returns
    ``None`` if no usable date is present.
    """
    for key in order:
        try:
            parts = info[key]["date-parts"][0]
        except (KeyError, IndexError, TypeError):
            continue
        if parts and parts[0] is not None:
            return "-".join(str(p) for p in parts)
    return None


# --------------------------------------------------------------------------- #
# DBLP — the curated authority for CS/ML/theory conference bibliography
# --------------------------------------------------------------------------- #

_dblp_session = None
_DBLP_SLEEP = 2.0  # be polite; DBLP throttles aggressive callers
_DBLP_API = "https://dblp.org/search/publ/api"


class DBLPThrottled(RuntimeError):
    """DBLP kept returning 429/503 after all retries — distinct from "no hit"."""


def _get_dblp_session():
    """A shared :class:`requests.Session` with a polite User-Agent."""
    global _dblp_session
    if _dblp_session is None:
        _dblp_session = requests.Session()
        _dblp_session.headers["User-Agent"] = (
            "zotcleanup/0.1 (https://github.com/texra-ai/zotero-cleanup-skills)"
        )
    return _dblp_session


def dblp_search(title: str, rows: int = 10, retries: int = 4) -> list[dict]:
    """Search DBLP publications by ``title``; return the ``info`` dicts (or []).

    Each ``info`` carries DBLP's canonical fields: ``title``, ``venue``,
    ``volume``, ``number``, ``pages``, ``year``, ``type``, ``doi``, ``authors``.

    An empty list means a *genuine* no-hit (HTTP 200, no results). When DBLP
    rate-limits us (429/503), we honour ``Retry-After`` and back off, and only
    after exhausting retries raise :class:`DBLPThrottled` — so callers can tell
    "this paper isn't in DBLP" apart from "we got throttled", and never silently
    record a throttle as a miss.
    """
    params = {"q": title, "format": "json", "h": rows}
    session = _get_dblp_session()
    for attempt in range(retries + 1):
        try:
            resp = session.get(_DBLP_API, params=params, timeout=30)
        except Exception:
            if attempt == retries:
                raise DBLPThrottled(f"network error for {title!r}")
            time.sleep(_DBLP_SLEEP * (attempt + 2))
            continue

        # 429 (rate-limit) and any 5xx (DBLP also 500s under load) are retryable.
        if resp.status_code == 429 or resp.status_code >= 500:
            if attempt == retries:
                raise DBLPThrottled(
                    f"persistent HTTP {resp.status_code} on {title!r}"
                )
            retry_after = resp.headers.get("Retry-After")
            wait = int(retry_after) if (retry_after or "").isdigit() else 30 * (attempt + 1)
            time.sleep(min(wait, 120))
            continue

        time.sleep(_DBLP_SLEEP)
        try:
            resp.raise_for_status()
            hits = resp.json().get("result", {}).get("hits", {}).get("hit", [])
        except Exception:
            if attempt == retries:
                raise DBLPThrottled(f"parse error on {title!r}")
            time.sleep(_DBLP_SLEEP * (attempt + 2))
            continue
        return [h["info"] for h in hits if "info" in h]
    return []


def dblp_authors(info: dict) -> list[str]:
    """Author display names from a DBLP ``info`` dict (handles 1-vs-many shape)."""
    authors = (info.get("authors") or {}).get("author")
    if authors is None:
        return []
    if isinstance(authors, dict):  # DBLP collapses a single author to a dict
        authors = [authors]
    names = []
    for a in authors:
        name = a.get("text") if isinstance(a, dict) else a
        if name:
            # DBLP disambiguates homonyms with a trailing number ("Wei Li 0001").
            names.append(re.sub(r"\s+\d{4}$", "", name).strip())
    return names


# --------------------------------------------------------------------------- #
# DOI sanity helpers
# --------------------------------------------------------------------------- #


def is_researchgate_doi(doi: Optional[str]) -> bool:
    """True for ResearchGate placeholder DOIs (those containing ``RG.``)."""
    return bool(doi) and "RG." in doi


def is_arxiv_placeholder_doi(doi: Optional[str]) -> bool:
    """DataCite arXiv DOIs that stand in for a *real* publisher DOI."""
    return bool(doi) and "10.48550/arxiv." in doi.lower()


# --------------------------------------------------------------------------- #
# Pure string utilities
# --------------------------------------------------------------------------- #


def norm_title(t: str) -> str:
    """Normalize a title for fuzzy matching: lowercase, replace non-alphanumeric
    runs with single spaces, collapse whitespace.

    Used by stages 13/19 and ``tools/import_bib.py`` to compare titles across
    arXiv / Crossref / DBLP, where punctuation and spacing differ but the words
    are the same. Idempotent.
    """
    collapsed = re.sub(r"[^a-z0-9 ]+", " ", (t or "").lower())
    return re.sub(r"\s+", " ", collapsed).strip()


def split_list(seq, size: int = 50) -> Iterator[list]:
    """Yield ``seq`` in chunks of ``size`` (Zotero batch-write limit is 50)."""
    seq = list(seq)
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def clean_arxiv_categories(extra_field: str) -> str:
    """Collapse ``[cs, stat] [cs.LG]`` -> ``[cs.LG]`` in an ``extra`` field."""
    return re.sub(r"\[(.*?)\] \[(.*?)\]", r"[\2]", extra_field)


def strip_extra_lines(extra: str, prefixes: Iterable[str]) -> str:
    """Drop whole lines of ``extra`` that start with any of ``prefixes``.

    Used to remove bookkeeping lines (e.g. ``Citation Key:``) while preserving
    the rest of the field. Leading whitespace before a prefix is ignored.
    """
    if not extra:
        return extra
    prefixes = tuple(prefixes)
    kept = [ln for ln in extra.splitlines() if not ln.lstrip().startswith(prefixes)]
    return "\n".join(kept).strip()


# --------------------------------------------------------------------------- #
# Composite arXiv enrichment (shared by stages 02/03)
# --------------------------------------------------------------------------- #


_template_fields: dict[str, set] = {}
_STRUCTURAL = {"key", "version", "dateAdded", "dateModified", "parentItem"}


def _valid_data_fields(zot, item_type: str) -> set:
    """Field names allowed on ``item_type`` (from Zotero's item template, cached)."""
    if item_type not in _template_fields:
        _template_fields[item_type] = set(zot.item_template(item_type).keys())
    return _template_fields[item_type]


def retype(zot, ch, data: dict, new_type: str) -> None:
    """Change ``itemType`` to ``new_type`` and drop fields invalid for it.

    Zotero rejects a PATCH that carries a field not allowed for the item's type
    (e.g. ``journalAbbreviation`` on a ``preprint``), so when changing type we
    remove the now-foreign fields from the payload rather than send stale values.
    """
    ch.set("itemType", new_type)
    allowed = _valid_data_fields(zot, new_type) | _STRUCTURAL
    for field in list(data.keys()):
        if field not in allowed:
            old = data.pop(field)
            ch.diffs.append((field, old, f"<removed: invalid for {new_type}>"))


def arxiv_enrich_or_demote(zot, ch, data: dict, arxiv_id: str, *, set_url: bool = True) -> None:
    """Look up an arXiv id and apply the canonical preprint-handling logic.

    Appends the primary category to ``extra`` (if absent), then either records
    the real publisher DOI arXiv reports, or — when arXiv has no real DOI —
    demotes the item to a ``preprint`` (dropping journal-only fields).

    ``ch`` is a ``cli.Changes`` recorder (anything with a ``.set`` method).
    """
    paper = arxiv_paper(arxiv_id)

    category = getattr(paper, "primary_category", None)
    extra = data.get("extra") or ""
    if category and category not in extra:
        ch.set("extra", f"{extra} [{category}]".strip())

    doi = getattr(paper, "doi", None)
    if doi and not is_researchgate_doi(doi):
        ch.set("DOI", doi)
    else:
        retype(zot, ch, data, "preprint")
        if set_url:
            ch.set("url", "http://arxiv.org/abs/" + arxiv_id)


# --------------------------------------------------------------------------- #
# Text-field cleanup primitives (shared by hygiene stages 15, 17, 18)
# --------------------------------------------------------------------------- #


_BBT_DOUBLE_BRACE = re.compile(r"\{\{([^{}]*)\}\}")


def strip_bbt_braces(s: str) -> str:
    """Strip BetterBibTeX double-brace case protection (``{{X}}`` → ``X``).

    Iterates until stable so nested forms like ``{{{X}}}`` are fully unwrapped.
    Singletons (``{X}``) are intentionally left alone — they may carry .bst
    case-protection that downstream rendering still needs.
    """
    if not s or "{{" not in s:
        return s
    while (new := _BBT_DOUBLE_BRACE.sub(r"\1", s)) != s:
        s = new
    return s


# --- LaTeX accent commands → Unicode (used by stage 17, available for any
# future text-cleanup stage that needs to decode LaTeX-escape leftovers).
_LATEX_DIACRITICS = {
    '"': {"a": "ä", "e": "ë", "i": "ï", "o": "ö", "u": "ü", "y": "ÿ",
          "A": "Ä", "E": "Ë", "I": "Ï", "O": "Ö", "U": "Ü", "Y": "Ÿ"},
    "'": {"a": "á", "c": "ć", "e": "é", "i": "í", "l": "ĺ", "n": "ń",
          "o": "ó", "r": "ŕ", "s": "ś", "u": "ú", "y": "ý", "z": "ź",
          "A": "Á", "C": "Ć", "E": "É", "I": "Í", "L": "Ĺ", "N": "Ń",
          "O": "Ó", "R": "Ŕ", "S": "Ś", "U": "Ú", "Y": "Ý", "Z": "Ź"},
    "`": {"a": "à", "e": "è", "i": "ì", "o": "ò", "u": "ù",
          "A": "À", "E": "È", "I": "Ì", "O": "Ò", "U": "Ù"},
    "^": {"a": "â", "c": "ĉ", "e": "ê", "g": "ĝ", "h": "ĥ", "i": "î",
          "j": "ĵ", "o": "ô", "s": "ŝ", "u": "û", "w": "ŵ", "y": "ŷ",
          "A": "Â", "C": "Ĉ", "E": "Ê", "G": "Ĝ", "H": "Ĥ", "I": "Î",
          "J": "Ĵ", "O": "Ô", "S": "Ŝ", "U": "Û", "W": "Ŵ", "Y": "Ŷ"},
    "~": {"a": "ã", "n": "ñ", "o": "õ", "A": "Ã", "N": "Ñ", "O": "Õ"},
}
_LATEX_BRACED = {
    "c": {"c": "ç", "s": "ş", "C": "Ç", "S": "Ş"},      # cedilla
    "v": {"c": "č", "e": "ě", "n": "ň", "r": "ř", "s": "š", "z": "ž",
          "C": "Č", "E": "Ě", "N": "Ň", "R": "Ř", "S": "Š", "Z": "Ž"},  # caron
    "u": {"a": "ă", "g": "ğ", "A": "Ă", "G": "Ğ"},      # breve
    "=": {"a": "ā", "e": "ē", "i": "ī", "o": "ō", "u": "ū",
          "A": "Ā", "E": "Ē", "I": "Ī", "O": "Ō", "U": "Ū"},   # macron
    ".": {"z": "ż", "Z": "Ż"},                          # dot-above
    "H": {"o": "ő", "u": "ű", "O": "Ő", "U": "Ű"},      # double-acute
    "k": {"a": "ą", "e": "ę", "A": "Ą", "E": "Ę"},      # ogonek
}
_LATEX_SPECIAL = {
    r"\ss": "ß", r"\l": "ł", r"\L": "Ł",
    r"\o": "ø", r"\O": "Ø", r"\ae": "æ", r"\AE": "Æ",
    r"\aa": "å", r"\AA": "Å",
}
_LATEX_DOTLESS_I = re.compile(r"\\i\b")
_LATEX_DOTLESS_J = re.compile(r"\\j\b")
_LATEX_DIACRITIC_PATS = [
    (re.compile(r"\\\\?" + re.escape(accent) + r"\{?([A-Za-z])\}?"), table)
    for accent, table in _LATEX_DIACRITICS.items()
]
_LATEX_BRACED_PATS = [
    (re.compile(r"\\\\?" + re.escape(cmd) + r"\{([A-Za-z])\}"), table)
    for cmd, table in _LATEX_BRACED.items()
]


def latex_to_unicode(s: str) -> str:
    """Restore Unicode from common LaTeX accent commands.

    Handles single-backslash and double-backslash (double-escaped) forms,
    braced (``\\"{o}``) and unbraced (``\\"o``) accents, the dotless ``\\i`` /
    ``\\j`` commands when used under another accent (``\\"\\i`` → ``ï``), the
    cedilla / caron / breve / macron / dot-above / double-acute / ogonek
    families, and special letter commands (``\\ss`` → ß, ``\\l`` → ł, …).

    Patterns are pre-compiled at import time so callers can invoke this on
    every field without paying the compile cost per call.
    """
    if not s or "\\" not in s:
        return s
    # Strip \i and \j first so the accent patterns see plain ``i``/``j``.
    s = _LATEX_DOTLESS_I.sub("i", s)
    s = _LATEX_DOTLESS_J.sub("j", s)
    for pat, table in _LATEX_DIACRITIC_PATS:
        s = pat.sub(lambda m, t=table: t.get(m.group(1), m.group(0)), s)
    for pat, table in _LATEX_BRACED_PATS:
        s = pat.sub(lambda m, t=table: t.get(m.group(1), m.group(0)), s)
    # After diacritic decoding, `s` may have no backslashes left — skip the
    # 9-key special-letter loop on the (common) clean-already case.
    if "\\" in s:
        for cmd, ch in _LATEX_SPECIAL.items():
            s = s.replace(cmd, ch)
    return s


def compile_canonical_replacer(mapping: dict[str, str]) -> Callable[[str], str]:
    """Build a fast word-boundary canonical-form replacer from a lookup table.

    Given ``{lowercase_token: canonical_form}``, returns a function that:

    * Matches each key on word boundaries, case-insensitively.
    * Replaces the match with the canonical form.
    * Leaves the match alone when it's already canonical (idempotent — no
      diff churn on already-correct titles).
    * Tries longer keys before shorter ones (so ``bose-einstein`` matches
      before bare ``bose``).

    The regex alternation is compiled once at builder time, so per-call cost
    is just `pattern.sub` on the input. Suitable for sweeping over a 16k-item
    library.
    """
    keys_by_length = sorted(mapping, key=len, reverse=True)
    pattern = re.compile(
        r"\b(" + "|".join(re.escape(k) for k in keys_by_length) + r")\b",
        re.IGNORECASE,
    )

    def replace(s: str) -> str:
        if not s:
            return s
        # Idempotency falls out: when the match is already canonical, the
        # substitution returns the same text and the result string equals s.
        return pattern.sub(lambda m: mapping[m.group(0).lower()], s)

    # Expose the compiled alternation so callers can do cheap candidate
    # pre-filtering (`replace.pattern.search(s)`) without paying for the
    # full sub.
    replace.pattern = pattern   # type: ignore[attr-defined]
    return replace
