---
name: sql-review
description: >-
  Review SQL migrations before they run: table locks, missing indexes on new
  foreign keys, unsafe column type changes and irreversible steps. Use on any
  new or changed migration file. Don't use for formatting query results as
  tables; that is markdown-tables.
category: database
owner: data-team
---

# SQL review

Check each statement for lock level and duration, then for reversibility.
Flag anything that rewrites a large table inside a transaction.
