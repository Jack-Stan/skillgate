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

# Changelog writer

1. Find the last tag with `git describe --tags --abbrev=0`.
2. List merged commits since then and drop merge noise and chores.
3. Group the rest under Keep a Changelog headings and add them under
   `## [Unreleased]`.
