"""Command-line entry point: ``skillgate lint | build | check``."""

from __future__ import annotations

import argparse
import difflib
import sys
from collections.abc import Sequence
from pathlib import Path

from skillgate import __version__
from skillgate.build import Plan, apply, plan
from skillgate.config import Config, ConfigError, load_config
from skillgate.lint import lint
from skillgate.routing import RoutingError

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        config = load_config(Path.cwd(), args.config)
        return args.handler(config, args)
    except (ConfigError, RoutingError) as exc:
        print(f"skillgate: error: {exc}", file=sys.stderr)
        return EXIT_USAGE


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="skillgate",
        description="Lint, index and drift-check a Claude Code skills folder.",
    )
    parser.add_argument("--version", action="version", version=f"skillgate {__version__}")
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        help="config file (default: nearest skillgate.toml or "
        "pyproject.toml with [tool.skillgate])",
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    p = sub.add_parser("lint", help="validate SKILL.md frontmatter and routing entries")
    p.set_defaults(handler=cmd_lint)

    p = sub.add_parser("build", help="apply routing.json and regenerate index, registry, lock")
    p.set_defaults(handler=cmd_build)

    p = sub.add_parser("check", help="like build, but change nothing; exit 1 on drift")
    p.add_argument("--diff", action="store_true", help="show a unified diff of each drift")
    p.set_defaults(handler=cmd_check)
    return parser


def cmd_lint(config: Config, args: argparse.Namespace) -> int:
    findings = lint(config)
    for finding in findings:
        print(finding)
    if findings:
        print(f"\n{len(findings)} problem(s).")
        return EXIT_FAIL
    print("lint: all skills pass")
    return EXIT_OK


def cmd_build(config: Config, args: argparse.Namespace) -> int:
    result = plan(config)
    _print_notes(result)
    apply(result)
    for change in result.changes:
        print(f"wrote {config.rel(change.path)}")
    count = len(result.skills)
    if result.changes:
        print(f"build: {count} skills, {len(result.changes)} file(s) written")
    else:
        print(f"build: up to date ({count} skills)")
    return _report_problems(result)


def cmd_check(config: Config, args: argparse.Namespace) -> int:
    result = plan(config)
    _print_notes(result)
    for change in result.changes:
        print(f"DRIFT  {config.rel(change.path)}: {change.reason}")
        if args.diff:
            _print_diff(config, change.path, change.old, change.new)
    status = _report_problems(result)
    if result.changes:
        print(f"\n{len(result.changes)} file(s) out of date. Run: skillgate build")
        return EXIT_FAIL
    if status == EXIT_OK:
        print(f"check: in sync ({len(result.skills)} skills)")
    return status


def _print_notes(result: Plan) -> None:
    for note in result.notes:
        print(f"note: {note}")


def _report_problems(result: Plan) -> int:
    for problem in result.problems:
        print(f"ERROR  {problem}")
    return EXIT_FAIL if result.problems else EXIT_OK


def _print_diff(config: Config, path: Path, old: str | None, new: str) -> None:
    name = config.rel(path)
    diff = difflib.unified_diff(
        (old or "").splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile=f"a/{name}" if old is not None else "/dev/null",
        tofile=f"b/{name}",
    )
    sys.stdout.writelines(diff)
    print()


if __name__ == "__main__":
    sys.exit(main())
