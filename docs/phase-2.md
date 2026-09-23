# Phase 2 plan — Picks and projects

Scope and "done" criteria come from [the roadmap](roadmap.md#phase-2--picks-and-projects).
This document turns them into ordered, PR-sized steps. Each step keeps the
test suite green, touches only the files listed, and is usable on its own.

Phase 1 collects; Phase 2 adds the object the pipeline is about. A content
project is a folder with a `project.md` card and a `brief.md`, created from a
piece of collected material the person placed under `used` in a review sheet. Nothing here writes prose or
publishes; that is Phase 3.

The state machines this phase touches are defined in
[the state model](state-model.md); this plan follows that document.

## Decisions taken before writing code

- **`project.md` front matter is real YAML**, not the JSON-scalar form the
  notes mirror uses. Notes are machine-owned; a project card is edited by
  hand in Obsidian's Properties panel, so it must be idiomatic YAML that
  Obsidian understands. It is written with `yaml.safe_dump` and read with
  `yaml.safe_load`.
- **Project files are the source of truth; there is no `projects` state
  table.** `status`, `week`, and `INDEX.md` scan `projects/**/project.md`, so
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

Steps 1 to 5 are implemented and covered by the test suite (138 tests, no
network and no real Notes library). Step 6, the Notion board, is open: it
needs an integration token and a database, and everything above works without
it.

Decisions taken while implementing:

- A project directory keeps the cleaned title, so `{slug}` became `{title}`.
- **Gate 1 is a sheet of its own, not a section of the weekly digest.** The
  digest is a record of a period and is rebuilt on every sync; decisions are
  not tied to one period and must survive rebuilding. `picks/<date>.md` is
  written once, edited by hand, applied, and then kept as the record of that
  round.
- **A line is moved, not ticked.** The sheet has one heading per outcome
  (`undecided`, `used`, `later`, `reference`, `dropped`) and the person drags
  a line under the heading that says what happens to it. Checkboxes could only
  express yes or no; there are four outcomes.
- **A topic gathers material; one line to one project was wrong.** Asterism
  exists to turn scattered notes into one piece, so the unit that becomes a
  project is a topic with the fragments it gathered, written as a `### topic`
  heading under `used`. The topic name is the piece's name, which also ends
  the earlier awkwardness of a project being named after whichever fragment
  happened to spawn it. Grouping stays a suggestion in a file: classification
  rules today, an enricher or a language model later, but the person always
  edits the headings before `apply` reads them.
- **Identity is the link.** A line is recognized by the note it points at, so
  the text around the link can be re-worded freely and no machine marker has
  to sit in the file.
- Items placed in `later` come back in every following sheet until they get
  another outcome, because "not now" is not a decision that closes anything.
- Rules in `review.rules` give a line its starting section; a rule with
  `auto: true` is applied without listing the item at all, and the sheet says
  how many were taken that way. A rule may never produce `used`: creating a
  project is a decision.
- The session was called *triage* while it was being written; the word
  implied ranking by urgency, which is not what the four outcomes do. Command,
  directory and state machine are all `propose`.

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

- `Project` dataclass and `projects/model.py`: render and parse
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
  id already present in `projects/`, so ids never collide and never need
  state.
- Path from `project.path` with `{year}`, `{date}`, `{title}`, `{id}`,
  `{pillar}`, `{type}`; each segment cleaned like a note file name;
  collisions get ` (2)`.
- `asterism new "<title>" --pillar <key> --type <type> [--platforms a,b]
  [--source notes/...]` creates the folder, `project.md`, and `brief.md`
  from the templates, and prints the path.
- Packaged defaults `settings/templates/project.md` and
  `settings/templates/brief-default.md`; a type or pillar may override with
  `settings/templates/brief-<name>.md`. Rendering is
  `{{name}}` substitution, no template engine.

Files: new `src/asterism/projects/{paths,scaffold}.py`,
`src/asterism/templates/*.md`, `src/asterism/cli.py`, `tests/test_project_scaffold.py`.

## Step 3 — `status`, `week`, and the browsing views

Design:

- `projects/registry.py`: load every `projects/**/project.md`, report
  unreadable ones instead of failing the command.
- `asterism status [--pillar] [--status] [--year]`: a grouped listing with
  per-platform published marks.
- `asterism week`: one page for the weekly session — projects in flight with
  the gate each is waiting on, projects published in the period, and how long
  it has been since the last review sheet.
- `projects/INDEX.md` (a table) and `projects/projects.base` (an Obsidian Bases
  view) regenerated by any command that changes a project.

Files: new `src/asterism/projects/{registry,index}.py`, `src/asterism/cli.py`,
`tests/test_project_index.py`.

## Step 4 — Assignments and classification

Design:

- State schema 3 adds `assignments`: `(source, source_id) → decision
  (later | reference | used | dropped), project_id, decided_at`, with a
  migration in both backends. An item with no row has not been decided; there
  is no stored "pending" value.
- `enrich/classify.py`: rule-based only. An item's pillar comes from the
  first pillar whose `tags` aliases match one of the item's tags or a
  segment of its `parent` path; otherwise `None`, which the review sheet
  leaves blank rather than guessing.

Files: `src/asterism/models.py`, `src/asterism/state/*`, new
`src/asterism/enrich/{__init__,classify}.py`, `tests/test_state.py`,
`tests/test_classify.py`.

## Step 5 — Gate 1: `propose` and `apply`

Design:

- `asterism propose [--since DATE]` writes `picks/<date>-<time>.md`: every
  item that has no outcome yet, each line placed under the outcome its rule
  suggests and under `undecided` when no rule matches. Lines are grouped by
  source and then by the folder the item sits in, newest first at every
  depth, so the sheet reads like the source's own tree. An open sheet is
  refreshed rather than duplicated, and placements already made are kept.
- The sheet's front matter names the periods it covers: the fewest closed
  digest documents that still hold undecided items, coarsest first, so
  reading one week is reading its seven days. Periods still accumulating are
  never offered.
- The person moves lines between the outcome headings in Obsidian, and may
  write a `### topic` heading under `used` and gather several lines beneath it.
  A piece is usually made of several fragments, so one line to one project is
  the exception, not the rule; `used` therefore carries no source headings,
  because where material came from stops mattering once it will be made.
- `asterism apply [--date PREFIX]` records one assignment per placed line.
  Each topic under `used` becomes one project whose title is the topic and
  whose `sources` are all of its lines; a `used` line with no topic above it
  becomes a project of its own, titled after the item. Lines left under
  `undecided` are left alone; the sheet is marked `applied` and kept. Applying
  twice does nothing.
- `asterism material [--status] [--source]` reads the outcomes back without
  opening the sheets.

Files: new `src/asterism/gates/{__init__,review}.py`, `src/asterism/cli.py`,
`tests/test_review.py`.

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
moving a line under `used` in a review sheet, with that material linked in
the brief; unclassified material carries no pillar rather than a guessed one;
`status` and `week` answer what is in flight without opening Notion.
