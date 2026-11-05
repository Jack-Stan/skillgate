from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

import pytest

from skillgate.cli import main
from skillgate.config import Config, load_config

DEMO = Path(__file__).resolve().parent.parent / "examples" / "demo"


@dataclass
class Result:
    code: int
    out: str


@dataclass
class Project:
    root: Path
    capsys: pytest.CaptureFixture[str]

    @property
    def skills(self) -> Path:
        return self.root / ".claude" / "skills"

    @property
    def config(self) -> Config:
        return load_config(self.root)

    def skill_md(self, name: str) -> Path:
        return self.skills / name / "SKILL.md"

    def write_skill(self, name: str, frontmatter: str, body: str = "# Body\n") -> Path:
        path = self.skill_md(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"---\n{frontmatter}---\n\n{body}", encoding="utf-8")
        return path

    def run(self, *args: str) -> Result:
        self.capsys.readouterr()
        code = main(list(args))
        captured = self.capsys.readouterr()
        return Result(code, captured.out + captured.err)

    def snapshot(self) -> dict[str, bytes]:
        return {
            p.relative_to(self.root).as_posix(): p.read_bytes()
            for p in sorted(self.root.rglob("*"))
            if p.is_file()
        }


@pytest.fixture
def demo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> Project:
    """A private copy of examples/demo, already built, as the working directory."""
    root = tmp_path / "demo"
    shutil.copytree(DEMO, root)
    monkeypatch.chdir(root)
    return Project(root, capsys)


@pytest.fixture
def empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> Project:
    """An empty project with default config and an empty routing.json."""
    root = tmp_path / "proj"
    (root / ".claude" / "skills").mkdir(parents=True)
    (root / ".claude" / "skills" / "routing.json").write_text('{"skills": {}}\n')
    monkeypatch.chdir(root)
    return Project(root, capsys)
