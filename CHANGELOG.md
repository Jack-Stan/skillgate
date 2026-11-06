# Changelog

## [0.3.0] - 2026-11-06

### Added

- `skillgate eval [--dry-run] [--json] [--model M] [--cases FILE]`: routing
  evals. Claude routes each case in `evals.json` to one skill (or none),
  using the descriptions as `skillgate build` leaves them. Misses and
  skill-to-skill collisions are reported, and the command exits 1 below
  `eval_min_accuracy`. Opt-in: `pip install "skillgate[eval]"` plus an
  Anthropic credential.
- Settings `evals`, `eval_model`, `eval_effort`, `eval_min_accuracy`.
- Lint rule SG012: `evals.json`, when present, is validated without calling
  the API (JSON, keys, empty or duplicate prompts, expected skills exist).

### Documentation

- README: migration notes for projects replacing their own index script
  (`index.json` shape, `path` field, keys that are not copied, lock file).

## [0.2.0] - 2026-11-05

### Added

- `skillgate init [--dry-run]`: creates `routing.json` from the skills on
  disk, seeded from their current category and owner, or adds entries for
  new skills to an existing file without changing the others.
- Lint rule SG011: a list-form `avoid` item ending in `(skill-name)` must
  name an existing skill other than the skill itself.

### Changed

- CI uses `actions/checkout@v5` and `actions/setup-python@v6` (Node 24).

## [0.1.0] - 2026-11-05

### Added

- `skillgate lint`: frontmatter and routing checks SG001 to SG010.
- `skillgate build`: applies the `routing.json` overlay (category, owner,
  `avoid` clause) into each `SKILL.md`, then regenerates `index.json`,
  `SKILLS.md` and the lock file. Re-runs are idempotent, and the build
  self-heals if the lock is lost.
- `skillgate check [--diff]`: reports drift without writing anything; exits 1
  on drift.
- Configuration through `skillgate.toml` or `[tool.skillgate]`.
- Example project in `examples/demo`, with a vendored skill.
- pre-commit hook definitions.

[0.3.0]: https://github.com/Jack-Stan/skillgate/releases/tag/v0.3.0
[0.2.0]: https://github.com/Jack-Stan/skillgate/releases/tag/v0.2.0
[0.1.0]: https://github.com/Jack-Stan/skillgate/releases/tag/v0.1.0
