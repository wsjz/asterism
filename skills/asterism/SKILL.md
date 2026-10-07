---
name: asterism
description: Drive an Asterism content vault - sort collected material, group it into candidate topics, confirm a topic, gather material, draft, adapt and publish. Use when the user asks to review what was collected, find topics worth writing, assemble a report from notes, or move a piece of content forward. Requires the `asterism` CLI and a vault path.
---

# Driving Asterism

Asterism turns scattered notes into published content. It is a CLI over a
Markdown vault: every stage reads and writes files, and nothing is hidden in a
database. You drive it; you are not inside it.

The CLI keeps the record: what was collected, what was decided about each note,
which project it went into, and which gate each piece has passed. It never
writes prose. Grouping, drafting, checking a draft and rewriting it for a
platform are judgment, and they are yours, as this file describes.

Pass `--vault <path>` to every command and `--json` whenever you need to parse
the result. `--json` prints one object with `command` and `ok`; an error prints
the same shape with `error`.

## The flow

```text
sync ──► propose ──► apply ──► confirm ──► gather ──► draft ──► accept ──► adapt ──► publish
         (sort)     (candidates)  GATE 1   (material)  (you)     GATE 2     (you)     GATE 3
```

## What you do at each step

**1. Collect.** `asterism sync --vault V` mirrors the sources into
`notes/<source>/origin/` and rolls up digests. Never edit anything under
`notes/`: it is a mirror the collector rewrites.

**2. Sort.** `asterism propose --vault V --json` writes `picks/<date>.md`,
listing everything with no outcome yet. Read the sheet and the digests it names
in `covers`. It offers finished periods; when `listed` is 0 and `waiting` is
not, what was collected today is still accumulating, and `--now` offers it too.

**3. Group — this is the work worth doing.** The sheet already groups notes
that repeat the same heading into a `### thread` with a count; those are threads
the person has been pulling for weeks, and they are usually the best candidates.
When a project already carries a thread, the sheet says `Already in <id>
(<status>)` under it and `propose --json` lists it in `written`: propose that
thread as more material for the existing piece, not as a new one.
Your job is the grouping a count cannot see: fragments in different folders,
sources and weeks that are about the same thing.

In the sheet, move each line under the outcome it deserves:

- `used` — becomes a content project
- `later` — worth making, but not now (it comes back every round)
- `reference` — keep as material, will not be a piece of its own
- `dropped` — seen, not keeping
- `undecided` — leave it for the person

Under `used`, gather the lines of one piece beneath a `### topic` heading. One
topic becomes one project holding all of its material. **A piece is made of
several fragments; one line to one project is the exception.** Look for
relations the person cannot see themselves: fragments in different folders,
different sources and different weeks that are about the same thing.

For every topic you propose, write one line of reasoning under the heading so
the person can audit why those fragments belong together. Never invent a line
that is not already in the sheet.

**4. Apply.** `asterism apply --vault V --json` records the outcomes and turns
each topic into a project with status `candidate`. Editing the sheet after it
is applied does nothing; open a new round with `propose`.

**5. Offer angles.** A candidate's `02-brief.md` has a `## Candidate angles`
section. Replace the placeholder with the angles its material can actually
support, numbered, each with the promise it would keep:

```markdown
1. **Debugging MCP across environments** — stop losing an afternoon to a dry run that passes locally
   _Why these belong together: 09-08 and 09-10 both hit it, 09-22 found the cause._
2. **A month of MetricFlow in practice** — what the assistant got right and wrong
   _Why these belong together: the show case on 09-15 and the two feedback rounds around it._
```

The indented italic line is read back and shown at the gate, so write one for
every angle: it is how the person judges whether your grouping is right without
opening the brief.

**6. Stop at gate 1.** `asterism confirm <id> --vault V --json` with no angle
lists what is on offer and changes nothing. Show the angles to the person and
let them choose. Do not pick one yourself, and do not run `confirm --angle N`
unless they said which one.

**7. Gather more material.** `asterism gather <id> --from <path> [--since D]
[--until D] --vault V` pulls already-filed notes into the project. Use it for
pieces assembled from a period of material, such as a monthly report, since
sorting only ever offers an item once. Add `--dry-run` first. Gathering does
not change what was decided about those notes.

**8. Outline, then draft.** Fill the brief's `## Outline` with the sections the
piece will have, one per line. Then write `03-draft.md` in the project folder:
the title as `# `, the card's promise in italics under it, and one `## ` per
outline line. Never copy the brief's planning headings (Core question,
Audience): no finished piece has a section by those names. Where the prose uses
a fragment, link it (`[[notes/...|words]]`, or a Markdown link when the
vault sets `links: markdown`); that is how the person checks
where a claim came from.

Once the draft exists it belongs to the writer. Do not restructure, regenerate
or rewrite it unless asked, and run `asterism snapshot -m "<why>"` before a
large edit you were asked for. `gather` refreshes the brief's source list and
never touches the draft.

**9. Prepare gate 2, then stop.** Read the draft against its card and tell the
person, in the conversation rather than in a file:

- sections that have no prose yet;
- whether it keeps the card's `promise`, or that the card has none;
- how many of the gathered notes it links: a low number is normal, since a
  month of notes yields one thread, but linking none is worth saying;
- claims that need a source and have none.

Then ask whether it is good enough. Run `asterism accept <id>` only when they
say it is.

**10. Adapt.** The card's `platforms` say where the piece goes; change them with
`asterism set <id> --platform X` when the person names them. For each one,
write `04-exports/<platform>.md` following `settings/platforms/<platform>.md`.
Those rules are the person's taste: when the file does not exist, keep the
draft's prose as it is and say the rules are missing; never invent them. An
export that already exists is the person's: never overwrite it, and rewrite it
in place only when asked.

**11. Gate 3, then stop.** List the exports, and any platform on the card that
has none, and ask whether it goes out. The person posts it; nothing is pushed
from here. When they say it went out, run `asterism publish <id> --url
<platform>=<url>` with each link they give you. A piece with no platform, such as
a report for one person, finishes with a plain `publish`.

## Boundaries

- **Never pass a gate.** `confirm --angle N`, `accept` and `publish` are the
  person's three answers. Prepare each question, present it, and run the
  command only once they have answered it.
- **Never edit `notes/`.** Change the sheet, the briefs, the drafts.
- **Never overwrite the person's writing.** A draft or an export they have
  worked on is edited in place, only when asked, after a snapshot.
- **Never delete.** No command deletes anything; do not work around that.
- Leave the sheet parseable: a line is recognized by the note it links to, so
  keep the link and reword freely around it.
- Say what you changed in terms of files, and leave anything you were unsure
  about under `undecided` rather than guessing.

## Reading the vault directly

| Path | What it holds |
|---|---|
| `notes/<source>/origin/` | collected items, one file each, mirrored |
| `notes/<source>/digest/` | daily, weekly, monthly rollups |
| `picks/<date>.md` | the sorting sheet; `kind: sort`, `state: open` or `applied` |
| `projects/<year>/<date>-<title>/` | a project, its files numbered in production order: `01-project.md` (the card), `02-brief.md`, `03-draft.md`, `04-exports/<platform>.md`. A project from before this layout may also hold `04-check.md`, `05-exports/` and `06-release.md`; leave them, and read its exports from `05-exports/` |
| `projects/INDEX.md` | every project as a table |
| `settings/platforms/<platform>.md` | the person's rules for rewriting a piece for that platform |
| `settings/templates/` | the card and brief templates new projects start from |
| `asterism.yaml` | pillars, types, platforms, picks rules |

`asterism status --json` and `asterism week --json` answer what exists and what
each project is waiting for without reading any of it.

`asterism set <id> --pillar P --type T --platform X` changes the card's fields
when the person has told you what they should be; it never moves the status.

`asterism find <text> --json` searches the collected notes and the writing and
answers with `notes`, one entry per note carrying its `day`, its `outcome`
(`used`, `later`, `reference`, `dropped` or null) and the `project` it went
into; use it before proposing a topic, to check whether the person has already
published on it, and while drafting, to find the day something was first
written down. Front matter is searched only with `--meta`. `asterism snapshot -m "<why>"` commits the vault before you make
a large edit, so the person can undo it.
