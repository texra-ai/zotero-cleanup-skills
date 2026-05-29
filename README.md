<div align="center">

# zotcleanup

**Point an AI agent at your Zotero library and let it fix the metadata** — wrong
item types, missing DOIs, published preprints still marked preprint, inconsistent
journal names — previewing every change before it writes.

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
&nbsp;![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)
&nbsp;![Claude Code plugin](https://img.shields.io/badge/Claude_Code-plugin-d97757)
&nbsp;![Codex plugin](https://img.shields.io/badge/Codex-plugin-000000)
&nbsp;[![GitHub stars](https://img.shields.io/github/stars/texra-ai/zotero-cleanup-skills?style=social)](https://github.com/texra-ai/zotero-cleanup-skills/stargazers)

</div>

A Claude Code / Codex **skill** plus independent, **dry-run-safe** scripts, built
on the [pyzotero](https://github.com/urschrei/pyzotero), arXiv, and Crossref APIs.

## What it fixes

A working Zotero library accumulates rot:

- arXiv preprints that were published long ago, still typed `preprint` (or `document`)
- one journal under several names — `Phys Rev Lett`, `Physical Review Letters`, …
- import gunk in titles and names — `{{braces}}`, `&amp;`, `SCHMIDT`, `M\"uller`
- placeholder DOIs (ResearchGate `RG.…`, DataCite arXiv) that aren't the real one
- hundreds of unfiled references
- AI agents that hallucinate citations off a messy library — a verified one gives them real DOIs and venues to cite

zotcleanup fixes each in a pass you review first:

```text
$ uv run scripts/15_clean_titles.py --limit 3
DRY-RUN — no writes: 3 candidate items

[1/3] change Tensor Networks for {{Quantum}} Simulation
           title: 'Tensor Networks for {{Quantum}} Simulation' -> 'Tensor Networks for Quantum Simulation'
[2/3] change Entanglement &amp; Thermalization in Closed Systems
           title: 'Entanglement &amp; Thermalization in Closed Systems' -> 'Entanglement & Thermalization in Closed Systems'

Would update 2/3 items.
Re-run with --apply to write these changes.
```

Nothing is written until you pass `--apply`. Every value is looked up from a named
authority (arXiv, Crossref, DBLP) above a match threshold — never guessed.

## Setup

Requires [uv](https://docs.astral.sh/uv/) and Python ≥ 3.10.

```bash
uv sync   # create the venv and install dependencies
```

Set your Zotero credentials as environment variables (these win over `.env`, and
work when the skill runs from any directory):

```bash
export ZOTERO_API_KEY=...           # https://www.zotero.org/settings/keys
export ZOTERO_LIBRARY_ID=1234567    # your numeric userID, same page
export ZOTERO_LIBRARY_TYPE=user
export CROSSREF_MAILTO=you@example.com   # optional: Crossref polite pool
```

Or copy `.env.example` to `.env` (gitignored) and fill in the same keys.

Verify it works:

```bash
uv run python -c "from zotcleanup import get_client; print(get_client().count_items(), 'items')"
```

## Use as an agent skill (Claude Code / Codex)

The `zotero-cleanup` skill (in `skills/`) ships as a plugin so an agent can drive
the pipeline. Install it once; it's then available in any project.

### Claude Code

```
/plugin marketplace add texra-ai/zotero-cleanup-skills
/plugin install zotcleanup@zotcleanup
```

### Codex

```
codex plugin marketplace add texra-ai/zotero-cleanup-skills
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

Still needs `uv sync` and your Zotero credentials (see [Setup](#setup)).

## Usage

**Everything defaults to a dry run**: scripts print an `old -> new` diff and
write nothing until you pass `--apply`.

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

### Driving it with the skill

With the plugin installed, describe the goal; the skill runs the right stages
dry-run first and writes only after you confirm:

> "Standardize my journal titles, but show me the preview first."

> "My published arXiv preprints are still typed as preprints — fix them and fetch the real DOIs."

> "File my unfiled references into the right collections."

## The pipeline (order matters)

`run_pipeline.py` runs the data and hygiene stages in this order — each stage
consumes what the earlier ones produced:

```
01 → 02 → 20 → 03 → 04 → 05 → 06 → 07 → 08 → 09 → 14 → 15 → 16 → 17 → 18
```

Stage 20 runs early (right after 02) on purpose: it demotes mis-typed journal
articles to preprints so stage 03 can then fetch their DOIs.

### Data & metadata stages

| # | Script | Example |
|---|--------|---------|
| 01 | `01_documents_to_preprints.py` | `document` with url `arxiv.org/abs/2303.08774` → `preprint` |
| 02 | `02_arxiv_journals_to_preprints.py` | `journalArticle`, publicationTitle `"arXiv:1706.03762"` → `preprint` |
| 20 | `20_clean_journal_preprint_urls.py` | `journalArticle` (has DOI), url `arxiv.org/abs/1810.04805` → url cleared |
| 03 | `03_preprints_fetch_doi.py` | `preprint` `arXiv:2007.14822` → `extra` gains `[cs.MS]` (+ DOI if arXiv reports one) |
| 04 | `04_preprints_to_journals.py` | `preprint` DOI `10.1103/PhysRevLett.130.133601` → `journalArticle` "Physical Review Letters" 130, 133601 |
| 05 | `05_conferences.py` | proceedingsTitle `"Advances in neural information processing systems"` → `"Adv. Neural inf. Process. Syst."` |
| 06 | `06_journal_metadata_fixes.py` | empty `pages` → `"133601"` (Crossref article number) |
| 07 | `07_strip_arxiv_from_journals.py` | `extra` line `"arXiv: 2103.00020 [cs.CV]"` → removed |
| 08 | `08_standardize_journal_titles.py` | `"Nat Rev Phys"` → `"Nature Reviews Physics"` + abbr `"Nat. Rev. Phys."` |
| 09 | `09_tag_arxiv_categories.py` | arXiv id `2106.09685` → `extra` gains `[cs.CL]` |

### Hygiene stages (mechanical scrubbers, run last)

| # | Script | Example |
|---|--------|---------|
| 14 | `14_clean_extra.py` | `extra` line `"Citation Key: lu2023"` → removed |
| 15 | `15_clean_titles.py` | `"{{Quantum}} Error &amp; Correction"` → `"Quantum Error & Correction"` |
| 16 | `16_resolve_placeholder_dois.py` | placeholder DOI `"10.13140/RG.2.2.12345"` → `"10.1103/PhysRevX.13.041023"` |
| 17 | `17_clean_creator_names.py` | lastName `"SMITH"` → `"Smith"`; `"M\"uller"` → `"Müller"` |
| 18 | `18_capitalize_proper_nouns.py` | `"a markov study of nmr"` → `"a Markov study of NMR"` |

Stages 05 and 06 take an optional sub-action (default `all`):
`05_conferences.py {convert-duplicates,fill-proceedings,standardize-neurips,all}`,
`06_journal_metadata_fixes.py {fix-issues,fix-pages,all}`.

### Organizing collections (stages 10–12)

Stages 01–09 fix item *metadata*; these reorganize the *collection tree*. They
share the `zotcleanup.collections` layer (`Tree` + batched, dry-run-aware
`create`/`rename`/`add_items`/`merge`) and are run individually, not by
`run_pipeline.py`.

| # | Script | Example |
|---|--------|---------|
| 10 | `10_organize_unfiled.py` | unfiled "Adam: A Method for Stochastic Optimization" → filed under `01 Optimization` |
| 11 | `11_normalize_collection_names.py` | `"00Core"` → `"00 Core"` |
| 12 | `12_merge_collections.py` | sibling collections `"QEC"` + `"Qec"` → merged (`--merge SRC DST`) |

Stage 10 holds no classification logic: `--export` dumps unfiled items + a
collection catalog, an external classifier writes an assignment map
`{item_key: [collection_key, …]}`, and `--map` applies it (batched, additive,
dry-run first).

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
