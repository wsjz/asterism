"""Generic adapter over the opencli command-line tool.

Asterism guarantees the pipeline contract here: safe subprocess use, JSON
parsing, size limits, validation, and stable identity. The meaning of each
column comes from opencli's community adapters and the user's mapping.
"""
from .source import OpencliSource, Runner, run_opencli

__all__ = ["OpencliSource", "Runner", "run_opencli"]
