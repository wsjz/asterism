# Phase 2 plan — Content projects and the first gate

Scope and "done" criteria come from [the roadmap](roadmap.md#phase-2--content-projects-and-the-first-gate).
This document turns them into ordered, PR-sized steps. Each step keeps the
test suite green, touches only the files listed, and is usable on its own.

Phase 1 collects; Phase 2 adds the object the pipeline is about. A content
project is a folder with a `project.md` card and a `brief.md`, created from a
fragment the person ticked in the weekly digest. Nothing here writes prose or
publishes; that is Phase 3.

## Decisions taken before writing code

- **`project.md` front matter is real YAML**, not the JSON-scalar form the
  notes mirror uses. Notes are machine-owned; a project card is edited by
  hand in Obsidian's Properties panel, so it must be idiomatic YAML that
  Obsidian understands. It is written with `yaml.safe_dump` and read with
  `yaml.safe_load`.
- **Project files are the source of truth; there is no `projects` state
  table.** `status`, `week`, and `INDEX.md` scan `content/**/project.md`, so
  an edit made in Obsidian is picked up on the next command without a sync
  step. Only the human decision about a fragment (`assignments`) needs state,
  because no file records it otherwise.
- **Directory and file names follow the Phase 1 naming rule**: the cleaned
  title, keeping case and spaces, no slugs and no hashes. A project folder is
  `2026-09-22 Desktop Status Screen`, so `{slug}` in the roadmap's path
  template is spelled `{title}` here.
- **Nothing empty is created.** `new` writes the project folder,
  `project.md`, and `brief.md`. Stage directories for media are created in
  Phase 3 when a file actually lands in them, the same rule that keeps
  digests sparse.
- **Status is owned by the person.** The machine sets it when it creates a
  project and validates that the value is known; moving a project forward is
  an edit in Obsidian (or, from step 6, in Notion). No transition engine.
- **Templates live in the vault and seed themselves.** `new` copies the
  packaged default to `templates/` when the file is missing, then renders the
  vault's copy, so the templates are discoverable and editable.

## Status

Steps 1 to 5 are implemented and covered by the test suite (128 tests, no
network and no real Notes library). Step 6, the Notion board, is open: it
needs an integration token and a database, and everything above works without
it.

Decisions taken while implementing:

- A project directory keeps the cleaned title, so `{slug}` became `{title}`.
- Identity in the candidates list is carried by an HTML comment
  (`<!-- asterism:<source>:<source_id> -->`), invisible when rendered, so a
  line survives being re-worded by hand.
- Everything from `## Candidates` to the end of a digest belongs to the
  person; the digest builder preserves it, which is what makes ticks survive
  a sync.
- `propose` keeps the lines of items that were already applied, so a week's
  digest stays a record of what was decided that week.

## Step 1 — Content and project configuration, and the project model

Design:

- `asterism.yaml` gains two blocks, both optional with working defaults:

  ```yaml
  content:
    pillars:
      - { key: vibe-coding, name: Vibe Coding, tags: [vibe-coding] }
      - { key: desk-setup,  name: Desk Setup,  tags: [desk-setup] }
    types: [tutorial, review, makeover, opinion, checklist]
    platforms: [blog, zhihu, xiaohongshu, douyin, sspai, flowus]
  project:
    id_format: "{year}-{seq:03d}"
    path: "{year}/{date}-{title}"
    layout: flat
    numbered: true
    stages: …            # the roadmap's default list
    bindings: { unassigned_media: originals, platform_exports: export, covers: cover }
  ```

- `ContentProject` dataclass and `projects/model.py`: render and parse
  `project.md` front matter (`id`, `title`, `pillar`, `type`, `status`,
  `promise`, `primary`, `platforms`, `scheduled`, `created`, `sources`,
  `published`, `notion`), validated on load with clear errors.
- Stage parsing and validation (bindings reference existing keys,
  `platform_exports` is a `media_per_platform` stage, names are safe
  relative paths). Stages are not used to create anything yet.

Files: `src/asterism/config.py`, new `src/asterism/projects/{__init__,model,stages}.py`,
`tests/test_project_model.py`, `tests/test_config.py`.

## Step 2 — Scaffolding and `new`

Design:

- Content id from `project.id_format`, the sequence taken from the highest
  id already present in `content/`, so ids never collide and never need
  state.
- Path from `project.path` with `{year}`, `{date}`, `{title}`, `{id}`,
  `{pillar}`, `{type}`; each segment cleaned like a note file name;
  collisions get ` (2)`.
- `asterism new "<title>" --pillar <key> --type <type> [--platforms a,b]
  [--source notes/...]` creates the folder, `project.md`, and `brief.md`
  from the templates, and prints the path.
- Packaged defaults `templates/project.md` and `templates/brief-default.md`;
  a pillar may override with `templates/brief-<pillar>.md`. Rendering is
  `{{name}}` substitution, no template engine.

Files: new `src/asterism/projects/{paths,scaffold}.py`,
`src/asterism/templates/*.md`, `src/asterism/cli.py`, `tests/test_project_scaffold.py`.

## Step 3 — `status`, `week`, and the browsing views

Design:

- `projects/registry.py`: load every `content/**/project.md`, report
  unreadable ones instead of failing the command.
- `asterism status [--pillar] [--status] [--year]`: a grouped listing with
  per-platform published marks.
- `asterism week`: one page for the weekly session — projects in flight with
  the gate each is waiting on, projects published in the period, and the
  count of fragments waiting in the current candidates list.
- `content/INDEX.md` (a table) and `content/projects.base` (an Obsidian Bases
  view) regenerated by any command that changes a project.

Files: new `src/asterism/projects/{registry,index}.py`, `src/asterism/cli.py`,
`tests/test_project_index.py`.

## Step 4 — Assignments and classification

Design:

- State schema 3 adds `assignments`: `(source, source_id) → decision
  (pending | ignored | promoted), project_id, decided_at`, with a migration
  in both backends.
- `enrich/classify.py`: rule-based only. An item's pillar comes from the
  first pillar whose `tags` aliases match one of the item's tags or a
  segment of its `parent` path; otherwise `None`, which the candidates list
  shows as unclassified rather than guessing.

Files: `src/asterism/models.py`, `src/asterism/state/*`, new
`src/asterism/enrich/{__init__,classify}.py`, `tests/test_state.py`,
`tests/test_classify.py`.

## Step 5 — Gate 1: `propose` and `apply`

Design:

- `asterism propose [--week LABEL]` appends or refreshes a `## Candidates`
  section in that week's digest: one checkbox per undecided item of the
  period, grouped by pillar, unclassified last, each line a wikilink with
  its date. Existing ticks are preserved when the section is refreshed.
- The digest builder preserves everything from `## Candidates` to the end of
  the file when it rebuilds a digest, so ticks survive a sync.
- `asterism apply [--week LABEL]` reads the ticks, creates one project per
  ticked item (title from the item, pillar from its classification, status
  `approved`, the item linked in `sources` and quoted in the brief), records
  the assignment, and rewrites the line as applied with a link to the
  project. Unticked items stay pending.

Files: new `src/asterism/gates/{__init__,candidates}.py`,
`src/asterism/digest/builder.py`, `src/asterism/cli.py`,
`tests/test_gate_candidates.py`.

## Step 6 — Optional Notion board

Deferred to the end of the phase because it needs the person's integration
token and a database, and because everything above must keep working without
it. Notion is a projection, not a store.

Design:

- **The vault owns every field, always.** `project.md` stays complete and
  authoritative whether or not a board exists. A vault with no board
  configured is the base case, which is what steps 1 to 5 already deliver.
- **The board is a second surface, not a second truth.** A run pushes the
  card's values to the row, adds `obsidian://open?vault=...&file=...` links to
  `project.md` and `draft.md` plus publication links and counts, and reads
  back what the person changed there since the last run.
- **Three-way comparison against a stored snapshot** decides each field:
  remote changed and local did not means take the remote value; local changed
  and remote did not means push it up; both changed means report the conflict
  and keep the local value. Nothing is ever overwritten silently.
- **Absence is never a value.** A missing row, a missing database, a revoked
  token or no network are reported and skipped; they never clear a field. The
  `notion` field on the card distinguishes "no row yet" from "the row is
  gone", and Asterism never deletes a row and never recreates a deleted one
  on its own. `asterism board restore` rebuilds rows from the cards when the
  person asks for it.
- **Every project command works with the board switched off**, so removing
  the configuration is a supported way to stop using Notion.

Files: new `src/asterism/deliver/notion_board.py`, `src/asterism/config.py`,
`src/asterism/state/*` (the snapshot), `src/asterism/cli.py`,
`tests/test_notion_board.py`.

## Done when

The user's current piece of content is tracked as a project created by
ticking a fragment in a weekly digest, with that fragment linked in the
brief; unclassified fragments appear with empty checkboxes rather than a
guessed pillar; `status` and `week` answer what is in flight without opening
Notion.
