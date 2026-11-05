# skillgate

[![CI](https://github.com/Jack-Stan/skillgate/actions/workflows/ci.yml/badge.svg)](https://github.com/Jack-Stan/skillgate/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Keep a Claude Code `.claude/skills/` folder honest: **lint** the frontmatter,
**build** a routing overlay and an index into it, and **check** for drift in CI.

## Why

Claude Code picks a skill by matching your request against every skill's
`description`. With five skills that works. Somewhere around twenty, the
descriptions start to overlap: "update the changelog" and "write the release
notes" both look like a match, and the router guesses.

The fix is negative routing: each description also says what it is *not* for,
and which sibling to use instead. That raises three maintenance problems:

1. **Vendored skills.** You can't hand-edit a skill you copied from upstream;
   the next re-vendor wipes your clause.
2. **Drift.** Hand-written registries and indexes go stale the day after you
   write them.
3. **Idempotency.** A script that appends a clause has to know, on every run,
   whether the clause is already there.

skillgate keeps all routing in one overlay file, `routing.json`, applies it to
every `SKILL.md`, regenerates `index.json` and `SKILLS.md`, and fails CI when
anything is out of sync.

## 30-second quickstart

```bash
git clone https://github.com/Jack-Stan/skillgate
cd skillgate
python -m pip install -e .
cd examples/demo
skillgate check                     # in sync (5 skills)
```

Simulate a re-vendor that wipes the local routing:

```bash
cp upstream/markdown-tables/SKILL.md .claude/skills/markdown-tables/SKILL.md
skillgate check --diff              # exit 1, shows the missing clause
skillgate build                     # clause, category and owner restored
skillgate check                     # exit 0
```

## In your own project

```bash
python -m pip install git+https://github.com/Jack-Stan/skillgate@v0.2.0
skillgate init                      # routing.json with an entry per existing skill
```

`init` seeds each entry from the skill's current `category` and `owner`, so
the first build leaves every `SKILL.md` untouched. Fill in the `avoid` lists,
then:

```bash
skillgate lint
skillgate build
```

Run `init` again whenever you add skills: it appends entries for new
skills and never changes existing ones.

Commit the result, including `index.json`, `SKILLS.md` and
`.skillgate-lock.json`. From then on, run `skillgate check` in CI.

### Migrating from your own index script

If a home-grown script already writes `index.json`, check what reads it
before you switch. skillgate's index has a fixed shape:

```json
{
  "version": 1,
  "count": 5,
  "categories": ["database", "docs"],
  "skills": [
    {"name": "...", "description": "...", "category": "...", "owner": "...",
     "path": ".claude/skills/<name>/SKILL.md"}
  ]
}
```

- The SKILL.md location is `path`, relative to the project root. Scripts
  often call it `entrypoint`.
- Only `name`, `description`, `category`, `owner` and `path` are emitted.
  Extra frontmatter keys such as `auto-activate` or `triggers` stay in each
  SKILL.md but are not copied into the index.
- Skills are sorted by name, not grouped by category.
- The lock file is `.skillgate-lock.json` and has its own format. An older
  script's lock can be deleted; the first `skillgate build` rebuilds the
  lock from the skill files without changing them.

## Commands

| Command | What it does | Exit code |
|---|---|---|
| `skillgate init [--dry-run]` | Creates `routing.json`, or adds an entry for each skill that has none. Existing entries are never changed. | 0 |
| `skillgate lint` | Validates frontmatter and routing entries (rules below). Read-only. | 1 on any finding |
| `skillgate build` | Applies `routing.json` into each `SKILL.md`; rewrites `index.json`, `SKILLS.md` and the lock. | 1 if a problem was found (for example a skill with no routing entry) |
| `skillgate check [--diff]` | Plans a build and writes nothing. | 1 if a build would change any file |

Every command exits 2 on a configuration error, an unreadable
`routing.json`, or bad usage.

`check` passes if and only if `build` would write nothing. The test suite
asserts that property.

## The routing overlay

```json
{
  "skills": {
    "changelog-writer": {
      "category": "release",
      "owner": "docs-team",
      "avoid": [
        "user-facing announcements of a release (release-notes)",
        "writing a single commit message (commit-message)"
      ]
    },
    "sql-review": {
      "category": "database",
      "avoid": "Don't use for formatting query results as tables; that is markdown-tables."
    }
  }
}
```

- `category`, `owner`: written into the frontmatter. Leave a key out and
  skillgate doesn't touch it.
- `avoid` takes a list or a string. A list becomes one generated sentence,
  `Don't use for A or B.`; a string is used verbatim. The clause is appended
  to the skill's own description. End a list item with `(skill-name)` to
  name the sibling to use instead; lint checks that the sibling exists
  (SG011). String clauses are free text and aren't checked.
- Unknown keys are an error, so a typo such as `categroy` can't slip through.
  Keys that start with `_` are ignored and can hold comments.

`changelog-writer` above ends up with:

```yaml
---
name: changelog-writer
description: >-
  Update CHANGELOG.md from the commits merged since the last tag, grouped into
  Added, Changed, Fixed and Removed. Use when preparing a release or when
  asked to bring the changelog up to date. Don't use for user-facing
  announcements of a release (release-notes) or writing a single commit
  message (commit-message).
category: release
owner: docs-team
---
```

### How re-runs stay idempotent

`.skillgate-lock.json` records each skill's base description (its own words)
and the clause that was applied. On the next build:

- **Description unchanged since the last build:** recognised exactly, and the
  stored base is reused.
- **Description changed** (a re-vendor or an upstream edit): the new text is
  taken as the base, and any known clause is stripped from its end first.
- **Lock deleted or corrupt:** the clause is stripped from the end of the
  description, and the rebuilt lock comes out byte-identical. The tests cover
  this case.

A file whose frontmatter already has the right values is never rewritten, even
if its layout differs. When a rewrite does happen, the managed keys come first,
the remaining keys keep their order, and the body is preserved byte-for-byte.
YAML comments inside a rewritten frontmatter block are not kept.

## Configuration

skillgate reads `skillgate.toml`, or `[tool.skillgate]` in `pyproject.toml`,
from the nearest directory at or above the working directory. `--config PATH`
overrides the search. Every key is optional. Paths are relative to the config
file.

```toml
[tool.skillgate]
skills_dir = ".claude/skills"
routing = ".claude/skills/routing.json"       # default: <skills_dir>/routing.json
lock = ".claude/skills/.skillgate-lock.json"  # default: <skills_dir>/.skillgate-lock.json
index = ".claude/skills/index.json"           # default: <skills_dir>/index.json
registry = ".claude/skills/SKILLS.md"         # default: <skills_dir>/SKILLS.md
required_fields = ["name", "description"]
description_min_length = 40
description_max_length = 1024
require_routing = true      # false: skills without an entry are fine, and routing.json is optional
```

## Lint rules

| Code | Rule |
|---|---|
| SG001 | skill folder has no `SKILL.md` |
| SG002 | frontmatter is missing, unclosed, not valid YAML, or not a mapping |
| SG003 | a `required_fields` entry is missing or empty |
| SG004 | `name` does not match the folder name |
| SG005 | folder name is not lowercase letters, digits and single hyphens, at most 64 characters |
| SG006 | description is shorter than `description_min_length` |
| SG007 | description is longer than `description_max_length` |
| SG008 | skill has no entry in `routing.json` |
| SG009 | `routing.json` entry has no skill folder |
| SG010 | `routing.json` is missing or invalid |
| SG011 | a list-form `avoid` item ends in `(skill-name)` naming a skill that doesn't exist, or the skill itself |

Every rule runs to completion, so one run reports every problem.

## CI and pre-commit

GitHub Actions:

```yaml
- run: python -m pip install git+https://github.com/Jack-Stan/skillgate@v0.2.0
- run: skillgate lint
- run: skillgate check --diff
```

pre-commit:

```yaml
repos:
  - repo: https://github.com/Jack-Stan/skillgate
    rev: v0.2.0
    hooks:
      - id: skillgate-lint
      - id: skillgate-check
```

## Development

```bash
python -m pip install -e ".[dev]"
pytest
ruff check .
ruff format --check .
```

## Releasing

1. Open a PR that bumps `version` in `pyproject.toml` and
   `src/skillgate/__init__.py` and dates the `CHANGELOG.md` section. Merge it.
2. Go to **Actions → Release → Run workflow** and enter the tag (for example
   `v0.3.0`) and the full SHA of the merge commit.

The workflow checks that the commit is on `main`, that `pyproject.toml`
there has the matching version, and that the tag doesn't exist yet. It then
creates the tag and a GitHub Release, using that version's changelog section
as the notes.

## Roadmap

- **v0.3:** routing evals. Run sample prompts against the real skill set and
  report which skill was chosen, so collisions show up as failing cases rather
  than as hunches. This needs an API key, so it will be opt-in.

skillgate doesn't rewrite your descriptions for you, and that isn't planned.

## License

MIT. See [LICENSE](LICENSE).
