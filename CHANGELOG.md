# Changelog

## [0.1.0] - unreleased

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
