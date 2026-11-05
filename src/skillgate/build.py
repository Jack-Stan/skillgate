"""Plan and apply a build: overlay routing into SKILL.md, regenerate outputs.

``plan()`` is pure: it reads the tree and returns every file that a build
would write. ``skillgate build`` applies the plan; ``skillgate check`` reports
it. So "check passes" means exactly "build would change nothing".
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from skillgate.config import Config
from skillgate.routing import (
    LockEntry,
    compose,
    dump_lock,
    load_lock,
    load_routing,
    resolve_base,
    terminate,
)
from skillgate.skills import SKILL_FILE, FrontmatterError, discover, read_skill, render_frontmatter

INDEX_VERSION = 1


@dataclass(frozen=True)
class FileChange:
    path: Path
    old: str | None  # None if the file does not exist yet
    new: str
    reason: str


@dataclass
class Plan:
    changes: list[FileChange] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    skills: list[dict[str, Any]] = field(default_factory=list)


def plan(config: Config) -> Plan:
    """Work out what a build would write. Raises RoutingError on a bad routing.json."""
    result = Plan()
    routes = load_routing(config.routing, required=config.require_routing)
    lock, note = load_lock(config.lock)
    if note:
        result.notes.append(note)

    if not config.skills_dir.is_dir():
        result.problems.append(f"{config.rel(config.skills_dir)}: skills folder not found")
        return result

    new_lock: dict[str, LockEntry] = {}
    folders = discover(config.skills_dir)
    rows = []

    for folder in folders:
        rel = config.rel(folder / SKILL_FILE)
        if not (folder / SKILL_FILE).is_file():
            result.problems.append(f"{rel}: missing")
            continue
        try:
            skill = read_skill(folder)
        except FrontmatterError as exc:
            result.problems.append(f"{rel}: {exc}")
            continue

        desired = dict(skill.frontmatter)
        base = skill.description
        route = routes.get(skill.folder)
        if route is None:
            if config.require_routing:
                result.problems.append(f"{rel}: no entry in {config.rel(config.routing)}")
        else:
            entry = lock.get(skill.folder)
            clauses = {route.clause} | ({entry.clause} if entry else set())
            base = resolve_base(skill.description, entry, clauses)
            if route.clause:
                # Store the base exactly as it appears inside the composed text,
                # so a base recovered without the lock is byte-identical.
                base = terminate(base)
            if not base:
                result.problems.append(f"{rel}: description is empty once routing is removed")
            composed = compose(base, route.clause)
            if len(composed) > config.description_max_length:
                result.problems.append(
                    f"{rel}: composed description is {len(composed)} characters, "
                    f"over the maximum of {config.description_max_length}"
                )
            desired["description"] = composed
            if route.category is not None:
                desired["category"] = route.category
            if route.owner is not None:
                desired["owner"] = route.owner
            new_lock[skill.folder] = LockEntry(base=base, clause=route.clause)

            # Compare parsed values, not bytes: an in-sync file is never
            # rewritten just because it is formatted differently.
            if desired != skill.frontmatter:
                result.changes.append(
                    FileChange(
                        path=skill.path,
                        old=skill.text,
                        new=render_frontmatter(desired) + skill.body,
                        reason=f"frontmatter does not match {config.rel(config.routing)}",
                    )
                )

        result.skills.append(
            {
                "name": skill.folder,
                "description": str(desired.get("description", "")),
                "category": desired.get("category"),
                "owner": desired.get("owner"),
                "path": rel,
            }
        )
        rows.append((skill.folder, desired.get("category"), desired.get("owner"), base))

    folder_names = {f.name for f in folders}
    for name in sorted(set(routes) - folder_names):
        result.problems.append(
            f"{config.rel(config.routing)}: '{name}' has no skill folder in "
            f"{config.rel(config.skills_dir)}"
        )

    _stage(result, config.index, render_index(result.skills), "out of date")
    _stage(result, config.registry, render_registry(rows), "out of date")
    if routes:
        _stage(result, config.lock, dump_lock(new_lock), "out of date")
    return result


def apply(result: Plan) -> None:
    for change in result.changes:
        change.path.parent.mkdir(parents=True, exist_ok=True)
        change.path.write_text(change.new, encoding="utf-8")


def render_index(skills: list[dict[str, Any]]) -> str:
    # No timestamp: the index must be a pure function of the tree.
    data = {
        "version": INDEX_VERSION,
        "count": len(skills),
        "categories": sorted({s["category"] for s in skills if s["category"]}),
        "skills": sorted(skills, key=lambda s: s["name"]),
    }
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def render_registry(rows: list[tuple[str, Any, Any, str]]) -> str:
    lines = [
        "# Skills",
        "",
        "<!-- Generated by skillgate from SKILL.md frontmatter and routing.json.",
        "     Do not edit by hand: edit the skill or the overlay, then run `skillgate build`. -->",
        "",
        f"{len(rows)} skill{'s' if len(rows) != 1 else ''}.",
        "",
        "| Skill | Category | Owner | Description |",
        "|---|---|---|---|",
    ]
    for name, category, owner, base in sorted(rows):
        lines.append(f"| `{name}` | {_cell(category)} | {_cell(owner)} | {_cell(base)} |")
    return "\n".join(lines) + "\n"


def _cell(value: Any) -> str:
    if value is None or value == "":
        return "-"
    return str(value).replace("|", "\\|").replace("\n", " ")


def _stage(result: Plan, path: Path, text: str, reason: str) -> None:
    old = path.read_text(encoding="utf-8") if path.is_file() else None
    if old != text:
        result.changes.append(
            FileChange(path=path, old=old, new=text, reason="missing" if old is None else reason)
        )
