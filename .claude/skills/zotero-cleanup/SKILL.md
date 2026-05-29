---
name: zotero-cleanup
description: >-
  Clean up and normalize a personal Zotero library: convert documents/preprints
  to the right item types, fetch arXiv DOIs, promote published preprints to
  journal articles via Crossref, fix conference/issue/page metadata, and
  standardize journal abbreviations; also organize the collection tree — file
  unfiled items into collections, normalize folder names, merge duplicates. Use
  when the user asks to tidy, fix, update, normalize, or organize their Zotero
  references, arXiv preprints, journal metadata, folders, or unfiled items.
---

# Zotero library cleanup

A pipeline of standalone scripts (in `scripts/`) that fix common metadata
problems in a Zotero library via the pyzotero, arXiv, and Crossref APIs.

## Golden rule: dry-run first, always

Every script defaults to **dry-run** and prints a per-item `old -> new` diff
without writing. The real library is at stake and some stages are slow.

1. Run the stage **without** `--apply` (optionally with `--limit 5`).
2. Show the user the diff and let them confirm.
3. Only then re-run **with `--apply`**.

Never run `--apply` against the live library without explicit user confirmation.

## Pre-flight

Credentials come from a gitignored `.env` (see `.env.example`):
`ZOTERO_API_KEY`, `ZOTERO_LIBRARY_ID`, `ZOTERO_LIBRARY_TYPE`. Confirm it works:

```bash
uv run python -c "from zotcleanup import get_client; print(get_client().count_items(), 'items')"
```

If that raises `ConfigError`, the user must create `.env` from `.env.example`
(and get a key at https://www.zotero.org/settings/keys).

## Run order (matters — each stage consumes what the previous produced)

Run the whole thing with `uv run run_pipeline.py [--apply] [--limit N]`, or run
stages individually:

| # | Command | What it does |
|---|---------|--------------|
| 01 | `uv run scripts/01_documents_to_preprints.py` | `document` + arXiv URL -> `preprint` |
| 02 | `uv run scripts/02_arxiv_journals_to_preprints.py` | arXiv-mislabelled journal articles -> `preprint` or real DOI |
| 20 | `uv run scripts/20_clean_journal_preprint_urls.py` | journalArticles still carrying a preprint URL — capture arXiv id into `archiveID`, clear `url` (or demote to preprint if the journal metadata is incomplete) |
| 03 | `uv run scripts/03_preprints_fetch_doi.py` | fetch arXiv DOI + category for preprints; tidy category brackets |
| 04 | `uv run scripts/04_preprints_to_journals.py` | preprints with a real DOI -> `journalArticle` (Crossref metadata) |
| 05 | `uv run scripts/05_conferences.py [all\|convert-duplicates\|fill-proceedings\|standardize-neurips]` | conference paper fixes |
| 06 | `uv run scripts/06_journal_metadata_fixes.py [all\|fix-issues\|fix-pages]` | issue/page/extra repair via Crossref |
| 07 | `uv run scripts/07_strip_arxiv_from_journals.py` | drop the `arXiv:` line from `extra` once an item is confirmed as a published journal article |
| 08 | `uv run scripts/08_standardize_journal_titles.py` | canonical journal titles + abbreviations |
| 09 | `uv run scripts/09_tag_arxiv_categories.py` | tag `[primary_category]` into `extra` for any arXiv item |
| 14 | `uv run scripts/14_clean_extra.py` | strip importer cruft from `extra` (Citation Key, tex.howpublished, Accepted:, Issue: month-name, Publication Title:, Medium:) |
| 15 | `uv run scripts/15_clean_titles.py` | strip BBT brace-protection (`{{X}}`) and HTML entities (`&amp;`, `&lt;`, …) from titles |
| 16 | `uv run scripts/16_resolve_placeholder_dois.py` | replace `10.13140/RG.…` / `10.48550/arxiv.…` DOIs with the real publisher DOI (Crossref title+author lookup; ≥0.85 title fuzzy + surname overlap required) |
| 17 | `uv run scripts/17_clean_creator_names.py` | LaTeX accents → Unicode (`\"o`→ö, `\'e`→é, `\v{c}`→č, `\l`→ł), strip BBT braces, Title-case ALL-CAPS surnames, drop trailing junk |
| 18 | `uv run scripts/18_capitalize_proper_nouns.py` | capitalize proper nouns + acronyms in titles (`markov`→Markov, `schrodinger`→Schrödinger, `nmr`→NMR, `bose-einstein`→Bose-Einstein, …). BBT then brace-protects each on export so the `.bst` can't lowercase them back. |

`run_pipeline.py` runs the whole list — data stages (01, 02, 20, 03–09) then
hygiene (14–18). Common flags on every stage: `--apply`, `--limit N`,
`--verbose`. (`scripts/13_conferences_dblp.py` and
`scripts/19_fill_missing_dois.py` are standalone — not part of the default
pipeline; see the on-demand section.)

Why the order: documents must become preprints (01) before preprint stages can
see them; DOIs must be fetched (03) before preprints can be promoted (04);
stage 07 needs items already promoted to `journalArticle` before it can safely
drop the arXiv line; title standardization (08) and category tagging (09) come
after the type/data work; the hygiene stages (14–17) are mechanical scrubbers
that run last on whatever the data stages produced.

## Organizing collections (folders), not just item metadata

Stages 01–09 fix *item* fields. Stages 10–12 reorganize the *collection tree*
and item↔collection membership. They share the same dry-run-first rule and the
reusable `zotcleanup.collections` layer (`Tree` for cheap in-memory lookups,
plus `create_collection` / `rename_collection` / `add_items_to_collection` /
`merge_collection`, all batched ≤50 writes and `dry_run`-aware).

| # | Command | What it does |
|---|---------|--------------|
| 10 | `uv run scripts/10_organize_unfiled.py --export f.json` / `--map f.json [--apply]` | file unfiled references into collections |
| 11 | `uv run scripts/11_normalize_collection_names.py` | canonicalize leading numeric prefixes (`00Core`→`00 Core`); scoped to `TARGET_ROOTS`, casing left alone |
| 12 | `uv run scripts/12_merge_collections.py` / `--merge SRC DST` | report collision-named collections; merge a chosen pair |

### Filing unfiled items — the agent-assisted pattern

Deciding *which* collection a paper belongs in is judgement, so keep it OUT of
the script. Two phases:

1. `--export unfiled.json` dumps every unfiled reference (title, abstract, tags)
   plus a flat catalog of assignable collections (key + path). Annotations and
   other non-references are skipped.
2. An agent (or several in parallel, one per slice) reads that file and writes an
   assignment map `{item_key: [collection_key, ...]}` — preferring the most
   specific existing leaf, allowing multi-home, proposing new folders only for
   genuine gaps. `--map assignments.json` then applies it, batched, dry-run
   first. Items are only ever *added* to collections, never removed.

This keeps stage 10 generic (it just moves items per a map); the intelligence is
swappable. Library-specific choices (target roots in stage 11, which new folders
to create) stay in config/prompts, not baked into the engine.

## Fixing mistyped `document` items & thin `thesis` records — agent-assisted research

`document` is the catch-all Zotero assigns when an import won't classify;
`thesis` records are usually typed right but missing
`thesisType`/`university`/`place`/`date`/`url`. Both need per-item judgement +
external verification, so (like stage 10) keep the intelligence in agents and the
writing in a small bespoke script:

1. **Export** candidates to JSON (key, title, creators, date, url, DOI, extra, abstract).
2. **Dispatch research agents** (≈8 items each, parallel) to verify against
   authoritative sources — Crossref, dblp (CS/ML), arXiv, official university
   repositories (CaltechTHESIS, MIT DSpace, mediaTUM/edoc, ILLC …). **Never
   guess**: return `confidence` + `source` URL, leave a field blank rather than
   invent it. They return strict JSON `{key, proposed_itemType, fields, confidence, source}`.
3. **Apply via a dry-run script** with `retype` + `cli.Changes` + `--apply` (next
   section); set `creators`/`title` only where flagged wrong.

`document` type map: GitHub repo → `computerProgram` (`programmingLanguage`/`company`);
blog → `blogPost`; docs/site → `webpage`; lecture/course notes → `report`
(`reportType="Lecture notes"`, `institution`); a real paper → its
`journalArticle`/`conferencePaper`/`preprint` form with the published DOI.

Recurring gotchas: OCR-garbled titles (`"… signature redacted"`, trailing
`"thesis"`); broken diacritics in university names (`"Universit ̈ at M ̈ unchen"`
→ `"Universität München"`); author name splits/accents (Şahinoğlu, Brandão); a
"thesis" that's actually lecture notes; bachelor/honors theses (`thesisType` is
free text); federal vs. awarding institution (University of London → Imperial
College London). Normalize `thesisType` to `"PhD dissertation"`/`"Master's thesis"`.
(Cross-type duplicates between Zotero records are covered in the
"Reorganizing the topic tree" section below.)

## Building blocks for bespoke one-off fixes

For a finite, known set of corrections (an errata list, a few mistyped items),
script on these primitives — same dry-run-first rule:

- **`from zotcleanup import get_client`** → configured pyzotero client. Search
  `c.items(q=…, itemType="-attachment || note")` (default
  `qmode="titleCreatorYear"`; `"everything"` is slow full-text and returns
  attachments). `c.item(key)` reads, `c.update_item(fresh)` writes (handles the
  version token), `c.addto_collection(col, item)` / `c.delete_item(item)` for
  membership/removal.
- **`from zotcleanup.cli import Changes, apply_updates`** → `Changes(item["data"])`;
  `ch.set(field, value)` records a diff only on change, so `if ch:` gates the
  write. `apply_updates` runs a transform over candidates with the shared
  `--apply/--dry-run/--limit` loop.
- **`from zotcleanup.helpers import retype, crossref_works, arxiv_paper`** →
  `retype(zot, ch, data, new_type)` switches `itemType` and drops fields invalid
  for it; the rest fetch Crossref/arXiv metadata (`CROSSREF_MAILTO` joins the
  polite pool).

Pattern: a `PLAN = {key: {field: value}}` (+ a creator/`retype` map), loop with
`Changes`, print the diff, gate writes behind `--apply`. Locate by quick search
and show the diff before writing; prefer fixing the entry the manuscript actually
`\cite`s.

## Reorganizing the topic tree — patterns that worked

These restructure the `Lib: Topics` tree (additively when possible) without
losing items or eroding the user's curated granularity.

**1. Promote project refs → topic knowledge bases (additive).** Export items
under `Project: Current` (or `Mendeley Import`) that aren't yet in any topic +
the full Lib:Topics catalog (key + path). Dispatch ~8 parallel sonnet agents
(slices of ~150), each producing `{item_key: [topic_key, ...]}` with
precision-over-recall (omit when no topic fits). Apply *additively* (add to
topic, keep project membership). **Validate item keys with `^[A-Z0-9]{8}$`
before fetching** — agents occasionally emit malformed keys and an unchecked
`c.item()` aborts the whole loop.

**2. Don't jam items into parents — audit & refine.** Even with "prefer the
most specific leaf" in the prompt, agents dump ~40% of items into parent
topics when uncertain. After every promotion run, audit: for each non-leaf
topic folder, count `Tree.num_items(k)`. Items sitting directly there (not
in any descendant) need a second pass. Dispatch refinement agents whose only
job is to pick the best **child from that item's own parent's children list**
(or omit to keep at parent if none truly fits). Apply atomically per item
(`cols.add(child); cols.discard(parent); update`) — not add-then-remove in
two passes, which goes stale-version between writes.

**3. Bulging parents → carve new subfolders.** When the audit shows a parent
with ~20+ loose items in coherent clusters and no existing leaf fits, the
right move is to **create new sibling subfolders**, not force them deeper.
(Example: `Topic - AI & LLMs` gained `Alignment & safety`, `Foundation
models`, `Prompting & in-context learning`.)

**4. Grow thin folders by gathering scattered papers.** A 1-2 item folder
with a meaningful technical label is usually under-populated, not redundant.
For each thin leaf: search the library, vet, add additively. Two flavors —
(a) names that match titles literally (`Boltzmann machine`, `Wavelet`):
direct `c.items(q=…)` search; (b) abbreviated/jargon names (`QuPCA`,
`Neural QEC`, `Code Concatenation`): hand agents a small search helper they
can `uv run` via Bash and let them expand to synonyms + vet. Expect a real
share of thin folders to return **nothing** — that means the topic is
genuinely sparse in this library, not mis-filed. **Never dissolve a
meaningful thin folder just for being thin** — that erases curated
granularity. Dissolve only when the label is generic (`00 Survey`,
`Editorial`, `Deepmind`-as-only-child).

**5. Cross-type dedup (preprint ↔ published).** Keep the published twin.
Before deleting the loser: (a) check the manuscript doesn't `\cite` it under
its own citekey, (b) **re-parent its child PDFs/notes to the survivor** so
attachments aren't lost, (c) **union its collections into the survivor** so
folder membership survives, (d) back up its JSON. Then `delete_item` (API
deletes are permanent — no trash).

**6. Folder-naming rules.** Same name under different parents is
**legitimate** (context-scoped subfolders, not duplicates); only sibling
collisions — same parent + same name — are. Align casing **evidence-based**:
rename a lowercase variant to its existing Title-case sibling rather than
blind-Title-casing everything (acronyms like `PEPS`/`MERA`/`QEC` break).
Prefer singular for collection-of-papers labels (`GAN`, `Tensor Network`,
`Normalizing Flow`). Numeric prefix is `NN Name` — single space, no hyphen.
Keep abbreviation prefixes consistent within a tier (under `Topic - QML`,
either all `Qu*` or none; don't mix).

## Optional / on-demand (NOT in the default pipeline)

- `uv run scripts/13_conferences_dblp.py` — verify & enrich `conferencePaper`
  items against **DBLP** (the curated authority for CS/ML/theory venues). Only
  trusts a hit when title is a fuzzy-match AND year agrees (±1) AND authors
  overlap; fills missing `DOI`/venue/`date`/`pages`/`volume` on a CONFIRMED
  match, reports year/author disagreements as **SUSPECT**, leaves NOT-FOUND
  alone. Network-bound (one query/paper). Run it *before* stage 05
  `fill-proceedings`, so the DOIs it finds let Crossref add publisher/place.
  Flags: `--only-missing` (skip complete papers), `--canonical-venue`
  (overwrite an existing proceedingsTitle with DBLP's canonical venue).
- `uv run scripts/19_fill_missing_dois.py` — recover identity of
  under-specified journalArticles: `demote-shells` retypes DOI-less/title-less
  shells to `preprint` (arXiv title search), `fill-dois` sets a missing DOI
  from a confident DBLP/Crossref title match. Sub-actions
  `{demote-shells,fill-dois,all}` (default `all`).
- `uv run scripts/tools/import_bib.py FILE.bib` — import a `.bib` into Zotero
  (maps `@article`/`@inproceedings`/`@unpublished`/`@misc`; skips titles already
  present). Dry-run by default.
- `uv run scripts/tools/detect_dead_dois.py` — HEAD-checks every non-placeholder
  DOI against doi.org, reports 404s, and with `--apply` repairs/clears them.
- `uv run scripts/tools/scan_import_artifacts.py` — **read-only** audit for
  bad-import artifacts (arXiv ids in volume/pages, fake "et al." authors);
  caches to `scan_cache.json` (gitignored), `--refresh` to re-pull.
- `uv run scripts/tools/scrape_dois.py` — slow HTML fallback that scrapes
  `citation_doi` tags for arXiv articles the API path missed. Use before stage
  04 only if needed.
- `uv run scripts/tools/delete_all_tags.py` — **destructive**: deletes every tag.
  Reports the count by default; only deletes with `--yes`. Never run unprompted.

## Customizing

- Journal abbreviation table: edit `JOURNAL_TABLE` in
  `scripts/08_standardize_journal_titles.py`.
- Suspicious issue value for stage 06: `--suspicious-issue N` (default `2`).
