# Asterism ⁂

Turn scattered notes into publishable content.

Asterism is a local-first, Git-native content production pipeline for a single
creator. It collects notes and captures from the tools you already use,
normalizes them into portable Markdown, rolls them up into daily, weekly, and
monthly digests, and keeps local state so repeated runs only rewrite changed
content. Later phases turn those digests into content projects, drafts,
platform versions, and published pieces, with a person involved only at a few
decision gates and with an LLM as an optional accelerator, never a dependency.
See [the roadmap](docs/roadmap.md) for the destination and the current phase.

The code repository and the private content vault are intentionally separate:

```text
asterism/          public application source
my-notes-vault/    private Markdown, state, and logs
```

The repository also contains a `notes/` skeleton that shows
the output layout and can be used for local testing. Collected content inside
those source directories is ignored by Git; only their README files are
tracked.

## Current scope

Phase 1, collection, provides:

- Apple Notes collection through macOS's built-in `osascript`, with daily-log
  notes split into one item per time-stamped line;
- flomo HTML/ZIP export collection without account credentials;
- Cubox collection through the official `cubox-cli` JSON interface;
- local Markdown directory collection, including Obsidian vaults;
- scoped Notion collection through the official Markdown API;
- opencli collections: allowlisted read-only commands of the community
  [opencli](https://github.com/jackwener/opencli) tool, mapped to fields by
  configuration;
- a source-neutral item model with provenance (`origin`), optional `url`,
  `author`, parents, tags, and source metadata, rendered as versioned front
  matter;
- daily, weekly, monthly, and yearly digests, each level independently
  configurable, with optional archiving of rolled-up documents;
- file or SQLite state backends behind one interface, with migrations;
- atomic file writes, deterministic paths, dry-run and incremental sync,
  per-source error isolation, and an opt-in Git commit after a successful sync;
- `missing` to review items a source stopped returning; nothing is deleted.

Phase 2, content projects, adds:

- a content project per piece: a folder with a `project.md` card in YAML front
  matter that Obsidian's Properties panel edits, and a `brief.md` from a
  per-pillar template;
- `new`, `status`, and `week`, plus a regenerated `content/INDEX.md` and a
  seeded Obsidian Bases view;
- the first decision gate: `propose` lists the week's undecided items as
  checkboxes in that week's digest, and `apply` turns the ticked ones into
  projects, recording the decision so they are not asked about again.

Drafts, publishing, and optional LLM enhancement come in later phases.

Every project field lives in its card in the vault, so the pipeline runs
complete without any external service. A Notion board, a NAS, and a language
model are projections and accelerators that can be added or removed at any
time; losing one loses convenience, never content or state.

## Requirements

- macOS with Apple Notes;
- Python 3.11 or newer;
- permission for the invoking terminal or application to control Notes.

Cubox collection additionally requires the official `cubox-cli` to be installed
and authenticated locally. Asterism never accepts its token as a command-line
argument and does not inspect its credential file.

Installing the Cubox or flomo desktop application alone does not expose a stable,
documented read interface. Cubox sync uses the separate official CLI; flomo sync
currently uses an official HTML/ZIP export. Asterism does not inspect either
application's private local database.

The runtime's only third-party dependency is PyYAML, used to read the vault
configuration through `yaml.safe_load`.

## Development setup

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m unittest discover -s tests
```

## Quick start

Create a private content vault outside this repository:

```bash
asterism init ~/Documents/AsterismVault
```

The command interactively asks whether state should be stored as a readable
JSON file or a local SQLite database. It creates this layout:

```text
AsterismVault/
  asterism.yaml
  notes/
  state/
  logs/
```

Check the configuration and macOS integration:

```bash
asterism doctor --vault ~/Documents/AsterismVault
```

Preview a synchronization, then write the files. Without `--source`, every
configured source runs; one source failing is reported and does not stop the
others. Digests are generated after a successful sync, and `--commit` records
a Git snapshot when the vault is a repository (nothing is ever pushed):

```bash
asterism sync --vault ~/Documents/AsterismVault --dry-run
asterism sync --vault ~/Documents/AsterismVault
asterism sync --vault ~/Documents/AsterismVault --commit
```

Select sources explicitly with `--source`, which may repeat:

```bash
# Apple Notes
asterism sync --vault ~/Documents/AsterismVault --source apple-notes

# flomo official HTML or ZIP export
asterism sync --vault ~/Documents/AsterismVault --source flomo

# Cubox through the authenticated official CLI
asterism sync --vault ~/Documents/AsterismVault --source cubox

# Any local Markdown directory, including Obsidian
asterism sync --vault ~/Documents/AsterismVault --source markdown

# Notion pages within the configured scope
asterism sync --vault ~/Documents/AsterismVault --source notion

# One opencli collection declared in asterism.yaml
asterism sync --vault ~/Documents/AsterismVault --source opencli:twitter-bookmarks
```

For Apple Notes daily logs, name the folders whose notes should be split into
time-stamped fragments and the timezone those times are written in:

```yaml
sources:
  apple_notes:
    daily_log_folders:
      - Daily Log
    timezone: Asia/Shanghai
```

For flomo, configure the exported file in the vault's `asterism.yaml`:

```yaml
sources:
  flomo:
    export_path: /absolute/path/to/flomo-export.zip
```

For Cubox, install and authenticate the official CLI in your own terminal, then
verify the integration without exposing credentials:

```bash
cubox-cli auth status
asterism doctor --vault ~/Documents/AsterismVault --source cubox
```

For a Markdown or Obsidian source, configure one or more input roots outside the
Asterism vault:

```yaml
sources:
  markdown:
    roots:
      - /absolute/path/to/ObsidianVault
```

For Notion, create a read-content integration, share only the desired root pages
or data sources with it, and configure their UUIDs. The token is read only from
the environment and is never stored in `asterism.yaml`:

```yaml
sources:
  notion:
    root_page_ids:
      - 00000000-0000-0000-0000-000000000000
    data_source_ids: []
    discover_all: false
```

```bash
export ASTERISM_NOTION_TOKEN='set-this-in-your-shell-or-secret-manager'
asterism doctor --vault ~/Documents/AsterismVault --source notion
asterism sync --vault ~/Documents/AsterismVault --source notion
```

`discover_all: true` means every page visible to that integration, not every
page in the workspace regardless of permissions. Explicit scope is recommended:
it limits accidental collection, makes the result predictable, and reduces API
work.

For opencli, install the tool yourself (`npm install -g @jackwener/opencli`)
and declare which read-only commands Asterism may run and how their columns
map to fields. Asterism validates each collection against `opencli list`,
refuses write commands, and treats the meaning of the columns as the
responsibility of opencli's community adapters and your mapping:

```yaml
sources:
  opencli:
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

```bash
asterism doctor --vault ~/Documents/AsterismVault --source opencli:twitter-bookmarks
```

Browser-backed commands need Chrome with the OpenCLI extension and a login on
the site; exit code 69 or 77 from opencli is reported with that guidance.

## Digests

After each sync Asterism rolls collected items into `digest/`: one document
per day, week, month, and (if enabled) year. Each level is independent and
ends its period on a configured day; the open period is rebuilt on every
sync, closed periods are generated once and can be re-done with
`asterism digest --regenerate 2026-W39`. Higher levels embed the lower
documents with Obsidian links, or merge their text when the lower level is
archived by moving. `review_status` in a digest's front matter is yours to
edit; the machine never changes it.

```yaml
digest:
  timezone: Asia/Shanghai
  week: { run_on: 3, include_days: true, archive_days: false }   # periods end on Wednesday
  month: { run_on: last }
  year: { enabled: false }
```

```bash
asterism digest --vault ~/Documents/AsterismVault
asterism missing --vault ~/Documents/AsterismVault
```

`archive.enabled` is a master switch, off by default; with it on, rolled-up
digests are copied or moved below `archive.root`, which may be a NAS mount.
`doctor` reports the vault's storage, warns when the vault sits on a network
filesystem, and shows which archive switches are masked.

## Content projects

A project is a folder under `content/` holding the card and the brief for one
piece. The weekly session is one file: open the week's digest, tick what is
worth making, and apply.

```bash
asterism propose --vault ~/Documents/AsterismVault            # list this week's undecided items
# tick the lines you want in the digest, then
asterism apply --vault ~/Documents/AsterismVault              # each tick becomes a project
asterism status --vault ~/Documents/AsterismVault --pillar desk-setup
asterism week --vault ~/Documents/AsterismVault               # what is in flight and what waits
asterism new "Desk lighting" --vault ~/Documents/AsterismVault --pillar desk-setup --type tutorial
```

Pillars decide how fragments are classified and which brief template a new
project starts from; a fragment matching no pillar is listed as unclassified
rather than guessed:

```yaml
content:
  pillars:
    - { key: vibe-coding, name: Vibe Coding, tags: [coding] }
    - { key: desk-setup, name: Desk Setup, tags: [desk] }
  types: [tutorial, review, makeover, opinion, checklist]
  platforms: [blog, zhihu, xiaohongshu, douyin, sspai, flowus]
project:
  path: "{year}/{date}-{title}"   # or "{pillar}/{date}-{title}"
```

Templates are seeded into the vault the first time they are used
(`templates/project.md`, `templates/brief-<pillar>.md`), so editing them
changes every later project. Status is yours: the machine sets it when it
creates a project and reads it afterwards, so moving a piece forward is an
edit in Obsidian.

`--vault` determines the output root. With the command above, Apple Notes are
written to:

```text
~/Documents/AsterismVault/notes/apple-notes/
```

Every source controls its own safe directory name, producing paths such as
`notes/flomo/`, `notes/cubox/`, `notes/markdown/`, `notes/notion/`, and
`notes/opencli-<collection>/`. Below that, the source's own hierarchy is
mirrored: Apple Notes folders, Cubox folders, Markdown directories, and Notion
parent pages become subdirectories, and a note that moves in its source moves
on disk too. Asterism does not choose the project repository
as the vault automatically.

For deliberate local development, this repository includes a credential-free
[`asterism.yaml`](asterism.yaml), so the repository itself can be selected:

```bash
.venv/bin/python -m asterism.cli doctor --vault .
.venv/bin/python -m asterism.cli sync --vault . --dry-run
# Remove --dry-run only when you intend to write private test output to notes/.
```

The generated notes, state, and logs are ignored by Git. The source-specific
README files remain tracked.

To avoid an interactive prompt during initialization:

```bash
asterism init ~/Documents/AsterismVault --state-backend sqlite
```

## Front matter and upgrades

Every note starts with a fixed-order front matter block versioned by
`schema`. See [the source support plan](docs/sources.md) for the fields.
Upgrading to a new schema rewrites every note once on the next sync; the
file names and state keys do not change.

## Safety model

Asterism treats note content and paths as untrusted input. File names are the
cleaned title (`Week6 26.09.15.md`, `Weekly (2).md` on a collision, fixed once
recorded), directory names are the cleaned source hierarchy, generated paths
are kept inside the configured vault,
SQLite queries are parameterized, and Markdown is written atomically. The
collector never reads the private Notes database and never invokes a shell.

Locked notes that macOS does not expose are skipped by Notes itself. Asterism
does not attempt to bypass platform permissions.

## Roadmap

Asterism is being built in phases. The current phase makes collection reliable
and incremental; later phases add content projects, human decision gates,
composition, delivery, feedback, and optional LLM enhancement. See
[the roadmap](docs/roadmap.md) for the destination, the scope of each phase,
and what the architecture looks like at the end of each one.
