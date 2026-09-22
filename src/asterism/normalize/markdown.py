"""A small HTML tree parser and HTML-to-Markdown conversion (standard library only)."""
from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
import re
from typing import Iterator


BLOCK_TAGS = frozenset(
    {"article", "blockquote", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "p", "section"}
)
HEADING_TAGS = {f"h{level}": level for level in range(1, 7)}
LIST_TAGS = frozenset({"ul", "ol"})
INDENT = "  "
VOID_TAGS = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
)


@dataclass(slots=True)
class Node:
    tag: str
    attrs: dict[str, str]
    children: list[Node | str] = field(default_factory=list)


class _TreeParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("document", {})
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = Node(tag.lower(), {key.lower(): value or "" for key, value in attrs})
        self.stack[-1].children.append(node)
        if tag.lower() not in VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if self.stack[-1].tag == tag.lower():
            self.stack.pop()

    def handle_endtag(self, tag: str) -> None:
        target = tag.lower()
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == target:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(data)


def parse_html(document: str) -> Node:
    """Parse ``document`` into a tree. Raises ``ValueError`` on malformed input."""
    parser = _TreeParser()
    try:
        parser.feed(document)
        parser.close()
    except Exception as error:  # HTMLParser raises a variety of exceptions
        raise ValueError("malformed HTML") from error
    return parser.root


def walk(node: Node) -> Iterator[Node]:
    for child in node.children:
        if isinstance(child, Node):
            yield child
            yield from walk(child)


def has_class(node: Node, class_name: str) -> bool:
    return class_name in node.attrs.get("class", "").split()


def first_descendant_with_class(node: Node, class_name: str) -> Node | None:
    return next((candidate for candidate in walk(node) if has_class(candidate, class_name)), None)


def plain_text(node: Node) -> str:
    return "".join(child if isinstance(child, str) else plain_text(child) for child in node.children)


def markdown_text(node: Node, depth: int = 0, ordered: bool = False, checklist: bool = False) -> str:
    """Render a tree as Markdown.

    Handles emphasis, links, headings, line breaks, and nested lists including
    the checklists Apple Notes exports as ``<li class="checked">``. ``depth``
    counts enclosing lists, so nesting becomes indentation. Some editors nest
    a list as a sibling of the item it belongs to rather than inside it, which
    is why the depth is carried down rather than read from the tree shape.
    """
    parts: list[str] = []
    counter = 0
    for child in node.children:
        if isinstance(child, str):
            # newlines between <li> tags are source formatting, not content
            if node.tag in LIST_TAGS and not child.strip():
                continue
            parts.append(child)
            continue
        if child.tag == "br":
            parts.append("\n")
            continue
        if child.tag in LIST_TAGS:
            parts.append(
                markdown_text(
                    child,
                    depth + 1,
                    ordered=child.tag == "ol",
                    checklist=_is_checklist(child) or (checklist and child.tag == "ul"),
                )
            )
            parts.append("\n")
            continue

        prefix = ""
        if child.tag == "li":
            counter += 1
            prefix = INDENT * max(depth - 1, 0) + _marker(child, counter, ordered, checklist)
        body = markdown_text(child, depth, ordered, checklist)
        if child.tag in {"b", "strong"}:
            body = f"**{body.strip()}**"
        elif child.tag in {"em", "i"}:
            body = f"*{body.strip()}*"
        elif child.tag == "a" and child.attrs.get("href", "").startswith(("http://", "https://")):
            body = f"[{body.strip()}]({child.attrs['href']})"
        elif child.tag in HEADING_TAGS:
            body = f"{'#' * HEADING_TAGS[child.tag]} {body.strip()}"
        elif child.tag == "li":
            body = body.rstrip("\n")  # a trailing <br> inside an item is noise
        parts.append(prefix + body)
        if child.tag in BLOCK_TAGS:
            parts.append("\n")
    text = "".join(parts).replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"\n{3,}", "\n\n", text)


def _is_checklist(node: Node) -> bool:
    classes = node.attrs.get("class", "").lower()
    return "checklist" in classes or any(
        isinstance(child, Node) and child.tag == "li" and _checked(child) is not None
        for child in node.children
    )


def _checked(item: Node) -> bool | None:
    classes = item.attrs.get("class", "").lower().split()
    if "checked" in classes:
        return True
    if "unchecked" in classes:
        return False
    return None


def _marker(item: Node, position: int, ordered: bool, checklist: bool) -> str:
    state = _checked(item)
    if state is not None or checklist:
        return f"- [{'x' if state else ' '}] "
    return f"{position}. " if ordered else "- "


def html_to_markdown(document: str) -> str:
    """Convert an HTML fragment or document to Markdown text."""
    return markdown_text(parse_html(document)).strip()
