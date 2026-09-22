"""Content projects: the object the pipeline produces, one folder per piece."""
from .model import BRIEF_FILE, PROJECT_FILE, ContentProject, ProjectError, split_front_matter
from .index import INDEX_FILE, write_views
from .lifecycle import drop_project, restore_project
from .paths import next_id, render_path, unique_directory
from .registry import Registry, load_projects
from .scaffold import create_project, ensure_template, render_template
from .stages import artifact_path, stage_directory, stage_for_artifact

__all__ = [
    "BRIEF_FILE",
    "ContentProject",
    "PROJECT_FILE",
    "ProjectError",
    "INDEX_FILE",
    "Registry",
    "artifact_path",
    "create_project",
    "drop_project",
    "ensure_template",
    "load_projects",
    "next_id",
    "render_path",
    "render_template",
    "restore_project",
    "split_front_matter",
    "stage_directory",
    "stage_for_artifact",
    "unique_directory",
    "write_views",
]
