"""skillgate eval, against a fake client and against the real SDK on a mock transport.

No test here makes a network call or needs an API key.
"""

import json
from types import SimpleNamespace

import httpx2 as httpx  # the HTTP client the anthropic SDK 1.x+ is built on
import pytest

from skillgate.config import ConfigError, load_config
from skillgate.evals import (
    Case,
    EvalError,
    answer_schema,
    load_cases,
    run,
    skill_catalogue,
)

SKILLS = {"changelog-writer", "commit-message", "markdown-tables", "release-notes", "sql-review"}


class FakeClient:
    """Answers each prompt from a {prompt: skill} map; records every request."""

    def __init__(self, answers, stop_reason="end_turn", raw=None):
        self.answers = answers
        self.stop_reason = stop_reason
        self.raw = raw
        self.requests = []
        self.messages = self

    def create(self, **kwargs):
        self.requests.append(kwargs)
        prompt = kwargs["messages"][0]["content"]
        text = (
            self.raw
            if self.raw is not None
            else json.dumps({"skill": self.answers.get(prompt, "none"), "reason": "because"})
        )
        return SimpleNamespace(
            stop_reason=self.stop_reason,
            content=[SimpleNamespace(type="text", text=text)],
            usage=SimpleNamespace(
                input_tokens=10,
                output_tokens=5,
                cache_read_input_tokens=100,
                cache_creation_input_tokens=0,
            ),
        )


def write_cases(project, cases):
    path = project.skills / "evals.json"
    path.write_text(json.dumps({"cases": cases}))
    return path


# --- cases file ------------------------------------------------------------


def test_demo_cases_are_valid(demo):
    names = {n for n, _ in skill_catalogue(demo.config)}
    cases = load_cases(demo.config.evals, names)
    assert len(cases) >= 5
    assert any(c.expect is None for c in cases)


@pytest.mark.parametrize(
    ("cases", "message"),
    [
        ([], "no cases"),
        ([{"prompt": "x"}], 'missing "expect"'),
        ([{"prompt": "", "expect": None}], "non-empty string"),
        ([{"prompt": "x", "expect": "ghost"}], "'ghost' is not a skill"),
        ([{"prompt": "x", "expect": None, "expected": "a"}], "unknown key"),
        (["just a string"], "expected an object"),
        ([{"prompt": "x", "expect": None}, {"prompt": " x ", "expect": None}], "duplicate"),
    ],
)
def test_invalid_cases(demo, cases, message):
    path = write_cases(demo, cases)
    with pytest.raises(EvalError, match=message):
        load_cases(path, SKILLS)


def test_missing_and_malformed_cases_file(demo, tmp_path):
    with pytest.raises(EvalError, match="not found"):
        load_cases(tmp_path / "nope.json", SKILLS)
    bad = tmp_path / "bad.json"
    bad.write_text("{")
    with pytest.raises(EvalError, match="invalid JSON"):
        load_cases(bad, SKILLS)


# --- what gets sent ---------------------------------------------------------


def test_catalogue_uses_built_descriptions(demo):
    # Strip the routing clause from disk: the eval must still see the composed
    # description, i.e. what the skill will say after `skillgate build`.
    path = demo.skill_md("release-notes")
    path.write_text(path.read_text().replace(" Don't use for updating", " X"))
    catalogue = dict(skill_catalogue(demo.config))
    assert catalogue["release-notes"].endswith(
        "Don't use for updating CHANGELOG.md itself (changelog-writer)."
    )


def test_catalogue_refuses_a_broken_project(demo):
    demo.write_skill("unrouted", "name: unrouted\ndescription: Not in routing.json at all.\n")
    with pytest.raises(EvalError, match="no entry in"):
        skill_catalogue(demo.config)


def test_answer_schema_only_allows_real_skills_or_none(demo):
    schema = answer_schema(skill_catalogue(demo.config))
    assert set(schema["properties"]["skill"]["enum"]) == SKILLS | {"none"}
    assert schema["additionalProperties"] is False


def test_request_shape(demo):
    client = FakeClient({})
    catalogue = skill_catalogue(demo.config)
    run(demo.config, [Case("hello", None)], catalogue, client=client)
    (request,) = client.requests
    assert request["model"] == "claude-opus-5-5"
    assert request["messages"] == [{"role": "user", "content": "hello"}]
    assert request["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "- sql-review: Review SQL migrations" in request["system"][0]["text"]
    assert request["output_config"]["format"]["type"] == "json_schema"
    assert "effort" not in request["output_config"]
    assert "temperature" not in request  # rejected by current models


def test_effort_and_model_come_from_config(demo):
    (demo.root / "skillgate.toml").write_text(
        (demo.root / "skillgate.toml").read_text()
        + 'eval_model = "claude-sonnet-5-5"\neval_effort = "low"\n'
    )
    client = FakeClient({})
    run(demo.config, [Case("hi", None)], skill_catalogue(demo.config), client=client)
    assert client.requests[0]["model"] == "claude-sonnet-5-5"
    assert client.requests[0]["output_config"]["effort"] == "low"


@pytest.mark.parametrize(
    ("toml", "message"),
    [
        ('eval_effort = "turbo"\n', "eval_effort must be one of"),
        ("eval_min_accuracy = 1.5\n", "from 0 to 1"),
        ("eval_min_accuracy = true\n", "from 0 to 1"),
    ],
)
def test_invalid_eval_settings(tmp_path, toml, message):
    (tmp_path / "skillgate.toml").write_text(toml)
    with pytest.raises(ConfigError, match=message):
        load_config(tmp_path)


# --- scoring ----------------------------------------------------------------


def test_scoring_and_collisions(demo):
    cases = [
        Case("notes for 2.0", "release-notes"),
        Case("notes for 3.0", "release-notes"),
        Case("update the changelog", "changelog-writer"),
        Case("what is quicksort", None),
        Case("fix this table", "markdown-tables"),
    ]
    client = FakeClient(
        {
            "notes for 2.0": "changelog-writer",  # collision
            "notes for 3.0": "changelog-writer",  # same collision again
            "update the changelog": "changelog-writer",
            "what is quicksort": "none",
            "fix this table": "none",  # a miss, but not a collision
        }
    )
    report = run(demo.config, cases, skill_catalogue(demo.config), client=client)
    assert report.passed == 2
    assert report.accuracy == pytest.approx(0.4)
    assert report.collisions() == [("release-notes", "changelog-writer", 2)]
    assert report.input_tokens == 50
    assert report.cache_read_input_tokens == 500


@pytest.mark.parametrize(
    ("stop_reason", "raw", "error"),
    [
        ("refusal", None, "declined"),
        ("max_tokens", None, "cut off"),
        ("end_turn", "not json", "not valid JSON"),
        ("end_turn", '{"reason": "no skill key"}', "not valid JSON"),
    ],
)
def test_bad_answers_are_errors_not_passes(demo, stop_reason, raw, error):
    client = FakeClient({}, stop_reason=stop_reason, raw=raw)
    report = run(demo.config, [Case("x", None)], skill_catalogue(demo.config), client=client)
    (outcome,) = report.outcomes
    assert not outcome.passed
    assert error in outcome.error


def test_api_failure_aborts_the_run(demo):
    class Broken:
        def __init__(self):
            self.calls = 0
            self.messages = self

        def create(self, **kwargs):
            self.calls += 1
            raise RuntimeError("401 invalid x-api-key")

    client = Broken()
    cases = [Case("a", None), Case("b", None)]
    with pytest.raises(EvalError, match="API call failed"):
        run(demo.config, cases, skill_catalogue(demo.config), client=client)
    assert client.calls == 1


# --- CLI --------------------------------------------------------------------


def test_cli_dry_run_needs_no_key_or_sdk(demo, monkeypatch):
    def boom():
        raise AssertionError("dry run must not build a client")

    monkeypatch.setattr("skillgate.cli.make_client", boom)
    result = demo.run("eval", "--dry-run")
    assert result.code == 0
    assert "9 API calls" in result.out
    assert "- markdown-tables:" in result.out


def test_cli_exit_codes_follow_min_accuracy(demo, monkeypatch):
    cases = json.loads(demo.config.evals.read_text())["cases"]
    perfect = {c["prompt"]: c["expect"] or "none" for c in cases}
    monkeypatch.setattr("skillgate.cli.make_client", lambda: FakeClient(perfect))
    result = demo.run("eval")
    assert result.code == 0
    assert "9/9 routed correctly (100%)" in result.out

    one_wrong = dict(perfect)
    first = cases[0]["prompt"]
    one_wrong[first] = "release-notes"
    monkeypatch.setattr("skillgate.cli.make_client", lambda: FakeClient(one_wrong))
    result = demo.run("eval")
    assert result.code == 1
    assert "Collisions" in result.out

    (demo.root / "skillgate.toml").write_text(
        (demo.root / "skillgate.toml").read_text() + "eval_min_accuracy = 0.8\n"
    )
    assert demo.run("eval").code == 0


def test_cli_json_report(demo, monkeypatch):
    monkeypatch.setattr("skillgate.cli.make_client", lambda: FakeClient({}))
    result = demo.run("eval", "--json")
    data = json.loads(result.out)
    assert data["cases"] == 9
    assert {"prompt", "expected", "chosen", "passed", "reason", "error"} <= set(data["results"][0])


def test_cli_invalid_cases_is_a_usage_error(demo):
    write_cases(demo, [{"prompt": "x", "expect": "ghost"}])
    result = demo.run("eval", "--dry-run")
    assert result.code == 2
    assert "is not a skill" in result.out


def test_cli_missing_sdk_is_a_usage_error(demo, monkeypatch):
    import builtins

    real_import = builtins.__import__

    def no_anthropic(name, *args, **kwargs):
        if name == "anthropic":
            raise ImportError("no module named anthropic")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_anthropic)
    result = demo.run("eval")
    assert result.code == 2
    assert 'pip install "skillgate[eval]"' in result.out


# --- the real SDK, no network ------------------------------------------------


def test_real_sdk_request_and_response_on_a_mock_transport(demo):
    """Build the request with the actual Anthropic SDK and parse a real-shaped reply."""
    import anthropic  # dev extra, so this always runs in CI

    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "model": seen["body"]["model"],
                "content": [
                    {"type": "text", "text": '{"skill": "sql-review", "reason": "migration"}'}
                ],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 12, "output_tokens": 7},
            },
        )

    client = anthropic.Anthropic(
        api_key="test-key", http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    report = run(
        demo.config,
        [Case("Is this migration safe?", "sql-review")],
        skill_catalogue(demo.config),
        client=client,
    )
    assert report.passed == 1
    assert seen["url"].endswith("/v1/messages")
    body = seen["body"]
    assert body["output_config"]["format"]["schema"]["properties"]["skill"]["enum"][-1] == "none"
    assert body["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert report.input_tokens == 12
