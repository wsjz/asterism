# Phase 3 plan — The whole flow, driven by an agent

Scope and "done" criteria come from [the roadmap](roadmap.md#phase-3--work-logs-composition-and-delivery-mode-a-complete)
and from [the agent contract](roadmap.md#the-agent-and-the-ai-native-contract).
This document turns them into ordered, PR-sized steps.

Phase 2 sorts collected material and gathers it into candidate projects.
Phase 3 carries a candidate all the way to a published piece:

```text
sort material ──► candidate ──gate 1──► making ──gate 2──► ready ──gate 3──► published
  review/<date>.md   the pile and    confirm     draft.md    review the   confirm
  (intake, not       its angles      the topic   + exports   draft        publication
   a gate)
```

The agent lives outside and drives this through the CLI; every step is a
command that works without it.

## Status

Steps A to D are implemented and covered by the test suite (174 tests, no
network). `--json` is on every command except `init`, which runs before a vault
exists and asks a question instead.

Decisions taken while implementing:

- **A draft is never overwritten.** `draft` re-reads what is already written
  under each heading and puts it back, so composing again after the brief
  changed adds the new headings and keeps the prose.
- **An edited export is never overwritten either.** A generated export carries
  an `asterism:generated` marker; deleting that marker, which rewriting it by
  hand naturally does, makes `adapt` leave the file alone and say so.
- **A gate is passed by ticking, not by running a command.** `accept` and
  `publish` refuse while any box in the gate sheet is unticked and name the
  ones that are. This is what keeps an agent from passing a gate: it can write
  the sheet, it cannot answer it.
- **Checks only report what a machine can be sure of** — an empty section, a
  gathered note the prose never mentions, a missing promise or platform.
  Whether the writing is good is the gate's question.
- **Platform rules live in the vault** at `platforms/<platform>.md`, seeded
  with an empty shape on first use. The code never encodes a platform's taste.
- **A citation is a link, not a mention.** The uncited check first looked for
  the note's name anywhere in the prose, which passed trivially whenever a
  project was named after the fragment it grew from — the common case, since
  that is where a one-fragment project's title comes from. It now collects the
  link targets in the prose and asks whether the note is among them.
- **An older vault is told apart from an empty section.** Templates are seeded
  into the vault once and never rewritten, so a vault created before
  `## Candidate angles` existed keeps a brief without it. `confirm` now says
  which of the two it is — the section is missing and the template predates it,
  or the section is there with no angle written yet — because the fix differs.
- **A gate sheet belongs to its project, not to `review/`.** Writing gates 2
  and 3 into `review/` left that directory with two unrelated uses, orphaned a
  gate sheet whenever its project was dropped, and let a project id of the form
  `2026-ai-001` produce a file name that the sorting sheets' glob matched — so
  a gate sheet could be applied, or rewritten, as a round of sorting. The
  sheets moved into the project as `check.md` and `release.md`, named after the
  commands that write them, and every sheet now carries `kind` so it is found
  by what it says it is rather than by the shape of its name.
- **A project folder reads as its production order.** Alphabetically,
  `brief.md`, `check.md`, `draft.md` and `project.md` say nothing about what
  comes first. The flat layout now numbers them — `01-project.md` through
  `06-release.md` — reusing the existing `project.numbered` switch rather than
  adding one, since it already means "show the order in the names" for stage
  directories. Files a project already has keep their names: renaming would
  break every link written to them, so `find_artifact` prefers the numbered
  name but writes to the plain one when that is what exists, and card discovery
  reads both. Both `load_projects` and `next_id` go through the same lookup,
  because the first version had only the registry finding numbered cards, which
  quietly handed out an id that was already taken.
- **`doctor` reports a structure, then prints it.** Its storage section became
  `_storage_report` plus `_print_storage` rather than a second pass of the same
  logic for JSON, so the two forms cannot drift apart.

## Step A — Confirm the topic (restore `candidate`)

The state machine has always said `candidate ──gate 1──► making`, but `apply`
created projects as `making`, so the gate never existed.

- `apply` creates projects as `candidate`.
- The brief template gains `## Candidate angles`: one line per angle with the
  promise it would keep. A deterministic run leaves the section with a single
  angle taken from the topic heading; an agent fills in more.
- `asterism confirm <id> --angle N | --title T --promise P` writes the chosen
  angle into `title` and `promise` and moves the status to `making`. It is the
  only way the machine moves that status, and it refuses a project that is not
  a `candidate`.

Files: `src/asterism/gates/review.py`, `src/asterism/projects/confirm.py`,
`src/asterism/templates/brief-default.md`, `src/asterism/cli.py`,
`tests/test_confirm.py`.

## Step B — Gather material into a project

A reporting piece is assembled from material that was already filed, which
gate-1 sorting never offers again.

- `asterism gather <id> --from <path prefix> [--since D] [--until D]` appends
  every collected item under that prefix in that window to the project's
  `sources`, rewrites the brief's material section, and reports what it added.
  Running it twice adds nothing.
- Gathering does not change a material's outcome: a note filed as `reference`
  stays `reference` when a piece quotes it. `sources` is the many-to-one
  carrier; the assignment is only the record that the note was decided.

Files: new `src/asterism/projects/gather.py`, `src/asterism/cli.py`,
`tests/test_gather.py`.

## Step C — The agent skill and `--json`

- `--json` on every reporting command, one object with stable keys.
- `skills/asterism/SKILL.md`: the flow, the boundaries, and the exact commands.

Files: `src/asterism/cli.py`, new `src/asterism/report.py`,
`skills/asterism/SKILL.md`, `tests/test_json_output.py`.

## Step D — Draft, review, adapt, publish

- `asterism draft <id>` composes `draft.md` from the brief's headings with the
  gathered material quoted under each, every quote carrying a link back.
- `asterism check <id>` writes gate 2, `content/<project>/04-check.md`: what the
  draft still lacks (empty sections, uncited claims, missing platforms) and a
  place to answer. `asterism accept <id>` reads it and moves `making → ready`.
- `asterism adapt <id>` writes `exports/<platform>.md` per configured platform
  from `vault/platforms/<platform>.md` rules.
- `asterism release <id>` writes gate 3, `content/<project>/06-release.md`,
  listing the exports and the targets. `asterism publish <id>` reads it, records the
  publication in `project.md`, and moves `ready → published`.

Files: new `src/asterism/compose/{__init__,skeleton,checks,adapt}.py`, new
`src/asterism/gates/{draft,publish}.py`, `src/asterism/cli.py`, tests per module.

## Done when

A candidate produced by sorting is confirmed, gathered, drafted, reviewed,
adapted and published through the commands alone, and an agent following
`skills/asterism/SKILL.md` can drive every step of it except passing the three
gates.
