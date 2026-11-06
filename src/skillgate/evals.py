"""``skillgate eval``: measure whether Claude routes sample prompts to the right skill.

Each case is a prompt plus the skill it should land on (or ``null`` when no
skill should fire). For every case, Claude is shown the skill names and
descriptions exactly as ``skillgate build`` would leave them, and has to answer
with one skill name or ``none``. Wrong answers between two real skills are
routing collisions: the descriptions don't separate those skills well enough.

This calls the Claude API and costs money, so it never runs implicitly: it
needs ``pip install "skillgate[eval]"`` and an Anthropic credential, and
``--dry-run`` shows exactly what would be sent without calling anything.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from skillgate.build import plan
from skillgate.config import Config

NONE = "none"
CASE_KEYS = frozenset({"prompt", "expect"})

SYSTEM_PROMPT = """\
You route a user's request to at most one skill. Each skill below has a name \
and a description saying when to use it and when not to. Pick the skill whose \
description fits the request best. If no skill fits, answer "none". Judge only \
by the descriptions; do not try to carry out the request.

Skills:
{skills}"""


class EvalError(Exception):
    """The cases file is missing or invalid, or the API could not be used."""


@dataclass(frozen=True)
class Case:
    prompt: str
    expect: str | None


@dataclass(frozen=True)
class Outcome:
    case: Case
    got: str | None  # None means "no skill"; see `error` for failures
    reason: str = ""
    error: str | None = None

    @property
    def passed(self) -> bool:
        return self.error is None and self.got == self.case.expect


@dataclass
class Report:
    model: str
    outcomes: list[Outcome] = field(default_factory=list)
    input_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    output_tokens: int = 0

    @property
    def passed(self) -> int:
        return sum(o.passed for o in self.outcomes)

    @property
    def accuracy(self) -> float:
        return self.passed / len(self.outcomes) if self.outcomes else 1.0

    def collisions(self) -> list[tuple[str, str, int]]:
        """(expected skill, chosen skill, count) for misroutes between two real skills."""
        pairs = Counter(
            (o.case.expect, o.got)
            for o in self.outcomes
            if not o.passed and o.error is None and o.case.expect and o.got
        )
        return [(a, b, n) for (a, b), n in sorted(pairs.items(), key=lambda kv: (-kv[1], kv[0]))]

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "cases": len(self.outcomes),
            "passed": self.passed,
            "accuracy": round(self.accuracy, 4),
            "usage": {
                "input_tokens": self.input_tokens,
                "cache_read_input_tokens": self.cache_read_input_tokens,
                "cache_creation_input_tokens": self.cache_creation_input_tokens,
                "output_tokens": self.output_tokens,
            },
            "collisions": [
                {"expected": a, "chosen": b, "count": n} for a, b, n in self.collisions()
            ],
            "results": [
                {
                    "prompt": o.case.prompt,
                    "expected": o.case.expect,
                    "chosen": o.got,
                    "passed": o.passed,
                    "reason": o.reason,
                    "error": o.error,
                }
                for o in self.outcomes
            ],
        }


def load_cases(path: Path, skill_names: set[str]) -> list[Case]:
    """Read and validate the cases file. Every expected skill must exist."""
    if not path.is_file():
        raise EvalError(f"cases file not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise EvalError(f"{path}: invalid JSON: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("cases"), list):
        raise EvalError(f'{path}: expected an object with a "cases" list')

    cases = []
    for i, raw in enumerate(data["cases"]):
        where = f"{path}: cases[{i}]"
        if not isinstance(raw, dict):
            raise EvalError(f"{where}: expected an object")
        unknown = sorted(k for k in raw if k not in CASE_KEYS and not k.startswith("_"))
        if unknown:
            raise EvalError(f"{where}: unknown key(s) {', '.join(unknown)}")
        prompt = raw.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise EvalError(f"{where}: prompt must be a non-empty string")
        if "expect" not in raw:
            raise EvalError(f'{where}: missing "expect" (a skill name, or null for no skill)')
        expect = raw["expect"]
        if expect is not None and (not isinstance(expect, str) or expect not in skill_names):
            raise EvalError(f"{where}: expect {expect!r} is not a skill in this project")
        cases.append(Case(prompt=prompt.strip(), expect=expect))
    if not cases:
        raise EvalError(f"{path}: no cases")
    return cases


def skill_catalogue(config: Config) -> list[tuple[str, str]]:
    """(name, description) per skill, as they will read once `skillgate build` has run."""
    result = plan(config)
    if result.problems:
        raise EvalError(
            "fix these before running evals:\n" + "\n".join(f"  {p}" for p in result.problems)
        )
    return [(s["name"], " ".join(s["description"].split())) for s in result.skills]


def system_prompt(catalogue: list[tuple[str, str]]) -> str:
    return SYSTEM_PROMPT.format(skills="\n".join(f"- {n}: {d}" for n, d in catalogue))


def answer_schema(catalogue: list[tuple[str, str]]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "skill": {"type": "string", "enum": [n for n, _ in catalogue] + [NONE]},
            "reason": {"type": "string"},
        },
        "required": ["skill", "reason"],
        "additionalProperties": False,
    }


def make_client() -> Any:
    try:
        import anthropic
    except ImportError as exc:
        raise EvalError(
            'skillgate eval needs the Anthropic SDK: pip install "skillgate[eval]"'
        ) from exc
    return anthropic.Anthropic()


def run(
    config: Config,
    cases: list[Case],
    catalogue: list[tuple[str, str]],
    *,
    client: Any,
    model: str | None = None,
) -> Report:
    """Route every case through the model. API failures abort the run (EvalError)."""
    model = model or config.eval_model
    report = Report(model=model)
    # Identical system prompt for every case, so cache it: only the first
    # request pays full price for the skill list.
    system = [
        {
            "type": "text",
            "text": system_prompt(catalogue),
            "cache_control": {"type": "ephemeral"},
        }
    ]
    output_config: dict[str, Any] = {
        "format": {"type": "json_schema", "schema": answer_schema(catalogue)}
    }
    if config.eval_effort:
        output_config["effort"] = config.eval_effort

    for case in cases:
        try:
            response = client.messages.create(
                model=model,
                max_tokens=16000,
                system=system,
                messages=[{"role": "user", "content": case.prompt}],
                output_config=output_config,
            )
        # The SDK already retries 408/409/429/5xx and connection errors. Anything
        # that still fails (bad key, unknown model, outage) would fail every
        # case the same way, so stop at the first one rather than burn quota.
        except Exception as exc:
            raise EvalError(f"API call failed on case {case.prompt[:50]!r}: {exc}") from exc
        for key in (
            "input_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
            "output_tokens",
        ):
            setattr(report, key, getattr(report, key) + _usage(response, key))
        report.outcomes.append(_outcome(case, response))
    return report


def _outcome(case: Case, response: Any) -> Outcome:
    if response.stop_reason == "refusal":
        return Outcome(case, got=None, error="the model declined to answer")
    if response.stop_reason == "max_tokens":
        return Outcome(case, got=None, error="the answer was cut off (max_tokens)")
    text = next((b.text for b in response.content if b.type == "text"), None)
    try:
        answer = json.loads(text or "")
        skill = answer["skill"]
        reason = str(answer.get("reason", ""))
    except (json.JSONDecodeError, KeyError, TypeError):
        return Outcome(case, got=None, error="the answer was not valid JSON")
    return Outcome(case, got=None if skill == NONE else skill, reason=reason)


def _usage(response: Any, key: str) -> int:
    value = getattr(getattr(response, "usage", None), key, 0)
    return value if isinstance(value, int) else 0
