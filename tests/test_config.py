from pathlib import Path

import pytest

from skillgate.config import ConfigError, load_config


def test_defaults_without_any_config(tmp_path):
    config = load_config(tmp_path)
    assert config.source is None
    assert config.skills_dir == tmp_path / ".claude/skills"
    assert config.routing == tmp_path / ".claude/skills/routing.json"
    assert config.lock == tmp_path / ".claude/skills/.skillgate-lock.json"
    assert config.required_fields == ("name", "description")


def test_outputs_follow_a_custom_skills_dir(tmp_path):
    (tmp_path / "skillgate.toml").write_text('skills_dir = "agent/skills"\n')
    config = load_config(tmp_path)
    assert config.index == tmp_path / "agent/skills/index.json"


def test_pyproject_table_is_found_from_a_subdirectory(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\n\n[tool.skillgate]\nindex = "docs/skills.json"\n'
    )
    sub = tmp_path / "a" / "b"
    sub.mkdir(parents=True)
    config = load_config(sub)
    assert config.root == tmp_path
    assert config.index == tmp_path / "docs/skills.json"


def test_pyproject_without_table_is_skipped(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "outer"\n')
    inner = tmp_path / "inner"
    inner.mkdir()
    (inner / "pyproject.toml").write_text('[project]\nname = "inner"\n')
    assert load_config(inner).source is None


def test_skillgate_toml_wins_over_pyproject(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[tool.skillgate]\nskills_dir = "a"\n')
    (tmp_path / "skillgate.toml").write_text('skills_dir = "b"\n')
    assert load_config(tmp_path).skills_dir == tmp_path / "b"


def test_explicit_config_paths_are_relative_to_the_file(tmp_path):
    conf = tmp_path / "conf"
    conf.mkdir()
    (conf / "custom.toml").write_text('skills_dir = "../skills"\n')
    config = load_config(tmp_path, Path("conf/custom.toml"))
    assert config.skills_dir.resolve() == (tmp_path / "skills").resolve()


@pytest.mark.parametrize(
    ("toml", "message"),
    [
        ('skils_dir = "x"\n', "unknown setting"),
        ("skills_dir = 3\n", "non-empty string"),
        ('required_fields = "name"\n', "list of strings"),
        ("description_max_length = -1\n", "non-negative"),
        ("description_min_length = 10\ndescription_max_length = 5\n", "larger than"),
        ('require_routing = "yes"\n', "true or false"),
        ("not = = toml\n", "invalid TOML"),
    ],
)
def test_invalid_settings(tmp_path, toml, message):
    (tmp_path / "skillgate.toml").write_text(toml)
    with pytest.raises(ConfigError, match=message):
        load_config(tmp_path)


def test_explicit_config_must_exist(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path, Path("missing.toml"))


def test_explicit_pyproject_needs_the_table(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n')
    with pytest.raises(ConfigError, match=r"no \[tool.skillgate\]"):
        load_config(tmp_path, Path("pyproject.toml"))
