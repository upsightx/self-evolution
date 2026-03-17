---
name: self-evolution
description: |
  Structured memory database for AI agents. Remember WHY, not just WHAT.
  Decisions with rejected alternatives. Observations with classification.
  Dual-path search for CJK/English. Zero dependencies.

  **Use when**: recording decisions, lessons, discoveries; searching past experience; session-end memory extraction.
---

# Self-Evolution: Structured Memory

One tool: `memory_db.py`. SQLite + FTS5. Zero dependencies.

## What it does

Records three things:
1. **Observations** — what happened (typed: discovery/bugfix/feature/refactor/decision/change)
2. **Decisions** — what you chose, what you rejected, and why
3. **Session summaries** — what was done, what was learned

Searches with dual-path (FTS5 + LIKE) so both English and Chinese work.

## Usage

```bash
cd /root/.openclaw/workspace/memory/structured

# Search
python3 memory_db.py search "部署"
python3 memory_db.py decisions "SQLite"

# Write
python3 memory_db.py add discovery "标题" "描述"
python3 memory_db.py decision "标题" "决策" "拒绝方案" "原因"

# Stats
python3 memory_db.py stats
```

Python:
```python
from memory_db import *
add_observation('bugfix', '标题', narrative='描述', facts=['事实'], concepts=['标签'])
add_decision('标题', '决策', rejected_alternatives=['方案B'], rationale='原因')
results = search('关键词')
```

## When to record

**Record decisions** when you choose between alternatives — especially when the choice isn't obvious.

**Record observations** when:
- Something fails unexpectedly (bugfix)
- You discover a non-obvious fact (discovery)
- You build something worth remembering (feature)

**Record session summaries** at the end of important sessions.

Don't record routine operations. If it's not worth searching for later, don't write it.

## Relationship with existing memory

- `MEMORY.md` — curated long-term memory (human-readable overview)
- `memory/*.md` — daily logs (raw)
- `memory/structured/memory.db` — searchable structured records (this tool)
- `memory_search` — semantic search across .md files

Use this tool for precise retrieval ("why did we choose X?"). Use memory_search for fuzzy recall ("something about deployment last week").
