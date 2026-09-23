---
name: asterism
description: Drive an Asterism content vault - sort collected material, group it into candidate topics, confirm a topic, gather material, draft, adapt and publish. Use when the user asks to review what was collected, find topics worth writing, assemble a report from notes, or move a piece of content forward. Requires the `asterism` CLI and a vault path.
---

# Driving Asterism

Asterism turns scattered notes into published content. It is a CLI over a
Markdown vault: every stage reads and writes files, and nothing is hidden in a
database. You drive it; you are not inside it.

Pass `--vault <path>` to every command and `--json` whenever you need to parse
the result. `--json` prints one object with `command` and `ok`; an error prints
the same shape with `error`.

## The flow

```text
sync ──► review ──► apply ──► confirm ──► gather ──► draft ──► check ──► adapt ──► release
         (sort)     (candidates) GATE 1              (material) (draft)  GATE 2     GATE 3
```

## What you do at each step

**1. Collect.** `asterism sync --vault V` mirrors the sources into
`notes/<source>/origin/` and rolls up digests. Never edit anything under
`notes/`: it is a mirror the collector rewrites.

**2. Sort.** `asterism review --vault V --json` writes `review/<date>.md`,
listing everything with no outcome yet. Read the sheet and the digests it names
in `covers`.

**3. Group — this is the work worth doing.** In the sheet, move each line under
the outcome it deserves:

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
is applied does nothing; open a new round with `review`.

**5. Offer angles.** A candidate's `02-brief.md` has a `## Candidate angles`
section. Replace the placeholder with the angles its material can actually
support, numbered, each with the promise it would keep:

```markdown
1. **Debugging MCP across environments** — stop losing an afternoon to a dry run that passes locally
2. **A month of MetricFlow in practice** — what the assistant got right and wrong
```

**6. Stop at gate 1.** `asterism confirm <id> --vault V --json` with no angle
lists what is on offer and changes nothing. Show the angles to the person and
let them choose. Do not pick one yourself, and do not run `confirm --angle N`
unless they said which one.

**7. Gather more material.** `asterism gather <id> --from <path> [--since D]
[--until D] --vault V` pulls already-filed notes into the project. Use it for
pieces assembled from a period of material, such as a monthly report, since
sorting only ever offers an item once. Add `--dry-run` first. Gathering does
not change what was decided about those notes.

**8. Draft, review, adapt, publish.** `draft`, `check`, `adapt` and `release`
carry the piece the rest of the way. `check` writes `04-check.md` and `release`
writes `06-release.md`, both inside the project folder: each lists what the machine
could verify and asks three questions as checkboxes. Prepare them; the person
ticks them. `accept` and `publish` refuse while any box is unticked.

## Boundaries

- **Never pass a gate.** `confirm`, the gate-2 acceptance and the gate-3
  publication are the three questions the person owns. Prepare them, present
  them, wait.
- **Never edit `notes/`.** Change the sheet, the briefs, the drafts.
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
| `review/<date>.md` | the sorting sheet; `kind: sort`, `state: open` or `applied` |
| `content/<year>/<date>-<title>/` | a project, its files numbered in production order: `01-project.md`, `02-brief.md`, `03-draft.md`, `04-check.md`, `05-exports/`, `06-release.md` |
| `content/INDEX.md` | every project as a table |
| `asterism.yaml` | pillars, types, platforms, review rules |

`asterism status --json` and `asterism week --json` answer what exists and what
each project is waiting for without reading any of it.
