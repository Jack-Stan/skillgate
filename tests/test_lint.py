import json

import pytest

from skillgate.lint import RULES, lint

GOOD = "A perfectly reasonable description that is long enough to route on."


def codes(project):
    return [f.code for f in lint(project.config)]


def route(project, *names):
    path = project.skills / "routing.json"
    data = json.loads(path.read_text())
    data["skills"].update({n: {"category": "c"} for n in names})
    path.write_text(json.dumps(data))


def test_demo_passes(demo):
    result = demo.run("lint")
    assert result.code == 0
    assert "all skills pass" in result.out


def test_clean_skill_passes(empty):
    empty.write_skill("good-skill", f"name: good-skill\ndescription: {GOOD}\n")
    route(empty, "good-skill")
    assert codes(empty) == []


def test_missing_skill_md(empty):
    (empty.skills / "hollow").mkdir()
    route(empty, "hollow")
    assert codes(empty) == ["SG001"]


@pytest.mark.parametrize("text", ["no fence\n", "---\nname: a\n", "---\nname: [x\n---\n"])
def test_bad_frontmatter(empty, text):
    (empty.skills / "broken").mkdir()
    (empty.skills / "broken" / "SKILL.md").write_text(text)
    route(empty, "broken")
    assert codes(empty) == ["SG002"]


def test_missing_required_fields(empty):
    empty.write_skill("bare", "license: MIT\n")
    route(empty, "bare")
    findings = lint(empty.config)
    assert [f.code for f in findings] == ["SG003", "SG003"]
    assert {f.message for f in findings} == {
        "missing required field 'name'",
        "missing required field 'description'",
    }


def test_blank_description_counts_as_missing(empty):
    empty.write_skill("blank", "name: blank\ndescription: '   '\n")
    route(empty, "blank")
    assert codes(empty) == ["SG003"]


def test_name_must_match_folder(empty):
    empty.write_skill("right-name", f"name: wrong-name\ndescription: {GOOD}\n")
    route(empty, "right-name")
    findings = lint(empty.config)
    assert [f.code for f in findings] == ["SG004"]
    assert "'wrong-name' does not match folder 'right-name'" in findings[0].message


@pytest.mark.parametrize("folder", ["Bad_Name", "double--hyphen", "-leading", "x" * 65])
def test_invalid_skill_names(empty, folder):
    empty.write_skill(folder, f"name: {folder}\ndescription: {GOOD}\n")
    route(empty, folder)
    assert codes(empty) == ["SG005"]


def test_description_too_short(empty):
    empty.write_skill("terse", "name: terse\ndescription: Does stuff.\n")
    route(empty, "terse")
    assert codes(empty) == ["SG006"]


def test_description_too_long(empty):
    empty.write_skill("verbose", f"name: verbose\ndescription: {'word ' * 250}\n")
    route(empty, "verbose")
    assert codes(empty) == ["SG007"]


def test_length_limits_come_from_config(empty):
    (empty.root / "skillgate.toml").write_text("description_max_length = 50\n")
    empty.write_skill("medium", f"name: medium\ndescription: {GOOD}\n")
    route(empty, "medium")
    assert codes(empty) == ["SG007"]


def test_skill_without_routing_entry(empty):
    empty.write_skill("loner", f"name: loner\ndescription: {GOOD}\n")
    assert codes(empty) == ["SG008"]


def test_routing_not_required_when_disabled(empty):
    (empty.root / "skillgate.toml").write_text("require_routing = false\n")
    (empty.skills / "routing.json").unlink()
    empty.write_skill("loner", f"name: loner\ndescription: {GOOD}\n")
    assert codes(empty) == []


def test_routing_entry_without_folder(empty):
    route(empty, "ghost")
    assert codes(empty) == ["SG009"]


def test_invalid_routing_file(empty):
    (empty.skills / "routing.json").write_text("[]")
    empty.write_skill("a-skill", f"name: a-skill\ndescription: {GOOD}\n")
    assert codes(empty) == ["SG010"]


def test_all_rules_run_and_are_reported(empty):
    # One file breaking several rules reports every one of them, not just the first.
    empty.write_skill("Bad", "name: other\ndescription: short\n")
    route(empty, "ghost")
    result = empty.run("lint")
    assert result.code == 1
    for code in ("SG004", "SG005", "SG006", "SG008", "SG009"):
        assert code in result.out
    assert "5 problem(s)" in result.out


def test_every_rule_is_documented():
    assert sorted(RULES) == [f"SG{n:03d}" for n in range(1, 11)]
