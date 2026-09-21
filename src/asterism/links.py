"""Links in generated Markdown, in the style the vault is configured for.

Obsidian wikilinks by default, so collected notes, digests, and projects form
one graph with working backlinks; plain Markdown links when the vault is read
outside Obsidian.
"""
from __future__ import annotations

import os
from pathlib import Path


def _text(label: str) -> str:
    return " ".join(label.replace("[", "").replace("]", "").replace("|", "-").split())


def relative_href(target: Path, from_file: Path) -> str:
    return os.path.relpath(target, start=from_file.parent).replace(os.sep, "/")


def link_to(style: str, vault: Path, target_relative: str, label: str, *, from_file: Path) -> str:
    """A link to a vault-relative path, labelled for a reader."""
    if style == "wikilink":
        return f"[[{target_relative.removesuffix('.md')}|{_text(label)}]]"
    return f"[{_text(label)}]({relative_href(vault / target_relative, from_file)})"
