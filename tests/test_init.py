import json

from skillgate.build import plan

GOOD = "A perfectly reasonable description that is long enough to route on."


def routing(project):
    return json.loads((project.skills / "routing.json").read_text())


def fresh(empty):
    (empty.skills / "routing.json").unlink()
    return empty


def test_creates_routing_from_existing_skills(empty):
    fresh(empty)
    empty.write_skill("b-skill", f"name: b-skill\ndescription: {GOOD}\ncategory: ops\nowner: me\n")
    empty.write_skill("a-skill", f"name: a-skill\ndescription: {GOOD}\n")
    (empty.skills / "not-a-skill").mkdir()

    result = empty.run("init")
    assert result.code == 0
    assert "added a-skill" in result.out and "added b-skill" in result.out
    assert routing(empty)["skills"] == {
        "a-skill": {"avoid": []},
        "b-skill": {"category": "ops", "owner": "me", "avoid": []},
    }


def test_first_build_after_init_leaves_skills_untouched(empty):
    fresh(empty)
    empty.write_skill("a-skill", f"name: a-skill\ndescription: {GOOD}\ncategory: ops\n")
    empty.run("init")
    changed = {c.path.name for c in plan(empty.config).changes}
    assert "SKILL.md" not in changed
    assert empty.run("build").code == 0
    assert empty.run("lint").code == 0


def test_adds_only_missing_entries_and_keeps_existing(demo):
    before = routing(demo)
    demo.write_skill("new-skill", f"name: new-skill\ndescription: {GOOD}\n")

    result = demo.run("init")
    assert result.code == 0
    after = routing(demo)
    assert after["skills"]["new-skill"] == {"avoid": []}
    del after["skills"]["new-skill"]
    assert after == before


def test_noop_when_every_skill_has_an_entry(demo):
    path = demo.skills / "routing.json"
    original = path.read_bytes()
    result = demo.run("init")
    assert result.code == 0
    assert "already has an entry" in result.out
    assert path.read_bytes() == original


def test_dry_run_writes_nothing(empty):
    fresh(empty)
    empty.write_skill("a-skill", f"name: a-skill\ndescription: {GOOD}\n")
    result = empty.run("init", "--dry-run")
    assert result.code == 0
    assert json.loads(result.out)["skills"] == {"a-skill": {"avoid": []}}
    assert not (empty.skills / "routing.json").exists()


def test_skill_with_broken_frontmatter_still_gets_an_entry(empty):
    (empty.skills / "broken").mkdir()
    (empty.skills / "broken" / "SKILL.md").write_text("no frontmatter\n")
    empty.run("init")
    assert routing(empty)["skills"] == {"broken": {"avoid": []}}


def test_refuses_to_extend_invalid_routing(empty):
    (empty.skills / "routing.json").write_text('{"skills": {"a": {"categroy": "x"}}}')
    result = empty.run("init")
    assert result.code == 2
    assert "unknown key" in result.out


def test_missing_skills_dir_is_an_error(empty):
    (empty.root / "skillgate.toml").write_text('skills_dir = "nowhere"\n')
    assert empty.run("init").code == 2
