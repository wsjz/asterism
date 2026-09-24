# Asterism ⁂

**Turn scattered notes into published pieces.**

You collect more than you write. Ideas land in Apple Notes, articles pile up in
Cubox, fragments accumulate in flomo — and by the time you sit down to write,
finding the one thread running through three weeks of them is harder than the
writing itself.

Asterism does that part. It gathers everything you collected into one place,
shows you which notes keep circling the same subject, and turns the one you
choose into a piece — carrying its material with it, all the way to a draft and
a version per platform.

It never writes for you, never deletes anything, and never publishes without
you saying so. Everything it makes is Markdown in a folder you own, which
Obsidian opens as is.

## A round

Three folders, in the order you meet them:

```text
notes/       everything collected, one file per item, mirrored and never edited by hand
picks/       one sheet per round: what you have not decided about yet
projects/    one folder per piece, from a candidate topic to a recorded publication
```

A round takes a few minutes and looks like this:

1. **`asterism sync`** pulls in whatever is new.
2. **`asterism propose`** writes `picks/<date>.md`. Notes that keep repeating
   the same heading are already grouped into a thread with a count — that is
   usually where the piece is.
3. **You open the sheet** and move each line under what should happen to it:
   `used`, `later`, `reference`, `dropped`. Under `used`, gather the lines of
   one piece beneath a heading you write. That heading is the piece.
4. **`asterism apply`** turns each heading into a project, carrying its notes.
5. From there the piece has its own folder, numbered in the order you work:
   `01-project` `02-brief` `03-draft` `04-check` `05-exports` `06-release`.

You are asked to decide exactly three times: what the piece will be, whether
the draft is good enough, and whether it goes out. Nothing moves past those
without you.

## Quick start

### The first ten minutes

With a few notes exported from one tool, this goes from nothing to a project
you can start writing in:

```bash
asterism init ~/Vault --state-backend file          # a private vault, made a Git repository
# point one source at your notes in ~/Vault/asterism.yaml, for example
#   sources: { markdown: { roots: [/path/to/your/notes] } }
asterism sync --vault ~/Vault                       # notes/<source>/origin/, plus digests
asterism propose --vault ~/Vault --now              # picks/<date>.md, today's notes included
# in the sheet, move the lines of one piece under `## II. used`, beneath a
# `### topic` heading of your own, then
asterism apply --vault ~/Vault                      # the topic becomes a candidate project
asterism confirm <id> --vault ~/Vault --angle 1     # gate 1: this is the piece
asterism draft <id> --vault ~/Vault                 # 03-draft.md, its sections from the brief's outline
```

Without `--now`, `propose` offers only periods that have ended, which is the
right rhythm once you sort every few days; the first day, it would offer
nothing.

## Connecting your notes

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
  .asterism/state/     bookkeeping; a dot keeps it out of Obsidian's file tree
```

It is also made a Git repository, unless the folder is already inside one, so
the writing has a history from the first day. Nothing is ever pushed. The rest
of the top level appears only once there is something in it: `projects/` and
`picks/` with the first round of sorting, `settings/templates/` and
`settings/platforms/` with the first project, `trash/` when a project is set
aside.

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

## Projects, pillars and platforms

A project is a folder under `projects/` holding the card and the brief for one
piece. The session is one file: `propose` writes a sheet of what has no outcome
yet, you move each line under the outcome it deserves, and `apply` records
them.

```bash
asterism propose --vault ~/Documents/AsterismVault             # write picks/<date>.md
asterism propose --vault ~/Documents/AsterismVault --now       # include what was collected today
# move lines under used / later / reference / dropped; under used, gather the
# lines of one piece beneath a `### topic` heading, then
asterism apply --vault ~/Documents/AsterismVault              # each topic becomes one project
asterism status --vault ~/Documents/AsterismVault --pillar desk-setup
asterism week --vault ~/Documents/AsterismVault               # what is in flight and what waits
asterism new "Desk lighting" --vault ~/Documents/AsterismVault --pillar desk-setup --type tutorial
```

Pillars decide how collected material is classified and which brief template
a new project starts from; material matching no pillar carries no pillar
rather than a guessed one. Write each pillar's aliases in the language the
material uses — they are matched against tags, folder names and the topic
headings you write, never against a translation of them:

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

A piece you decide not to finish is dropped: `asterism drop <id>` moves its
folder to `trash/` with nothing deleted, and `asterism restore <id>` brings it
back as a candidate. The five state machines the pipeline runs on are defined
in [the state model](docs/state-model.md).

Templates are seeded into the vault the first time they are used
(`settings/templates/project.md`, `settings/templates/brief-<name>.md`), so editing them
changes every later project. Status is yours: the machine sets it when it
creates a project and reads it afterwards, so moving a piece forward is an
edit in Obsidian.

`--vault` determines the output root. With the command above, Apple Notes are
written to:

```text
~/Documents/AsterismVault/notes/apple-notes/origin/
```

Every source controls its own safe directory name, producing paths such as
`notes/flomo/origin/`, `notes/cubox/origin/`, and
`notes/opencli-<collection>/origin/`. Below `origin/`, the source's own
hierarchy is mirrored: Apple Notes folders, Cubox folders, Markdown directories, and Notion
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

The generated notes and state are ignored by Git. The source-specific
README files remain tracked.

To avoid an interactive prompt during initialization:

```bash
asterism init ~/Documents/AsterismVault --state-backend sqlite
```

## Digests

After each sync Asterism rolls collected items up inside the source's own
directory, which splits in two: `notes/<source>/origin/` holds what was
collected and `notes/<source>/digest/{daily,weekly,monthly,yearly}/` holds the
rollups over it. Every level holds its whole period:
a week contains the week's items, a month contains the month's, so a higher
level is readable on its own and archiving the lower one away loses nothing. Each level is independent and
ends its period on a configured day; the open period is rebuilt on every
sync, closed periods are generated once and can be re-done with
`asterism digest --regenerate 2026-W39`. `include_days` and its siblings decide whether a level carries the content of
the level below. A digest carries no review state of its own: whether a period
has been dealt with is derived from the decisions on its items.

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

## Writing with it

Two questions come up constantly while writing, and both are one lookup:

```bash
asterism find "RANGE_COMPARE" --vault V            # when did I first write this down?
asterism find "percent_of_total" --vault V --in content   # have I published this already?
```

The answer is one entry per note: the day it was written, what became of it
(`used -> 2026-001`, `reference`, nothing yet), and the lines that matched.
`--in notes` searches what was collected, `--in content` the drafts and exports
you wrote, `--in digest` the rollups, and the default searches the first two.
Briefs are left out on purpose: they quote the material, so searching them
returns the notes a second time. Front matter is left out too, so a search
for a tag finds the prose and not every header that carries it; `--meta`
searches the headers as well.

A vault that is a Git repository gets a save point on demand:

```bash
asterism snapshot --vault V -m "before rewriting the middle"
```

It commits everything the vault tracks — the writing as much as the notes —
and never pushes. `sync --commit` does the same after a collection run.

## Driving it with an agent

Every command except `init` takes `--json` and prints one object with stable
keys, so an agent can read a result instead of a paragraph. `skills/asterism/SKILL.md`
teaches one the flow and, more importantly, its boundary: an agent sorts,
groups, gathers, drafts and adapts, and stops at each of the three gates for
the person to answer. Copy it into `~/.claude/skills/` to use it with Claude
Code.

## How it works

The internals, for anyone who wants them. Skip this if you only want to write.

Every stage writes files into the vault and reads them back; nothing is passed
in memory between commands, so each one can be run on its own and re-run
safely. The state machines are defined once in
[the state model](docs/state-model.md).

### Collection and digests

One command collects and rolls up. Each adapter turns its source into
validated `SourceItem` objects; the pipeline writes one Markdown file per item
and the digest builder rolls those items up by period. Both live in the
source's own directory.

```text
Apple Notes   flomo export   Cubox CLI   Markdown dirs   Notion API   opencli
     |            |             |             |             |            |
     +------------+-------------+------+------+-------------+------------+
                                       |
                        sources/  each adapter calls normalize/
                        (HTML to Markdown, dates, URLs, the title rule)
                                       |
                            SourceItem (schema 1)
                    core: source, source_id, content_text
                    common: title, url, author, parent, tags,
                            created_at, updated_at, origin
                    free:   source_meta
                                       |
        +------------------------------+------------------------------+
        |                                                             |
   pipeline/                                                    digest/
   one file per item, atomic write,                    periods, self-contained
   hierarchy mirrored, moves followed                  levels, sparse output
        |                                                             |
   notes/<source>/origin/<the source's folders>/<title>.md   notes/<source>/digest/
                                                              {daily,weekly,monthly,yearly}/
        |                                                             |
        +------------------------------+------------------------------+
                                       |
                    state/  items, digests, assignments
                    (file or SQLite, same interface, migrated)
                                       |
                            optional `git commit`
```

Commands: `init`, `doctor`, `sync [--commit] [--dry-run]`, `digest`,
`missing`, `migrate-config`.

### Choosing, and the projects it makes

Collection never decides anything. Phase 2 gives every collected item an
outcome and turns the chosen ones into content projects. The person appears
once, in the middle.

```text
   notes/<source>/{origin,digest}/            state/assignments
              |                                      |
              +------------------+-------------------+
                                 |
                  gates/review  coverage: the fewest closed digests
                  that still hold undecided items, coarsest first
                                 |
                  enrich/classify  pillar by rule, never guessed
                  threads: a heading repeated across notes, counted
                                 |
                  picks/<date>.md      <-- the person moves lines
                  sections: used | later | reference | dropped | undecided
                  under used, a `### topic` gathers the lines of one piece
                                 |
                  `asterism apply`
                                 |
        +------------------------+------------------------+
        |                                                 |
  state/assignments                              projects/scaffold
  later | reference | used | dropped             projects/<year>/<date>-<title>/
                                                   01-project.md  the card, YAML front matter
                                                   02-brief.md    from the pillar's template,
                                                                  with the source quoted in it
                                                 (names carry the production order; set
                                                  project.numbered: false to drop them)
                                                 projects/INDEX.md, projects.base
                                                 trash/  projects set aside
```

Commands: `propose [--since] [--now]`, `apply`, `confirm`, `gather`, `material`, `new`,
`set`, `status`, `week`, `find`, `snapshot`, `drop`, `restore`.

### From a topic to a published piece

A confirmed project is carried to a recorded publication by commands alone.

```text
   projects/<year>/<date>-<title>/
     01-project.md  02-brief.md    gather  already-filed material, by path and window
             |                             (an item's outcome never changes)
        `asterism draft`
             |
     03-draft.md  the sections the brief's `## Outline` names, the gathered
             |       material under `## Material`, nothing else
             |       <-- the person writes the prose; composing again only
             |           refreshes the material list and never touches it
        `asterism check`   -> 04-check.md            GATE 2: what the checks found,
             |                                        how much material the piece uses,
             |                                        plus three questions to tick
        `asterism accept`  -> making becomes ready
             |
        `asterism adapt`   -> 05-exports/<platform>.md  carrying settings/platforms/<platform>.md
             |                                        inline, for you to rewrite against
             |                                        an edited export is never overwritten
        `asterism release` -> 06-release.md          GATE 3: the exports and three questions
             |
        `asterism publish` -> ready becomes published, the record lands on the card
```

Commands: `draft`, `check`, `accept`, `adapt`, `release`, `publish [--url
platform=URL]`. Nothing is pushed anywhere: publishing records what went out.

### What is left

There is no phase 4. An orchestrator that advanced every project to its next
gate, and a package of language-model enhancers, were both planned and both
dissolved by the decision that **the agent lives outside Asterism and drives it
through the CLI**: the agent is the orchestrator, and it does the enhancing
through the same commands a person uses. The pipeline still runs with no model
at all.

What remains is a short list rather than a phase, in the order it is likely to
matter — see [the roadmap](docs/roadmap.md):

```text
threads without structure   a folder of saved articles has no repeated headings;
                            the untried signals are its folder and its domain
deliver/blog_git            one push, for the one platform with an interface
sources/worklog + assets.md git commits and coding sessions; a media manifest
feedback/                   metrics and comments, once something has been published
```

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

The code repository and your vault are intentionally separate: the vault holds
private notes, so it is a different folder with its own Git history.

```text
asterism/          this repository, public
my-notes-vault/    your Markdown, its state, and its history
```

This repository also contains a `notes/` skeleton showing the output layout,
usable as a vault for local testing. Collected content inside it is ignored by
Git; only the README files are tracked.


```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m unittest discover -s tests
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

## Where it stands

- **Used for real:** collecting, digests, choosing, projects. Run on a real
  vault for weeks.
- **Walked three times, not yet lived with:** the whole flow, from an empty
  vault to a recorded publication. Three pieces have gone through it in one
  sitting; it has not carried a week of ordinary writing, which is the bar the
  roadmap sets for calling a phase finished.
- **Not built:** work-log adapters, the `assets.md` media manifest, pushing to
  the blog, and metrics and comments flowing back as material. `adapt` copies
  the prose under each platform's rules for you or an agent to rewrite;
  `publish` records where a piece went and never pushes anywhere.

### In detail

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
- `new`, `status`, and `week`, plus a regenerated `projects/INDEX.md` and a
  seeded Obsidian Bases view;
- the first decision gate: `propose` writes a sheet of everything that has no
  outcome yet, one heading per outcome, and `apply` records where each line
  ended up and turns the `used` ones into projects, so nothing is asked about
  twice.

Phase 3, from draft to a recorded publication, adds:

- `confirm` to choose a candidate's angle, and `gather` to add material already
  filed by path and date window;
- `draft`, a skeleton from the brief's outline with the material linked under
  it, never rewritten once the writing has started;
- `check` and `accept` (gate 2), `adapt` into one export per platform with the
  platform's own rules inline, `release` and `publish` (gate 3);
- `find`, one entry per note with its date and what became of it, and
  `snapshot`, a Git save point for the vault.

Where things stand:

Every project field lives in its card in the vault, so the pipeline runs
complete without any external service. A Notion board, a NAS, and a language
model are projections and accelerators that can be added or removed at any
time; losing one loses convenience, never content or state.

## Roadmap

Asterism is being built in phases. Phases 1 to 3, from collection to a recorded
publication, are implemented; what remains is feedback flowing back as material,
an unattended orchestrator, and optional LLM enhancement. See
[the roadmap](docs/roadmap.md) for the destination, the scope of each phase,
and what the architecture looks like at the end of each one.
