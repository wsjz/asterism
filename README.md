# Asterism ⁂

[中文](README_CN.md)

**Turn scattered notes into published pieces.**

You collect more than you write. Ideas land in Apple Notes, articles pile up in
Cubox, fragments accumulate in flomo — and by the time you sit down to write,
finding the one thread running through three weeks of them is harder than the
writing itself.

Asterism does that part. It gathers what you collected into one place, shows
you which notes keep circling the same subject, and turns the one you choose
into a piece — carrying its material with it, to a draft and a version per
platform.

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

Next: [connecting your other notes](docs/configuring.md).

## Writing with it

Two questions come up constantly while writing, and both are one lookup:

```bash
asterism find "RANGE_COMPARE" --vault V                   # when did I first write this down?
asterism find "percent_of_total" --vault V --in content   # have I published this already?
```

The answer is one entry per note: the day it was written, what became of it,
and the lines that matched.

A vault that is a Git repository gets a save point on demand:

```bash
asterism snapshot --vault V -m "before rewriting the middle"
```

It commits everything the vault tracks — the writing as much as the notes — and
never pushes.

## Driving it with an agent


Every command except `init` takes `--json` and prints one object with stable
keys, so an agent can read a result instead of a paragraph. `skills/asterism/SKILL.md`
teaches one the flow and, more importantly, its boundary: an agent sorts,
groups, gathers, drafts and adapts, and stops at each of the three gates for
the person to answer. Copy it into `~/.claude/skills/` to use it with Claude
Code.

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

## Requirements

macOS with Apple Notes, Python 3.11 or newer, and permission for your terminal
to control Notes. Cubox needs the official `cubox-cli` installed and logged in;
flomo reads an official HTML or ZIP export. Asterism never reads either app's
private database and never takes a token on the command line. Its only
third-party dependency is PyYAML.

## Safety model

Note content and paths are treated as untrusted input: generated paths stay
inside the vault, SQLite queries are parameterized, Markdown is written
atomically, and the collector never invokes a shell. Nothing is ever deleted,
and nothing is ever pushed.

## More

- [Configuring a vault](docs/configuring.md) — sources, pillars, platforms, digests
- Working on Asterism itself: [AGENTS.md](AGENTS.md)
