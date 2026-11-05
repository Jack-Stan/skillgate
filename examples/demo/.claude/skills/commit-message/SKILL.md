---
name: commit-message
description: >-
  Draft a Conventional Commits message from the staged diff: type, optional
  scope, imperative summary under 72 characters, and a body that explains why.
  Use when the user asks for a commit message. Don't use for summarising a
  whole release (changelog-writer).
category: git
owner: platform
---

# Commit message

Read `git diff --cached`. Pick the type from the dominant change, keep the
summary imperative, and explain the reason in the body, not the mechanics.
