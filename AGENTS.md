# Asterism agent guide

## Product intent

Asterism is an automated content production pipeline for one creator: it turns
scattered notes and work logs into digests, content projects, drafts, platform
versions, and published pieces, with a person involved only at a few decision
gates. It should feel quiet, local-first, and predictable. Prefer a small
trustworthy pipeline over a broad platform. The destination, the phases, and
the current phase are in `docs/roadmap.md`; work one phase at a time.

## Fixed architectural decisions

- Python is the application and orchestration language.
- AppleScript is a thin macOS adapter invoked through `/usr/bin/osascript`.
- Do not read Apple Notes' private SQLite database.
- Do not add a persisted JSONL intermediate layer. Adapter output may use an
  in-memory serialization format for process transport.
- Normalize directly to one Markdown file per source item.
- Keep the normalized model source-neutral: `parent` represents hierarchy,
  `tags` represents cross-cutting labels, and `source_meta` contains adapter-only
  scalar metadata. Never promote one source's organization model to a universal
  requirement.
- Support both file and SQLite state backends behind the same interface.
- Keep the public code repository separate from every private content vault.
- Do not automatically delete local Markdown when a source item disappears.
- Never push Git changes. Committing is opt-in (`sync --commit`) and only after
  every source succeeded.
- Configuration is YAML (`asterism.yaml`), read with `yaml.safe_load` only and
  validated strictly after loading. PyYAML is the single third-party dependency.
- `content_text` is always Markdown. Converting HTML or plain text is the
  adapter's job; the model never carries a content format flag.
- Shared conversions (HTML to Markdown, datetime parsing, URL canonicalization,
  the title rule) live in `normalize/` as pure functions and nowhere else.
- All adapters are first-party code held to the same rules. What differs is
  who guarantees the data's meaning: first-party channels (osascript,
  cubox-cli, the Notion API) are guaranteed by Asterism; opencli collections
  are guaranteed by opencli's community adapters and the user's mapping, and
  `origin` in the front matter records which.
- The pipeline must be fully usable without an LLM. An LLM only enhances a
  deterministic artifact and is off by default.
- Ownership of a content project's fields is split, never shared: the vault
  owns content and machine facts, Notion (from Phase 2) owns management
  fields; each field flows one way.

## Engineering rules

- Python 3.11+ and standard library first. PyYAML is the only dependency; add
  another only when its value clearly outweighs installation and supply-chain
  cost. External tools (cubox-cli, opencli, git) are optional binaries found
  on PATH and detected by `doctor`, never Python dependencies.
- Keep source adapters, rendering, state, storage, and publishing boundaries
  independent.
- Treat source content, titles, identifiers, and configured paths as untrusted.
- Resolve and validate paths before writing; generated files must remain below
  the configured vault.
- Use parameterized SQL only.
- Invoke subprocesses with argument arrays, never `shell=True`.
- Write user content atomically before updating state.
- Avoid logging note bodies or other private content.
- Never access or commit credentials, tokens, private keys, `.env` files, vault
  contents, state databases, or logs.
- Preserve backward compatibility for state schema changes or provide an
  explicit migration.

## Verification

Run before handing off a change:

```bash
# once: python3 -m venv .venv && .venv/bin/python -m pip install -e .
.venv/bin/python -m unittest discover -s tests
.venv/bin/python -m compileall -q src tests
```

Without the virtual environment, prefix both commands with `PYTHONPATH=src`.

Tests must not require access to the user's real Notes library. Inject a fake
source into pipeline tests. Real Notes access is an explicit manual check.

## Phases

Phase 1 (collection) is implemented; see `docs/phase-1.md` for its steps and
`docs/roadmap.md` for what comes next. Do not start a later phase's modules
(content projects, gates, compose, deliver, feedback, llm) until the current
phase's "done" criteria hold, including real use on the user's own vault.

## Source adapter contract

Every adapter must expose a stable `name`, a safe `output_name`, an `Origin`,
and return validated `SourceItem` objects whose titles come from
`normalize.derive_title`. `source_id` is identity and must be native or a
canonical URL, never derived from content; parents and tags are mutable
metadata and must never be used as identity. Keep authentication inside the
adapter boundary and obtain credentials only from environment variables or an
approved local credential store. Adapters are registered in
`sources/registry.py`; the CLI never constructs them directly.

