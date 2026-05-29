# zotcleanup

A small, scriptable pipeline for cleaning up a personal [Zotero](https://www.zotero.org)
reference library. It normalizes item types, backfills DOIs from arXiv, promotes
published preprints to journal articles via Crossref, and standardizes journal
metadata — using the [pyzotero](https://github.com/urschrei/pyzotero), arXiv, and
Crossref APIs.

Originally a pile of Jupyter notebooks; reorganized into independent, dry-run-safe
scripts that share a small helper package.

## Setup

Requires [uv](https://docs.astral.sh/uv/) and Python ≥ 3.10.

```bash
uv sync   # create the venv and install dependencies
```

Then provide your Zotero credentials. Real environment variables take precedence
over a `.env` file, so either works — **exporting environment variables is
recommended**, since it also works when the skill runs from another directory:

```bash
export ZOTERO_API_KEY=...           # get one at https://www.zotero.org/settings/keys
export ZOTERO_LIBRARY_ID=1234567    # your userID, shown on that same page
export ZOTERO_LIBRARY_TYPE=user
export CROSSREF_MAILTO=you@example.com   # optional: joins Crossref's faster "polite pool"
```

Add those lines to your shell profile (`~/.zshrc`, `~/.bashrc`) to persist them.
Or, when working inside this repo, use a local `.env` (gitignored — never commit
it):

```bash
cp .env.example .env   # then edit it with the same keys
```

Verify it works:

```bash
uv run python -c "from zotcleanup import get_client; print(get_client().count_items(), 'items')"
```

## Use as an agent skill (Claude Code / Codex)

This repo bundles the `zotero-cleanup` agent skill (in `skills/`) and ships it as
a plugin, so an AI coding agent can drive the pipeline for you. Install it once
and the skill is available in any project.

### Claude Code

```
/plugin marketplace add LionSR/zotcleanup
/plugin install zotcleanup@zotcleanup
```

### Codex

```
codex plugin marketplace add LionSR/zotcleanup
```

Then enable **Zotero Cleanup** in the Codex plugin browser.

### Manual install

Clone this repo and point your agent at the `skills/` directory — or symlink
`skills/zotero-cleanup` into your agent's skills folder (`~/.claude/skills/` for
Claude Code).

### Update

| Platform | Command |
|----------|---------|
| Claude Code | `/plugin update zotcleanup` |
| Codex | `codex plugin marketplace upgrade zotcleanup` |
| Manual install | `git pull` in the clone |

The skill still needs the `zotcleanup` package installed (`uv sync`) and your
Zotero credentials available (see [Setup](#setup)).

## Usage

**Everything defaults to a dry run** — scripts print an `old -> new` diff and
write nothing until you pass `--apply`. Preview first, confirm, then apply.

Run a single stage:

```bash
uv run scripts/04_preprints_to_journals.py            # dry run
uv run scripts/04_preprints_to_journals.py --limit 5  # preview just 5 items
uv run scripts/04_preprints_to_journals.py --apply    # write changes
```

Or run the whole pipeline in order:

```bash
uv run run_pipeline.py --dry-run --limit 5   # preview a few items per stage
uv run run_pipeline.py --apply               # run it all for real
```

Common flags on every stage: `--apply`, `--limit N`, `--verbose`.

## The pipeline (order matters)

`run_pipeline.py` runs the data and hygiene stages in this order — each stage
consumes what the earlier ones produced:

```
01 → 02 → 20 → 03 → 04 → 05 → 06 → 07 → 08 → 09 → 14 → 15 → 16 → 17 → 18
```

Stage 20 runs early (right after 02) on purpose: it demotes mis-typed journal
articles to preprints so stage 03 can then fetch their DOIs.

### Data & metadata stages

| # | Script | Purpose |
|---|--------|---------|
| 01 | `01_documents_to_preprints.py` | `document` + arXiv URL/id → `preprint` |
| 02 | `02_arxiv_journals_to_preprints.py` | arXiv-mislabelled journal articles → `preprint` / real DOI |
| 20 | `20_clean_journal_preprint_urls.py` | clear leftover arXiv/bioRxiv URLs on journal articles (or demote mis-typed ones) |
| 03 | `03_preprints_fetch_doi.py` | fetch arXiv DOI + category; tidy category brackets |
| 04 | `04_preprints_to_journals.py` | preprints with a real DOI → `journalArticle` (Crossref) |
| 05 | `05_conferences.py` | conference papers: retype duplicates, fill proceedings, NeurIPS abbrev |
| 06 | `06_journal_metadata_fixes.py` | fix issue numbers, page numbers, clean `extra` |
| 07 | `07_strip_arxiv_from_journals.py` | strip the arXiv line from published articles' `extra` |
| 08 | `08_standardize_journal_titles.py` | canonical journal titles + abbreviations |
| 09 | `09_tag_arxiv_categories.py` | tag `[primary_category]` into `extra` for any item with an arXiv id |

### Hygiene stages (mechanical scrubbers, run last)

| # | Script | Purpose |
|---|--------|---------|
| 14 | `14_clean_extra.py` | strip importer cruft (`Citation Key:`, stray `Issue:`/`Volume:` lines, …) from `extra` |
| 15 | `15_clean_titles.py` | strip BetterBibTeX braces + HTML entities from titles |
| 16 | `16_resolve_placeholder_dois.py` | replace ResearchGate / arXiv placeholder DOIs with the real publisher DOI (Crossref) |
| 17 | `17_clean_creator_names.py` | clean author/editor names: LaTeX→Unicode, BBT braces, ALL-CAPS surnames |
| 18 | `18_capitalize_proper_nouns.py` | capitalize curated proper nouns + acronyms in titles |

Stages 05 and 06 take an optional sub-action (default `all`):
`05_conferences.py {convert-duplicates,fill-proceedings,standardize-neurips,all}`,
`06_journal_metadata_fixes.py {fix-issues,fix-pages,all}`.

### Organizing collections (stages 10–12)

Stages 01–09 fix item *metadata*; these reorganize the *collection tree*. They
share the `zotcleanup.collections` layer (`Tree` + batched, dry-run-aware
`create`/`rename`/`add_items`/`merge`) and are run individually, not by
`run_pipeline.py`.

| # | Script | Purpose |
|---|--------|---------|
| 10 | `10_organize_unfiled.py` | file unfiled references: `--export f.json`, then `--map f.json [--apply]` |
| 11 | `11_normalize_collection_names.py` | canonicalize leading numeric prefixes (`00Core` → `00 Core`) |
| 12 | `12_merge_collections.py` | report collision-named collections; `--merge SRC DST` to fold one in |

Stage 10 deliberately holds no classification logic: `--export` dumps unfiled
items + a collection catalog, something intelligent writes an assignment map
`{item_key: [collection_key, …]}`, and `--map` applies it (batched, additive,
dry-run first). Swap in any classifier without touching the engine.

### Standalone stages & tools (not run by the pipeline)

Numbered stages that exist but aren't wired into `run_pipeline.py`:

- `scripts/13_conferences_dblp.py` — verify & enrich conference papers against
  **DBLP**. Believes a hit only when title fuzzy-matches **and** year agrees
  (±1) **and** authors overlap, then fills missing DOI / canonical venue /
  date / pages / volume; year-or-author disagreements are reported as SUSPECT
  and left untouched. Run before stage 05 `fill-proceedings` (its DOIs feed the
  Crossref publisher/place fill). Flags: `--only-missing`, `--canonical-venue`.
- `scripts/19_fill_missing_dois.py` — recover identity of under-specified
  journal articles. `demote-shells` retypes DOI-less, title-less
  `journalArticle`s to `preprint` (via an arXiv title search); `fill-dois` sets
  a missing DOI from a confident DBLP/Crossref title match. Sub-actions:
  `{demote-shells,fill-dois,all}` (default `all`).

Utilities under `scripts/tools/`:

- `import_bib.py` — import a BibTeX/BetterBibTeX `.bib` (passed as a path) into
  Zotero, mapping `@article`/`@inproceedings`/`@unpublished`/`@misc` to the right
  `itemType`; skips titles already in the library. Dry-run by default.
- `detect_dead_dois.py` — `HEAD`s `https://doi.org/<doi>` for every
  non-placeholder DOI (in parallel), reports 404s, and with `--apply` repairs
  known DOI patterns or clears the rest.
- `scan_import_artifacts.py` — **read-only** library-wide audit for bad-import
  artifacts (arXiv ids leaking into volume/issue/pages/publication-title, fake
  "et al." authors). Caches the full pull to `scan_cache.json` (gitignored);
  `--refresh` re-pulls. Writes nothing.
- `scrape_dois.py` — slow HTML fallback scraping `citation_doi` meta tags for
  arXiv articles the API path missed.
- `delete_all_tags.py` — **destructive**, deletes every tag; only acts with
  `--yes`.

## Layout

```
zotcleanup/        shared package: client (env / .env config), helpers, CLI
                   engine, collections (Tree + folder/membership operations)
scripts/           numbered stages 01–20: data/metadata (01–09), collection
                   organization (10–12), DBLP enrichment (13), hygiene (14–18),
                   DOI backfill (19), preprint-URL cleanup (20)
scripts/tools/     opt-in / destructive utilities
skills/            the zotero-cleanup agent skill (installable as a plugin)
run_pipeline.py    runs the metadata + hygiene stages in order
                   (01, 02, 20, 03–09, 14–18); not 10–12, 13, or 19
.claude-plugin/    Claude Code marketplace + plugin manifest
.codex-plugin/     Codex plugin manifest
.agents/           cross-agent marketplace manifest
```

## Customizing

- Add journals to `JOURNAL_TABLE` in `scripts/08_standardize_journal_titles.py`.
- Tune rate limits / date priority in `zotcleanup/helpers.py`.

## License

MIT — see [LICENSE](LICENSE).
