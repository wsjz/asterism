"""Content projects: the object the pipeline produces, one folder per piece."""
from .model import BRIEF_FILE, PROJECT_FILE, ContentProject, ProjectError, split_front_matter
from .confirm import Angle, angles, confirm_project, offers_angles
from .gather import Gathered, gather_into, matching_items
from .index import INDEX_FILE, write_views
from .lifecycle import drop_project, restore_project
from .paths import next_id, render_path, unique_directory
from .registry import Registry, load_projects
from .scaffold import create_project, ensure_template, render_template
from .stages import ARTIFACT_ORDER, artifact_path, find_artifact, stage_directory, stage_for_artifact

__all__ = [
    "Angle",
    "BRIEF_FILE",
    "ContentProject",
    "Gathered",
    "PROJECT_FILE",
    "ProjectError",
    "INDEX_FILE",
    "Registry",
    "angles",
    "ARTIFACT_ORDER",
    "artifact_path",
    "confirm_project",
    "create_project",
    "drop_project",
    "find_artifact",
    "gather_into",
    "ensure_template",
    "load_projects",
    "matching_items",
    "next_id",
    "offers_angles",
    "render_path",
    "render_template",
    "restore_project",
    "split_front_matter",
    "stage_directory",
    "stage_for_artifact",
    "unique_directory",
    "write_views",
]
