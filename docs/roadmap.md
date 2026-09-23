# Asterism roadmap

Asterism is an automated content production pipeline for a single creator. It
turns scattered notes and work logs into published content on several
platforms, with a human involved only at three decision gates. The pipeline is
fully usable without a language model; an LLM is an optional accelerator that
users may configure for a further level of automation.

This document is the shared reference for scope. It describes the destination,
the phases that lead there, and what the architecture looks like at the end of
each phase. Phases are delivered one at a time. A phase is finished when its
"done" criteria hold and it has been used for at least one real piece of
content, not when its tests pass.

## Destination

```text
sources ──► notes mirror ──► enrich ──► content projects ──► compose ──► deliver
 (notes,      vault/notes/    dedupe,     vault/projects/<project>/ drafts,     blog repo,
  work logs,                  classify,   state machine,        platform    publish
  feedback)                   rank        three human gates     versions    packages
                                                                    ▲
                                              feedback (metrics, comments) ┘
```

The state machines the whole pipeline runs on are defined once in
[the state model](state-model.md).

Design principles that hold across every phase:

- Files are the only interface between stages. Gates are Markdown files a
  person edits; the state machine reads them.
- Every stage has a deterministic baseline that works with the standard
  library alone. An LLM never owns a step; it only enhances a deterministic
  artifact and can be switched off at any time.
- Nothing is deleted or published automatically. Collection never deletes,
  publishing never happens without the third gate.
- The vault is the single source of truth and is complete on its own. Every
  other tool is a projection that can be rebuilt from it: Notion is a nicer
  surface for planning, NAS holds copies, an LLM enhances a deterministic
  artifact. Losing any of them loses convenience, never content or state.
- Generated Markdown links with Obsidian wikilinks by default
  (`links: wikilink | markdown` in configuration), so digests, briefs, drafts,
  and asset lists connect raw notes and projects into one graph: backlinks
  show where a fragment was used, and search and the graph surface related
  material while writing. Discovery happens in Obsidian, and planning is
  comfortable in Notion for those who add it.

## The agent and the AI-native contract

Asterism does not contain an agent. An agent — Claude Code, a script, or the
a model called by either — sits outside and drives the pipeline
through the CLI and the vault's files. This follows the first design
principle: files are the only interface between stages, so whatever drives
them is interchangeable and none of it is in the state machine.

What the pipeline owes an agent, and what every command must therefore
provide:

- **A machine-readable form.** Every command that reports anything takes
  `--json` and prints one JSON object with stable keys on stdout; the
  human-readable form is unchanged and stays the default.
- **Idempotence.** Running a command twice does what running it once did.
  Where that is impossible the command says what it already did and changes
  nothing.
- **A preview.** Every command that writes takes `--dry-run` and prints what
  it would write without touching the vault.
- **A next step on failure.** An error names the command that would fix it.
- **Gates that only a person passes.** An agent may gather, compose, adapt,
  and write suggestions into any file. It may not move a project's status: the
  three gate commands exist so that a person answers the gate's question, and
  an agent invoking one on its own is a bug, not a feature. The switches that
  advance state are never implied by another command.
- **Suggestions live in files, marked.** Anything an agent wrote that a person
  is meant to check is a normal part of the Markdown it belongs in, removable
  by deleting it, and the file's front matter records who wrote it.

The skill under `skills/asterism/` teaches an agent this flow and these
boundaries. It is data for the agent, not part of the pipeline: deleting it
changes nothing about how Asterism runs.

## Phase 1 — Collection

**Status.** Implemented; see [the Phase 1 plan](phase-1.md). The remaining
criterion is one week of daily real use without manual fixes.

**Goal.** Every note-like input the pipeline will ever need is reliably and
incrementally mirrored into the vault with provenance, and the collection
architecture is stable enough that later phases only add adapters.

Five adapters already exist: Apple Notes, flomo export, Cubox CLI, local
Markdown directories, and Notion. This phase hardens them, fixes the shared
model and utilities, and adds the one adapter still missing (opencli).

**Scope.**

1. Foundation, no behavior change: extract `vault.py` (layout, path
   validation, atomic write) from `pipeline.py`; add a `normalize/` package
   with the shared pure functions (HTML to Markdown from the flomo adapter,
   datetime parsing from `sources/utils.py`, URL canonicalization, and one
   title rule used by every adapter: native title, else first heading, else
   first non-empty line with list markers, leading timestamps, and bare URLs
   stripped and cut at the first sentence end or 60 characters, else the URL's
   domain and last path segment, else none; a title is fixed once stored and
   an enricher may only fill an empty one); add a
   source registry so `--source` resolves names to factories; give the front
   matter a `schema` version.
2. Model: add `origin` (adapter, producer, producer_version), `url`, and
   `author` to `SourceItem`. Cubox moves its URL out of `source_meta`.
   Rendering order is fixed and documented in `docs/sources.md`.
3. Fragment items: an Apple Notes note in a configured "daily log" folder is
   split into one item per time-stamped line. `source_id` is note id plus the
   line anchor, `parent` is the note, `created_at` is the line's own time.
   All other notes remain one item each.
4. Harden the local Markdown and Notion adapters: fixture-based tests for
   symlink and traversal rejection, exclusion of the Asterism vault itself,
   Notion pagination and rate-limit behavior, and `doctor` checks for both.
   Later phases use the Markdown adapter to know what knowledge already
   exists.
5. opencli adapter: one generic adapter driven by an explicit allowlist of
   read-only commands and a minimal field mapping in configuration. It
   validates each configured command against `opencli list --format json`,
   treats exit codes 66 and an empty array as "no changes", and reports 69
   and 77 with guidance. Its field semantics are provided by opencli's
   community adapters and the user's mapping, not by Asterism.
6. Missing items: `asterism missing` lists items the source no longer returns.
   Nothing is deleted.
7. Opt-in snapshot: `asterism sync --commit` commits the vault after a
   successful sync so Git history is the immutable snapshot layer. No push.
8. Storage roots: parse `storage` (`media_root`, `inbox`), `archive`
   (`enabled`, `root`, `mode`, `on_publish`, `auto_execute`), and an optional
   local `state_dir`; extend path validation to several
   roots; `doctor` warns when the vault sits on a network filesystem and
   requires local state there. Media directories themselves are created in
   Phase 3.
9. Digests: periodic aggregation of collected items into daily, weekly,
   monthly, and yearly documents under `digest/`. Each granularity is enabled
   independently and ends its period on a configured day (`run_on`: ISO
   weekday for weeks; week index, per-month day list, or `last` for months;
   month for years). Lower levels can be embedded or merged into the next
   level and optionally archived. Missed periods are generated on the next
   run; the current period is regenerated on every sync until it closes.
   Requires `first_seen_at` on item state and a `digests` state table. This
   is the first user-facing creation feature and needs no projects.
10. YAML configuration: `asterism.yaml` replaces `asterism.toml`, parsed
   with PyYAML through `safe_load` only. PyYAML becomes the project's single
   third-party dependency, justified because human-edited front matter in
   Phase 2 needs the same parser. Values are validated strictly after
   loading to counter implicit typing (month-day lists must be quoted
   strings), `init` writes YAML, and having both files present is an error.
   README and AGENTS.md drop the "no third-party dependencies" statement
   when this lands.

**Done when.**

- All adapters are incremental and idempotent: a second run with no source
  changes writes nothing.
- `doctor` reports a useful diagnosis for every source, including the exit
  code guidance for opencli.
- File and SQLite state backends behave identically under the test suite.
- Tests need no network, no real Notes library, no Chrome, and no opencli
  binary; every external process is a fake runner.
- One week of the user's real notes has been collected daily without manual
  fixes.

**Architecture at the end of Phase 1.**

```text
cli: init · doctor · sync [--commit] · missing · digest
        │
     config ──► registry ──► sources/
                              apple_notes (+ fragment splitter)
                              flomo (export)          each adapter calls
                              cubox                   normalize/ and returns
                              markdown                validated SourceItem
                              notion (token from env)
                              opencli (allowlist + mapping)
                                   │
                              SourceItem (schema 1: core · common · source_meta)
                                   │
                              pipeline ──► vault/notes/<source>/*.md  +  state/
                                   │
                              digest/ ──► vault/notes/<source>/digest/{daily,weekly,monthly,yearly}/   self-contained rollups
                                   │
                              optional git commit
horizontal: models · vault · normalize · state (file | sqlite) · logging without content
```

**Deliberately deferred.** Work-log sources (git history, coding session
transcripts, screenshots) are also collection, but they only matter once
content projects exist to attach them to. They arrive in Phase 3 through the
same adapter contract.

## Phase 2 — Picks and projects

**Status.** Done, except the Notion board (step 6 of
[the Phase 2 plan](phase-2.md)), which needs an integration token and a
database and which everything else works without. Used for real: three pieces
have come through it.

**Goal.** The pipeline has its core object, the content project, and a review
round that turns collected material into projects being made, with one
human decision.

**Scope.** `Project` model and `project.md` front matter; configurable
production stages (`project.stages`, see "Production stages") that decide
the project folder layout while the status machine stays fixed; the status
machine (`candidate → making → ready → published → retrospected`, plus
`dropped` for a piece set aside in `trash/`, see
[the state model](state-model.md)); `new`, `status`, `week`, `material`, `drop`, `restore`; a machine-maintained `projects/INDEX.md` table (date,
title, pillar, type, status, platforms) regenerated on every status change
as a browsing view, plus a generated `projects/projects.base` for Obsidian
Bases; an optional Notion board: a projection of the cards into a database
whose rows join projects by content id, used as a nicer surface for planning
and as a second place to edit the management fields. The vault owns every
field at all times, so the board is never a store: a run pushes the card's
values and `obsidian://open?vault=...&file=...` links to the row, reads back
whatever the person changed there, and reports rather than acts when the row,
the database or the token is gone. Deleting the board loses an input device
and nothing else; a vault with no board configured behaves exactly the same
minus that surface. Gates 1 and 3 may be completed either in Notion or in the
vault's own files, gate 2 stays in the editor; a row created by hand
scaffolds a project, and a project created from a digest creates a row;
`content.pillars` in `asterism.yaml` (key, name,
tag aliases for classification, brief template) and `content.types`; pillar is
front matter metadata and only shapes directories when `project.path`
includes `{pillar}`; brief
templates per content pillar; deterministic `enrich/` (exact and normalized
dedupe, rule-based classification from tags and folders, ranking by fragment
count, recency, and question density); `propose` writes `picks/<date>.md`,
the gate-1 sheet, listing everything that has no outcome yet under the
outcome a rule suggests, and `apply` records where each line ended up and
turns the `used` ones into projects. New state table: `assignments`; projects
themselves are files, not rows.

**Done when.** The user's current piece of content is tracked as a project
created from a review sheet, with the material it came from linked into the
brief. Unclassified material sits under `undecided` rather than being
guessed into a pillar.

**Architecture at the end of Phase 2.**

```text
cli: everything in Phase 1 + review · apply · new · status · week · material · drop · restore
        │
sources/ ──► vault/notes/<source>/origin/ ──► enrich/ (dedupe · rule classify · rank) ──► state.assignments
                                                                              │
                                   gates/review ──► vault/picks/<date>.md ◄── the person sorts material (gate 1)
                                   gates/apply   ──► projects/ (scaffold · state machine)
                                                          │
                                                     vault/projects/<project>/{project,brief}.md
new vault directories: projects/ · picks/ · settings/templates/brief-<name>.md
```

## Phase 3 — From a topic to a published piece

**Status.** The flow is complete and has been walked three times, from an
empty vault through to a recorded publication; see
[the Phase 3 plan](phase-3.md) for what each of those runs changed. Three parts
of the scope below are not built: the work-log adapters, the `assets.md`
manifest, and `deliver/blog_git`. Until the last of those exists, `publish`
records a publication rather than performing one.

**Goal.** A piece of content goes from a project being made to a published
blog post and ready-to-paste packages for the other platforms, using only commands
and a text editor.

**Scope.** Work-log adapters (git commits and diffs, coding session
transcripts, and a media adapter for screenshot, recording, photo, and export
directories that records metadata only) attached to projects by id and time
window; the per-project `assets.md` manifest with media roles; `compose/`: the material outline (`draft.md` skeleton with
brief sections as headings and the relevant quotes, commits, and errors placed
under each), coverage and citation checks, deterministic per-platform
transforms with checklists, publish packages; gates 2 and 3; `deliver/blog_git`
pushing to a preview branch and merging on confirmation; `check`, `adapt`,
`publish` commands.

**Done when.** One real piece has been published to the blog through the
pipeline and posted to at least one manual platform from its package, and the
material outline saved measurable writing time compared with the previous
piece.

**Architecture at the end of Phase 3.**

```text
cli: everything in Phase 2 + check · adapt · publish
        │
sources/notes/ + sources/worklog/ (git · coding sessions · screenshots) ──► vault/notes/ ──► enrich ──► gate 1 ──► projects
                                                                                                                │
                                                              gather (by project id and time window) ──► brief.md
                                                                                                                │
                                                    compose/skeleton ──► draft.md ◄── human writes prose
                                                                             │
                                                    compose/checks (coverage · citations · images) ──► gate 2  projects/<project>/check.md
                                                                             │
                                                    compose/adapt/<platform> (rules in vault/platforms/*.md) ──► exports/*.md + package
                                                                             │
                                                    gate 3  projects/<project>/release.md ──► deliver/blog_git ──► blog repository
                                                                                       other platforms ──► human pastes, link recorded
new state table: deliveries
```

## What is left, and why it is not a phase

Phases 4 and 5 used to stand here: an orchestrator that advanced every project
one step until a gate, a scheduler, and an `llm/` package of enhancers. Both
were dissolved by a later decision — **the agent lives outside Asterism and
drives it through the CLI** — which made most of what they contained redundant
rather than unbuilt.

| Was planned as | What happened to it |
|---|---|
| `run`, advancing every project to its next gate | The agent is the orchestrator. It reads `--json`, follows the skill, and stops at the gates because the gate commands refuse to move without a person's answer. |
| `llm/enhancers`: classify, brief, draft, adapt | The agent does these through the same commands a person uses. The pipeline still runs with no model at all, which was the point of keeping them optional. |
| `scheduler/` generating a launchd job | A plist or a cron line, not a package. It belongs in the documentation. |
| The retrospective document | A template in `settings/templates/`, not code. |
| `deliver/notion_mirror`, `deliver/nas_manifest` | Optional projections, built when they are wanted. |

What genuinely remains, in the order it is likely to matter:

1. **Threads in material that carries no structure.** Repeated headings find
   the threads in a work log; a folder of saved articles has none, so the sheet
   degrades silently to a flat list — no error, just no suggestion, in exactly
   the step that is hardest by hand. The signals left untried are deterministic:
   the folder an item was saved into, and the domain it came from.
2. **`deliver/blog_git`.** One `git push` for the one platform that has an
   interface. Every other platform is, and will remain, a human pasting from a
   package and a link recorded on the card.
3. **Work-log adapters and `assets.md`.** Git commits and coding sessions are
   the most direct material for technical writing; media needs a manifest
   before there is media to track.
4. **Feedback.** Metrics and comments seven days after publishing, questions in
   comments becoming new material. This one waits on evidence: nothing has been
   published yet, so there is nothing to measure and no way to tell whether the
   loop closes.

## Digests: one tree per source, aggregated by time

Digests roll collected items up by period inside the source's own directory,
which splits in two: `notes/<source>/origin/` holds what was collected and
`notes/<source>/digest/<level>/` holds the rollups over it. Every level holds its
whole period rather than pointing at the level below: a week contains the
week, a month contains the month. That is what makes archiving the lower
level safe, and what makes a digest worth reading on its own. They start in Phase 1 because they
need nothing but the notes mirror, and later phases attach to them: the
weekly digest carries gate 1 from Phase 2, projects gather material through
the daily digests from Phase 3, the monthly digest becomes the monthly
retrospective once a piece has been published, and an enricher may add a summary.

```yaml
digest:
  timezone: Asia/Shanghai
  after_sync: true
  excerpt_chars: 300
  day:
    enabled: true
  week:
    enabled: true
    run_on: 3                 # ISO weekday on which the period ends (1 = Monday)
    include_days: true
    archive_days: true        # after rolling up, archive daily digests using archive.mode
  month:
    enabled: true
    run_on: 4                 # end of the 4th seven-day block; or ["01-31", "02-28", …]; or last
    include_weeks: true
    archive_weeks: false
  year:
    enabled: false
    run_on: 12                # month whose last day ends the period
    include_months: true
  llm:                        # only when an enricher writes summaries
    summary: true             # extra <period>.summary.md
    placement: separate       # separate | inline
```

Semantics:

- A period ends on its `run_on` day and starts the day after the previous
  one. Labels use the ISO week or calendar month of the end day, and the
  front matter records the exact `period_start` and `period_end`.
- Levels are independent. With weeks disabled, months aggregate days
  directly.
- Items belong to the day of their `created_at`, or of `first_seen_at` when
  the source gives no time. Each daily digest lists items first seen that day
  and, separately, items updated that day.
- Lifecycle state is fixed and machine-owned: `open → closed → rolled →
  archived`. Digests carry no review state; see
  [the state model](state-model.md).
- Missed periods are generated on the next run; the open period is rebuilt
  on every sync; closed periods change only with `--regenerate`.
- `include_days`, `include_weeks` and `include_months` decide whether a level
  carries the content of the level below; with them off it keeps only its
  front matter counts.
- Archiving of lower levels is a boolean per level and only acts when
  `archive.enabled` is true. Because every level is rendered from state and
  already holds its whole period, moving or copying the lower documents away
  never takes content out of the higher ones.

## Production stages

The steps of production, and therefore the project folder layout, are
configuration. Asterism hard-codes neither the directories nor their numbers;
it only needs a few bindings that point at stage keys. The status machine and
the gates are separate from stages and stay fixed.

```yaml
project:
  id_format: "{year}-{seq:03d}"
  path: "{year}/{date}-{slug}"     # creation date; alternatives: {pillar}/{date}-{slug}; the id stays in front matter
  layout: flat                 # flat: Markdown at the project root, media in stage dirs; staged: everything in stage dirs
  numbered: true               # directory names get a position prefix (01-, 02-, …); `dir:` overrides
  stages:                      # default when omitted; add, remove, or reorder freely
    - { key: brief,     artifacts: [project.md, brief.md] }
    - { key: research,  artifacts: [assets.md] }
    - { key: originals, media: [photo, video, screen-recording] }
    - { key: project,   media: [editing] }
    - { key: export,    media_per_platform: true }
    - { key: cover,     media: [cover] }
    - { key: archive,   artifacts: [draft.md, exports/, review.md] }
  bindings:                    # the only stage knowledge the machine relies on
    unassigned_media: originals
    platform_exports: export
    covers: cover
```

Rules:

- State records stage keys, never directory names, so renumbering or
  renaming stages does not orphan existing projects; `asterism stages
  migrate --dry-run` shows the renames and `--execute` applies them.
- `artifacts` decide where Markdown is materialized when a project is
  archived; with `layout: flat` the working copy keeps Markdown at the
  project root for Obsidian.
- Stages without a binding are for people only; the machine never writes
  into them.
- Validation: bindings must reference existing keys, `platform_exports`
  must point at a `media_per_platform` stage, and every directory and
  artifact name must be a safe relative path inside the project.

## Storage roots and layout

The vault is a single directory today. The target design keeps one vault for
text, Git, and state, and adds separately configurable roots for large files,
because Git repositories, SQLite databases, and fsync-based atomic writes do
not belong on a network share while media does.

```yaml
# the directory holding asterism.yaml is the vault: text, Git, state; local disk recommended
storage:
  media_root: /Volumes/Content            # optional; large files, may be a NAS mount;
                                          # default: git-ignored subdirectories inside the vault
  inbox:
    - ~/ContentVault/inbox
    - ~/Library/Mobile Documents/com~apple~CloudDocs/Asterism Inbox

archive:
  enabled: false                          # master switch; when off, nothing is moved or copied and archive commands only write plans
  root: /Volumes/Archive/Content          # may be a NAS mount; default <vault>/archive/, git-ignored
  mode: copy                              # copy | move, applies to digests only; project folders are always copied
  on_publish: false                       # write an archive plan when a project is published
  auto_execute: false                     # otherwise `asterism archive <ID> --execute`

state:
  backend: sqlite
  # state_dir: ~/Library/Application Support/Asterism/ContentVault   # keep state local when the vault is remote
```

Every root uses the same relative project path (`<project>` below, by default
`<year>/<date>-<slug>` from `project.path`), so a project
differs only by prefix across the vault, the media root, and the archive
root. `archive.enabled` is a master switch: when it is off no phase moves
or copies files, and per-level digest archiving flags are ignored. Generated paths are validated against their own root, and a command
that touches media stops when `media_root` is not mounted rather than writing
into an empty local directory.

Layout by phase, cumulative:

```text
Phase 1   <vault>/asterism.yaml · .asterism/state/ · .gitignore
          <vault>/notes/<source>/origin/<the source's own hierarchy>/<title>.md
          <vault>/notes/<source>/digest/{daily,weekly,monthly,yearly}/<year>/<label>.md
          <vault>/archive/notes/… or <archive.root>/notes/… for rolled-up lower levels when archiving is on
Phase 2 + <vault>/picks/<date>.md          one round of choosing; gate 1 is the project card
          <vault>/projects/INDEX.md · <vault>/projects/projects.base
          <vault>/trash/<year>/<project>/   projects set aside
          <vault>/projects/<year>/<date>-<title>/{project,brief}.md
          <vault>/settings/templates/{project,brief-<name>}.md
Phase 3 + <vault>/notes/worklog/{git,sessions,media}/
          <vault>/projects/<year>/<date>-<slug>/{draft,assets}.md · exports/<platform>.md
          <vault>/projects/<year>/<date>-<slug>/{check,release}.md   gates 2 and 3
          <vault>/settings/platforms/<platform>.md
          <media_root>/<year>/<date>-<slug>/<stage dirs from project.stages; default 03-originals/{photo,video,screen-recording}, 04-project, 05-export/<platform>, 06-cover>/
          <inbox>/ (one or more)
Later  + <vault>/projects/<year>/<date>-<slug>/07-review.md
          <vault>/notes/feedback/<platform>/
          <archive.root>/<year>/<date>-<slug>/  text and media merged into the full stage structure (default 01–07); copy only
Enriched  no new directories; enhanced files are marked in front matter; optional <period>.summary.md beside each digest; cache in <vault>/.asterism/llm-cache/
```

When `media_root` is on the NAS, Obsidian previews work through a symlink
`<vault>/media -> media_root` that Git ignores; without the symlink,
`assets.md` falls back to `file://` links.

## Photos and video

Media files live inside the project folder next to the text, in
subdirectories that Git ignores. The repository holds only Markdown; the
vault directory on disk holds everything, and Obsidian can embed and play the
files in place.

```text
ContentVault/projects/2026/2026-09-21-ai-desk-dashboard/
  project.md · brief.md · draft.md · assets.md · review.md · exports/*.md    tracked by Git
  <stage dirs from project.stages>                                         ignored by Git; defaults:
  03-originals/{photo,video,screen-recording}/                             originals
  04-project/                                                              editing projects
  05-export/{blog,zhihu,xiaohongshu,douyin}/                               finished pieces
  06-cover/                                                                covers
ContentVault/inbox/                                                        ignored: unassigned captures
```

Ingress:

- Mac screenshots and recordings land in `inbox/` after pointing the system
  capture location there once.
- iPhone and iPad photos reach `inbox/` through a Shortcut that saves to an
  iCloud Drive folder configured as a second inbox, or through AirDrop. The
  Photos library itself is never read.
- Editor exports are saved directly into the project's `05-export/`.
- `asterism attach <ID> <file>` or the time-window `gather` moves files from
  `inbox/` into the project. Files outside `inbox/` and project folders are
  never moved.

Use and archive:

```text
sources/worklog/media  ──►  notes/worklog/media/<sha256>.md   machine index: hash, path, captured time
                            projects/<project>/assets.md       human view: ![[03-originals/photo/before.jpg]] with a role
                                   ├─► compose/adapt/xhs      images by role
                                   ├─► compose/adapt/douyin   shot list against recorded clips
                                   └─► deliver/blog_git       copies referenced images into the blog repository, resized with `sips`
Later: deliver/nas_manifest copies the whole project folder to archive.root when archiving is enabled and executed; never deletes; flags originals for cold backup
```

Rules:

- Identity is the file's sha256, so a move only updates the recorded path.
- Roles (cover, before, after, step, demo, b-roll, final) are set by people
  in `assets.md` or by filename convention; the machine only reads them.
- The iPad sees text through a Git client but not media; media is viewed on
  the NAS or in iCloud Drive.
- Remote images from flomo or Cubox stay URLs in `source_meta`.
- Editing, photo selection, and uploading stay outside the pipeline.

### Rating

`assets.md` has one human field for priority: `rating`. Empty means not yet
reviewed, `0` means rejected, `1`–`5` is priority within a role. The machine
adds `used_in` after publishing and never asks a person to fill it.

```markdown
| file | role | rating | note | used_in |
|---|---|---|---|---|
| 03-originals/photo/before-01.jpg | before | 4 | old layout | blog, xhs |
| 03-originals/photo/before-02.jpg | before | 0 | shaky | |
| 03-originals/video/session-01.mov | demo | 5 | error at 12:40 | douyin |
```

Rules:

- Generation takes the highest rated file per role, then unrated files, and
  never a `0`.
- Archiving keeps files rated at or above `archive.media.min_rating`, keeps
  every file with a non-empty `used_in` regardless of rating, flags 5-star
  and used files for cold backup, and lists `0` files for manual deletion.
- A red Finder tag on a file imports as `0`; everything else is rated by
  editing `assets.md` in Obsidian, where the images are shown inline.
- Mode B may suggest a rating and a note; the person keeps the last word.

```yaml
archive:
  media:
    min_rating: 1        # 0 archives unrated files too
```

### Media workflow, with and without a model

Efficiency comes from giving footage structure while shooting: shots follow
the brief's shot list, files follow role naming, and the creator talks while
working. The same six steps run either way; a model adds a layer on each.

| Step | Deterministic | A model adds |
|---|---|---|
| Plan | Shot list from the pillar's brief template with suggested filename prefixes | Suggests which shots matter most based on past projects |
| Land | Captures move from `inbox/` into the project; roles prefilled from filename conventions | A vision model assigns roles, writes descriptions and alt text, flags near-duplicate shots |
| Check | Missing shots reported by comparing the shot list with `assets.md` | Checks image content against the shot list, not only filenames |
| Draft | Material outline embeds the images and clips under each brief section | Narration recorded while working is transcribed and placed under the brief sections, each sentence cited to a clip and time |
| Adapt | Blog images copied and resized; Xiaohongshu image list by role with crop hints; Douyin script beside a shot table; frame extraction and cut lists when `ffmpeg` is installed | Coding-session timestamps aligned with the recording timeline produce an edit marker table; captions, subtitles, cover text candidates generated |
| Publish and review | Links and public image URLs written back to `assets.md`; NAS plan | Comments about specific shots attached to the matching `assets.md` lines to inform the next plan |

Optional external tools, detected by `doctor` and never Python dependencies:
`ffmpeg` for frames, clips, and subtitle files (no model needed), and a local
whisper-class transcriber for narration. Without them the pipeline
falls back to time-point lists and hand-written narration.

## Where each tool lands

| Tool | Role | Phase | Asterism does | Asterism does not |
|---|---|---|---|---|
| Apple Notes, flomo, Cubox | Capture | 1 | Collect incrementally | Write back |
| Obsidian | Production and storage of Markdown; existing knowledge base as a source | 1 (source), 2 onward (editor) | Read an existing vault through the Markdown adapter; keep `projects/` and `templates/` editable in Obsidian; show read-only management fields and generated views | Manage status or schedule; that is Notion's job |
| Notion | Existing pages as a source; the management board | 1 (source), 2 (board) | Read pages; own status, schedule, priority, platforms, promise, and notes for every project; receive published links, metrics, and draft links from the vault; allow gates 1 and 3 and project creation from a row | Store drafts, assets, or any content; share a field with the vault |
| opencli | Personal bookmarks as a source; metrics and comments as feedback | 1 (source), 4 (feedback) | Run allowlisted read-only commands | Publish through browser automation by default |
| Personal blog | Authoritative version, search entry, long-term asset | 3 (publish), 4 (feedback) | Fullest export with front matter, code, and an update log; push to a preview branch and merge on gate 3; the only fully automated publication | Deploy (the blog repository does); collect search metrics through opencli |
| Zhihu | Answer one explicit question | 3, 4 | Question-first rewrite template; publish package; votes and comments through opencli; search demand as a ranking signal in Phase 2 | Post automatically |
| Xiaohongshu | Discovery and saves | 3, 4 | Title length check, step list, no code blocks, topics from tags, image slots; publish package; views, likes, saves, and comments through opencli | Post through browser automation by default |
| Douyin | Visual proof and persona | 3, 4 | Spoken script with a three-second hook, shot list from the brief, caption and topics; link recording | Edit or upload video; creator metrics are entered by hand until an adapter exists |
| sspai | Editorial experience article | 3 | Structure template stressing real usage and personal judgment; publish package | Post automatically; no metrics adapter, entered by hand or skipped |
| FlowUs | Material delivery for Chinese readers | 3 | Extract lists, parameter tables, and steps into a paste-ready page | Post automatically |
| Synology NAS | Main archive by content id | 4 | Generate the directory name and `assets.md` manifest | Move media files |
| Baidu Netdisk | External delivery and cold backup | 4 | Flag irreplaceable originals and finished pieces in the manifest | Upload |
| iCloud | Device sync and photo ingress | 3 | Read synced screenshot, recording, and photo directories as work logs | Host the vault; the vault is a local Git repository, and iPad access goes through a Git client or Obsidian Git |
| MacBook | Main production machine | all | Run every command, the launchd scheduler, Git, Chrome with the opencli extension, and any LLM call | — |
| iPad | Reading, annotation, review, teleprompter | 2 onward | Operate the three gates through a Git client or Obsidian Git; read the Douyin script export as a prompter | Run commands |
| iPhone | Capture and shooting | 1 (capture), 3 (material) | Feed Apple Notes, flomo, and Cubox; photos and videos reach the work-log source through iCloud | Run commands; progress is viewed on the Notion board |

## Evolution notes

- **Phases 4 and 5 were removed rather than postponed.** They described an
  orchestrator and a package of language-model enhancers. Deciding that the
  agent lives outside Asterism and drives it through the CLI made both
  redundant: the agent orchestrates, and it enhances through the same commands
  a person uses. What was left of them is listed above as work, not as a phase.
- **The remaining phase titles were rewritten to match what exists.** Phase 2
  was called "Content projects, sorting, and confirming a topic" and Phase 3
  "Work logs, composition, and delivery" — three things of which only the
  middle one was built. A phase named for an old plan makes the plan look
  finished when it is not.
- Collection is finished in Phase 1 and is only extended by new adapters
  afterwards; its contract (`Source.collect() -> list[SourceItem]`) does not
  change.
- Templates, platform rules, and classification keywords live in the vault
  as Markdown and YAML from Phase 2 on, so the first pieces of content can
  reshape them without code changes.
- Each phase ends with this document, `docs/sources.md`, and the README
  updated to describe what exists, not what is planned.
