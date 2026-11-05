"""The routing overlay (routing.json) and the lock file that keeps it idempotent.

routing.json is the single source of truth for a skill's ``category``,
``owner`` and negative-routing clause (``avoid``). skillgate composes the
clause onto the skill's own description, so vendored skills never need a hand
edit: re-vendor from upstream, run ``skillgate build``, done.

The lock file records, per skill, the *base* description (the skill's own
words) and the clause that was applied. On the next run an unchanged
description is recognised exactly and its base reused, so the clause is never
applied twice. If the lock is lost, the clause is stripped from the end of the
description instead, so the result is the same.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROUTE_KEYS = frozenset({"category", "owner", "avoid"})
LOCK_VERSION = 1


class RoutingError(Exception):
    """routing.json is missing, unreadable or malformed."""


@dataclass(frozen=True)
class Route:
    category: str | None = None
    owner: str | None = None
    clause: str = ""


@dataclass(frozen=True)
class LockEntry:
    base: str
    clause: str


def normalize(text: str) -> str:
    """Collapse all whitespace runs to single spaces."""
    return " ".join(text.split())


def avoid_clause(avoid: str | list[str] | None) -> str:
    """Turn an ``avoid`` value into the sentence appended to a description.

    A string is used verbatim. A list is joined into one generated sentence:
    ``["a (x)", "b (y)"]`` -> ``"Don't use for a (x) or b (y)."``
    """
    if not avoid:
        return ""
    if isinstance(avoid, str):
        return normalize(avoid)
    items = [normalize(item).rstrip(".") for item in avoid if normalize(item)]
    if not items:
        return ""
    if len(items) == 1:
        joined = items[0]
    elif len(items) == 2:
        joined = f"{items[0]} or {items[1]}"
    else:
        joined = ", ".join(items[:-1]) + f", or {items[-1]}"
    return f"Don't use for {joined}."


def terminate(text: str) -> str:
    """Normalise whitespace and make sure the text ends a sentence."""
    text = normalize(text)
    if text and text[-1] not in ".!?":
        text += "."
    return text


def compose(base: str, clause: str) -> str:
    """Join base and clause with a sentence boundary between them."""
    if not clause:
        return normalize(base)
    return f"{terminate(base)} {clause}".strip()


def resolve_base(current: str, entry: LockEntry | None, clauses: set[str]) -> str:
    """The skill's own description, with any applied routing clause removed.

    Exact, not heuristic: if ``current`` is what we composed last time, the
    stored base is returned. Otherwise ``current`` is a fresh description (a
    re-vendor, a hand edit, or a lost lock) and any known clause is stripped
    from its end, repeatedly, so a doubled clause is cleaned up too.
    """
    current = normalize(current)
    if entry is not None and compose(entry.base, entry.clause) == current:
        return entry.base
    base = current
    known = sorted((c for c in clauses if c), key=len, reverse=True)
    stripped = True
    while stripped:
        stripped = False
        for clause in known:
            if base == clause or base.endswith(" " + clause):
                base = base[: -len(clause)].rstrip()
                stripped = True
                break
    return base


def load_routing(path: Path, *, required: bool = True) -> dict[str, Route]:
    if not path.is_file():
        if required:
            raise RoutingError(f"routing file not found: {path}")
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RoutingError(f"{path}: invalid JSON: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("skills"), dict):
        raise RoutingError(f'{path}: expected an object with a "skills" object')

    routes: dict[str, Route] = {}
    for name, entry in data["skills"].items():
        routes[name] = _parse_route(path, name, entry)
    return routes


def _parse_route(path: Path, name: str, entry: Any) -> Route:
    where = f"{path}: skills.{name}"
    if not isinstance(entry, dict):
        raise RoutingError(f"{where}: expected an object")
    unknown = sorted(k for k in entry if k not in ROUTE_KEYS and not k.startswith("_"))
    if unknown:
        raise RoutingError(
            f"{where}: unknown key(s) {', '.join(unknown)} "
            f"(allowed: {', '.join(sorted(ROUTE_KEYS))})"
        )
    for key in ("category", "owner"):
        if key in entry and entry[key] is not None and not isinstance(entry[key], str):
            raise RoutingError(f"{where}.{key}: expected a string")
    avoid = entry.get("avoid")
    if avoid is not None and not (
        isinstance(avoid, str)
        or (isinstance(avoid, list) and all(isinstance(a, str) for a in avoid))
    ):
        raise RoutingError(f"{where}.avoid: expected a string or a list of strings")
    return Route(
        category=entry.get("category"), owner=entry.get("owner"), clause=avoid_clause(avoid)
    )


def load_lock(path: Path) -> tuple[dict[str, LockEntry], str | None]:
    """Read the lock. A missing or unreadable lock is not fatal: it self-heals.

    Returns the entries and, if the lock could not be used, a note saying why.
    """
    if not path.is_file():
        return {}, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        entries = {
            name: LockEntry(base=str(e["base"]), clause=str(e["clause"]))
            for name, e in data["skills"].items()
        }
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
        return {}, f"{path.name} is unreadable and will be rebuilt from the skill files"
    return entries, None


def dump_lock(entries: dict[str, LockEntry]) -> str:
    data = {
        "version": LOCK_VERSION,
        "skills": {
            name: {"base": e.base, "clause": e.clause} for name, e in sorted(entries.items())
        },
    }
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"
