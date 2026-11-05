"""``skillgate init``: scaffold routing.json from the skills already on disk."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from skillgate.config import Config
from skillgate.routing import RoutingError, load_routing
from skillgate.skills import SKILL_FILE, FrontmatterError, discover, read_skill


@dataclass
class InitPlan:
    path: Path
    added: list[str] = field(default_factory=list)
    text: str | None = None  # None: nothing to write


def plan_init(config: Config) -> InitPlan:
    """Add an entry for every skill that has none. Existing entries are never changed.

    New entries are seeded from the skill's current ``category`` and ``owner``,
    so the first ``skillgate build`` leaves every SKILL.md as it is.
    """
    result = InitPlan(path=config.routing)
    if config.routing.is_file():
        load_routing(config.routing)  # refuse to extend a file that is already invalid
        data: dict[str, Any] = json.loads(config.routing.read_text(encoding="utf-8"))
    else:
        data = {
            "_comment": "Routing overlay for skillgate: category, owner and an `avoid` "
            "list per skill. End an avoid item with (skill-name) to name the sibling "
            "to use instead. Apply with `skillgate build`.",
            "skills": {},
        }
    skills: dict[str, Any] = data["skills"]

    if not config.skills_dir.is_dir():
        raise RoutingError(f"skills folder not found: {config.skills_dir}")
    for folder in discover(config.skills_dir):
        if folder.name in skills or not (folder / SKILL_FILE).is_file():
            continue
        skills[folder.name] = _seed(folder)
        result.added.append(folder.name)

    if result.added or not config.routing.is_file():
        data["skills"] = dict(sorted(skills.items()))
        result.text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    return result


def _seed(folder: Path) -> dict[str, Any]:
    entry: dict[str, Any] = {}
    try:
        frontmatter = read_skill(folder).frontmatter
    except FrontmatterError:
        frontmatter = {}
    for key in ("category", "owner"):
        if isinstance(frontmatter.get(key), str):
            entry[key] = frontmatter[key]
    entry["avoid"] = []
    return entry
