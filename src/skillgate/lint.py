"""Static checks on SKILL.md files and their routing entries."""

from __future__ import annotations

from dataclasses import dataclass

from skillgate.config import Config
from skillgate.routing import RoutingError, load_routing
from skillgate.skills import (
    MAX_NAME_LENGTH,
    NAME_RE,
    SKILL_FILE,
    FrontmatterError,
    discover,
    read_skill,
)

# Stable codes, so CI logs and docs can refer to a rule by name.
RULES = {
    "SG001": "skill folder has no SKILL.md",
    "SG002": "SKILL.md frontmatter is missing or invalid",
    "SG003": "required frontmatter field is missing or empty",
    "SG004": "name does not match the folder name",
    "SG005": "name is not a valid skill name",
    "SG006": "description is too short",
    "SG007": "description is too long",
    "SG008": "skill has no routing entry",
    "SG009": "routing entry has no skill folder",
    "SG010": "routing file is missing or invalid",
}


@dataclass(frozen=True, order=True)
class Finding:
    path: str
    code: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.code} {self.message}"


def lint(config: Config) -> list[Finding]:
    """Run every rule to completion and return all findings, sorted."""
    findings: list[Finding] = []

    def add(path: str, code: str, message: str) -> None:
        findings.append(Finding(path, code, message))

    if not config.skills_dir.is_dir():
        add(config.rel(config.skills_dir), "SG001", "skills folder not found")
        return findings

    routes: dict[str, object] | None
    try:
        routes = load_routing(config.routing, required=config.require_routing)
    except RoutingError as exc:
        add(config.rel(config.routing), "SG010", str(exc).replace(f"{config.routing}: ", ""))
        routes = None

    folders = discover(config.skills_dir)
    for folder in folders:
        rel = config.rel(folder / SKILL_FILE)
        if not (folder / SKILL_FILE).is_file():
            add(rel, "SG001", f"'{folder.name}/' has no {SKILL_FILE}")
            continue
        try:
            skill = read_skill(folder)
        except FrontmatterError as exc:
            add(rel, "SG002", str(exc))
            continue

        fm = skill.frontmatter
        for key in config.required_fields:
            value = fm.get(key)
            if value is None or (isinstance(value, str) and not value.strip()):
                add(rel, "SG003", f"missing required field '{key}'")

        name = fm.get("name")
        if name not in (None, "") and str(name) != folder.name:
            add(rel, "SG004", f"name '{name}' does not match folder '{folder.name}'")
        if not NAME_RE.match(folder.name) or len(folder.name) > MAX_NAME_LENGTH:
            add(
                rel,
                "SG005",
                f"'{folder.name}' must be lowercase letters, digits and single hyphens, "
                f"at most {MAX_NAME_LENGTH} characters",
            )

        description = fm.get("description")
        if isinstance(description, str) and description.strip():
            length = len(" ".join(description.split()))
            if length < config.description_min_length:
                add(
                    rel,
                    "SG006",
                    f"description is {length} characters; at least "
                    f"{config.description_min_length} are needed to route on",
                )
            if length > config.description_max_length:
                add(
                    rel,
                    "SG007",
                    f"description is {length} characters; the maximum is "
                    f"{config.description_max_length}",
                )

        if routes is not None and config.require_routing and folder.name not in routes:
            add(rel, "SG008", f"no entry for '{folder.name}' in {config.rel(config.routing)}")

    if routes is not None:
        names = {f.name for f in folders}
        for orphan in sorted(set(routes) - names):
            add(config.rel(config.routing), "SG009", f"'{orphan}' has no skill folder")

    return sorted(findings)
