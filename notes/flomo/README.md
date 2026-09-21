# flomo output

Implementation status: **HTML/ZIP export adapter available**.

flomo memos will be normalized into this directory. flomo has no folder model;
its hierarchical labels such as `#Books/Title/Chapter` will be written to the
Markdown `tags` list, with `parent: null`.

Available ingestion mode:

- offline import from an official HTML or ZIP export.

Planned ingestion mode:

- live reads through the official flomo MCP when explicitly authorized;

Configure `sources.flomo.export_path` in the selected vault's `asterism.toml`,
then run `asterism sync --vault <vault> --source flomo`.

The current adapter imports textual memo content and tags. Attachment copying is
not implemented yet; the original export should be retained as the attachment
backup.

All generated files in this directory are ignored by Git. This README is the
only tracked file.
