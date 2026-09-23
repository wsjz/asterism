"""Turning a project's material into a draft, its checks, and platform versions."""
from .skeleton import DRAFT_FILE, MATERIAL_HEADING, compose_draft, draft_path
from .checks import Finding, check_draft
from .adapt import EXPORTS_DIR, adapt_project, export_path, platform_rules_path

__all__ = [
    "DRAFT_FILE",
    "EXPORTS_DIR",
    "Finding",
    "MATERIAL_HEADING",
    "adapt_project",
    "check_draft",
    "compose_draft",
    "draft_path",
    "export_path",
    "platform_rules_path",
]
