from __future__ import annotations

import argparse
from datetime import date, datetime
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

from .config import PROJECT_STATUSES, Config, initialize_vault, load_config, migrate_config
from .digest import DigestBuilder, parse_label
from .digest.periods import period_containing
from .gates import apply_candidates, propose_candidates
from .gates.candidates import pending_count
from .pipeline import Pipeline
from .projects import create_project, load_projects, write_views
from .projects.model import NEXT_ACTION
from .sources import Source, SourceError
from .sources.registry import OPENCLI_PREFIX, SOURCE_NAMES, build_source, configured_sources, is_known_source
from .sources.opencli import run_opencli
from .sources.opencli.manifest import load_manifest, validate_collection
from .state import FileStateBackend, SQLiteStateBackend, StateBackend
from .vault import network_filesystem


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="asterism", description="Turn scattered notes into publishable content."
    )
    parser.add_argument("--version", action="version", version="asterism 0.1.0")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="initialize a private content vault")
    init_parser.add_argument("vault", type=Path)
    init_parser.add_argument("--state-backend", choices=("file", "sqlite"))

    doctor_parser = subparsers.add_parser("doctor", help="check the local configuration")
    doctor_parser.add_argument("--vault", type=Path, required=True)
    doctor_parser.add_argument(
        "--source",
        default="apple-notes",
        metavar="SOURCE",
        help=f"one of {', '.join(SOURCE_NAMES)} or opencli:<collection>",
    )

    sync_parser = subparsers.add_parser("sync", help="collect and normalize notes")
    sync_parser.add_argument("--vault", type=Path, required=True)
    sync_parser.add_argument(
        "--source",
        action="append",
        dest="sources",
        metavar="SOURCE",
        help=(
            f"one of {', '.join(SOURCE_NAMES)} or opencli:<collection>; may repeat; "
            "default: every configured source"
        ),
    )
    sync_parser.add_argument("--dry-run", action="store_true")
    sync_parser.add_argument(
        "--no-digest", action="store_true", help="skip digest generation after this sync"
    )
    sync_parser.add_argument(
        "--commit", action="store_true",
        help="git commit the vault after a fully successful sync (never pushes)",
    )

    migrate_parser = subparsers.add_parser(
        "migrate-config", help="write asterism.yaml from an existing asterism.toml"
    )
    migrate_parser.add_argument("--vault", type=Path, required=True)

    missing_parser = subparsers.add_parser(
        "missing", help="list items a source stopped returning; nothing is deleted"
    )
    missing_parser.add_argument("--vault", type=Path, required=True)
    missing_parser.add_argument("--source", metavar="SOURCE")

    digest_parser = subparsers.add_parser(
        "digest", help="generate pending digests and rebuild the open ones"
    )
    digest_parser.add_argument("--vault", type=Path, required=True)
    digest_parser.add_argument(
        "--regenerate", metavar="PERIOD",
        help="rebuild one period by label, e.g. 2026-09-21, 2026-W39, 2026-09, 2026",
    )

    new_parser = subparsers.add_parser("new", help="create a content project")
    new_parser.add_argument("title")
    new_parser.add_argument("--vault", type=Path, required=True)
    new_parser.add_argument("--pillar", help="content pillar key from content.pillars")
    new_parser.add_argument("--type", dest="type_", help="content type from content.types")
    new_parser.add_argument(
        "--platform", action="append", dest="platforms", metavar="PLATFORM",
        help="publication target; may repeat, first one becomes the primary",
    )
    new_parser.add_argument(
        "--source", action="append", dest="sources", metavar="PATH",
        help="vault-relative path of a note this project grew from; may repeat",
    )
    new_parser.add_argument("--promise", help="what the reader can do after reading")
    new_parser.add_argument("--status", choices=PROJECT_STATUSES, default="candidate")

    status_parser = subparsers.add_parser("status", help="list content projects and their state")
    status_parser.add_argument("--vault", type=Path, required=True)
    status_parser.add_argument("--pillar")
    status_parser.add_argument("--status", dest="only_status", choices=PROJECT_STATUSES)
    status_parser.add_argument("--year", type=int)

    week_parser = subparsers.add_parser("week", help="one page for the weekly session")
    week_parser.add_argument("--vault", type=Path, required=True)

    propose_parser = subparsers.add_parser(
        "propose", help="list this week's undecided items as candidates in its digest"
    )
    propose_parser.add_argument("--vault", type=Path, required=True)
    propose_parser.add_argument("--week", metavar="LABEL", help="a week label such as 2026-W39")

    apply_parser = subparsers.add_parser(
        "apply", help="turn the ticked candidates of a week into content projects"
    )
    apply_parser.add_argument("--vault", type=Path, required=True)
    apply_parser.add_argument("--week", metavar="LABEL", help="a week label such as 2026-W39")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "init":
            return _init(args.vault, args.state_backend)
        if args.command == "doctor":
            config = load_config(args.vault)
            _require_source(config, args.source)
            return _doctor(config, args.source)
        if args.command == "sync":
            config = load_config(args.vault)
            names = args.sources or configured_sources(config)
            for name in names:
                _require_source(config, name)
            return _sync_all(
                config, names, dry_run=args.dry_run, digest=not args.no_digest, commit=args.commit
            )
        if args.command == "propose":
            return _propose(load_config(args.vault), args.week)
        if args.command == "apply":
            return _apply(load_config(args.vault), args.week)
        if args.command == "status":
            return _status(load_config(args.vault), args)
        if args.command == "week":
            return _week(load_config(args.vault))
        if args.command == "new":
            return _new(load_config(args.vault), args)
        if args.command == "digest":
            return _digest(load_config(args.vault), args.regenerate)
        if args.command == "missing":
            return _missing(load_config(args.vault), args.source)
        if args.command == "migrate-config":
            written = migrate_config(args.vault)
            print(f"Wrote {written}")
            print("Check it, then delete asterism.toml; both files present is an error.")
            return 0
    except (SourceError, FileExistsError, FileNotFoundError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 2


def _require_source(config: Config, name: str) -> None:
    if not is_known_source(config, name):
        raise ValueError(
            f"unknown source {name!r}; choose one of {', '.join(SOURCE_NAMES)} or opencli:<collection>"
        )


def _init(vault: Path, backend: str | None) -> int:
    selected = backend
    if selected is None:
        if not sys.stdin.isatty():
            raise ValueError("--state-backend is required in non-interactive mode")
        answer = input("State backend [file/sqlite] (file): ").strip().lower()
        selected = answer or "file"
    config = initialize_vault(vault, selected)
    print(f"Initialized Asterism vault at {config.vault}")
    print("Private note content will be written only inside this vault.")
    return 0


def _doctor(config: Config, source_name: str) -> int:
    _doctor_storage(config)
    checks: list[tuple[str, bool]] = [
        ("notes directory", config.notes_root.is_dir()),
        ("state directory", config.state_dir.is_dir()),
    ]
    if source_name == "apple-notes":
        checks.extend(
            (
                ("macOS", platform.system() == "Darwin"),
                ("osascript", shutil.which("osascript") == "/usr/bin/osascript"),
            )
        )
    elif source_name == "flomo":
        checks.append(
            (
                "flomo export",
                config.flomo_export_path is not None
                and config.flomo_export_path.is_file(),
            )
        )
    elif source_name == "cubox":
        checks.append(("cubox-cli", shutil.which("cubox-cli") is not None))
    elif source_name == "markdown":
        checks.append(
            (
                "Markdown roots",
                bool(config.markdown_roots)
                and all(path.is_dir() and not path.is_symlink() for path in config.markdown_roots),
            )
        )
    elif source_name.startswith(OPENCLI_PREFIX):
        return _doctor_opencli(config, source_name[len(OPENCLI_PREFIX):], checks)
    elif source_name == "notion":
        checks.extend(
            (
                (
                    "Notion scope",
                    bool(config.notion_root_page_ids or config.notion_data_source_ids)
                    or config.notion_discover_all,
                ),
                ("Notion token environment", bool(os.environ.get("ASTERISM_NOTION_TOKEN"))),
            )
        )
    for label, passed in checks:
        print(f"{'OK' if passed else 'FAIL'}  {label}")
    if not all(passed for _, passed in checks):
        if source_name == "flomo" and config.flomo_export_path is None:
            print("Hint: configure sources.flomo.export_path in asterism.yaml.")
            if Path("/Applications/flomo.app").is_dir():
                print(
                    "The flomo desktop app is installed, but collection currently uses "
                    "an official HTML/ZIP export rather than its private app data."
                )
        elif source_name == "cubox" and shutil.which("cubox-cli") is None:
            print("Hint: install the official Cubox CLI, then authenticate in your terminal.")
            if Path("/Applications/Cubox.app").is_dir():
                print(
                    "The Cubox desktop app is installed, but the adapter needs the "
                    "separate official cubox-cli command."
                )
        elif source_name == "markdown" and not config.markdown_roots:
            print("Hint: configure sources.markdown.roots in asterism.yaml.")
        elif source_name == "notion":
            print(
                "Hint: configure a Notion scope and provide ASTERISM_NOTION_TOKEN "
                "through your environment."
            )
        return 1
    print(f"OK  state backend: {config.state_backend}")
    if source_name == "apple-notes":
        print("Note: macOS may request permission to control Notes on the first sync.")
    elif source_name == "cubox":
        print("Note: run 'cubox-cli auth status' yourself to verify local authentication.")
    return 0


def _doctor_opencli(config: Config, collection_name: str, checks: list[tuple[str, bool]]) -> int:
    collection = config.opencli.collection(collection_name)
    assert collection is not None  # validated by _require_source
    binary = shutil.which(config.opencli.binary or "opencli")
    checks.append(("opencli binary", binary is not None))
    problems: list[str] = []
    if binary is not None:
        try:
            manifest = load_manifest(lambda args, timeout: run_opencli(args, timeout, binary=config.opencli.binary))
            problems = validate_collection(collection, manifest)
        except SourceError as error:
            problems = [str(error)]
    for label, passed in checks:
        print(f"{'OK' if passed else 'FAIL'}  {label}")
    blocking = [problem for problem in problems if not problem.endswith("informational")]
    for problem in problems:
        print(f"{'FAIL' if problem in blocking else 'NOTE'}  {problem}")
    if binary is None:
        print("Hint: npm install -g @jackwener/opencli, then run 'opencli list' once in your terminal.")
        return 1
    if blocking:
        return 1
    print(f"OK  collection {collection_name}: {collection.producer} --format json")
    print("Note: exit code 69 means Chrome with the OpenCLI extension is not running; 77 means log in to the site in Chrome.")
    return 0


def _doctor_storage(config: Config) -> None:
    """Report where things live and warn about network filesystems and masked switches."""
    print(f"Vault: {config.vault}")
    vault_fs = network_filesystem(config.vault)
    if vault_fs:
        print(f"WARN  vault is on a network filesystem ({vault_fs}); Git and SQLite are unreliable there")
        if config.state_dir_override is None:
            print("WARN  set state.state_dir to a local directory when the vault is remote")
    print(f"State: {config.state_dir} ({config.state_backend})")
    if config.storage.media_root is not None:
        status = "mounted" if config.storage.media_root.is_dir() else "NOT AVAILABLE"
        print(f"Media root: {config.storage.media_root} ({status})")
    for inbox in config.storage.inbox:
        status = "present" if inbox.is_dir() else "missing"
        print(f"Inbox: {inbox} ({status})")
    if config.archive.enabled:
        status = "mounted" if config.archive_root.is_dir() else "NOT AVAILABLE"
        print(f"Archive: {config.archive_root} ({status}, mode {config.archive.mode})")
    else:
        masked = [
            f"digest.{level}.archive_{lower}"
            for level, lower in (("week", "days"), ("month", "weeks"), ("year", "months"))
            if config.digest.level(level).archive_lower
        ]
        if masked:
            print("Archive: disabled; these switches have no effect: " + ", ".join(masked))
        else:
            print("Archive: disabled")


def _missing(config: Config, source_name: str | None) -> int:
    """Items whose last sighting predates their source's latest sync."""
    wanted = _internal_source_name(source_name) if source_name else None
    total = 0
    with _state_backend(config) as state:
        for source in sorted(state.sources()):
            if wanted is not None and source != wanted:
                continue
            items = state.items(source)
            latest = max(item.last_seen_at for item in items)
            gone = [item for item in items if item.last_seen_at < latest]
            for item in gone:
                total += 1
                print(f"{source}\t{item.last_seen_at}\t{item.relative_path}")
    if total == 0:
        print("No missing items.")
    else:
        print(f"{total} missing item(s) retained locally; delete or archive them yourself.")
    return 0


def _internal_source_name(cli_name: str) -> str:
    """Map a CLI source name to the ``source`` recorded in state."""
    if cli_name == "apple-notes":
        return "apple_notes"
    if cli_name.startswith(OPENCLI_PREFIX):
        return f"opencli-{cli_name[len(OPENCLI_PREFIX):]}"
    return cli_name


def _state_backend(config: Config) -> StateBackend:
    if config.state_backend == "file":
        return FileStateBackend(config.state_dir / "manifest.json")
    return SQLiteStateBackend(config.state_dir / "asterism.sqlite")


def _build_source(config: Config, source_name: str) -> Source:
    return build_source(config, source_name)


def _new(config: Config, args: argparse.Namespace) -> int:
    project = create_project(
        config,
        title=args.title,
        pillar=args.pillar,
        type_=args.type_,
        platforms=tuple(args.platforms or ()),
        sources=tuple(args.sources or ()),
        promise=args.promise,
        status=args.status,
    )
    directory = project.directory.relative_to(config.vault)
    print(f"Created {project.id}: {directory}")
    print(f"Fill in the brief, then move the status on from '{project.status}'.")
    return 0


def _week_period(config: Config, label: str | None):
    if label:
        period = parse_label(label, config.digest)
        if period.level != "week":
            raise ValueError(f"{label} is not a week; use a label such as 2026-W39")
        return period
    return period_containing("week", date.today(), config.digest)


def _propose(config: Config, label: str | None) -> int:
    period = _week_period(config, label)
    with _state_backend(config) as state:
        count, digest_file = propose_candidates(config, state, period)
    where = digest_file.relative_to(config.vault)
    if count:
        print(f"{count} candidate(s) for {period.label} in {where}")
        print(f"Tick what is worth making, then run `asterism apply --week {period.label}`.")
    else:
        print(f"Nothing undecided in {period.label}; {where} is up to date.")
    return 0


def _apply(config: Config, label: str | None) -> int:
    period = _week_period(config, label)
    with _state_backend(config) as state:
        created = apply_candidates(config, state, period)
    write_views(config, load_projects(config))
    if not created:
        print(f"No ticked candidates in {period.label}.")
        return 0
    for candidate, project_id in created:
        print(f"Created {project_id}: {candidate.title}")
    print("Fill in each brief, then move the status on from 'approved'.")
    return 0


def _status(config: Config, args: argparse.Namespace) -> int:
    registry = load_projects(config)
    write_views(config, registry)
    selected = registry.filtered(pillar=args.pillar, status=args.only_status, year=args.year)
    if not selected.projects:
        print("No projects match." if registry.projects else "No projects yet; create one with `asterism new`.")
    else:
        counts = {status: len(selected.by_status(status)) for status in PROJECT_STATUSES}
        summary = ", ".join(f"{count} {status}" for status, count in counts.items() if count)
        print(f"{len(selected.projects)} project(s): {summary}")
        print()
        for status in PROJECT_STATUSES:
            for project in selected.by_status(status):
                print(_project_line(config, project))
    for problem in registry.problems:
        print(f"unreadable  {problem}", file=sys.stderr)
    return 1 if registry.problems else 0


def _project_line(config: Config, project) -> str:
    created = project.created.isoformat() if project.created else "          "
    platforms = ", ".join(
        f"{name}{'+' if project.published_on(name) else '-'}" for name in project.platforms
    )
    return f"{project.status:<13}{created}  {project.id}  {project.title}" + (
        f"   [{platforms}]" if platforms else ""
    )


def _week(config: Config, today: date | None = None) -> int:
    today = today or date.today()
    period = period_containing("week", today, config.digest)
    registry = load_projects(config)
    write_views(config, registry)

    print(f"Week {period.label} ({period.start.isoformat()} to {period.end.isoformat()})")
    in_flight = registry.in_flight()
    if in_flight:
        print(f"\nIn flight ({len(in_flight)})")
        for project in sorted(in_flight, key=lambda item: PROJECT_STATUSES.index(item.status), reverse=True):
            print(f"  {_project_line(config, project)}")
            print(f"{'':<15}waiting: {NEXT_ACTION.get(project.status, '')}")
    published = [
        project
        for project in registry.projects
        if project.is_published
        and any(
            _published_date(record) is not None and period.start <= _published_date(record) <= period.end
            for record in project.published.values()
        )
    ]
    if published:
        print(f"\nPublished this week ({len(published)})")
        for project in published:
            print(f"  {project.id}  {project.title}")
    digest_file = config.vault / period.relative_path
    waiting = pending_count(digest_file.read_text(encoding="utf-8")) if digest_file.is_file() else 0
    if waiting:
        print(f"\nCandidates waiting in {period.relative_path}: {waiting}")
        print(f"  tick what is worth making, then `asterism apply --week {period.label}`")
    if not in_flight and not published and not waiting:
        print("\nNothing in flight. Collect some notes, then run `asterism propose`.")
    return 0


def _published_date(record: object):
    if not isinstance(record, dict):
        return None
    value = record.get("at")
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _digest(config: Config, regenerate: str | None) -> int:
    with _state_backend(config) as state:
        builder = DigestBuilder(config, state)
        if regenerate:
            print(builder.regenerate(parse_label(regenerate, config.digest)))
        else:
            for message in builder.run():
                print(f"Digest: {message}")
    return 0


def _sync_all(
    config: Config, names: list[str], *, dry_run: bool, digest: bool, commit: bool
) -> int:
    """Run every named source; one failure is reported and does not stop the others."""
    failures = 0
    created = updated = 0
    any_missing = False
    mode = "Dry run" if dry_run else "Sync"
    with _state_backend(config) as state:
        for name in names:
            try:
                source = _build_source(config, name)
                result = Pipeline(source, state, config.vault).sync(dry_run=dry_run)
            except (SourceError, ValueError) as error:
                failures += 1
                print(f"{mode} [{name}]: skipped — {error}", file=sys.stderr)
                continue
            created += result.created
            updated += result.updated
            any_missing = any_missing or result.missing > 0
            print(
                f"{mode} [{name}]: {result.discovered} discovered, {result.created} new, "
                f"{result.updated} updated, {result.unchanged} unchanged, "
                f"{result.missing} missing"
            )
        if digest and not dry_run and config.digest.after_sync and failures < len(names):
            for message in DigestBuilder(config, state).run():
                print(f"Digest: {message}")
    if any_missing:
        print("Missing source items were retained locally; run `asterism missing` to review.")
    if commit and not dry_run:
        if failures:
            print("Commit skipped: a source failed; fix it and re-run with --commit.", file=sys.stderr)
        else:
            print(_commit_vault(config.vault, created, updated))
    return 1 if failures else 0


def _commit_vault(vault: Path, created: int, updated: int) -> str:
    """Stage notes and digests and commit them; never pushes."""
    def git(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(
            ["git", "-C", str(vault), *arguments], capture_output=True, text=True, check=False, timeout=120
        )
        if check and completed.returncode != 0:
            raise ValueError(f"git {arguments[0]} failed: {completed.stderr.strip()[:200]}")
        return completed

    inside = git("rev-parse", "--is-inside-work-tree", check=False)
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return "Commit skipped: the vault is not a Git repository (run `git init` there to enable snapshots)."
    git("add", "-A", "--", "notes", "digest")
    staged = git("diff", "--cached", "--quiet", check=False)
    if staged.returncode == 0:
        return "Commit skipped: nothing changed."
    stamp = datetime.now().astimezone().replace(microsecond=0).isoformat()
    message = f"sync {stamp} (+{created} ~{updated})"
    git("commit", "-q", "-m", message)
    return f"Committed: {message}"


if __name__ == "__main__":
    raise SystemExit(main())
