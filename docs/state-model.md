# State model

The one place the pipeline's state machines are defined. Everything else
(roadmap, phase plans, code, tests) follows this document; when a machine
changes, this file changes first and the change is stated as a diff against
what it says today.

Four state machines carry meaning for the person, and one is machine
bookkeeping. They do not overlap: each answers a different question.

| Machine | Question it answers | Carrier | Values |
|---|---|---|---|
| Source health | Is this source working, and how much has piled up? | state, one row per source | `ok`, `failed`, `auth_required` |
| Material | What did I decide about this collected item? | state, one row per item | none, `later`, `reference`, `used`, `dropped` |
| Review sheet | Has this review sheet been applied? | `review/<date>.md` front matter | `open`, `applied` |
| Content project | How far along is this piece? | `content/<project>/project.md` front matter | `candidate`, `making`, `ready`, `published`, `retrospected`, `dropped` |
| Digest lifecycle (internal) | Can this period still change? | state, one row per source, level and period | `open`, `closed`, `rolled`, `archived` |

## Source health

```text
ok | failed | auth_required     with last_run_at and the number of undecided items
```

Written by `sync` for each source it ran. `failed` and `auth_required` keep
the last successful run's data; nothing is cleared because a run failed.
Read by `doctor` and `week` to answer "which source has not run for a week"
and "which source has thirty items waiting".

## Material

```text
(no record)  the item has never been decided; this is the default and is not stored
     |
     +--> later       worth making, but not now; appears in every later sheet until decided
     +--> reference   kept as material; will not become a piece of its own
     +--> used        became material of a content project, carrying that project's id
     +--> dropped     seen, not kept
```

An item is *dealt with* when it is `reference`, `used`, or `dropped`. `later`
and no record both mean it still needs a decision. `used` is written by the
machine when a project is created from the item; the other three are written
by the person moving a line in a review sheet.

Statuses are never written into `notes/<source>/origin/`, because that tree
is a mirror the collector rewrites. The permanent human-readable record is the review sheets
under `review/`, which are kept; state is the index over them.

## Review sheet

```text
open ──► applied
```

One row per `review/<date>.md`. `open` means the sheet is yours to edit;
`applied` means its decisions have been recorded and projects created.
Applying twice does nothing. Sheets are kept as the record of what was
decided when.

A sheet is built by covering the undecided span with the fewest digest
documents: from the earliest undecided day, take the coarsest digest that is
`closed` and still holds undecided items, jump past its end, repeat. Periods
that are still `open` are never offered, because they are still changing.

## Content project

```text
candidate ──gate 1──► making ──gate 2──► ready ──gate 3──► published ──after 7 days──► retrospected
    ▲                   │                  │
    └───── restore ─────┴──────────────────┴──────────► dropped
```

Five steps, three gates, and one exit. The five steps match the five states
the person already works with. What is *inside* `making` (gathering
material, writing) is answered by the files that exist in the project
folder, not by more states. Archiving is a storage action recorded in
`archive-plan.md`, not a state.

`dropped` is a piece that will not be finished for now. It is not a dead end:
a dropped project keeps everything it had, so restarting it is changing the
status back and moving the folder home.

Dropped projects live under `trash/` at the vault root, mirroring the same
`<year>/<project>` path they had under `content/`. `content/` therefore holds
only live work, and `status` reads it alone unless asked otherwise.
`asterism drop <id>` sets the status and moves the folder; `asterism restore
<id>` moves it back as a `candidate`. Nothing is ever deleted.

## Digest lifecycle (internal)

```text
open ──► closed ──► rolled ──► archived
```

Machine bookkeeping for a period document. `open` means the period is still
accumulating and its document is rebuilt on every sync. `closed` means the
period has passed. `rolled` means a higher level has been generated over it.
`archived` means the document was copied or moved below the archive root.
Only `closed` and later can enter a review sheet.

Digests carry no state of their own in this machine. Whether a period has
been decided is derived from its items, so there is no second copy to disagree
with the first.

## History of this model

- Content projects had ten states; reduced to six. `approved`, `gathering`
  and `drafted` became `making`; `reviewed`, `adapted` and `staged` became
  `ready`; `archived` became a storage action.
- Abandoning a piece was first defined as moving the folder out of
  `content/` with no state of its own. That is replaced: `dropped` is the
  sixth value, and the folder moves to `trash/` rather than out of the
  vault, so a restart is a status change and a move back.
- Material had two values (`ignored`, `promoted`) stored only in state;
  renamed to `dropped` and `used` and extended to five, with the review
  sheets as the visible record.
- Digests had a configurable `review_status` that the machine never wrote,
  which contradicted deriving "has this period been decided" from the items.
  It was removed rather than redefined.
- The sorting session was called *triage* while it was being written. The
  word implied ranking by urgency, which is not what the four outcomes do,
  so the session, its command and its directory are all `review`.
