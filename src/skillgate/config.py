"""Configuration discovery and validation.

skillgate reads its settings from, in order of precedence:

1. an explicit ``--config`` file,
2. the nearest ``skillgate.toml`` (top-level keys), or the nearest
   ``pyproject.toml`` that has a ``[tool.skillgate]`` table, searching from the
   working directory upwards,
3. built-in defaults, rooted at the working directory.

All paths in a config file are relative to the directory that holds it.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_SKILLS_DIR = ".claude/skills"

# Output files default to living next to the skills, so a project that only
# sets `skills_dir` gets a self-contained setup.
_DERIVED_DEFAULTS = {
    "routing": "routing.json",
    "lock": ".skillgate-lock.json",
    "index": "index.json",
    "registry": "SKILLS.md",
    "evals": "evals.json",
}

DEFAULT_EVAL_MODEL = "claude-opus-5-5"
EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")

_KNOWN_KEYS = {
    "skills_dir",
    *_DERIVED_DEFAULTS,
    "required_fields",
    "description_min_length",
    "description_max_length",
    "require_routing",
    "eval_model",
    "eval_effort",
    "eval_min_accuracy",
}


class ConfigError(Exception):
    """The configuration is missing, unreadable or invalid."""


@dataclass(frozen=True)
class Config:
    root: Path
    skills_dir: Path
    routing: Path
    lock: Path
    index: Path
    registry: Path
    evals: Path
    required_fields: tuple[str, ...] = ("name", "description")
    description_min_length: int = 40
    # Claude Code truncates skill descriptions beyond 1024 characters.
    description_max_length: int = 1024
    require_routing: bool = True
    eval_model: str = DEFAULT_EVAL_MODEL
    eval_effort: str | None = None  # None: the model's own default
    eval_min_accuracy: float = 1.0
    source: Path | None = None

    def rel(self, path: Path) -> str:
        """Render ``path`` relative to the project root, for messages and the index."""
        try:
            return path.resolve().relative_to(self.root.resolve()).as_posix()
        except ValueError:
            return path.as_posix()


def load_config(cwd: Path | None = None, explicit: Path | None = None) -> Config:
    cwd = (cwd or Path.cwd()).resolve()
    if explicit is not None:
        explicit = (cwd / explicit).resolve()
        if not explicit.is_file():
            raise ConfigError(f"config file not found: {explicit}")
        table = _read_table(explicit, required=True)
        return _build(explicit.parent, table, explicit)

    found = find_config(cwd)
    if found is None:
        return _build(cwd, {}, None)
    path, table = found
    return _build(path.parent, table, path)


def find_config(start: Path) -> tuple[Path, dict[str, Any]] | None:
    for directory in (start, *start.parents):
        dedicated = directory / "skillgate.toml"
        if dedicated.is_file():
            return dedicated, _read_table(dedicated, required=True)
        pyproject = directory / "pyproject.toml"
        if pyproject.is_file():
            table = _read_table(pyproject, required=False)
            if table is not None:
                return pyproject, table
    return None


def _read_table(path: Path, *, required: bool) -> dict[str, Any] | None:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: invalid TOML: {exc}") from exc
    if path.name == "pyproject.toml":
        table = data.get("tool", {}).get("skillgate")
        if table is None:
            if required:
                raise ConfigError(f"{path}: no [tool.skillgate] table")
            return None
        return table
    return data


def _build(root: Path, table: dict[str, Any], source: Path | None) -> Config:
    unknown = sorted(set(table) - _KNOWN_KEYS)
    if unknown:
        raise ConfigError(f"{source}: unknown setting(s): {', '.join(unknown)}")

    skills_dir = root / _string(table, "skills_dir", DEFAULT_SKILLS_DIR, source)
    paths = {
        key: (root / table[key]) if key in table else (skills_dir / default)
        for key, default in _DERIVED_DEFAULTS.items()
    }
    for key in _DERIVED_DEFAULTS:
        if key in table:
            _string(table, key, "", source)

    required = table.get("required_fields", ["name", "description"])
    if not isinstance(required, list) or not all(isinstance(f, str) for f in required):
        raise ConfigError(f"{source}: required_fields must be a list of strings")

    min_len = _int(table, "description_min_length", 40, source)
    max_len = _int(table, "description_max_length", 1024, source)
    if min_len > max_len:
        raise ConfigError(f"{source}: description_min_length is larger than the maximum")

    require_routing = table.get("require_routing", True)
    if not isinstance(require_routing, bool):
        raise ConfigError(f"{source}: require_routing must be true or false")

    eval_model = _string(table, "eval_model", DEFAULT_EVAL_MODEL, source)
    eval_effort = table.get("eval_effort")
    if eval_effort is not None and eval_effort not in EFFORT_LEVELS:
        raise ConfigError(f"{source}: eval_effort must be one of {', '.join(EFFORT_LEVELS)}")
    min_accuracy = table.get("eval_min_accuracy", 1.0)
    if (
        isinstance(min_accuracy, bool)
        or not isinstance(min_accuracy, int | float)
        or not 0 <= min_accuracy <= 1
    ):
        raise ConfigError(f"{source}: eval_min_accuracy must be a number from 0 to 1")

    return Config(
        root=root,
        skills_dir=skills_dir,
        required_fields=tuple(required),
        description_min_length=min_len,
        description_max_length=max_len,
        require_routing=require_routing,
        eval_model=eval_model,
        eval_effort=eval_effort,
        eval_min_accuracy=float(min_accuracy),
        source=source,
        **paths,
    )


def _string(table: dict[str, Any], key: str, default: str, source: Path | None) -> str:
    value = table.get(key, default)
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{source}: {key} must be a non-empty string")
    return value


def _int(table: dict[str, Any], key: str, default: int, source: Path | None) -> int:
    value = table.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ConfigError(f"{source}: {key} must be a non-negative integer")
    return value
