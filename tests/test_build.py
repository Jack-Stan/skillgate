"""build / check: idempotency, drift detection, lock self-heal, re-vendoring."""

import json

from skillgate.build import plan

LOCK = ".claude/skills/.skillgate-lock.json"


def test_demo_is_committed_in_sync(demo):
    result = demo.run("check")
    assert result.code == 0, result.out
    assert "in sync (5 skills)" in result.out


def test_build_is_idempotent(demo):
    before = demo.snapshot()
    assert demo.run("build").code == 0
    assert demo.snapshot() == before


def test_build_from_scratch_matches_committed_output(demo):
    # Reset every skill to its own words only, and drop all generated files.
    built = demo.snapshot()
    lock = json.loads((demo.root / LOCK).read_text())["skills"]
    for name, entry in lock.items():
        path = demo.skill_md(name)
        body = path.read_text().split("---\n", 2)[2]
        description = json.dumps(entry["base"])  # JSON strings are valid YAML
        path.write_text(f"---\nname: {name}\ndescription: {description}\n---\n{body}")
    demo.skill_md("markdown-tables").write_text(
        (demo.root / "upstream/markdown-tables/SKILL.md").read_text()
    )
    for name in ("index.json", "SKILLS.md", ".skillgate-lock.json"):
        (demo.skills / name).unlink()

    assert demo.run("build").code == 0
    assert demo.snapshot() == built
    assert demo.run("build").code == 0
    assert demo.snapshot() == built


def test_check_changes_nothing(demo):
    demo.skill_md("sql-review").write_text(
        demo.skill_md("sql-review").read_text().replace("category: database", "category: wrong")
    )
    before = demo.snapshot()
    result = demo.run("check")
    assert result.code == 1
    assert demo.snapshot() == before


def test_check_detects_routing_edit(demo):
    routing = demo.skills / "routing.json"
    data = json.loads(routing.read_text())
    data["skills"]["sql-review"]["owner"] = "someone-else"
    routing.write_text(json.dumps(data))

    result = demo.run("check")
    assert result.code == 1
    assert "DRIFT  .claude/skills/sql-review/SKILL.md" in result.out
    assert "index.json" in result.out and "SKILLS.md" in result.out


def test_check_detects_hand_edited_index(demo):
    (demo.skills / "index.json").write_text("{}\n")
    result = demo.run("check")
    assert result.code == 1
    assert "index.json: out of date" in result.out


def test_check_detects_missing_outputs(demo):
    (demo.skills / "SKILLS.md").unlink()
    result = demo.run("check")
    assert result.code == 1
    assert "SKILLS.md: missing" in result.out


def test_check_diff_shows_change(demo):
    (demo.skills / "SKILLS.md").write_text("stale\n")
    result = demo.run("check", "--diff")
    assert "-stale" in result.out
    assert "+# Skills" in result.out


def test_check_passes_if_and_only_if_build_writes_nothing(demo):
    demo.skill_md("commit-message").write_text(
        demo.skill_md("commit-message").read_text().replace("owner: platform", "owner: x")
    )
    assert plan(demo.config).changes
    demo.run("build")
    assert plan(demo.config).changes == []


def test_changed_avoid_replaces_the_old_clause(demo):
    routing = demo.skills / "routing.json"
    data = json.loads(routing.read_text())
    data["skills"]["release-notes"]["avoid"] = ["drafting tweets (social-posts)"]
    routing.write_text(json.dumps(data))

    demo.run("build")
    description = _description(demo)
    assert description.endswith("Don't use for drafting tweets (social-posts).")
    assert "changelog-writer" not in description
    assert description.count("Don't use") == 1


def _description(demo):
    index = json.loads((demo.skills / "index.json").read_text())
    return next(s["description"] for s in index["skills"] if s["name"] == "release-notes")


def test_lock_self_heals(demo):
    before = demo.snapshot()
    (demo.root / LOCK).unlink()

    result = demo.run("check")
    assert result.code == 1
    assert ".skillgate-lock.json: missing" in result.out

    assert demo.run("build").code == 0
    # No clause was folded into the base: every file is byte-identical again.
    assert demo.snapshot() == before


def test_corrupt_lock_self_heals(demo):
    before = demo.snapshot()
    (demo.root / LOCK).write_text("not json")
    result = demo.run("build")
    assert result.code == 0
    assert "unreadable" in result.out
    assert demo.snapshot() == before


def test_doubled_clause_is_cleaned_up(demo):
    path = demo.skill_md("commit-message")
    clause = "Don't use for summarising a whole release (changelog-writer)."
    path.write_text(path.read_text().replace(clause, f"{clause} {clause}"))
    (demo.root / LOCK).unlink()

    demo.run("build")
    text = path.read_text()
    assert " ".join(text.split()).count(clause) == 1


def test_revendor_restores_routing(demo):
    vendored = demo.skill_md("markdown-tables")
    built = vendored.read_text()
    vendored.write_text((demo.root / "upstream/markdown-tables/SKILL.md").read_text())

    assert demo.run("check").code == 1
    assert demo.run("build").code == 0
    assert vendored.read_text() == built


def test_upstream_description_update_is_taken_as_new_base(demo):
    vendored = demo.skill_md("markdown-tables")
    upstream = (demo.root / "upstream/markdown-tables/SKILL.md").read_text()
    vendored.write_text(upstream.replace("Align, sort and repair", "Align and repair"))

    demo.run("build")
    lock = json.loads((demo.root / LOCK).read_text())
    assert lock["skills"]["markdown-tables"]["base"].startswith("Align and repair")
    assert "Don't use" not in lock["skills"]["markdown-tables"]["base"]
    assert demo.run("check").code == 0


def test_body_and_unmanaged_keys_survive_build(demo):
    path = demo.skill_md("markdown-tables")
    body = path.read_text().split("---\n", 2)[2]
    path.write_text(path.read_text().replace("owner: docs-team", "owner: old"))
    demo.run("build")
    text = path.read_text()
    assert text.split("---\n", 2)[2] == body
    assert "license: MIT" in text


def test_in_sync_file_is_not_reformatted(demo):
    # Same values, different layout: build must leave the bytes alone.
    path = demo.skill_md("sql-review")
    original = path.read_text()
    text = original.replace(
        "category: database\nowner: data-team\n", "owner: data-team\ncategory: database\n"
    )
    assert text != original
    path.write_text(text)
    demo.run("build")
    assert path.read_text() == text


def test_missing_routing_entry_is_reported_and_skill_left_alone(demo):
    path = demo.write_skill(
        "unrouted", "name: unrouted\ndescription: A skill that nobody has routed yet, on purpose.\n"
    )
    original = path.read_text()
    result = demo.run("build")
    assert result.code == 1
    assert "unrouted/SKILL.md: no entry in .claude/skills/routing.json" in result.out
    assert path.read_text() == original
    assert '"unrouted"' in (demo.skills / "index.json").read_text()


def test_orphan_routing_entry_is_reported(demo):
    routing = demo.skills / "routing.json"
    data = json.loads(routing.read_text())
    data["skills"]["ghost"] = {"category": "x"}
    routing.write_text(json.dumps(data))
    result = demo.run("check")
    assert result.code == 1
    assert "'ghost' has no skill folder" in result.out


def test_composed_description_over_limit_is_a_problem(demo):
    routing = demo.skills / "routing.json"
    data = json.loads(routing.read_text())
    data["skills"]["sql-review"]["avoid"] = "x" * 1100
    routing.write_text(json.dumps(data))
    result = demo.run("build")
    assert result.code == 1
    assert "composed description is" in result.out


def test_index_shape(demo):
    index = json.loads((demo.skills / "index.json").read_text())
    assert index["version"] == 1
    assert index["count"] == 5
    assert index["categories"] == sorted(index["categories"])
    first = index["skills"][0]
    assert set(first) == {"name", "description", "category", "owner", "path"}
    assert first["path"] == ".claude/skills/changelog-writer/SKILL.md"


def test_bad_routing_json_is_a_usage_error_and_writes_nothing(demo):
    (demo.skills / "routing.json").write_text("{")
    before = demo.snapshot()
    result = demo.run("build")
    assert result.code == 2
    assert "invalid JSON" in result.out
    assert demo.snapshot() == before
