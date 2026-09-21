# Apple Notes output

Implementation status: **available**.

When the selected vault is this repository, normalized Apple Notes are written
to this directory. The current layout is flat: each filename contains a safe
title fragment and a stable hash derived from the Apple Notes identifier.

Example shape (illustrative only):

```text
display-setup--2f91c6e03d17a124.md
```

Apple Notes folders are not reproduced as filesystem directories. Their full
hierarchy is stored in the Markdown `parent` field, while the Notes account is
stored in `source_meta.account`.

All collected Markdown files in this directory are ignored by Git. Do not put
real note content in this README.

