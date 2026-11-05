import subprocess
import sys

import pytest

from skillgate import __version__
from skillgate.cli import main


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_command_is_required(capsys):
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2


def test_config_error_exits_2(empty):
    (empty.root / "skillgate.toml").write_text("bogus = 1\n")
    result = empty.run("lint")
    assert result.code == 2
    assert "unknown setting(s): bogus" in result.out


def test_explicit_config_flag(demo, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert demo.run("--config", str(demo.root / "skillgate.toml"), "check").code == 0


def test_missing_skills_dir(empty):
    (empty.root / "skillgate.toml").write_text('skills_dir = "nowhere"\nrequire_routing = false\n')
    assert empty.run("lint").code == 1
    assert empty.run("check").code == 1


def test_python_dash_m_entry_point(demo):
    proc = subprocess.run(
        [sys.executable, "-m", "skillgate", "check"],
        cwd=demo.root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
