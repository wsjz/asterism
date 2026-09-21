"""Pure conversion helpers shared by every source adapter.

Nothing in this package imports other Asterism modules or performs I/O.
Functions raise ``ValueError`` on bad input; adapters translate that into
their own error types.
"""
from .datetimes import parse_datetime
from .markdown import html_to_markdown
from .titles import derive_title
from .urls import canonical_url

__all__ = ["canonical_url", "derive_title", "html_to_markdown", "parse_datetime"]
