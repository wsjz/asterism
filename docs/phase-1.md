# Phase 1 plan — Collection

Scope and "done" criteria come from [the roadmap](roadmap.md#phase-1--collection-current).
This document turns them into ordered, PR-sized steps. Each step keeps the
test suite green (`PYTHONPATH=src python3 -m unittest discover -s tests`,
`python3 -m compileall -q src tests`), touches only the files listed, and is
usable on its own. Steps are ordered by dependency: configuration format first
because every later step adds configuration keys; the model change next because
it forces the one-time rewrite of the vault; features after that.

## Status

Steps 0–11 are implemented and covered by the test suite (84 tests, no
network, no real Notes library, no Chrome). Step 12's documentation is done;
its dogfooding criterion, one week of daily real use without manual fixes, is
open and is what closes Phase 1.

Deviations from the plan below, decided while implementing:

- `sources/utils.py` stays as the adapter-facing wrapper that turns
  `normalize.parse_datetime` failures into `SourceError`; only the logic moved.
- Titles are not frozen in state: filenames were already stable through the
  stored `relative_path`, so the front matter title simply follows the source.
- `missing` needs no new table; it lists items whose `last_seen_at` predates
  their source's latest sync.
- Digests skip closed periods that contain no items and skip rewriting a file
  whose only change would be `generated_at`, so `--commit` stays quiet when
  nothing happened.

Found during the first real Apple Notes collection (the exporter had never
run against a real library):

- The AppleScript used `records` as a variable name, which AppleScript reads
  as "every record"; renamed to `noteRecords`.
- `|creation date|` and `|modification date|` with pipes are not the Notes
  dictionary terms; every note failed inside a silent `try`. Now
  `creation date` and `modification date`.
- `folders of account` is already flattened across all levels, so recursing
  into subfolders visited nested folders several times with different path
  prefixes. Recursion now starts only from folders whose container is the
  account.
- Notes in `Recently Deleted` (and its Chinese-localized name) are skipped by default;
  `sources.apple_notes.exclude_folders` overrides the list.
- The output tree mirrors the source hierarchy: an item's `parent` becomes
  sanitized subdirectories under `notes/<source>/`, and when the source moves
  an item the file moves with it (same file name, state updated). The first
  flat layout was wrong. Fragment items carry `<folder>/<note title>` as
  their parent so they sit beside their note.
- Development runs use the repository itself as the vault (`--vault .`);
  collected content there is git-ignored.
- File names carry no hash: they are the cleaned title, with ` (2)`, ` (3)`
  suffixes when a directory already has that name (checked against state and
  disk), and are fixed once recorded so title changes do not rename files.

## Step 0 — Baseline

- Fix the verification commands in `AGENTS.md` and `README.md` to run from a
  virtual environment with the package installed (`pip install -e .`) or with
  `PYTHONPATH=src`; today the bare command fails with import errors.
- Add `tests/fixtures/` as the home for all fixture files added below.

Files: `AGENTS.md`, `README.md`.

## Step 1 — YAML configuration

Design:

- `asterism.yaml` replaces `asterism.toml`. Loader: `yaml.safe_load` only.
  PyYAML is the project's single dependency (`dependencies = ["PyYAML>=6"]`).
- After loading, every value is validated for type, range, and shape; YAML's
  implicit typing is countered by explicit checks (for example month-day lists
  must be quoted strings matching `MM-DD`).
- `init` writes `asterism.yaml`. If both `asterism.yaml` and `asterism.toml`
  exist, loading fails with a message. If only `asterism.toml` exists, loading
  fails and points at `asterism migrate-config`, which writes the YAML
  equivalent and tells the user to delete the TOML file.
- Existing keys keep their meaning: `state.backend`, `sources.apple_notes`,
  `sources.flomo`, `sources.markdown`, `sources.notion`.

Files: `pyproject.toml`, `src/asterism/config.py`, `src/asterism/cli.py`,
`asterism.toml` → `asterism.yaml` in the repository, `tests/test_config.py`.

Tests: load valid YAML; reject wrong types; reject both files present; migrate
a TOML file and compare; init writes YAML.

## Step 2 — Foundation refactor, no behavior change

Design:

- `vault.py`: layout constants (`notes`, `digest`, `state`, `logs`,
  `archive`, `inbox`), `normalize_vault`, `validated_target`, `atomic_write`
  moved from `pipeline.py` and `config.py`.
- `normalize/` package of pure functions with no Asterism imports:
  `markdown.py` (HTML to Markdown, moved from `sources/flomo.py`),
  `datetimes.py` (moved from `sources/utils.py`), `urls.py`
  (`canonical_url`: lowercase scheme and host, drop fragments and tracking
  parameters, strip trailing slash), `titles.py` (the title rule from the
  roadmap: native title, first heading, cleaned first line, URL host and last
  segment, none).
- `sources/registry.py`: maps a source name to a factory taking `Config`;
  parses `opencli:<collection>`; lists enabled sources for a config.
- `sources/utils.py` becomes a thin re-export and is removed at the end of
  the phase.

Files: new `src/asterism/vault.py`, `src/asterism/normalize/*`,
`src/asterism/sources/registry.py`; edits to `pipeline.py`, `config.py`,
`sources/flomo.py`, `sources/utils.py`, `cli.py`; new tests
`tests/test_normalize.py`, `tests/test_registry.py`.

Acceptance: a sync of the fixture vault before and after this step produces
byte-identical files.

## Step 3 — Model schema 1

Design:

- `SourceItem` gains `origin: Origin` (`adapter`, `producer`,
  `producer_version`, all short strings), `url: str | None`, and
  `author: str | None`, validated like the existing fields.
- Every adapter fills `origin`; Cubox moves `url` and `author` out of
  `source_meta`; Markdown fills `url` with nothing and `author` from front
  matter when present; Notion fills `url` with the page URL.
- Rendering order becomes: `schema`, `source`, `source_id`, `origin`,
  `title`, `url`, `author`, `parent`, `tags`, `created_at`, `updated_at`,
  `source_meta`. `rendering.parse_front_matter` reads what `render_markdown`
  writes (JSON scalar values) and is used by digests.
- This changes every content hash once; the next sync rewrites the vault.
  The README notes it.

Files: `models.py`, `rendering.py`, all five adapters, `docs/sources.md`,
`tests/test_rendering.py`, adapter tests.

## Step 4 — Title rule in every adapter

Design: each adapter calls `normalize.titles.derive_title(native, body, url)`
instead of its own logic. Filenames are already stable because
`relative_path` is stored in state, so the front matter title may follow the
source without renaming files. Mode B (Phase 5) may only fill an empty
title.

Files: the five adapters, `tests/test_normalize.py` cases for timestamps,
list markers, bare URLs, CJK sentence ends, 60-character cut.

## Step 5 — Apple Notes fragment items

Design:

- Configuration: `sources.apple_notes.daily_log_folders: ["Daily Log"]` and
  `sources.apple_notes.timezone` (default: the digest timezone).
- A note whose folder is in the list is split, not stored whole. A fragment
  starts at a line matching `^\s*(\d{1,2}):(\d{2})\s+` and runs to the next
  such line. Text before the first timestamp is a fragment anchored
  `preamble`.
- `source_id` = `<note id>#<HH:MM>` with `-2`, `-3` suffixes for repeated
  times; `parent` = note title; `created_at` = the note's date (from a
  leading `YYYY-MM-DD` in the title, else the note's creation date) combined
  with the line time in the configured timezone; `updated_at` = the note's
  modification time; `title` from the title rule on the fragment body.
- Editing an earlier fragment changes only that item; appending a new line
  creates one new item.

Files: `sources/apple_notes.py` (+ `sources/fragments.py` for the splitter),
`config.py`, `tests/test_fragments.py` with fixtures.

## Step 6 — State schema 2 and `missing`

Design:

- `ItemState` gains `first_seen_at`, `source_created_at`, and `title`, so
  digests can be built from state without parsing every note.
- File backend: `schema_version` 2 with an in-place migration that fills
  `first_seen_at` from `last_seen_at`. SQLite: `ALTER TABLE … ADD COLUMN`
  guarded by a `schema_version` table; both backends share one migration
  test.
- `StateBackend` gains `items(source) -> Iterable[ItemState]`,
  `items_between(start, end)`, and a `digests` table API
  (`get_digest`, `save_digest`, `pending_digests`).
- `asterism missing --vault [--source]`: items whose `last_seen_at` is older
  than the source's latest `last_seen_at`, printed with path and last seen
  time. Nothing is deleted.

Files: `models.py`, `state/*`, `cli.py`, `tests/test_state.py`,
`tests/test_cli_missing.py`.

## Step 7 — Digests

Design:

- Configuration block `digest` exactly as in the roadmap: `timezone`,
  `after_sync`, `excerpt_chars`, and per level `enabled`, `run_on`,
  `include_*`, `archive_*`, and (ignored in mode A)
  `llm`.
- `digest/periods.py`: pure functions that, given a date and the
  configuration, return the period containing it and the list of periods
  that ended before "now" and are not yet generated. Week periods end on the
  ISO weekday `run_on`; month periods end on the last day of the `run_on`-th
  seven-day block, on the listed `MM-DD`, or on the last calendar day; year
  periods end on the last day of month `run_on`. Timezone applied throughout.
- `digest/builder.py`: for a period, select items whose `source_created_at`
  (else `first_seen_at`) falls inside, group by source, render "new" and
  "updated" sections with wikilinks and excerpts, write atomically, record
  in the `digests` table with state `open` or `closed`. Higher levels embed
  (`![[…]]`) or merge lower documents according to `include_*` and the
  archive mode.
- `asterism digest --vault [--regenerate PERIOD]`; `sync` calls the same
  code after a successful run when `after_sync` is true, unless
  `--no-digest`.
- Lifecycle `open → closed → rolled → archived`.

Files: new `src/asterism/digest/*`, `config.py`, `cli.py`,
`tests/test_digest_periods.py` (fixed clock, cross-week, cross-month, list
`run_on`, catch-up of three missed periods, timezone edge),
`tests/test_digest_builder.py`.

## Step 8 — Storage roots, archive switch, doctor

Design:

- Configuration: `storage.media_root`, `storage.inbox`, `archive.enabled`,
  `archive.root`, `archive.mode`, `archive.on_publish`,
  `archive.auto_execute`, `state.state_dir`. Only the keys used in this
  phase act; the rest are validated and stored for later phases.
- `vault.py` validates paths against a named root and refuses to act when a
  configured root is not mounted.
- Digest archiving (`archive_*` per level) copies or moves rolled-up
  documents under `archive.root` (default `<vault>/archive/`) when
  `archive.enabled` is true.
- `doctor` gains: network filesystem detection for the vault (parse
  `/sbin/mount` output for the longest matching mount point and its type;
  warn on smbfs, afpfs, nfs, webdav and require a local `state_dir` there),
  a report of the active configuration (state location, roots, which archive
  sub-switches are masked by the master switch), and per-source checks for
  Markdown roots and Notion token presence.

Files: `config.py`, `vault.py`, `digest/archive.py`, `cli.py` (doctor),
`tests/test_vault.py`, `tests/test_doctor.py`.

## Step 9 — Markdown and Notion hardening

- Markdown: fixture tests for symlink rejection, traversal rejection,
  exclusion of the Asterism vault itself, front matter title and tags.
- Notion: fixture-based transport tests for pagination, HTTP 429 with
  `Retry-After`, and malformed payloads; `doctor` verifies the token is set
  without printing it.

Files: `sources/markdown.py`, `sources/notion.py`, their tests.

## Step 10 — opencli adapter

Design:

- Configuration:

  ```yaml
  sources:
    opencli:
      binary: opencli            # optional; found on PATH otherwise
      collections:
        - name: twitter-bookmarks
          command: [twitter, bookmarks]
          args: { limit: 200 }
          map:
            id: id
            url: url
            content: [text]
            created_at: created_at
            author: author
            exclude: [rank]
  ```

- `sources/opencli/source.py`: runs `[binary, *command, *args, --format,
  json]` through a runner with a timeout, checks the top-level value is a
  list, applies size limits, maps exit codes (0 rows; 66 or `[]` → no items;
  69 and 77 → `SourceError` with guidance; 2 → configuration error).
- `sources/opencli/mapping.py`: applies `map` to each row: identity from `id`
  else `url` else refuse; content fields joined; `created_at` and
  `updated_at` parsed tolerantly (invalid → `None`); remaining scalar fields
  into `source_meta`, non-scalars JSON-encoded, `exclude` dropped.
- `sources/opencli/manifest.py`: validates each collection against `opencli
  list --format json`: command exists, `access == "read"`, mapped fields are
  declared columns. Used by `doctor` and at the start of a sync.
- `source` name and `output_name` are `opencli-<collection>`; `origin` is
  `adapter: opencli, producer: <site>/<command>, producer_version` from
  `opencli --version`.

Files: new `src/asterism/sources/opencli/*`, `config.py`, `registry.py`,
`cli.py` (doctor), fixtures from the samples collected during evaluation in
`tests/fixtures/opencli/`, `tests/test_opencli_source.py`.

## Step 11 — `sync` over all sources, `--commit`, `--no-digest`

Design:

- Without `--source`, `sync` runs every enabled source from the registry.
  `--source` may repeat. One source's failure is reported on stderr and does
  not stop the others; the exit code is 1 if any failed.
- `--commit`: after all sources succeed, run `git add -A -- notes digest`
  and `git commit -m "sync <timestamp> (+new ~updated)"` with argument
  arrays, only if the vault is a Git repository; never push. Skipped with a
  note if there is nothing to commit.
- Output stays to counts and paths; no note content on stdout.

Files: `cli.py`, `pipeline.py` (multi-source orchestration may move to
`stages/collect.py`), `tests/test_cli_sync.py` using fake sources and a
temporary Git repository.

## Step 12 — Documentation and dogfooding

- README: positioning as a content production pipeline, YAML configuration,
  the PyYAML dependency, the one-time rewrite in Step 3, `digest` and
  `missing`.
- AGENTS.md: the dependency rule updated, verification commands, the rule
  that `content_text` is always Markdown, and that only `normalize/` holds
  shared conversion logic.
- docs/sources.md: schema 1 front matter, the opencli section (mapping
  provided by recipes), the fragment rule for Apple Notes.
- Run the real vault daily for one week with `--commit`; fix what breaks;
  then mark Phase 1 done in the roadmap.

## Order and checkpoints

| Step | Depends on | Checkpoint |
|---|---|---|
| 0 | — | tests run with the documented command |
| 1 | 0 | `init` writes YAML; TOML migrates |
| 2 | 1 | byte-identical sync before and after |
| 3 | 2 | vault rewritten once; front matter has `schema: 1` |
| 4 | 2 | title cases pass; no filename changes |
| 5 | 3, 4 | daily log note splits into fragments |
| 6 | 3 | state migrates; `missing` lists items |
| 7 | 6 | daily and weekly digests appear after sync |
| 8 | 1 | doctor reports roots and network filesystem |
| 9 | 3 | fixture tests pass for Markdown and Notion |
| 10 | 2, 3 | opencli collection syncs from fixtures and from a real allowlisted command |
| 11 | 7, 10 | one `sync --commit` collects all sources and commits |
| 12 | all | one week of real use without manual fixes |
