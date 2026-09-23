from __future__ import annotations

import argparse
from datetime import date, datetime
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

from .config import MATERIAL_DECISIONS, PROJECT_STATUSES, Config, initialize_vault, load_config, migrate_config
from .digest import DigestBuilder, parse_label
from .digest.periods import period_containing
from .gates import (
    apply_sheet,
    build_sheet,
    days_since_last,
    latest_sheet,
    pass_gate,
    record_publication,
    write_draft_gate,
    write_publish_gate,
)
from .pipeline import Pipeline
from .projects import (
    angles,
    confirm_project,
    create_project,
    drop_project,
    gather_into,
    load_projects,
    offers_angles,
    restore_project,
    write_views,
)
from .compose import adapt_project, check_draft, compose_draft, draft_path
from .projects.model import NEXT_ACTION
from .report import emit, emit_error
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

    confirm_parser = subparsers.add_parser(
        "confirm", help="gate 1: confirm what a candidate becomes and start making it"
    )
    confirm_parser.add_argument("project_id")
    confirm_parser.add_argument("--vault", type=Path, required=True)
    confirm_parser.add_argument(
        "--angle", type=int, metavar="N", help="number of an angle listed in the brief"
    )
    confirm_parser.add_argument("--title", help="the piece's name, when it is not an angle's")
    confirm_parser.add_argument("--promise", help="what the reader can do after reading")

    gather_parser = subparsers.add_parser(
        "gather", help="bring already-collected material into a project"
    )
    gather_parser.add_argument("project_id")
    gather_parser.add_argument("--vault", type=Path, required=True)
    gather_parser.add_argument(
        "--from", dest="prefix", required=True, metavar="PATH",
        help="vault-relative directory or note the material sits under",
    )
    gather_parser.add_argument("--since", metavar="DATE", help="ignore material before this day")
    gather_parser.add_argument("--until", metavar="DATE", help="ignore material after this day")
    gather_parser.add_argument(
        "--dry-run", action="store_true", help="report what would be added and write nothing"
    )

    draft_parser = subparsers.add_parser(
        "draft", help="compose the draft skeleton from the brief and the gathered material"
    )
    draft_parser.add_argument("project_id")
    draft_parser.add_argument("--vault", type=Path, required=True)

    check_parser = subparsers.add_parser(
        "check", help="gate 2: report what the draft lacks and ask the person to answer"
    )
    check_parser.add_argument("project_id")
    check_parser.add_argument("--vault", type=Path, required=True)

    accept_parser = subparsers.add_parser(
        "accept", help="gate 2: read the answered sheet and make the piece ready"
    )
    accept_parser.add_argument("project_id")
    accept_parser.add_argument("--vault", type=Path, required=True)

    adapt_parser = subparsers.add_parser(
        "adapt", help="write one export per platform from the draft"
    )
    adapt_parser.add_argument("project_id")
    adapt_parser.add_argument("--vault", type=Path, required=True)

    release_parser = subparsers.add_parser(
        "release", help="gate 3: list the exports and ask for the publication decision"
    )
    release_parser.add_argument("project_id")
    release_parser.add_argument("--vault", type=Path, required=True)

    publish_parser = subparsers.add_parser(
        "publish", help="gate 3: read the answered sheet and record the publication"
    )
    publish_parser.add_argument("project_id")
    publish_parser.add_argument("--vault", type=Path, required=True)
    publish_parser.add_argument(
        "--url", action="append", dest="urls", metavar="PLATFORM=URL", default=[],
        help="where it went live; may repeat",
    )

    status_parser = subparsers.add_parser("status", help="list content projects and their state")
    status_parser.add_argument("--vault", type=Path, required=True)
    status_parser.add_argument("--pillar")
    status_parser.add_argument("--status", dest="only_status", choices=PROJECT_STATUSES)
    status_parser.add_argument("--year", type=int)
    status_parser.add_argument(
        "--include-dropped", action="store_true", help="also read the projects under trash/"
    )

    drop_parser = subparsers.add_parser(
        "drop", help="stop work on a project and move it to trash/; nothing is deleted"
    )
    drop_parser.add_argument("project_id")
    drop_parser.add_argument("--vault", type=Path, required=True)

    restore_parser = subparsers.add_parser(
        "restore", help="bring a dropped project back as a candidate"
    )
    restore_parser.add_argument("project_id")
    restore_parser.add_argument("--vault", type=Path, required=True)

    week_parser = subparsers.add_parser("week", help="one page for the weekly session")
    week_parser.add_argument("--vault", type=Path, required=True)

    review_parser = subparsers.add_parser(
        "review", help="write today's sheet of collected material that has no outcome yet"
    )
    review_parser.add_argument("--vault", type=Path, required=True)
    review_parser.add_argument(
        "--since", metavar="DATE", help="ignore anything collected before this date, e.g. 2026-09-01"
    )

    material_parser = subparsers.add_parser(
        "material", help="list collected items by what was decided about them"
    )
    material_parser.add_argument("--vault", type=Path, required=True)
    material_parser.add_argument(
        "--status", dest="decision", choices=(*MATERIAL_DECISIONS, "undecided"),
        help="one outcome; all of them with counts when omitted",
    )
    material_parser.add_argument("--source", metavar="SOURCE")

    apply_parser = subparsers.add_parser(
        "apply", help="record the outcomes in a review sheet and create the projects"
    )
    apply_parser.add_argument("--vault", type=Path, required=True)
    apply_parser.add_argument(
        "--sheet", metavar="NAME",
        help="a sheet date or file name such as 2026-09-22 or 2026-09-22-150524; the newest open one by default",
    )
    # the agent contract: every command can report itself as one JSON object
    for name, sub in subparsers.choices.items():
        if name == "init":
            continue  # it runs before a vault exists and asks a question instead
        sub.add_argument(
            "--json", action="store_true", dest="as_json",
            help="print one JSON object instead of the human-readable report",
        )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "init":
            return _init(args.vault, args.state_backend)
        if args.command == "doctor":
            config = load_config(args.vault)
            _require_source(config, args.source)
            return _doctor(config, args.source, as_json=args.as_json)
        if args.command == "sync":
            config = load_config(args.vault)
            names = args.sources or configured_sources(config)
            for name in names:
                _require_source(config, name)
            return _sync_all(
                config, names, dry_run=args.dry_run, digest=not args.no_digest,
                commit=args.commit, as_json=args.as_json,
            )
        if args.command == "material":
            return _material(load_config(args.vault), args.decision, args.source, as_json=args.as_json)
        if args.command == "review":
            return _review(load_config(args.vault), args.since, as_json=args.as_json)
        if args.command == "apply":
            return _apply(load_config(args.vault), args.sheet, as_json=args.as_json)
        if args.command == "confirm":
            return _confirm(load_config(args.vault), args)
        if args.command == "gather":
            return _gather(load_config(args.vault), args)
        if args.command in ("draft", "check", "accept", "adapt", "release", "publish"):
            return _project_step(load_config(args.vault), args)
        if args.command == "drop":
            return _drop(load_config(args.vault), args.project_id, as_json=args.as_json)
        if args.command == "restore":
            return _restore(load_config(args.vault), args.project_id, as_json=args.as_json)
        if args.command == "status":
            return _status(load_config(args.vault), args)
        if args.command == "week":
            return _week(load_config(args.vault), as_json=args.as_json)
        if args.command == "new":
            return _new(load_config(args.vault), args)
        if args.command == "digest":
            return _digest(load_config(args.vault), args.regenerate, as_json=args.as_json)
        if args.command == "missing":
            return _missing(load_config(args.vault), args.source, as_json=args.as_json)
        if args.command == "migrate-config":
            written = migrate_config(args.vault)
            print(f"Wrote {written}")
            print("Check it, then delete asterism.toml; both files present is an error.")
            return 0
    except (SourceError, FileExistsError, FileNotFoundError, ValueError) as error:
        if getattr(args, "as_json", False):
            emit_error(args.command, str(error))
        else:
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


def _doctor(config: Config, source_name: str, *, as_json: bool = False) -> int:
    storage = _storage_report(config)
    if not as_json:
        _print_storage(storage)
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
        return _doctor_opencli(
            config, source_name[len(OPENCLI_PREFIX):], checks, storage, as_json=as_json
        )
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
    passed = all(ok for _label, ok in checks)
    hints = [] if passed else _doctor_hints(config, source_name)
    notes = []
    if source_name == "apple-notes":
        notes.append("macOS may request permission to control Notes on the first sync.")
    elif source_name == "cubox":
        notes.append("run 'cubox-cli auth status' yourself to verify local authentication.")

    if as_json:
        emit("doctor", {
            "source": source_name,
            "storage": storage,
            "checks": [{"label": label, "ok": ok} for label, ok in checks],
            "hints": hints,
            "notes": notes if passed else [],
        }, ok=passed)
        return 0 if passed else 1

    for label, ok in checks:
        print(f"{'OK' if ok else 'FAIL'}  {label}")
    if not passed:
        for hint in hints:
            print(hint)
        return 1
    print(f"OK  state backend: {config.state_backend}")
    for note in notes:
        print(f"Note: {note}")
    return 0


def _doctor_hints(config: Config, source_name: str) -> list[str]:
    """What to do about a failed check, in the order the person should try it."""
    if source_name == "flomo" and config.flomo_export_path is None:
        hints = ["Hint: configure sources.flomo.export_path in asterism.yaml."]
        if Path("/Applications/flomo.app").is_dir():
            hints.append(
                "The flomo desktop app is installed, but collection currently uses "
                "an official HTML/ZIP export rather than its private app data."
            )
        return hints
    if source_name == "cubox" and shutil.which("cubox-cli") is None:
        hints = ["Hint: install the official Cubox CLI, then authenticate in your terminal."]
        if Path("/Applications/Cubox.app").is_dir():
            hints.append(
                "The Cubox desktop app is installed, but the adapter needs the "
                "separate official cubox-cli command."
            )
        return hints
    if source_name == "markdown" and not config.markdown_roots:
        return ["Hint: configure sources.markdown.roots in asterism.yaml."]
    if source_name == "notion":
        return [
            "Hint: configure a Notion scope and provide ASTERISM_NOTION_TOKEN "
            "through your environment."
        ]
    return []


def _doctor_opencli(
    config: Config,
    collection_name: str,
    checks: list[tuple[str, bool]],
    storage: dict[str, object],
    *,
    as_json: bool = False,
) -> int:
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
    blocking = [problem for problem in problems if not problem.endswith("informational")]
    failed = binary is None or blocking or not all(ok for _label, ok in checks)
    hints = (
        ["Hint: npm install -g @jackwener/opencli, then run 'opencli list' once in your terminal."]
        if binary is None else []
    )

    if as_json:
        emit("doctor", {
            "source": f"{OPENCLI_PREFIX}{collection_name}",
            "storage": storage,
            "checks": [{"label": label, "ok": ok} for label, ok in checks],
            "problems": [
                {"detail": problem, "blocking": problem in blocking} for problem in problems
            ],
            "hints": hints,
        }, ok=not failed)
        return 1 if failed else 0

    for label, ok in checks:
        print(f"{'OK' if ok else 'FAIL'}  {label}")
    for problem in problems:
        print(f"{'FAIL' if problem in blocking else 'NOTE'}  {problem}")
    for hint in hints:
        print(hint)
    if failed:
        return 1
    print(f"OK  collection {collection_name}: {collection.producer} --format json")
    print("Note: exit code 69 means Chrome with the OpenCLI extension is not running; 77 means log in to the site in Chrome.")
    return 0


def _storage_report(config: Config) -> dict[str, object]:
    """Where everything lives, plus the two things worth warning about."""
    return {
        "vault": config.vault.as_posix(),
        "network_filesystem": network_filesystem(config.vault) or None,
        "state": config.state_dir.as_posix(),
        "backend": config.state_backend,
        "state_dir_override": config.state_dir_override.as_posix() if config.state_dir_override else None,
        "media_root": (
            {"path": config.storage.media_root.as_posix(), "mounted": config.storage.media_root.is_dir()}
            if config.storage.media_root is not None else None
        ),
        "inboxes": [
            {"path": inbox.as_posix(), "present": inbox.is_dir()} for inbox in config.storage.inbox
        ],
        "archive": {
            "enabled": config.archive.enabled,
            "root": config.archive_root.as_posix() if config.archive.enabled else None,
            "available": config.archive_root.is_dir() if config.archive.enabled else None,
            "mode": config.archive.mode if config.archive.enabled else None,
            "masked_switches": [] if config.archive.enabled else [
                f"digest.{level}.archive_{lower}"
                for level, lower in (("week", "days"), ("month", "weeks"), ("year", "months"))
                if config.digest.level(level).archive_lower
            ],
        },
    }


def _print_storage(report: dict[str, object]) -> None:
    print(f"Vault: {report['vault']}")
    if report["network_filesystem"]:
        print(
            f"WARN  vault is on a network filesystem ({report['network_filesystem']}); "
            "Git and SQLite are unreliable there"
        )
        if report["state_dir_override"] is None:
            print("WARN  set state.state_dir to a local directory when the vault is remote")
    print(f"State: {report['state']} ({report['backend']})")
    media = report["media_root"]
    if media is not None:
        print(f"Media root: {media['path']} ({'mounted' if media['mounted'] else 'NOT AVAILABLE'})")
    for inbox in report["inboxes"]:
        print(f"Inbox: {inbox['path']} ({'present' if inbox['present'] else 'missing'})")
    archive = report["archive"]
    if archive["enabled"]:
        state = "mounted" if archive["available"] else "NOT AVAILABLE"
        print(f"Archive: {archive['root']} ({state}, mode {archive['mode']})")
    elif archive["masked_switches"]:
        print("Archive: disabled; these switches have no effect: " + ", ".join(archive["masked_switches"]))
    else:
        print("Archive: disabled")


def _missing(config: Config, source_name: str | None, *, as_json: bool = False) -> int:
    """Items whose last sighting predates their source's latest sync."""
    wanted = _internal_source_name(source_name) if source_name else None
    rows: list[dict[str, str]] = []
    with _state_backend(config) as state:
        for source in sorted(state.sources()):
            if wanted is not None and source != wanted:
                continue
            items = state.items(source)
            latest = max(item.last_seen_at for item in items)
            for item in items:
                if item.last_seen_at < latest:
                    rows.append({"source": source, "last_seen": item.last_seen_at,
                                 "path": item.relative_path})
    if as_json:
        emit("missing", {"items": rows, "count": len(rows)})
        return 0
    total = len(rows)
    for row in rows:
        print(f"{row['source']}\t{row['last_seen']}\t{row['path']}")
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
    if args.as_json:
        emit("new", {"project": project.id, "directory": directory.as_posix(),
                     "status": project.status, "next": NEXT_ACTION[project.status]})
        return 0
    print(f"Created {project.id}: {directory}")
    print(f"Fill in the brief, then move the status on from '{project.status}'.")
    return 0


def _material(config: Config, decision: str | None, source: str | None, *, as_json: bool = False) -> int:
    """What was decided about the collected items, and where the record lives."""
    with _state_backend(config) as state:
        decided = {
            (assignment.source, assignment.source_id): assignment
            for assignment in state.assignments()
        }
        rows: list[tuple[str, str, str]] = []
        counts: dict[str, int] = {}
        for name in sorted(state.sources()):
            for item in state.items(name):
                assignment = decided.get((item.source, item.source_id))
                outcome = assignment.decision if assignment else "undecided"
                counts[outcome] = counts.get(outcome, 0) + 1
                if decision and outcome != decision:
                    continue
                if source and not item.relative_path.startswith(f"notes/{source}/"):
                    continue
                rows.append((outcome, item.relative_path, assignment.project_id if assignment else ""))

    if as_json:
        emit("material", {
            "counts": counts,
            "items": [
                {"outcome": outcome, "path": path, "project": project or None}
                for outcome, path, project in sorted(rows, key=lambda row: row[1])
            ],
        })
        return 0
    if not decision:
        print(", ".join(f"{count} {name}" for name, count in sorted(counts.items())) or "nothing collected yet")
        print("Add --status to list one outcome; the sheets under review/ hold the full record.")
        return 0
    for outcome, path, project_id in sorted(rows, key=lambda row: row[1]):
        print(f"{outcome:<10}{path}" + (f"   -> {project_id}" if project_id else ""))
    print(f"{len(rows)} item(s)")
    return 0


def _review(config: Config, since: str | None, today: date | None = None, *, as_json: bool = False) -> int:
    start = date.fromisoformat(since) if since else None
    with _state_backend(config) as state:
        sheet = build_sheet(config, state, since=start, today=today)
    where = sheet.path.relative_to(config.vault)
    if as_json:
        emit("review", {
            "sheet": where.as_posix(),
            "listed": sheet.listed,
            "covers": sheet.covers,
            "auto": sheet.auto,
            "lines": [
                {"path": line.relative_path, "title": line.title, "day": line.day,
                 "section": line.decision, "topic": line.group or None, "pillar": line.pillar}
                for line in sheet.lines
            ],
        })
        return 0
    for key, count in sorted(sheet.auto.items()):
        print(f"Applied by rule: {count} ({key})")
    if not sheet.lines:
        print(f"Nothing to decide; {where} is empty.")
        return 0
    print(f"{sheet.listed} item(s) to sort in {where}")
    for source, labels in sheet.covers.items():
        print(f"  read {source}: {', '.join(labels)}")
    print("Move each line into the section that says what happens to it, then run `asterism apply`.")
    return 0


def _apply(config: Config, sheet_date: str | None, today: date | None = None, *, as_json: bool = False) -> int:
    path = latest_sheet(config, sheet_date or "")
    if path is None or not path.is_file():
        raise FileNotFoundError(
            f"no review sheet matching {sheet_date!r}" if sheet_date
            else "no review sheet to apply; run `asterism review` first"
        )
    with _state_backend(config) as state:
        recorded, created = apply_sheet(config, state, path, today=today)
    write_views(config, load_projects(config))
    if as_json:
        emit("apply", {
            "sheet": path.relative_to(config.vault).as_posix(),
            "recorded": recorded,
            "created": [
                {"project": project_id, "from": line.relative_path, "topic": line.group or None}
                for line, project_id in created
            ],
        })
        return 0
    if not recorded:
        print(f"{path.relative_to(config.vault)} has nothing left to apply.")
        return 0
    print(", ".join(f"{count} {decision}" for decision, count in sorted(recorded.items())))
    for _line, project_id in created:
        print(f"Created {project_id}")
    if created:
        print("Fill in each brief, then move the status on from 'making'.")
    return 0


def _confirm(config: Config, args: argparse.Namespace) -> int:
    """Gate 1. The person answers it; an agent prepares the angles and waits."""
    registry = load_projects(config)
    project = registry.find(args.project_id)
    if project is None:
        raise ValueError(f"no live project with id {args.project_id!r}")
    if args.angle is None and not args.title:
        offered = angles(config, project)
        hint = None if offered else _angles_hint(config, project)
        if args.as_json:
            emit("confirm", {
                "project": project.id,
                "status": project.status,
                "confirmed": False,
                "angles": [
                    {"number": a.number, "title": a.title, "promise": a.promise or None}
                    for a in offered
                ],
                **({"hint": hint} if hint else {}),
            }, ok=bool(offered))
            return 1
        if not offered:
            raise ValueError(f"{project.id} lists no angles. {hint}")
        print(f"{project.id} offers {len(offered)} angle(s); confirm one with --angle N:")
        for angle in offered:
            print(f"  {angle.number}. {angle.title}" + (f" - {angle.promise}" if angle.promise else ""))
        return 1
    confirmed = confirm_project(
        config, project, angle=args.angle, title=args.title, promise=args.promise
    )
    write_views(config, load_projects(config))
    if args.as_json:
        emit("confirm", {
            "project": confirmed.id,
            "status": confirmed.status,
            "confirmed": True,
            "title": confirmed.title,
            "promise": confirmed.promise,
            "next": NEXT_ACTION[confirmed.status],
        })
        return 0
    print(f"Confirmed {confirmed.id}: {confirmed.title}")
    if confirmed.promise:
        print(f"Promise: {confirmed.promise}")
    print(f"Now {confirmed.status}; {NEXT_ACTION[confirmed.status]}.")
    return 0


def _angles_hint(config: Config, project) -> str:
    """Why there is nothing to choose from, which is two different problems."""
    if offers_angles(config, project):
        return (
            "Its brief has the section but no numbered angle yet. Write one as "
            "`1. **A title** - the promise it keeps`, or pass --title and --promise."
        )
    return (
        "Its brief has no '## Candidate angles' section: this vault's "
        "templates/brief-default.md predates it. Delete that file to seed the current "
        "template for later projects, add the section to this brief by hand, or pass "
        "--title and --promise."
    )


def _gather(config: Config, args: argparse.Namespace) -> int:
    registry = load_projects(config)
    project = registry.find(args.project_id)
    if project is None:
        raise ValueError(f"no live project with id {args.project_id!r}")
    since = date.fromisoformat(args.since) if args.since else None
    until = date.fromisoformat(args.until) if args.until else None
    with _state_backend(config) as state:
        result = gather_into(
            config, state, project, prefix=args.prefix, since=since, until=until,
            dry_run=args.dry_run,
        )
    if args.as_json:
        emit("gather", {
            "project": project.id,
            "added": list(result.added),
            "already": list(result.already),
            "sources": list(result.project.sources),
            "dry_run": bool(args.dry_run),
        })
        if result.added and not args.dry_run:
            write_views(config, load_projects(config))
        return 0
    if not result.added:
        print(f"{project.id} already has all {len(result.already)} matching item(s).")
        return 0
    verb = "would add" if args.dry_run else "added"
    print(f"{project.id} {verb} {len(result.added)} item(s); {len(result.already)} already there.")
    for relative in result.added[:10]:
        print(f"  {relative}")
    if len(result.added) > 10:
        print(f"  ... and {len(result.added) - 10} more")
    if not args.dry_run:
        write_views(config, load_projects(config))
        print("The brief's material section was rewritten; the outcomes of those notes are unchanged.")
    return 0


def _project_step(config: Config, args: argparse.Namespace) -> int:
    """Everything a project does after gate 1, one command per step."""
    registry = load_projects(config)
    project = registry.find(args.project_id)
    if project is None:
        raise ValueError(f"no live project with id {args.project_id!r}")
    handler = {
        "draft": _draft,
        "check": _check,
        "accept": _accept,
        "adapt": _adapt,
        "release": _release,
        "publish": _publish,
    }[args.command]
    return handler(config, project, args)


def _draft(config: Config, project, args: argparse.Namespace) -> int:
    target, headings = compose_draft(config, project)
    relative = target.relative_to(config.vault).as_posix()
    if args.as_json:
        emit("draft", {"project": project.id, "draft": relative, "headings": headings,
                       "material": len(project.sources)})
        return 0
    print(f"{project.id}: {relative} ({len(headings)} section(s), {len(project.sources)} item(s) of material)")
    print(f"Write the prose, then run `asterism check {project.id}`.")
    return 0


def _check(config: Config, project, args: argparse.Namespace) -> int:
    target, findings = write_draft_gate(config, project)
    relative = target.relative_to(config.vault).as_posix()
    if args.as_json:
        emit("check", {
            "project": project.id,
            "sheet": relative,
            "findings": [{"kind": f.kind, "detail": f.detail} for f in findings],
        })
        return 0
    print(f"{project.id}: gate 2 in {relative}")
    for finding in findings:
        print(f"  {finding.kind}: {finding.detail}")
    if not findings:
        print("  the checks found nothing")
    print(f"Answer the questions in the sheet, then run `asterism accept {project.id}`.")
    return 0


def _accept(config: Config, project, args: argparse.Namespace) -> int:
    moved = pass_gate(config, project, gate="check", status="ready")
    write_views(config, load_projects(config))
    if args.as_json:
        emit("accept", {"project": moved.id, "status": moved.status,
                        "next": NEXT_ACTION[moved.status]})
        return 0
    print(f"{moved.id} is ready; {NEXT_ACTION[moved.status]}.")
    print(f"Write the platform versions with `asterism adapt {moved.id}`.")
    return 0


def _adapt(config: Config, project, args: argparse.Namespace) -> int:
    results = adapt_project(config, project)
    written = [platform for platform, _path, ok in results if ok]
    kept = [platform for platform, _path, ok in results if not ok]
    if args.as_json:
        emit("adapt", {
            "project": project.id,
            "written": written,
            "kept": kept,
            "exports": {platform: path.relative_to(config.vault).as_posix()
                        for platform, path, _ok in results},
        })
        return 0
    for platform, path, ok in results:
        verb = "wrote" if ok else "kept edited"
        print(f"  {verb} {platform}: {path.relative_to(config.vault)}")
    print(f"Rewrite each export to its platform's rules, then run `asterism release {project.id}`.")
    return 0


def _release(config: Config, project, args: argparse.Namespace) -> int:
    target, missing = write_publish_gate(config, project)
    relative = target.relative_to(config.vault).as_posix()
    if args.as_json:
        emit("release", {"project": project.id, "sheet": relative, "missing": missing},
             ok=not missing)
        return 1 if missing else 0
    print(f"{project.id}: gate 3 in {relative}")
    for platform in missing:
        print(f"  missing export: {platform}")
    print(f"Answer the questions in the sheet, then run `asterism publish {project.id}`.")
    return 1 if missing else 0


def _publish(config: Config, project, args: argparse.Namespace) -> int:
    urls = {}
    for pair in args.urls:
        platform, _, url = pair.partition("=")
        if not url:
            raise ValueError(f"--url takes PLATFORM=URL, not {pair!r}")
        urls[platform] = url
    published = record_publication(project, urls=urls)
    moved = pass_gate(config, project, gate="release", status="published", published=published)
    write_views(config, load_projects(config))
    if args.as_json:
        emit("publish", {"project": moved.id, "status": moved.status,
                         "published": published, "next": NEXT_ACTION[moved.status]})
        return 0
    print(f"{moved.id} is published on {', '.join(sorted(published))}.")
    print("Nothing was pushed anywhere; the record is on the card.")
    return 0


def _drop(config: Config, project_id: str, *, as_json: bool = False) -> int:
    registry = load_projects(config)
    project = registry.find(project_id)
    if project is None:
        raise ValueError(f"no live project with id {project_id!r}")
    target = drop_project(config, project)
    write_views(config, load_projects(config))
    if as_json:
        emit("drop", {"project": project.id, "status": "dropped",
                      "directory": target.relative_to(config.vault).as_posix()})
        return 0
    print(f"Dropped {project.id}: {target.relative_to(config.vault)}")
    print(f"Nothing was deleted. Bring it back with `asterism restore {project.id}`.")
    return 0


def _restore(config: Config, project_id: str, *, as_json: bool = False) -> int:
    registry = load_projects(config, include_dropped=True)
    project = registry.find(project_id)
    if project is None:
        raise ValueError(f"no project with id {project_id!r}")
    target = restore_project(config, project)
    write_views(config, load_projects(config))
    if as_json:
        emit("restore", {"project": project.id, "status": "candidate",
                         "directory": target.relative_to(config.vault).as_posix()})
        return 0
    print(f"Restored {project.id} as a candidate: {target.relative_to(config.vault)}")
    return 0


def _status(config: Config, args: argparse.Namespace) -> int:
    registry = load_projects(config, include_dropped=args.include_dropped)
    write_views(config, registry)
    selected = registry.filtered(pillar=args.pillar, status=args.only_status, year=args.year)
    if args.as_json:
        emit("status", {
            "projects": [_project_payload(config, project) for project in selected.projects],
            "counts": {
                status: len(selected.by_status(status))
                for status in PROJECT_STATUSES
                if selected.by_status(status)
            },
            "problems": list(registry.problems),
        }, ok=not registry.problems)
        return 1 if registry.problems else 0
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


def _week(config: Config, today: date | None = None, *, as_json: bool = False) -> int:
    today = today or date.today()
    period = period_containing("week", today, config.digest)
    registry = load_projects(config)
    write_views(config, registry)
    in_flight = registry.in_flight()
    if as_json:
        return _week_json(config, registry, period, in_flight, today)

    print(f"Week {period.label} ({period.start.isoformat()} to {period.end.isoformat()})")
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
    elapsed = days_since_last(config, today=today)
    if elapsed is None:
        print("\nNo review sheet yet. Run `asterism review` to sort what has been collected.")
    elif elapsed >= config.review.every:
        print(f"\nLast review was {elapsed} day(s) ago; you sort every {config.review.every}.")
        print("  run `asterism review`")
    if not in_flight and not published:
        print("\nNothing in flight.")
    return 0


def _project_payload(config: Config, project) -> dict[str, object]:
    """One project as an agent reads it: what it is and what it waits for."""
    return {
        "id": project.id,
        "title": project.title,
        "status": project.status,
        "pillar": project.pillar,
        "type": project.type,
        "promise": project.promise,
        "platforms": list(project.platforms),
        "sources": list(project.sources),
        "directory": project.directory.relative_to(config.vault).as_posix() if project.directory else None,
        "next": NEXT_ACTION.get(project.status, ""),
    }


def _week_json(config: Config, registry, period, in_flight, today: date) -> int:
    published = [
        project
        for project in registry.projects
        if project.is_published
        and any(
            _published_date(record) is not None and period.start <= _published_date(record) <= period.end
            for record in project.published.values()
        )
    ]
    elapsed = days_since_last(config, today=today)
    emit("week", {
        "period": {"label": period.label, "start": period.start, "end": period.end},
        "in_flight": [_project_payload(config, project) for project in in_flight],
        "published": [_project_payload(config, project) for project in published],
        "days_since_review": elapsed,
        "review_due": elapsed is None or elapsed >= config.review.every,
    })
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


def _digest(config: Config, regenerate: str | None, *, as_json: bool = False) -> int:
    with _state_backend(config) as state:
        builder = DigestBuilder(config, state)
        messages = (
            builder.regenerate(parse_label(regenerate, config.digest)) if regenerate else builder.run()
        )
    if as_json:
        emit("digest", {"written": list(messages), "regenerated": regenerate})
        return 0
    for message in messages:
        print(f"Digest: {message}")
    return 0


def _sync_all(
    config: Config, names: list[str], *, dry_run: bool, digest: bool, commit: bool,
    as_json: bool = False,
) -> int:
    """Run every named source; one failure is reported and does not stop the others."""
    failures = 0
    created = updated = 0
    any_missing = False
    mode = "Dry run" if dry_run else "Sync"
    ran: list[dict[str, object]] = []
    skipped: list[dict[str, str]] = []
    digests: list[str] = []
    with _state_backend(config) as state:
        for name in names:
            try:
                source = _build_source(config, name)
                result = Pipeline(source, state, config.vault).sync(dry_run=dry_run)
            except (SourceError, ValueError) as error:
                failures += 1
                skipped.append({"source": name, "error": str(error)})
                if not as_json:
                    print(f"{mode} [{name}]: skipped — {error}", file=sys.stderr)
                continue
            created += result.created
            updated += result.updated
            any_missing = any_missing or result.missing > 0
            ran.append({
                "source": name,
                "discovered": result.discovered,
                "created": result.created,
                "updated": result.updated,
                "unchanged": result.unchanged,
                "missing": result.missing,
            })
            if not as_json:
                print(
                    f"{mode} [{name}]: {result.discovered} discovered, {result.created} new, "
                    f"{result.updated} updated, {result.unchanged} unchanged, "
                    f"{result.missing} missing"
                )
        if digest and not dry_run and config.digest.after_sync and failures < len(names):
            digests = list(DigestBuilder(config, state).run())
            if not as_json:
                for message in digests:
                    print(f"Digest: {message}")
    commit_note = None
    if commit and not dry_run:
        if failures:
            commit_note = "skipped: a source failed; fix it and re-run with --commit"
            if not as_json:
                print(f"Commit {commit_note}.", file=sys.stderr)
        else:
            commit_note = _commit_vault(config.vault, created, updated)
            if not as_json:
                print(commit_note)
    if as_json:
        emit("sync", {
            "dry_run": dry_run,
            "sources": ran,
            "skipped": skipped,
            "created": created,
            "updated": updated,
            "missing": any_missing,
            "digests": digests,
            "commit": commit_note,
        }, ok=not failures)
        return 1 if failures else 0
    if any_missing:
        print("Missing source items were retained locally; run `asterism missing` to review.")
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
    git("add", "-A", "--", "notes")
    staged = git("diff", "--cached", "--quiet", check=False)
    if staged.returncode == 0:
        return "Commit skipped: nothing changed."
    stamp = datetime.now().astimezone().replace(microsecond=0).isoformat()
    message = f"sync {stamp} (+{created} ~{updated})"
    git("commit", "-q", "-m", message)
    return f"Committed: {message}"


if __name__ == "__main__":
    raise SystemExit(main())
