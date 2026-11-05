# upstream/

A pristine copy of the vendored `markdown-tables` skill, as it would arrive
from its upstream collection, so you can try a re-vendor:

```bash
cp upstream/markdown-tables/SKILL.md .claude/skills/markdown-tables/SKILL.md
skillgate check   # exit 1: the local routing clause is gone
skillgate build   # routing restored from routing.json
skillgate check   # exit 0
```
