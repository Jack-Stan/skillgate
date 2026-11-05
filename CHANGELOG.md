# Changelog

## [Unreleased]

### Added

- `skillgate init [--dry-run]`: creates `routing.json` from the skills on
  disk, seeded from their current category and owner, or adds entries for
  new skills to an existing file without changing the others.
- Lint rule SG011: a list-form `avoid` item ending in `(skill-name)` must
  name an existing skill other than the skill itself.

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

[0.1.0]: https://github.com/Jack-Stan/skillgate/releases/tag/v0.1.0
