"""A small HTML tree parser and HTML-to-Markdown conversion (standard library only)."""
from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
import re
from typing import Iterator


BLOCK_TAGS = frozenset({"article", "blockquote", "div", "h1", "h2", "h3", "li", "p", "section"})
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


def markdown_text(node: Node) -> str:
    """Render a tree as Markdown: emphasis, links, list items, line breaks, blocks."""
    parts: list[str] = []
    for child in node.children:
        if isinstance(child, str):
            parts.append(child)
            continue
        if child.tag == "br":
            parts.append("\n")
            continue
        prefix = "- " if child.tag == "li" else ""
        body = markdown_text(child)
        if child.tag in {"b", "strong"}:
            body = f"**{body.strip()}**"
        elif child.tag in {"em", "i"}:
            body = f"*{body.strip()}*"
        elif child.tag == "a" and child.attrs.get("href", "").startswith(("http://", "https://")):
            body = f"[{body.strip()}]({child.attrs['href']})"
        parts.append(prefix + body)
        if child.tag in BLOCK_TAGS:
            parts.append("\n")
    text = "".join(parts).replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"\n{3,}", "\n\n", text)


def html_to_markdown(document: str) -> str:
    """Convert an HTML fragment or document to Markdown text."""
    return markdown_text(parse_html(document)).strip()
