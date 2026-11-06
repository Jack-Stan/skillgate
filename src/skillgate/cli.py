"""Command-line entry point: ``skillgate lint | build | check``."""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from skillgate import __version__
from skillgate.build import Plan, apply, plan
from skillgate.config import Config, ConfigError, load_config
from skillgate.evals import EvalError, load_cases, make_client, run, skill_catalogue, system_prompt
from skillgate.init import plan_init
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
    except (ConfigError, RoutingError, EvalError) as exc:
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

    p = sub.add_parser("init", help="create routing.json, or add entries for new skills")
    p.add_argument("--dry-run", action="store_true", help="print the result, write nothing")
    p.set_defaults(handler=cmd_init)

    p = sub.add_parser("lint", help="validate SKILL.md frontmatter and routing entries")
    p.set_defaults(handler=cmd_lint)

    p = sub.add_parser("build", help="apply routing.json and regenerate index, registry, lock")
    p.set_defaults(handler=cmd_build)

    p = sub.add_parser("check", help="like build, but change nothing; exit 1 on drift")
    p.add_argument("--diff", action="store_true", help="show a unified diff of each drift")
    p.set_defaults(handler=cmd_check)
    p = sub.add_parser(
        "eval", help="ask Claude to route sample prompts and report misroutes (calls the API)"
    )
    p.add_argument("--cases", type=Path, help="cases file (default: config `evals`)")
    p.add_argument("--model", help="model to route with (default: config `eval_model`)")
    p.add_argument("--dry-run", action="store_true", help="show what would be sent; no API calls")
    p.add_argument("--json", action="store_true", help="print the report as JSON")
    p.set_defaults(handler=cmd_eval)
    return parser


def cmd_init(config: Config, args: argparse.Namespace) -> int:
    result = plan_init(config)
    where = config.rel(result.path)
    if result.text is None:
        print(f"init: every skill already has an entry in {where}")
        return EXIT_OK
    if args.dry_run:
        print(result.text, end="")
        return EXIT_OK
    result.path.parent.mkdir(parents=True, exist_ok=True)
    result.path.write_text(result.text, encoding="utf-8", newline="\n")
    for name in result.added:
        print(f"added {name}")
    print(
        f"init: wrote {where} ({len(result.added)} new entries). "
        "Fill in each `avoid` list, then run: skillgate build"
    )
    return EXIT_OK


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


def cmd_eval(config: Config, args: argparse.Namespace) -> int:
    catalogue = skill_catalogue(config)
    cases_path = (Path.cwd() / args.cases) if args.cases else config.evals
    cases = load_cases(cases_path, {name for name, _ in catalogue})
    model = args.model or config.eval_model

    if args.dry_run:
        print(f"model: {model}")
        print(f"cases: {len(cases)} from {config.rel(cases_path)} ({len(cases)} API calls)")
        print("--- system prompt ---")
        print(system_prompt(catalogue))
        return EXIT_OK

    report = run(config, cases, catalogue, client=make_client(), model=model)
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    else:
        _print_report(report)
    ok = report.accuracy >= config.eval_min_accuracy
    return EXIT_OK if ok else EXIT_FAIL


def _print_report(report) -> None:
    for o in report.outcomes:
        expected = o.case.expect or "none"
        if o.error:
            print(f"ERROR  {o.case.prompt[:60]!r}: {o.error}")
        elif o.passed:
            print(f"PASS   {o.case.prompt[:60]!r} -> {expected}")
        else:
            chosen = o.got or "none"
            print(f"FAIL   {o.case.prompt[:60]!r}: expected {expected}, chose {chosen}")
            if o.reason:
                print(f"       reason: {o.reason}")
    collisions = report.collisions()
    if collisions:
        print("\nCollisions (expected -> chosen):")
        for a, b, n in collisions:
            print(f"  {a} -> {b}  x{n}")
    total = len(report.outcomes)
    print(
        f"\neval: {report.passed}/{total} routed correctly ({report.accuracy:.0%}) "
        f"on {report.model}; "
        f"tokens in {report.input_tokens} (+{report.cache_read_input_tokens} cached), "
        f"out {report.output_tokens}"
    )


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
