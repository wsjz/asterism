# Source support plan

Asterism normalizes different organization models without pretending they are
the same:

```text
stable identity  -> source + source_id
hierarchy        -> parent (optional)
cross references -> tags[]
adapter details  -> source_meta{}
```

`parent` and `tags` are mutable metadata. Moving a note or renaming a tag must
update the same item, not create a new item.

The output tree mirrors `parent`: an item is written below
`notes/<source>/<parent segments>/`, each segment sanitized, so Apple Notes
folders, Cubox folders, Markdown directories, and Notion parent pages keep
their structure on disk. When an item moves in its source, its file moves to
the new directory and keeps its name.

## Normalized front matter

```yaml
---
schema: 1
source: "flomo"
source_id: "memo-123"
origin: {"adapter": "flomo", "producer": "html-export"}
title: null
url: null
author: null
parent: null
tags: ["writing/ideas", "draft"]
created_at: "2026-09-21T10:30:00+08:00"
updated_at: "2026-09-21T10:45:00+08:00"
source_meta: {}
---
```

Keys appear in this fixed order. `schema` versions the front matter contract.
`origin` records the adapter and the upstream producer (and its version when
known) so a reader can tell who guarantees the item's semantics: a first-party
channel such as `cubox-cli`, or a community command such as
`twitter/bookmarks` behind the opencli adapter. `url` is the item's canonical
location in its source when it has one, and `author` distinguishes the user's
own words from saved material by others.

JSON flow syntax is used for arrays and objects because it is valid YAML and
lets the standard-library renderer safely quote untrusted values.

## Adapter assessment

### Apple Notes — implemented

- Access: local `osascript`/Apple Events.
- Identity: Notes object ID.
- Parent: complete account folder path.
- Tags: none exposed by the current adapter.
- Source metadata: account name.
- Sync class: unattended incremental scan after macOS permission is granted.
- Daily logs: notes in the folders listed under
  `sources.apple_notes.daily_log_folders` are split into one item per
  time-stamped line (`09:20 …`). The fragment's `source_id` is the note id
  plus the time anchor (`…#09:20`, `…#09:20-2` for a repeated time), its
  `parent` is the note title, and its `created_at` combines the note's day
  (a leading `YYYY-MM-DD` in the title, else the creation date) with the
  line's time in `sources.apple_notes.timezone`. Text before the first
  timestamp becomes a `preamble` fragment. Appending a line therefore adds
  one item instead of changing the whole note.

### flomo — HTML/ZIP implemented, live MCP planned

flomo uses hierarchical tags such as `#Books/Title/Chapter`, not folders. Its
documented input API is write-oriented. Official read access is available via
flomo MCP for MAX accounts, while every account can export HTML.

1. `flomo_mcp` (planned): live read adapter using `memo_search` and `memo_batch_get`.
   This requires explicit MCP authorization and must not embed or log a token.
2. `flomo_export` (implemented): offline snapshot importer for the official
   HTML or ZIP export.
   It is suitable for backup and bootstrap, but not unattended incremental sync.
   The first implementation imports text and tags; attachment copying remains
   pending, so the original export should be retained.

Mapping:

```text
memo id       -> source_id
memo content  -> content_text
flomo tags    -> tags[] (remove the leading #, retain slash hierarchy)
parent        -> null
```

Official references:

- [flomo MCP](https://help.flomoapp.com/advance/mcp)
- [flomo storage and HTML export](https://help.flomoapp.com/basic/storage.html)
- [flomo hierarchical tags](https://help.flomoapp.com/basic/tag.html)

### Cubox — implemented via official CLI

Cubox has both nested folders and hierarchical tags. Its public POST API is for
saving content, while the official CLI can search cards, read parsed Markdown,
read annotations, and list folder/tag structures. The adapter should invoke the
CLI with an argument array and request JSON output; it must never pass an API
credential on the command line.

Mapping:

```text
card id          -> source_id
folder path      -> parent
card tags        -> tags[]
parsed Markdown  -> content_text
URL, author, etc -> source_meta
```

Official references:

- [Cubox CLI](https://help.cubox.pro/ai/agents)
- [Cubox folders and tags](https://help.cubox.pro/manage/organize/)
- [Cubox export options](https://help.cubox.pro/share/d70f/)

### Obsidian or a Markdown directory — implemented, local filesystem

An Obsidian vault is already a local Markdown directory. The adapter reads files
under explicitly configured roots, skips hidden directories and symlinks, and
rejects any input root that overlaps the Asterism output vault.

Mapping:

```text
normalized relative path -> source_id
parent directory         -> parent
front matter / #tags     -> tags[]
Markdown                 -> content_text
filesystem timestamps    -> created_at / updated_at
```

No Obsidian process or cloud API is required for reading local files. Obsidian's
official URI supports opening and creating files, but filesystem reads are the
safer ingestion path: [Obsidian URI documentation](https://help.obsidian.md/Extending%2BObsidian/Obsidian%2BURI).

### Notion — implemented via official API

Use an internal integration with read-content capability. Asterism retrieves
page properties and the official enhanced-Markdown representation, and uses
paginated block traversal only to discover scoped descendants. Tokens come from
`ASTERISM_NOTION_TOKEN` and must never be written to `asterism.toml`.

The safe default is explicit scope: configure root page IDs and/or data source
IDs. `discover_all = true` is an opt-in mode that collects every page visible to
the integration. Notion permissions remain the upper bound in both modes.

Mapping:

```text
page UUID                  -> source_id
parent page/data source    -> parent
multi-select properties    -> tags[]
page blocks                -> content_text
selected page properties   -> source_meta
```

Official references:

- [Retrieve a page](https://developers.notion.com/reference/retrieve-a-page)
- [Retrieve a page as Markdown](https://developers.notion.com/reference/retrieve-page-markdown)
- [Search by title](https://developers.notion.com/reference/post-search)
- [Authorization](https://developers.notion.com/guides/get-started/authorization)

### opencli — implemented via one generic adapter

[opencli](https://github.com/jackwener/opencli) exposes 100+ websites as
commands with `--format json`. Asterism runs only the read-only commands the
user declares under `sources.opencli.collections`, each with a field mapping,
and validates them against `opencli list --format json` (command exists,
`access` is `read`, mapped fields are declared columns, arguments are known).
Browser-backed commands need Chrome with the OpenCLI extension and a login;
opencli's exit codes 69 and 77 are reported with that guidance, 66 and an
empty array mean no items.

Mapping (per collection, in configuration):

```text
map.id (else canonical map.url) -> source_id   never derived from content
map.content[]                   -> content_text (joined; html converted when content_format: html)
map.title / first line / URL    -> title (shared title rule)
map.created_at / updated_at     -> created_at / updated_at (unreadable values become null)
map.tags (split by separator)   -> tags[]
map.parent, map.author, map.url -> parent, author, url
every other scalar column       -> source_meta (non-scalars JSON-encoded; map.exclude dropped)
```

`origin` is `{"adapter": "opencli", "producer": "<site>/<command>",
"producer_version": "<opencli version>"}`. Asterism guarantees the pipeline
contract; the meaning and stability of the columns belong to opencli's
community adapters and the user's mapping.

## Implementation order

Phase 1 (collection) is complete for Apple Notes, flomo export, Cubox, local
Markdown, Notion, and opencli. Remaining collection work is incremental:

1. Live flomo MCP sync behind explicit authorization, once the account tier
   allows it.
2. Cubox detail collection tuning while preserving full Markdown and
   annotations.
3. Work-log sources (git history, coding-session transcripts, screenshots and
   recordings) arrive with content projects in Phase 3 of the roadmap.
