# Configuring a vault

[中文](configuring_CN.md)

Everything below is optional: a vault with one source configured already
collects, sorts and carries a piece to publication. Come here when you want to
change how it behaves.

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
`picks/` with the first round of sorting, `settings/templates/` with the
first project, `trash/` when a project is set aside. `settings/platforms/` is
yours to create when you write a platform's rules.

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

## Pillars, types and platforms


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
in the project card's `status`.

Templates are seeded into the vault the first time they are used
(`settings/templates/project.md`, `settings/templates/brief-<name>.md`), so editing them
changes every later project. Status is yours: it moves at the three gates,
`confirm`, `accept` and `publish`, or by an edit in Obsidian, and never on its
own.

How a piece is rewritten for a platform is a note you write yourself,
`settings/platforms/<platform>.md`: length, opening, what it must have and
must never do. Whoever writes the platform version, you or an agent, follows
it into `04-exports/<platform>.md`. Asterism ships no rules, because what works
on a platform is your judgment.

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
[`asterism.yaml`](../asterism.yaml), so the repository itself can be selected:

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

## Front matter and upgrades


Every note starts with a fixed-order front matter block versioned by
`schema`, which every collected note carries.
Upgrading to a new schema rewrites every note once on the next sync; the
file names and state keys do not change.

