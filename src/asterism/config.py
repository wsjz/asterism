from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import re
from string import Formatter
import tomllib
from typing import Any, Mapping

import yaml

from .vault import VaultPathError, atomic_write
from .vault import normalize_vault as _normalize_vault


CONFIG_NAME = "asterism.yaml"
LEGACY_CONFIG_NAME = "asterism.toml"
VALID_STATE_BACKENDS = frozenset({"file", "sqlite"})

MAX_PATH_LENGTH = 4096
MAX_SHORT_STRING = 255


class ConfigError(ValueError):
    """The configuration file is missing, ambiguous, or invalid."""


DIGEST_LEVELS: tuple[str, ...] = ("day", "week", "month", "year")
LINK_STYLES = frozenset({"wikilink", "markdown"})
MONTH_RUN_ON_LAST = "last"


@dataclass(frozen=True, slots=True)
class DigestLevelConfig:
    """One aggregation level.

    ``run_on`` is the day a period ends: an ISO weekday (1–7) for weeks; for
    months an integer N (the last day of the N-th seven-day block), a tuple of
    ``MM-DD`` strings (one end day per month), or ``"last"``; for years the
    month (1–12) whose last day ends the period. Days have no ``run_on``.
    ``include_lower`` embeds the lower level's documents; ``archive_lower``
    archives them after rolling up when archiving is enabled.
    """

    enabled: bool
    run_on: int | tuple[str, ...] | str | None = None
    include_lower: bool = True
    archive_lower: bool = False


@dataclass(frozen=True, slots=True)
class DigestConfig:
    timezone: str | None = None  # IANA name; None means the system's local zone
    after_sync: bool = True
    excerpt_chars: int = 300
    day: DigestLevelConfig = DigestLevelConfig(enabled=True)
    week: DigestLevelConfig = DigestLevelConfig(enabled=True, run_on=7)
    month: DigestLevelConfig = DigestLevelConfig(enabled=True, run_on=MONTH_RUN_ON_LAST)
    year: DigestLevelConfig = DigestLevelConfig(enabled=False, run_on=12)
    llm_summary: bool = False
    llm_placement: str = "separate"

    def level(self, name: str) -> DigestLevelConfig:
        return getattr(self, name)


ARCHIVE_MODES = frozenset({"copy", "move"})
# The folder macOS Notes uses for deleted notes, in English and in Chinese
# (U+6700 U+8FD1 U+5220 U+9664, "zui jin shan chu", literally "recently deleted").
RECENTLY_DELETED_FOLDERS: tuple[str, ...] = ("Recently Deleted", "\u6700\u8fd1\u5220\u9664")
DEFAULT_EXCLUDED_NOTES_FOLDERS: tuple[str, ...] = RECENTLY_DELETED_FOLDERS

_COLLECTION_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_COMMAND_WORD = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_ARG_NAME = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_FIELD_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
CONTENT_FORMATS = frozenset({"text", "html", "markdown"})


@dataclass(frozen=True, slots=True)
class OpencliMap:
    """Which columns of a command's rows feed which SourceItem slots.

    Everything not mapped or excluded lands in ``source_meta`` as a scalar.
    """

    id: str | None = None
    url: str | None = None
    title: str | None = None
    content: tuple[str, ...] = ()
    content_format: str = "text"
    created_at: str | None = None
    updated_at: str | None = None
    author: str | None = None
    tags: str | None = None
    tag_separator: str = ","
    parent: str | None = None
    exclude: tuple[str, ...] = ()

    def mapped_fields(self) -> tuple[str, ...]:
        names = [
            value
            for value in (self.id, self.url, self.title, self.created_at, self.updated_at, self.author, self.tags, self.parent)
            if value
        ]
        return tuple(dict.fromkeys((*names, *self.content)))


@dataclass(frozen=True, slots=True)
class OpencliCollection:
    name: str  # also the output directory suffix: notes/opencli-<name>/
    command: tuple[str, str]  # (site, command)
    args: tuple[tuple[str, str | int | bool], ...] = ()
    map: OpencliMap = OpencliMap()

    @property
    def producer(self) -> str:
        return f"{self.command[0]}/{self.command[1]}"


@dataclass(frozen=True, slots=True)
class OpencliConfig:
    binary: str | None = None  # None: look up "opencli" on PATH
    collections: tuple[OpencliCollection, ...] = ()

    def collection(self, name: str) -> OpencliCollection | None:
        return next((entry for entry in self.collections if entry.name == name), None)


@dataclass(frozen=True, slots=True)
class StorageConfig:
    media_root: Path | None = None  # large files; may be a NAS mount. None: inside the vault
    inbox: tuple[Path, ...] = ()  # unassigned captures; the only places Asterism moves files from


@dataclass(frozen=True, slots=True)
class ArchiveConfig:
    enabled: bool = False  # master switch: when off nothing is moved or copied anywhere
    root: Path | None = None  # None: <vault>/archive
    mode: str = "copy"  # applies to digests only; project folders are always copied
    on_publish: bool = False
    auto_execute: bool = False


MATERIAL_DECISIONS: tuple[str, ...] = ("later", "reference", "used", "dropped")


@dataclass(frozen=True, slots=True)
class ReviewRule:
    """What a source's items are suggested for, and whether to ask at all."""

    source: str  # the source's directory name, as under notes/
    default: str
    parent: str | None = None  # limit the rule to a folder and everything under it
    auto: bool = False  # apply without listing; the sheet shows a one-line summary

    def matches(self, source_dir: str, source_name: str, parent: str) -> bool:
        if self.source not in (source_dir, source_name):
            return False
        if self.parent is None:
            return True
        return parent == self.parent or parent.startswith(self.parent + "/")


@dataclass(frozen=True, slots=True)
class ReviewConfig:
    every: int = 7  # days; only used to say how long it has been
    rules: tuple[ReviewRule, ...] = ()

    def rule_for(self, source_dir: str, source_name: str, parent: str) -> ReviewRule | None:
        return next(
            (rule for rule in self.rules if rule.matches(source_dir, source_name, parent)), None
        )


DEFAULT_TYPES: tuple[str, ...] = ("tutorial", "review", "makeover", "opinion", "checklist")
DEFAULT_PLATFORMS: tuple[str, ...] = ("blog", "zhihu", "xiaohongshu", "douyin", "sspai", "flowus")
PROJECT_LAYOUTS = frozenset({"flat", "staged"})
# Five steps, three gates, and one exit. See docs/state-model.md.
PROJECT_STATUSES: tuple[str, ...] = (
    "candidate",
    "making",
    "ready",
    "published",
    "retrospected",
    "dropped",
)
LIVE_PROJECT_STATUSES: tuple[str, ...] = tuple(s for s in PROJECT_STATUSES if s != "dropped")
PATH_PLACEHOLDERS = frozenset({"year", "date", "title", "id", "pillar", "type"})
BINDING_NAMES = frozenset({"unassigned_media", "platform_exports", "covers"})

_KEY = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}$")


@dataclass(frozen=True, slots=True)
class Pillar:
    """A content pillar: a lasting subject the creator publishes about."""

    key: str
    name: str
    tags: tuple[str, ...] = ()  # aliases matched against an item's tags and folders
    brief: str | None = None  # template path relative to the vault


@dataclass(frozen=True, slots=True)
class ContentConfig:
    pillars: tuple[Pillar, ...] = ()
    types: tuple[str, ...] = DEFAULT_TYPES
    platforms: tuple[str, ...] = DEFAULT_PLATFORMS

    def pillar(self, key: str | None) -> Pillar | None:
        return next((entry for entry in self.pillars if entry.key == key), None)


@dataclass(frozen=True, slots=True)
class Stage:
    """One step of production, and therefore one directory in a project."""

    key: str
    artifacts: tuple[str, ...] = ()
    media: tuple[str, ...] = ()
    media_per_platform: bool = False
    dir: str | None = None  # explicit directory name, overriding the numbered key


DEFAULT_STAGES: tuple[Stage, ...] = (
    Stage("brief", artifacts=("project.md", "brief.md")),
    Stage("research", artifacts=("assets.md",)),
    Stage("originals", media=("photo", "video", "screen-recording")),
    Stage("project", media=("editing",)),
    Stage("export", media_per_platform=True),
    Stage("cover", media=("cover",)),
    Stage("archive", artifacts=("draft.md", "exports/", "review.md")),
)
DEFAULT_BINDINGS: dict[str, str] = {
    "unassigned_media": "originals",
    "platform_exports": "export",
    "covers": "cover",
}


@dataclass(frozen=True, slots=True)
class ProjectConfig:
    id_format: str = "{year}-{seq:03d}"
    path: str = "{year}/{date}-{title}"
    layout: str = "flat"
    numbered: bool = True
    stages: tuple[Stage, ...] = DEFAULT_STAGES
    bindings: tuple[tuple[str, str], ...] = tuple(sorted(DEFAULT_BINDINGS.items()))

    def stage(self, key: str) -> Stage | None:
        return next((entry for entry in self.stages if entry.key == key), None)

    def bound_stage(self, binding: str) -> Stage | None:
        key = dict(self.bindings).get(binding)
        return self.stage(key) if key else None


@dataclass(frozen=True, slots=True)
class Config:
    vault: Path
    state_backend: str
    apple_notes_account: str | None
    flomo_export_path: Path | None
    markdown_roots: tuple[Path, ...]
    notion_root_page_ids: tuple[str, ...]
    notion_data_source_ids: tuple[str, ...]
    notion_discover_all: bool
    apple_notes_daily_log_folders: tuple[str, ...] = ()
    apple_notes_timezone: str | None = None
    apple_notes_exclude_folders: tuple[str, ...] = DEFAULT_EXCLUDED_NOTES_FOLDERS
    digest: DigestConfig = DigestConfig()
    links: str = "wikilink"
    storage: StorageConfig = StorageConfig()
    archive: ArchiveConfig = ArchiveConfig()
    state_dir_override: Path | None = None
    opencli: OpencliConfig = OpencliConfig()
    content: ContentConfig = ContentConfig()
    review: ReviewConfig = ReviewConfig()
    project: ProjectConfig = ProjectConfig()

    @property
    def archive_root(self) -> Path:
        return self.archive.root if self.archive.root is not None else self.vault / "archive"

    @property
    def content_root(self) -> Path:
        return self.vault / "content"

    @property
    def trash_root(self) -> Path:
        """Where dropped projects wait; nothing is ever deleted."""
        return self.vault / "trash"

    @property
    def templates_root(self) -> Path:
        return self.vault / "templates"

    @property
    def notes_root(self) -> Path:
        # All normalized sources live below one vault-local notes root. Each
        # adapter supplies its own validated output directory name.
        return self.vault / "notes"

    @property
    def notes_dir(self) -> Path:
        """Apple Notes output path kept for configuration compatibility."""
        return self.notes_root / "apple-notes"

    @property
    def state_dir(self) -> Path:
        return self.state_dir_override if self.state_dir_override is not None else self.vault / "state"


def normalize_vault(path: Path) -> Path:
    try:
        return _normalize_vault(path)
    except VaultPathError as error:
        raise ConfigError(str(error)) from error


def config_path(vault: Path) -> Path:
    return normalize_vault(vault) / CONFIG_NAME


def load_config(vault: Path) -> Config:
    root = normalize_vault(vault)
    yaml_path = root / CONFIG_NAME
    legacy_path = root / LEGACY_CONFIG_NAME

    if yaml_path.is_file() and legacy_path.is_file():
        raise ConfigError(
            f"both {CONFIG_NAME} and {LEGACY_CONFIG_NAME} exist in {root}; "
            f"delete {LEGACY_CONFIG_NAME} after checking the YAML file"
        )
    if not yaml_path.is_file():
        if legacy_path.is_file():
            raise ConfigError(
                f"{LEGACY_CONFIG_NAME} is no longer read; run "
                f"'asterism migrate-config --vault {root}' to create {CONFIG_NAME}"
            )
        raise FileNotFoundError(f"configuration not found: {yaml_path}")

    raw = _read_yaml(yaml_path)
    return _build_config(root, raw)


def migrate_config(vault: Path) -> Path:
    """Write asterism.yaml from an existing asterism.toml without deleting it."""
    root = normalize_vault(vault)
    legacy_path = root / LEGACY_CONFIG_NAME
    yaml_path = root / CONFIG_NAME
    if not legacy_path.is_file():
        raise FileNotFoundError(f"nothing to migrate: {legacy_path} does not exist")
    if yaml_path.exists():
        raise FileExistsError(f"refusing to overwrite existing {yaml_path}")

    with legacy_path.open("rb") as handle:
        data = tomllib.load(handle)
    # Validate before writing so a broken TOML file never becomes a broken YAML file.
    _build_config(root, data)
    rendered = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, default_flow_style=False)
    atomic_write(yaml_path, rendered)
    return yaml_path


def initialize_vault(vault: Path, state_backend: str) -> Config:
    root = normalize_vault(vault)
    if state_backend not in VALID_STATE_BACKENDS:
        raise ConfigError("state backend must be 'file' or 'sqlite'")

    root.mkdir(parents=True, exist_ok=True)
    if not root.is_dir():
        raise ConfigError(f"vault is not a directory: {root}")

    for relative in ("notes", "state", "logs"):
        destination = (root / relative).resolve(strict=False)
        if not destination.is_relative_to(root):
            raise ConfigError("refusing to create a path outside the vault")
        destination.mkdir(parents=True, exist_ok=True)

    path = root / CONFIG_NAME
    if path.exists() or (root / LEGACY_CONFIG_NAME).exists():
        raise FileExistsError(f"configuration already exists in {root}")

    path.write_text(_default_config_text(state_backend), encoding="utf-8")
    ignore_path = root / ".gitignore"
    if not ignore_path.exists():
        ignore_path.write_text(
            "state/*\n!state/.gitkeep\nlogs/*\n!logs/.gitkeep\n*.tmp\n",
            encoding="utf-8",
        )
    for keep_path in (root / "state" / ".gitkeep", root / "logs" / ".gitkeep"):
        keep_path.touch(exist_ok=True)
    return Config(root, state_backend, None, None, (), (), (), False)


def _default_config_text(state_backend: str) -> str:
    return (
        "# Asterism vault configuration. Values are validated strictly after\n"
        "# loading; quote values such as \"01-31\" that YAML would otherwise\n"
        "# interpret as numbers or dates.\n"
        "state:\n"
        f"  backend: {state_backend}\n"
        "\n"
        "sources:\n"
        "  apple_notes:\n"
        "    # account: iCloud\n"
        "    # Notes in these folders are split into one item per time-stamped line.\n"
        "    # daily_log_folders:\n"
        "    #   - Daily Log\n"
        "    # timezone: Asia/Shanghai\n"
        "  flomo:\n"
        "    # export_path: /path/to/flomo-export.zip\n"
        "  markdown:\n"
        "    # roots:\n"
        "    #   - /path/to/ObsidianVault\n"
        "  notion:\n"
        "    # root_page_ids:\n"
        "    #   - 00000000-0000-0000-0000-000000000000\n"
        "    # data_source_ids: []\n"
        "    # discover_all: false\n"
        "\n"
        "# Periodic digests of collected items. Each level is independent; a period\n"
        "# ends on its run_on day. Defaults: daily and weekly (ending Sunday) and\n"
        "# monthly (ending on the last day), yearly off.\n"
        "# digest:\n"
        "#   timezone: Asia/Shanghai\n"
        "#   week: { run_on: 3, include_days: true, archive_days: false }\n"
        "#   month: { run_on: last }\n"
        "#   year: { enabled: false, run_on: 12 }\n"
        "\n"
        "  # opencli: community-maintained site commands. Only read-only commands\n"
        "  # listed here run; the mapping decides which columns become fields.\n"
        "  # opencli:\n"
        "  #   collections:\n"
        "  #     - name: twitter-bookmarks\n"
        "  #       command: [twitter, bookmarks]\n"
        "  #       args: { limit: 200 }\n"
        "  #       map: { id: id, url: url, content: [text], created_at: created_at, author: author }\n"
        "\n"
        "# Review: how often you sort collected material, and what each source\n"
        "# is suggested for. A rule with auto: true is applied without listing.\n"
        "# review:\n"
        "#   every: 3\n"
        "#   rules:\n"
        "#     - { source: apple-notes, parent: Daily Log, default: dropped, auto: true }\n"
        "#     - { source: cubox, default: reference }\n"
        "\n"
        "# Link style in generated Markdown: wikilink (Obsidian) or markdown.\n"
        "links: wikilink\n"
        "\n"
        "# Large files and unassigned captures. media_root may be a NAS mount.\n"
        "# storage:\n"
        "#   media_root: /Volumes/Content\n"
        "#   inbox:\n"
        "#     - ~/ContentVault/inbox\n"
        "\n"
        "# Archiving is off until enabled; then rolled-up digests (and later,\n"
        "# published projects) are copied or moved below archive.root.\n"
        "# archive:\n"
        "#   enabled: false\n"
        "#   root: /Volumes/Archive/Content\n"
        "#   mode: copy\n"
    )


# --- loading and validation -------------------------------------------------


def _read_yaml(path: Path) -> Mapping[str, Any]:
    if path.stat().st_size > 1_000_000:
        raise ConfigError(f"{path.name} is unexpectedly large")
    with path.open(encoding="utf-8") as handle:
        try:
            loaded = yaml.safe_load(handle)
        except yaml.YAMLError as error:
            raise ConfigError(f"{path.name} is not valid YAML: {error}") from error
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ConfigError(f"{path.name} must contain a mapping at the top level")
    return loaded


def _build_config(root: Path, raw: Mapping[str, Any]) -> Config:
    state = _table(raw, "state")
    backend = state.get("backend")
    if backend not in VALID_STATE_BACKENDS:
        raise ConfigError("state.backend must be 'file' or 'sqlite'")
    state_dir = _optional_path(state, "state_dir", "state.state_dir", root)

    storage_table = _table(raw, "storage")
    storage = StorageConfig(
        media_root=_optional_path(storage_table, "media_root", "storage.media_root", root),
        inbox=_path_list(storage_table, "inbox", "storage.inbox", root),
    )
    archive_table = _table(raw, "archive")
    archive_mode = archive_table.get("mode", "copy")
    if archive_mode not in ARCHIVE_MODES:
        raise ConfigError("archive.mode must be 'copy' or 'move'")
    archive = ArchiveConfig(
        enabled=_bool(archive_table, "enabled", False, "archive.enabled"),
        root=_optional_path(archive_table, "root", "archive.root", root),
        mode=archive_mode,
        on_publish=_bool(archive_table, "on_publish", False, "archive.on_publish"),
        auto_execute=_bool(archive_table, "auto_execute", False, "archive.auto_execute"),
    )

    sources = _table(raw, "sources")

    apple_notes = _table(sources, "apple_notes", "sources.apple_notes")
    account = _optional_short_string(apple_notes, "account", "sources.apple_notes.account")
    daily_log_folders = _string_list(
        apple_notes, "daily_log_folders", "sources.apple_notes.daily_log_folders"
    )
    apple_timezone = _optional_short_string(apple_notes, "timezone", "sources.apple_notes.timezone")
    if apple_timezone is not None:
        _validate_timezone(apple_timezone, "sources.apple_notes.timezone")
    exclude_folders = DEFAULT_EXCLUDED_NOTES_FOLDERS
    if "exclude_folders" in apple_notes:
        exclude_folders = _string_list(apple_notes, "exclude_folders", "sources.apple_notes.exclude_folders")

    flomo = _table(sources, "flomo", "sources.flomo")
    export_path = _optional_path(flomo, "export_path", "sources.flomo.export_path", root)

    markdown = _table(sources, "markdown", "sources.markdown")
    markdown_roots = _path_list(markdown, "roots", "sources.markdown.roots", root)

    notion = _table(sources, "notion", "sources.notion")
    root_page_ids = _string_list(notion, "root_page_ids", "sources.notion.root_page_ids")
    data_source_ids = _string_list(notion, "data_source_ids", "sources.notion.data_source_ids")
    discover_all = notion.get("discover_all", False)
    if not isinstance(discover_all, bool):
        raise ConfigError("sources.notion.discover_all must be true or false")

    opencli = _opencli_config(_table(sources, "opencli", "sources.opencli"))

    digest = _digest_config(_table(raw, "digest"))
    links = raw.get("links", "wikilink")
    if links not in LINK_STYLES:
        raise ConfigError("links must be 'wikilink' or 'markdown'")

    content = _content_config(_table(raw, "content"))
    review = _review_config(_table(raw, "review"))
    project = _project_config(_table(raw, "project"), content)

    return Config(
        vault=root,
        state_backend=backend,
        apple_notes_account=account,
        flomo_export_path=export_path,
        markdown_roots=markdown_roots,
        notion_root_page_ids=root_page_ids,
        notion_data_source_ids=data_source_ids,
        notion_discover_all=discover_all,
        apple_notes_daily_log_folders=daily_log_folders,
        apple_notes_timezone=apple_timezone,
        digest=digest,
        links=links,
        storage=storage,
        archive=archive,
        state_dir_override=state_dir,
        opencli=opencli,
        content=content,
        review=review,
        project=project,
    )


def _review_config(table: Mapping[str, Any]) -> ReviewConfig:
    defaults = ReviewConfig()
    every = table.get("every", defaults.every)
    if not isinstance(every, int) or isinstance(every, bool) or not 1 <= every <= 365:
        raise ConfigError("review.every must be a number of days between 1 and 365")
    raw_rules = table.get("rules", [])
    if not isinstance(raw_rules, list) or len(raw_rules) > 100:
        raise ConfigError("review.rules must be a list")
    rules: list[ReviewRule] = []
    for index, entry in enumerate(raw_rules):
        label = f"review.rules[{index}]"
        if not isinstance(entry, dict):
            raise ConfigError(f"{label} must be a mapping")
        source = entry.get("source")
        if not isinstance(source, str) or not source.strip() or len(source) > 64:
            raise ConfigError(f"{label}.source must name a collected source")
        default = entry.get("default")
        if default not in MATERIAL_DECISIONS:
            raise ConfigError(
                f"{label}.default must be one of {', '.join(MATERIAL_DECISIONS)}"
            )
        auto = _bool(entry, "auto", False, f"{label}.auto")
        if auto and default == "used":
            raise ConfigError(
                f"{label} cannot apply 'used' automatically; making a project is a decision"
            )
        parent = _optional_short_string(entry, "parent", f"{label}.parent")
        if parent is not None:
            _require_relative(parent, f"{label}.parent")
        rules.append(
            ReviewRule(
                source=source.strip(),
                default=default,
                parent=parent,
                auto=auto,
            )
        )
    return ReviewConfig(every=every, rules=tuple(rules))


def _content_config(table: Mapping[str, Any]) -> ContentConfig:
    defaults = ContentConfig()
    raw_pillars = table.get("pillars", [])
    if not isinstance(raw_pillars, list) or len(raw_pillars) > 50:
        raise ConfigError("content.pillars must be a list of at most 50 entries")
    pillars: list[Pillar] = []
    for index, entry in enumerate(raw_pillars):
        label = f"content.pillars[{index}]"
        if not isinstance(entry, dict):
            raise ConfigError(f"{label} must be a mapping")
        key = entry.get("key")
        if not isinstance(key, str) or _KEY.match(key) is None or len(key) > 40:
            raise ConfigError(f"{label}.key must be a short lowercase slug such as vibe-coding")
        if any(existing.key == key for existing in pillars):
            raise ConfigError(f"{label}.key duplicates another pillar: {key}")
        name = _optional_short_string(entry, "name", f"{label}.name") or key
        aliases = _string_list(entry, "tags", f"{label}.tags")
        brief = _optional_short_string(entry, "brief", f"{label}.brief")
        if brief is not None:
            _require_relative(brief, f"{label}.brief")
        pillars.append(Pillar(key=key, name=name, tags=(key, *aliases), brief=brief))

    types = _slug_list(table, "types", "content.types") or defaults.types
    platforms = _slug_list(table, "platforms", "content.platforms") or defaults.platforms
    return ContentConfig(pillars=tuple(pillars), types=types, platforms=platforms)


def _project_config(table: Mapping[str, Any], content: ContentConfig) -> ProjectConfig:
    defaults = ProjectConfig()
    id_format = _optional_short_string(table, "id_format", "project.id_format") or defaults.id_format
    _check_id_format(id_format)
    path = _optional_short_string(table, "path", "project.path") or defaults.path
    _check_path_template(path)
    layout = table.get("layout", defaults.layout)
    if layout not in PROJECT_LAYOUTS:
        raise ConfigError("project.layout must be 'flat' or 'staged'")
    numbered = _bool(table, "numbered", defaults.numbered, "project.numbered")

    stages = defaults.stages
    if "stages" in table:
        stages = _stages(table["stages"])
    bindings = dict(defaults.bindings) if "stages" not in table else {}
    if "bindings" in table:
        raw_bindings = table["bindings"]
        if not isinstance(raw_bindings, dict):
            raise ConfigError("project.bindings must be a mapping")
        bindings = {}
        for name, key in raw_bindings.items():
            if name not in BINDING_NAMES:
                raise ConfigError(
                    f"project.bindings.{name} is not a binding; use one of {', '.join(sorted(BINDING_NAMES))}"
                )
            if not isinstance(key, str) or not any(stage.key == key for stage in stages):
                raise ConfigError(f"project.bindings.{name} must name one of the configured stages")
            bindings[name] = key
    for name, key in bindings.items():
        if not any(stage.key == key for stage in stages):
            raise ConfigError(f"project.bindings.{name} names an unknown stage: {key}")
    exports = bindings.get("platform_exports")
    if exports is not None:
        stage = next(entry for entry in stages if entry.key == exports)
        if not stage.media_per_platform:
            raise ConfigError(
                "project.bindings.platform_exports must name a stage with media_per_platform: true"
            )
    return ProjectConfig(
        id_format=id_format,
        path=path,
        layout=layout,
        numbered=numbered,
        stages=stages,
        bindings=tuple(sorted(bindings.items())),
    )


def _stages(value: Any) -> tuple[Stage, ...]:
    if not isinstance(value, list) or not value or len(value) > 30:
        raise ConfigError("project.stages must be a non-empty list of at most 30 stages")
    stages: list[Stage] = []
    for index, entry in enumerate(value):
        label = f"project.stages[{index}]"
        if not isinstance(entry, dict):
            raise ConfigError(f"{label} must be a mapping")
        key = entry.get("key")
        if not isinstance(key, str) or _KEY.match(key) is None or len(key) > 40:
            raise ConfigError(f"{label}.key must be a short lowercase slug such as originals")
        if any(existing.key == key for existing in stages):
            raise ConfigError(f"{label}.key duplicates another stage: {key}")
        artifacts = _string_list(entry, "artifacts", f"{label}.artifacts")
        for artifact in artifacts:
            _require_relative(artifact, f"{label}.artifacts")
        media = _slug_list(entry, "media", f"{label}.media")
        per_platform = _bool(entry, "media_per_platform", False, f"{label}.media_per_platform")
        directory = _optional_short_string(entry, "dir", f"{label}.dir")
        if directory is not None and _SAFE_SEGMENT.match(directory) is None:
            raise ConfigError(f"{label}.dir must be a plain directory name")
        stages.append(
            Stage(key=key, artifacts=artifacts, media=media, media_per_platform=per_platform, dir=directory)
        )
    return tuple(stages)


def _slug_list(table: Mapping[str, Any], key: str, label: str) -> tuple[str, ...]:
    values = _string_list(table, key, label)
    for value in values:
        if _KEY.match(value) is None:
            raise ConfigError(f"{label} entries must be short lowercase slugs: {value!r}")
    return values


def _require_relative(value: str, label: str) -> None:
    candidate = PurePosixPath(value)
    if candidate.is_absolute() or ".." in candidate.parts or value.startswith("/"):
        raise ConfigError(f"{label} must be a relative path inside the project: {value!r}")


def _check_id_format(value: str) -> None:
    try:
        rendered = value.format(year=2026, seq=1, pillar="x", type="y")
    except (KeyError, IndexError, ValueError) as error:
        raise ConfigError(
            "project.id_format may use {year}, {seq}, {pillar} and {type}, for example '{year}-{seq:03d}'"
        ) from error
    if "{seq" not in value or not rendered.strip():
        raise ConfigError("project.id_format must include {seq} so ids stay unique")
    if _SAFE_SEGMENT.match(rendered) is None:
        raise ConfigError(f"project.id_format produces an unsafe id: {rendered!r}")


def _check_path_template(value: str) -> None:
    _require_relative(value, "project.path")
    names = {name for _, name, _, _ in Formatter().parse(value) if name}
    unknown = names - PATH_PLACEHOLDERS
    if unknown:
        raise ConfigError(
            f"project.path uses unknown placeholders: {', '.join(sorted(unknown))}; "
            f"available are {', '.join(sorted(PATH_PLACEHOLDERS))}"
        )
    if not names & {"title", "id"}:
        raise ConfigError("project.path must include {title} or {id} so projects have distinct folders")


def _opencli_config(table: Mapping[str, Any]) -> OpencliConfig:
    binary = _optional_short_string(table, "binary", "sources.opencli.binary")
    if binary is not None and ("/" in binary or "\\" in binary or " " in binary):
        raise ConfigError("sources.opencli.binary must be a bare command name found on PATH")
    raw_collections = table.get("collections", [])
    if not isinstance(raw_collections, list) or len(raw_collections) > 100:
        raise ConfigError("sources.opencli.collections must be a list")
    collections: list[OpencliCollection] = []
    for index, entry in enumerate(raw_collections):
        label = f"sources.opencli.collections[{index}]"
        if not isinstance(entry, dict):
            raise ConfigError(f"{label} must be a mapping")
        name = entry.get("name")
        if not isinstance(name, str) or not _COLLECTION_NAME.match(name) or len(name) > 40:
            raise ConfigError(f"{label}.name must be a short lowercase slug such as twitter-bookmarks")
        if any(existing.name == name for existing in collections):
            raise ConfigError(f"{label}.name duplicates another collection: {name}")
        command = entry.get("command")
        if (
            not isinstance(command, list)
            or len(command) != 2
            or not all(isinstance(word, str) and _COMMAND_WORD.match(word) for word in command)
        ):
            raise ConfigError(f"{label}.command must be [site, command], e.g. [twitter, bookmarks]")
        args_table = entry.get("args", {})
        if not isinstance(args_table, dict) or len(args_table) > 20:
            raise ConfigError(f"{label}.args must be a mapping of at most 20 options")
        args: list[tuple[str, str | int | bool]] = []
        for key, value in args_table.items():
            if not isinstance(key, str) or not _ARG_NAME.match(key):
                raise ConfigError(f"{label}.args keys must be lowercase option names such as limit")
            if isinstance(value, bool) or (isinstance(value, int) and -1_000_000 < value < 1_000_000):
                args.append((key, value))
            elif isinstance(value, str) and value and len(value) <= 1000 and "\n" not in value:
                args.append((key, value))
            else:
                raise ConfigError(f"{label}.args.{key} must be a short string, an integer, or a boolean")
        mapping = _opencli_map(_table(entry, "map", f"{label}.map"), f"{label}.map")
        collections.append(OpencliCollection(name, (command[0], command[1]), tuple(args), mapping))
    return OpencliConfig(binary=binary, collections=tuple(collections))


def _opencli_map(table: Mapping[str, Any], label: str) -> OpencliMap:
    def field(key: str) -> str | None:
        value = table.get(key)
        if value is None:
            return None
        if not isinstance(value, str) or not _FIELD_NAME.match(value):
            raise ConfigError(f"{label}.{key} must be a column name")
        return value

    content_value = table.get("content", [])
    if isinstance(content_value, str):
        content_value = [content_value]
    if not isinstance(content_value, list) or not all(isinstance(v, str) and _FIELD_NAME.match(v) for v in content_value):
        raise ConfigError(f"{label}.content must be a column name or a list of column names")
    content_format = table.get("content_format", "text")
    if content_format not in CONTENT_FORMATS:
        raise ConfigError(f"{label}.content_format must be text, html, or markdown")
    separator = table.get("tag_separator", ",")
    if not isinstance(separator, str) or not 1 <= len(separator) <= 3:
        raise ConfigError(f"{label}.tag_separator must be one to three characters")
    exclude_value = table.get("exclude", [])
    if not isinstance(exclude_value, list) or not all(isinstance(v, str) and _FIELD_NAME.match(v) for v in exclude_value):
        raise ConfigError(f"{label}.exclude must be a list of column names")
    mapping = OpencliMap(
        id=field("id"),
        url=field("url"),
        title=field("title"),
        content=tuple(content_value),
        content_format=content_format,
        created_at=field("created_at"),
        updated_at=field("updated_at"),
        author=field("author"),
        tags=field("tags"),
        tag_separator=separator,
        parent=field("parent"),
        exclude=tuple(exclude_value),
    )
    if mapping.id is None and mapping.url is None:
        raise ConfigError(f"{label} must map id or url so items have a stable identity")
    return mapping


def _digest_config(table: Mapping[str, Any]) -> DigestConfig:
    defaults = DigestConfig()
    timezone = _optional_short_string(table, "timezone", "digest.timezone")
    if timezone is not None:
        _validate_timezone(timezone, "digest.timezone")
    after_sync = _bool(table, "after_sync", defaults.after_sync, "digest.after_sync")
    excerpt = table.get("excerpt_chars", defaults.excerpt_chars)
    if not isinstance(excerpt, int) or isinstance(excerpt, bool) or not 20 <= excerpt <= 10_000:
        raise ConfigError("digest.excerpt_chars must be an integer between 20 and 10000")

    llm = _table(table, "llm", "digest.llm")
    llm_summary = _bool(llm, "summary", defaults.llm_summary, "digest.llm.summary")
    placement = llm.get("placement", defaults.llm_placement)
    if placement not in {"separate", "inline"}:
        raise ConfigError("digest.llm.placement must be 'separate' or 'inline'")

    return DigestConfig(
        timezone=timezone,
        after_sync=after_sync,
        excerpt_chars=excerpt,
        day=_digest_level(_table(table, "day", "digest.day"), "day", defaults.day),
        week=_digest_level(_table(table, "week", "digest.week"), "week", defaults.week),
        month=_digest_level(_table(table, "month", "digest.month"), "month", defaults.month),
        year=_digest_level(_table(table, "year", "digest.year"), "year", defaults.year),
        llm_summary=llm_summary,
        llm_placement=placement,
    )


_LOWER = {"week": "days", "month": "weeks", "year": "months"}


def _digest_level(table: Mapping[str, Any], name: str, default: DigestLevelConfig) -> DigestLevelConfig:
    label = f"digest.{name}"
    enabled = _bool(table, "enabled", default.enabled, f"{label}.enabled")
    run_on: int | tuple[str, ...] | str | None = default.run_on
    if "run_on" in table:
        run_on = _run_on(table["run_on"], name, label)
    include_lower = default.include_lower
    archive_lower = default.archive_lower
    if name in _LOWER:
        include_lower = _bool(table, f"include_{_LOWER[name]}", default.include_lower, f"{label}.include_{_LOWER[name]}")
        archive_lower = _bool(table, f"archive_{_LOWER[name]}", default.archive_lower, f"{label}.archive_{_LOWER[name]}")
    return DigestLevelConfig(enabled=enabled, run_on=run_on, include_lower=include_lower, archive_lower=archive_lower)


def _run_on(value: Any, name: str, label: str) -> int | tuple[str, ...] | str | None:
    if name == "day":
        raise ConfigError(f"{label}.run_on is not used for days")
    if isinstance(value, bool):
        raise ConfigError(f"{label}.run_on must not be a boolean")
    if name == "week":
        if isinstance(value, int) and 1 <= value <= 7:
            return value
        raise ConfigError(f"{label}.run_on must be an ISO weekday from 1 (Monday) to 7 (Sunday)")
    if name == "year":
        if isinstance(value, int) and 1 <= value <= 12:
            return value
        raise ConfigError(f"{label}.run_on must be a month from 1 to 12")
    # month
    if isinstance(value, int) and 1 <= value <= 5:
        return value
    if value == MONTH_RUN_ON_LAST:
        return MONTH_RUN_ON_LAST
    if isinstance(value, list) and len(value) == 12:
        days: list[str] = []
        for entry in value:
            if not isinstance(entry, str):
                raise ConfigError(
                    f"{label}.run_on entries must be quoted strings such as \"01-31\"; "
                    "unquoted values are read by YAML as numbers or dates"
                )
            parts = entry.split("-")
            if len(parts) != 2 or not all(part.isdigit() for part in parts):
                raise ConfigError(f"{label}.run_on entries must look like MM-DD")
            month, day = int(parts[0]), int(parts[1])
            if month != len(days) + 1 or not 1 <= day <= 31:
                raise ConfigError(f"{label}.run_on must list one MM-DD per month from 01 to 12 in order")
            days.append(f"{month:02d}-{day:02d}")
        return tuple(days)
    raise ConfigError(f"{label}.run_on must be a week index 1–5, a list of twelve MM-DD strings, or 'last'")


def _bool(table: Mapping[str, Any], key: str, default: bool, label: str) -> bool:
    value = table.get(key, default)
    if not isinstance(value, bool):
        raise ConfigError(f"{label} must be true or false")
    return value


def _validate_timezone(name: str, label: str) -> None:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ConfigError(f"{label} must be an IANA timezone name such as Asia/Shanghai") from error


def _table(parent: Mapping[str, Any], key: str, label: str | None = None) -> Mapping[str, Any]:
    value = parent.get(key)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"{label or key} must be a mapping")
    return value


def _optional_short_string(table: Mapping[str, Any], key: str, label: str) -> str | None:
    value = table.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_SHORT_STRING:
        raise ConfigError(f"{label} must be a short non-empty string")
    return value.strip()


def _resolve_path(value: Any, label: str, root: Path) -> Path:
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_PATH_LENGTH:
        raise ConfigError(f"{label} must be a path string")
    configured = Path(value).expanduser()
    return (configured if configured.is_absolute() else root / configured).resolve(strict=False)


def _optional_path(table: Mapping[str, Any], key: str, label: str, root: Path) -> Path | None:
    value = table.get(key)
    if value is None:
        return None
    return _resolve_path(value, label, root)


def _path_list(table: Mapping[str, Any], key: str, label: str, root: Path) -> tuple[Path, ...]:
    value = table.get(key, [])
    if not isinstance(value, list) or len(value) > 100:
        raise ConfigError(f"{label} must be a list of paths")
    return tuple(_resolve_path(item, label, root) for item in value)


def _string_list(table: Mapping[str, Any], key: str, label: str) -> tuple[str, ...]:
    value = table.get(key, [])
    if not isinstance(value, list) or len(value) > 100:
        raise ConfigError(f"{label} must be a list")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip() or len(item) > 100:
            raise ConfigError(f"{label} must contain short strings")
        result.append(item.strip())
    return tuple(dict.fromkeys(result))
