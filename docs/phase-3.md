# Phase 3 plan — From a topic to a published piece

Scope and "done" criteria come from [the roadmap](roadmap.md#phase-3--from-a-topic-to-a-published-piece)
and from [the agent contract](roadmap.md#the-agent-and-the-ai-native-contract).
This document turns them into ordered, PR-sized steps.

Phase 2 sorts collected material and gathers it into candidate projects.
Phase 3 carries a candidate all the way to a published piece:

```text
sort material ──► candidate ──gate 1──► making ──gate 2──► ready ──gate 3──► published
  picks/<date>.md   the pile and    confirm     draft.md    review the   confirm
  (intake, not       its angles      the topic   + exports   draft        publication
   a gate)
```

The agent lives outside and drives this through the CLI; every step is a
command that works without it.

## Status

Steps A to D are implemented and covered by the test suite (214 tests, no
network). `--json` is on every command except `init`, which runs before a vault
exists and asks a question instead.

Decisions taken while implementing:

- **A draft is never overwritten.** `draft` re-reads what is already written
  under each heading and puts it back, so composing again after the brief
  changed adds the new headings and keeps the prose.
- **An edited export is never overwritten either.** A generated export first
  carried an `asterism:generated` marker, and deleting it was how a person said
  the file was theirs. A trial run showed the flaw: rewrite the prose, leave
  the header alone, and the next `adapt` threw the rewrite away. The export now
  carries a fingerprint of what `adapt` wrote, and any difference from it means
  the file is kept and reported. Exports from before are still judged by the
  marker.
- **A gate is passed by ticking, not by running a command.** `accept` and
  `publish` refuse while any box in the gate sheet is unticked and name the
  ones that are. This is what keeps an agent from passing a gate: it can write
  the sheet, it cannot answer it.
- **Checks only report what a machine can be sure of** — an empty section, a
  gathered note the prose never mentions, a missing promise or platform.
  Whether the writing is good is the gate's question.
- **Platform rules live in the vault** at `settings/platforms/<platform>.md`, seeded
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
- **A gate sheet belongs to its project, not to `picks/`.** Writing gates 2
  and 3 into `picks/` left that directory with two unrelated uses, orphaned a
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

## What using it for real changed

The flow was then used to write one piece end to end — a technical article
assembled from a month of daily-log notes, taken from sorting through to a
recorded publication. Six things it got wrong, all fixed:

- **`draft` destroyed a finished draft.** It rebuilt the file from the brief's
  headings and kept only the sections whose headings still matched, so
  restructuring the piece — the first thing writing does — made the prose
  disappear on the next run. Nothing in Asterism may delete, so a draft that
  exists now belongs to the writer: composing again refreshes the material list
  and touches nothing else.
- **The draft copied the wrong headings.** The brief's sections are planning
  prompts (`Audience`, `Shots to record`), and no finished piece has a section
  by those names, so the writer's first act was deleting all of them. The brief
  gained `## Outline`, which is the only thing a draft copies.
- **The uncited check treated gathering as an obligation.** Fifteen notes
  gathered and four cited produced eleven findings, which is noise that buries
  the real ones: taking one thread out of a month is what writing from material
  looks like. It is now a line of arithmetic, and only a piece citing none of
  its material is a finding.
- **The brief template ignored the type.** A work report was handed
  "Shots to record" because templates were chosen by pillar alone. The type
  says what shape a piece has, and shape decides the skeleton, so the type's
  template is now chosen first and seeded on demand.
- **Gate 1 hid the reasoning.** An angle carries a line saying why its material
  belongs together, and the gate listed only the title — leaving the person
  unable to judge the grouping without opening the brief. The reason is read
  back and shown.
- **Platform rules sat in a file nobody had open.** Exports differed from each
  other by two header lines, and the rules to follow were one directory away.
  Each export now carries its platform's rules inline.

## What writing a second time asked for

Three more things, all deterministic, all from the same run:

- **The writing had no history.** `sync --commit` staged `notes/` alone, so a
  draft, a brief and a gate sheet were never in a snapshot. A vault's own
  `.gitignore` already says what is not worth keeping, so a snapshot now
  commits everything else, and `asterism snapshot -m "<why>"` makes a save
  point before a large edit. Nothing is ever pushed.
- **There was no way to look something up.** *When did I first write this down?*
  and *have I published this already?* are the same substring search over
  different directories. `asterism find` answers both. Digests are excluded by
  default because they repeat every line of the notes beneath them, and briefs
  because they quote the material — searching either returns the same sentence
  three times and buries the copy with a date on it.
- **Finding a thread did not need a language model.** The signal a reader uses
  when skimming a month of notes is a heading written again and again, and
  counting them is arithmetic. The sheet now groups notes that repeat a heading
  into a `### thread` carrying its count. On a real month of daily logs it
  produced exactly the two threads a person found by reading all of them, once
  a short trailing annotation — `(P0)` one week, `(P1)` the next — stopped
  splitting one thread in two.

## What writing a report asked for

The second piece was a monthly work report built from the same month of daily
logs, and its shape broke an assumption the first one never touched:

- **Not everything written is posted somewhere.** A report goes to one person;
  a note goes into a wiki. Gate 3 refused to open for a project whose card named
  no platform, so such a piece could reach `ready` and never leave it. Gate 3
  now opens either way: with platforms it lists the exports, without them it
  says so and asks the two questions that still apply — is it finished, and has
  it reached whoever it was for. `is_published` was already derived from the
  status rather than from the publication records, so nothing else had to move.

The outline and the threads both held on a shape they were not designed
against: the report's five sections came from the brief's `## Outline` exactly
as the article's seven did, and `check` reported four of fifteen notes cited
without a word of noise.

## What the whole flow, run from an empty vault, asked for

The third run started at `asterism init`: a new vault, a folder of three weeks
of working notes, then collection, digests, sorting, and a piece published from
a thread the sheet found. Five things it wanted:

- **A new vault was not a repository.** `init` writes a `.gitignore`, the
  pipeline offers `snapshot`, and `sync --commit` exists — a vault with all the
  shape of version control and none of it. `init` now runs `git init` unless
  the directory is already inside someone else's repository, and says so.
  Nothing is ever pushed.
- **`apply` named the wrong next step.** It still told the person to "move the
  status on from 'making'" after the projects it creates became candidates. It
  now points at `confirm`, which is the gate that actually comes next.
- **A card could only be edited in Obsidian.** Setting a pillar, a type or the
  platforms meant opening `01-project.md` by hand, which leaves anything
  driving the vault through the CLI — an agent, a script — unable to do what a
  person can. `asterism set <id>` changes those fields and nothing else; status
  still moves only through the gates.
- **A topic knew its pillar and could not say so.** Classification reads tags
  and folders, and a source with neither — a directory of Markdown — leaves
  every project unclassified even when the topic is called "CLI 设计" and `cli`
  is a configured alias. A topic's own name is now matched against the aliases:
  an ASCII alias must match a whole word so `cli` does not claim `client`, and
  an alias in another script matches anywhere. Aliases have to be written in
  the language the material uses; that is the person's to configure, not the
  machine's to infer.
- **A digest said every title twice.** Each entry links the item by title and
  then quoted the note's own `# Heading` directly underneath. The repeated
  heading is dropped.

## An empty sheet did not say why

Walking the whole flow a second time from an empty vault, `propose` printed
"Nothing to decide" when in fact twelve notes were waiting: they had all been
written that day, and a period is only offered once it has closed. The sentence
was true and useless — it reads as "you have collected nothing".

`propose` now separates the two. When nothing is listed but items are waiting it
says how many and why: their periods have not closed, so today's material comes
next round. `Sheet.waiting` carries the count, and `--json` reports it.

## The Bases view was empty three times

`projects/projects.base` showed no rows, and each time the reason was a
different wrong assumption about a file format I had not read carefully enough.

1. It filtered on `file.name == "project"`. Cards became `01-project.md` when
   the project folder started carrying its production order, and the filter had
   matched nothing ever since.
2. The repair filtered on `file.inFolder("content")` and
   `file.name.endsWith("project")`. Both are false: `file.name` **keeps the
   extension** — `file.basename` is the one without it — and the `content`
   folder is only at the vault root when the Asterism vault *is* the Obsidian
   vault. Open the folder above it, as anyone keeping the source notes beside
   the vault will, and every path gains a segment.
3. The filter is now `file.basename.endsWith("project")` and nothing else. The
   file says in a comment how to narrow it by folder, because the folder layout
   is the person's decision and not one Asterism can read.

**Obsidian rewrites a base the first time it opens it**, normalizing `note.x`
to `x`. That defeats the "replace it while it is still byte for byte ours"
repair: one look at the view in Obsidian and Asterism can never fix it again.
So `doctor` now reports a base whose filter cannot match, with the remedy —
delete it and run `status` — instead of trying to be clever. The byte-identical
repair stays for files nobody has opened.

Two general lessons, both expensive:

- **An empty view looks like no data, not like a bug.** The Markdown index was
  correct throughout, which is exactly why nobody looked at the base for weeks.
  A generated view over a format Asterism cannot evaluate needs a check that
  says whether it can match anything.
- **Read the format's own definition before generating it.** All three failures
  were guesses about `file.name`, about folders, about what is a shorthand —
  and each looked plausible enough to ship.

## What the vault's own top level should hold

Opening the vault in Obsidian shows its top level, so every directory there is
a row in the file tree competing with the work.

- **`logs/` never held anything.** `init` created it, `.gitkeep` kept it, the
  `.gitignore` ignored it, and no line of code ever wrote to it. It is gone.
- **`state/` moved to `.asterism/state/`.** It is bookkeeping a person never
  opens, and a leading dot keeps it out of Obsidian's tree entirely. The
  vault's `.gitignore` becomes one line. A vault that already has `state/`
  keeps using it, so nothing has to be moved to keep working.

What is left is what a person opens: `asterism.yaml`, `settings/`, `notes/`,
`projects/`, `picks/`, plus `trash/` and `archive/` once there is something in
them.

- **`templates/` and `platforms/` moved under `settings/`.** Both are
  configuration: written once, rarely changed, shaping output rather than being
  the work. Arguing that one is filled in and the other is read apart was a
  distinction between two kinds of configuration, not a reason to keep them at
  the top level. They stay *visible* rather than joining `.asterism/`, because
  they are Markdown a person edits in Obsidian and a hidden directory would
  prevent that. `asterism.yaml` stays at the root, where a project's
  configuration file belongs.

So there are two lines, not one. **Does a person open it** decides visible
against hidden; **is it the work** decides configuration against content:

| | visible | hidden |
|---|---|---|
| the work and its material | `projects/`, `notes/`, `picks/`, `trash/` | |
| configuration | `asterism.yaml`, `settings/` | |
| bookkeeping | | `.asterism/` |

## The vault's three directories are one sentence

`notes/`, `review/` and `content/` are not three kinds of thing, they are three
stages of one: **sources → notes → picks → projects**. Named as they were, the
sentence could not be read off the tree — `content` said nothing about what
distinguishes it from notes, and `review` named a paper rather than a step.

- **`review/` → `picks/`.** The step chooses what is worth making; the sheet
  records the choosing. `picks` says that and reads as nothing else in English.
  `topics` was the first choice and was dropped after checking: in topic-based
  authoring, which is the dominant convention in technical writing, a *topic*
  is a finished standalone page — the opposite end of the pipeline.
- **`content/` → `projects/`.** What is in there is mostly unfinished: a
  candidate, a draft, exports waiting for a gate. "Project" is what that is,
  it is what the code already called it, and it is the first folder of PARA,
  the most widely used convention for exactly this. Naming it after a finished
  work — `pieces`, `works`, `content` — overclaims every time it is opened.
- `notes/` stays: it is accurate, and every link already written points into it.
- The command became `asterism propose`, because the machine proposes and the
  person picks. `ContentProject` became `Project`, `content_root` became
  `projects_root`, and the `review:` configuration block became `picks:`.
- A vault that already has `review/` or `content/` keeps using them, like
  `state/` and `templates/` before it. Nothing has to be moved to keep working.

A round with nothing to decide no longer writes a sheet at all. The vault's
own rule is that nothing empty is created — it keeps digests sparse and stops
`new` from making stage directories — and an empty page saying "nothing to
decide" was breaking it in the one place a person looks every week.

**Obsidian hides the configuration file.** `asterism.yaml` does not appear in
the file explorer at all, because Obsidian shows only file types it can open
unless *Detect all file extensions* is on — so the vault's most important
settings file reads as missing rather than as hidden, the same failure as the
empty Bases view. The vault's README says where it is and which switch reveals
it.

**`init` now writes a `README.md` into the vault.** Folder names cannot express
order — a file tree sorts alphabetically and says nothing about what comes
first — so the one thing that makes the workflow legible at a glance is a page
that states it. That is worth more than any further argument about words.

## What a trial by another reader asked for

A creator who tried the flow on four fresh notes, with no history to lean on,
hit five things that a month of my own use had stopped noticing. Each became a
change in this round, in the order of what it would have cost them:

- **A rewritten export could be lost.** The fingerprint replaced the marker
  (above). This came first because it is the only one that destroys work.
- **The first day ended with "come back tomorrow".** `propose` offered only
  closed periods, and `week` sent them back to `propose`. `propose --now`
  offers the periods still accumulating, and both messages now name it. The
  routine round is unchanged: closed periods, every few days.
- **`find` read like grep.** Seven lines for a tag, six of them front matter.
  On the real vault it was worse: a folder name returned 51 header lines and
  nothing else. `find` now answers with notes, each under its date and outcome,
  and searches front matter only with `--meta`.
- **The brief was a form.** Eleven headings for a short piece, half of them
  about shots and screenshots. The default is now the three questions a piece
  cannot do without (what problem, for whom, what evidence) plus the outline
  and the material; a type template carries the rest.
- **The README promised two different things.** The scope section said drafts
  were later; the architecture section described them. It now says what is
  implemented, what has been used for real once, and what does not exist.

What they asked for and did not get yet: candidate topics grouped by shared
tags. The real vault has 131 notes and five with a tag, so tag co-occurrence
would group nothing there; it waits for material where tags carry topics.

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
- `asterism check <id>` writes gate 2, `projects/<project>/04-check.md`: what the
  draft still lacks (empty sections, uncited claims, missing platforms) and a
  place to answer. `asterism accept <id>` reads it and moves `making → ready`.
- `asterism adapt <id>` writes `exports/<platform>.md` per configured platform
  from `settings/platforms/<platform>.md` rules.
- `asterism release <id>` writes gate 3, `projects/<project>/06-release.md`,
  listing the exports and the targets. `asterism publish <id>` reads it, records the
  publication in `project.md`, and moves `ready → published`.

Files: new `src/asterism/compose/{__init__,skeleton,checks,adapt}.py`, new
`src/asterism/gates/{draft,publish}.py`, `src/asterism/cli.py`, tests per module.

## Done when

A candidate produced by sorting is confirmed, gathered, drafted, reviewed,
adapted and published through the commands alone, and an agent following
`skills/asterism/SKILL.md` can drive every step of it except passing the three
gates.
