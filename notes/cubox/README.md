# Cubox output

Implementation status: **official CLI adapter available**.

Cubox cards and annotations will be normalized into this directory through the
official Cubox CLI. Cubox folder hierarchy maps to `parent`, while Cubox labels
map to the Markdown `tags` list. Card-specific values such as the original URL
and author belong in `source_meta`.

After installing and authenticating `cubox-cli` locally, run:

```bash
asterism doctor --vault <vault> --source cubox
asterism sync --vault <vault> --source cubox
```

Asterism invokes only argument-array commands and never accepts a Cubox token in
its configuration or command line.

All generated files in this directory are ignored by Git. This README is the
only tracked file.
