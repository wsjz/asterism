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
 (notes,      vault/notes/    dedupe,     vault/content/<project>/ drafts,     blog repo,
  work logs,                  classify,   state machine,        platform    publish
  feedback)                   rank        three human gates     versions    packages
                                                                    ▲
                                              feedback (metrics, comments) ┘
```

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
   mode B may only fill an empty one); add a
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
                              digest/ ──► vault/digest/{daily,weekly,monthly,yearly}/   periodic rollups, each level optional
                                   │
                              optional git commit
horizontal: models · vault · normalize · state (file | sqlite) · logging without content
```

**Deliberately deferred.** Work-log sources (git history, coding session
transcripts, screenshots) are also collection, but they only matter once
content projects exist to attach them to. They arrive in Phase 3 through the
same adapter contract.

## Phase 2 — Content projects and the first gate (current)

**Status.** Steps 1 to 5 of [the Phase 2 plan](phase-2.md) are implemented:
project cards, scaffolding, `new`, `status`, `week`, the index and Bases
views, assignments in state, rule-based classification, and gate 1 through
`propose` and `apply`. The Notion management board (step 6) is left until the
rest has been used for real.

**Goal.** The pipeline has its core object, the content project, and a weekly
review that turns collected fragments into approved projects with one human
decision.

**Scope.** `ContentProject` model and `project.md` front matter; configurable
production stages (`project.stages`, see "Production stages") that decide
the project folder layout while the status machine stays fixed; the status
machine (`candidate → approved → gathering → drafted → reviewed → adapted →
staged → published → retrospected → archived`); `new`, `status`, `week`; a machine-maintained `content/INDEX.md` table (date,
title, pillar, type, status, platforms) regenerated on every status change
as a browsing view, plus a generated `content/projects.base` for Obsidian
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
count, recency, and question density); `propose` appends a candidates
section with checkboxes to the weekly digest, which is the gate-1 file, and
`apply` reads the ticked decisions. New state tables:
`assignments`, `projects`, `gates`.

**Done when.** The user's current piece of content is tracked as a project
created from a weekly review file, with its fragments linked into the brief.
Unclassified fragments appear in the review file with empty checkboxes rather
than being guessed.

**Architecture at the end of Phase 2.**

```text
cli: everything in Phase 1 + propose · apply · new · status · week
        │
sources/ ──► vault/notes/ ──► enrich/ (dedupe · rule classify · rank) ──► state.assignments
                                                                              │
                                   gates/propose ──► vault/digest/weekly/<year>/<week>.md ◄── human ticks (gate 1)
                                   gates/apply   ──► projects/ (scaffold · state machine)
                                                          │
                                                     vault/content/<project>/{project,brief}.md
                                                     state.projects · state.gates
new vault directories: content/ · templates/brief-<pillar>.md (gate 1 lives in the weekly digest)
```

## Phase 3 — Work logs, composition, and delivery (mode A complete)

**Goal.** A piece of content goes from approved project to published blog
post and ready-to-paste packages for the other platforms, using only commands
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
                                                    compose/checks (coverage · citations · images) ──► gate 2  review/<ID>-draft.md
                                                                             │
                                                    compose/adapt/<platform> (rules in vault/platforms/*.md) ──► exports/*.md + package
                                                                             │
                                                    gate 3  review/<ID>-publish.md ──► deliver/blog_git ──► blog repository
                                                                                       other platforms ──► human pastes, link recorded
new state table: deliveries
```

## Phase 4 — Feedback and unattended progression

**Goal.** The pipeline advances by itself between gates and closes the loop
from published content back to new candidates.

**Scope.** `feedback/`: metrics and comments through opencli seven days after
publishing, `review.md` retrospective, comments with questions becoming new
fragments; `deliver/notion_mirror` (one-way status board) and
`deliver/nas_manifest`; `run` orchestrator that advances every project one
step until a gate; `scheduler/` generating a launchd job.

**Done when.** After publishing, the retrospective appears without any manual
step, and the next weekly review contains candidates that originated in
comments.

**Architecture at the end of Phase 4.**

```text
scheduler/ (launchd) ──► cli run ──► advance every project one step, stop at gates
        │
everything in Phase 3
        │
deliver/notion_mirror (one-way status board) · deliver/nas_manifest (asset list by id)
        │
feedback/: published + 7 days ──► opencli metrics and comments ──► vault/content/<project>/review.md
                                              │
                          questions in comments ──► SourceItem ──► vault/notes/feedback/ ──► enrich ──► next weekly digest
```

## Phase 5 — Optional LLM enhancement (mode B)

**Goal.** Users who configure a language model get drafts instead of
skeletons; users who do not notice no difference.

**Scope.** `llm/provider` over HTTP with the standard library, credentials from
environment variables only; enhancers for classification suggestions, brief
prefill, draft prose from the material outline with citations, platform
rewrites, and comment summaries; `[automation.llm]` switches, all off by
default; a fake provider for tests; `doctor` reports the active mode.

**Done when.** The same project produces a full first draft with the switch
on and the material outline with it off, and every generated factual sentence
cites a `SourceItem`.

**Architecture at the end of Phase 5.**

```text
config [automation.llm] = false (default) | true
        │
llm/provider (standard-library HTTP, key from environment only)
llm/enhancers: classify · brief · draft · adapt · review
        │  input:  the deterministic artifact from compose, enrich, or feedback
        │  output: an enhanced version at the same path, front matter marks enhanced_by
        │  never part of the state machine; when off or failing, the original stands
everything in Phase 4 unchanged
```

## Digests: aggregation by time granularity

Digests roll collected items up by period. They start in Phase 1 because they
need nothing but the notes mirror, and later phases attach to them: the
weekly digest carries gate 1 from Phase 2, projects gather material through
the daily digests from Phase 3, the monthly digest becomes the monthly
retrospective in Phase 4, and mode B adds an optional summary in Phase 5.

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
  llm:                        # mode B only
    summary: true             # extra <period>.summary.md
    placement: separate       # separate | inline
  review_status:              # user-defined; the machine never changes it
    values: [unread, reviewed, promoted]
    default: unread
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
  archived`. `review_status` is a separate, user-defined field.
- Missed periods are generated on the next run; the open period is rebuilt
  on every sync; closed periods change only with `--regenerate`.
- Archiving of lower levels is a boolean per level and only acts when
  `archive.enabled` is true. With `archive.mode: copy` or no archiving,
  the higher level embeds the lower documents (`![[digest/daily/…]]`); with
  `move`, it merges their content because the files leave their place.

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
  on_publish: false                       # Phase 4: write an archive plan when a project is published
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
Phase 1   <vault>/asterism.yaml · notes/<source>/*.md · state/ · logs/ · .gitignore
          <vault>/digest/daily/<year>/<date>.md · weekly/<year>/<year>-W<week>.md · monthly/<year>/<year>-<month>.md · yearly/<year>.md
          <vault>/archive/digest/… or <archive.root>/digest/… for rolled-up lower levels when archiving is on
Phase 2 + (gate 1 is a candidates section in the weekly digest)
          <vault>/content/INDEX.md · <vault>/content/projects.base
          <vault>/content/<year>/<date>-<slug>/{project,brief}.md
          <vault>/templates/{project,brief-<pillar>}.md
Phase 3 + <vault>/notes/worklog/{git,sessions,media}/
          <vault>/content/<year>/<date>-<slug>/{draft,assets}.md · exports/<platform>.md
          <vault>/review/<ID>-{draft,publish}.md
          <vault>/platforms/<platform>.md
          <media_root>/<year>/<date>-<slug>/<stage dirs from project.stages; default 03-originals/{photo,video,screen-recording}, 04-project, 05-export/<platform>, 06-cover>/
          <inbox>/ (one or more)
Phase 4 + <vault>/content/<year>/<date>-<slug>/review.md
          <vault>/notes/feedback/<platform>/
          <archive.root>/<year>/<date>-<slug>/  text and media merged into the full stage structure (default 01–07); copy only
Phase 5   no new directories; enhanced files are marked in front matter; optional <period>.summary.md beside each digest; cache in <vault>/state/llm-cache/
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
ContentVault/content/2026/2026-09-21-ai-desk-dashboard/
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
                            content/<project>/assets.md       human view: ![[03-originals/photo/before.jpg]] with a role
                                   ├─► compose/adapt/xhs      images by role
                                   ├─► compose/adapt/douyin   shot list against recorded clips
                                   └─► deliver/blog_git       copies referenced images into the blog repository, resized with `sips`
Phase 4: deliver/nas_manifest copies the whole project folder to archive.root when archiving is enabled and executed; never deletes; flags originals for cold backup
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

### Media workflow in mode A and mode B

Efficiency comes from giving footage structure while shooting: shots follow
the brief's shot list, files follow role naming, and the creator talks while
working. The same six steps run in both modes; mode B adds a layer on each.

| Step | Mode A (deterministic) | Mode B adds |
|---|---|---|
| Plan | Shot list from the pillar's brief template with suggested filename prefixes | Suggests which shots matter most based on past projects |
| Land | Captures move from `inbox/` into the project; roles prefilled from filename conventions | A vision model assigns roles, writes descriptions and alt text, flags near-duplicate shots |
| Check | Missing shots reported by comparing the shot list with `assets.md` | Checks image content against the shot list, not only filenames |
| Draft | Material outline embeds the images and clips under each brief section | Narration recorded while working is transcribed and placed under the brief sections, each sentence cited to a clip and time |
| Adapt | Blog images copied and resized; Xiaohongshu image list by role with crop hints; Douyin script beside a shot table; frame extraction and cut lists when `ffmpeg` is installed | Coding-session timestamps aligned with the recording timeline produce an edit marker table; captions, subtitles, cover text candidates generated |
| Publish and review | Links and public image URLs written back to `assets.md`; NAS plan | Comments about specific shots attached to the matching `assets.md` lines to inform the next plan |

Optional external tools, detected by `doctor` and never Python dependencies:
`ffmpeg` for frames, clips, and subtitle files (usable in mode A), and a local
whisper-class transcriber for narration (mode B). Without them the pipeline
falls back to time-point lists and hand-written narration.

## Where each tool lands

| Tool | Role | Phase | Asterism does | Asterism does not |
|---|---|---|---|---|
| Apple Notes, flomo, Cubox | Capture | 1 | Collect incrementally | Write back |
| Obsidian | Production and storage of Markdown; existing knowledge base as a source | 1 (source), 2 onward (editor) | Read an existing vault through the Markdown adapter; keep `content/` and `templates/` editable in Obsidian; show read-only management fields and generated views | Manage status or schedule; that is Notion's job |
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

- Collection is finished in Phase 1 and is only extended by new adapters
  afterwards; its contract (`Source.collect() -> list[SourceItem]`) does not
  change.
- Templates, platform rules, and classification keywords live in the vault
  as Markdown and YAML from Phase 2 on, so the first pieces of content can
  reshape them without code changes.
- Each phase ends with this document, `docs/sources.md`, and the README
  updated to describe what exists, not what is planned.
