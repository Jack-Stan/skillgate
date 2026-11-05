"""Discovering skill folders and reading/writing SKILL.md frontmatter."""

from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

SKILL_FILE = "SKILL.md"

# Claude Code skill names: lowercase letters, digits and single hyphens, max 64.
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_NAME_LENGTH = 64

# Keys skillgate writes; rendered first, in this order, so diffs stay readable.
KEY_ORDER = ("name", "description", "category", "owner")


class FrontmatterError(ValueError):
    """A SKILL.md has no frontmatter, an unclosed block, or invalid YAML."""


@dataclass(frozen=True)
class Skill:
    folder: str
    path: Path
    text: str
    frontmatter: dict[str, Any]
    body: str

    @property
    def description(self) -> str:
        value = self.frontmatter.get("description")
        return "" if value is None else str(value)


def discover(skills_dir: Path) -> list[Path]:
    """Every visible sub-directory of the skills folder, sorted by name."""
    return sorted(
        p for p in skills_dir.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))
    )


def read_skill(folder: Path) -> Skill:
    path = folder / SKILL_FILE
    text = path.read_text(encoding="utf-8")
    frontmatter, body = parse_frontmatter(text)
    return Skill(folder=folder.name, path=path, text=text, frontmatter=frontmatter, body=body)


def split_frontmatter(text: str) -> tuple[str, str]:
    """Return (raw frontmatter, body). The body is kept byte-for-byte."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].lstrip("﻿").rstrip("\r\n") != "---":
        raise FrontmatterError("file does not start with a '---' frontmatter fence")
    for i in range(1, len(lines)):
        if lines[i].rstrip("\r\n") == "---":
            return "".join(lines[1:i]), "".join(lines[i + 1 :])
    raise FrontmatterError("frontmatter is never closed by a '---' line")


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    raw, body = split_frontmatter(text)
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        reason = str(exc).splitlines()[0]
        raise FrontmatterError(f"frontmatter is not valid YAML: {reason}") from exc
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise FrontmatterError("frontmatter is not a key/value mapping")
    return data, body


def render_frontmatter(data: dict[str, Any]) -> str:
    """Render frontmatter deterministically, with the description as a folded block.

    The output always parses back to exactly ``data``; if the hand-rolled layout
    would not, plain ``yaml.safe_dump`` is used instead.
    """
    ordered = {k: data[k] for k in KEY_ORDER if k in data}
    ordered.update((k, v) for k, v in data.items() if k not in ordered)

    lines = []
    for key, value in ordered.items():
        if key == "description" and isinstance(value, str) and value:
            lines.append(f"description: {fold(value)}")
        else:
            lines.append(_dump({key: value}))
    text = "\n".join(lines) + "\n"
    if not _round_trips(text, ordered):
        text = _dump(ordered) + "\n"
    return f"---\n{text}---\n"


def fold(value: str, indent: str = "  ", width: int = 78) -> str:
    """A YAML ``>-`` block. Never breaks on hyphens: a folded line break reads
    back as a space, which would turn ``sql-review`` into ``sql- review``."""
    body = textwrap.fill(
        " ".join(value.split()),
        width=width,
        initial_indent=indent,
        subsequent_indent=indent,
        break_on_hyphens=False,
        break_long_words=False,
    )
    return ">-\n" + body


def _round_trips(text: str, data: dict[str, Any]) -> bool:
    try:
        return yaml.safe_load(text) == data
    except yaml.YAMLError:
        return False


def _dump(data: dict[str, Any]) -> str:
    return yaml.safe_dump(
        data, sort_keys=False, allow_unicode=True, width=float("inf"), default_flow_style=False
    ).rstrip("\n")
