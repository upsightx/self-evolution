# 🧬 Self-Evolution

Structured memory database for AI agents. Remember WHY, not just WHAT.

## The Problem

AI agents forget everything between sessions. When they do keep logs, it's flat text — you can't search "why did we reject option B?" or "what deployment bugs have we hit before?"

## The Solution

One Python file. SQLite + FTS5. Zero dependencies.

```bash
python3 memory_db.py init
```

### Record decisions (the real value)

```bash
python3 memory_db.py decision \
  "Chose SQLite over PostgreSQL" \
  "Use SQLite + FTS5" \
  "PostgreSQL (too heavy)" \
  "Zero dependencies, system built-in"
```

This records not just what you chose, but what you rejected and why. So future-you doesn't waste time re-evaluating the same options.

### Record observations

```bash
# A bug you hit
python3 memory_db.py add bugfix "torch CUDA too heavy" "2GB+ dependency broke deployment"

# Something you discovered
python3 memory_db.py add discovery "MiniMax more stable than GLM5" "GLM5 returns 403 ~5% of the time"
```

Types: `decision`, `bugfix`, `feature`, `refactor`, `discovery`, `change`

### Search

```bash
# Search observations (works with English, Chinese, and mixed content)
python3 memory_db.py search "deployment"
python3 memory_db.py search "部署"

# Search decisions
python3 memory_db.py decisions "SQLite"

# Full details
python3 memory_db.py get 1

# Stats
python3 memory_db.py stats
```

### Python API

```python
from memory_db import *

init_db()

add_decision("Title", "What was decided",
    rejected_alternatives=["Option B", "Option C"],
    rationale="Why this option won")

add_observation("bugfix", "Title", 
    narrative="What happened",
    facts=["Concrete fact"],
    concepts=["tag1", "tag2"])

add_session_summary("What was requested",
    learned="What was learned",
    completed="What was done")

results = search("keyword")
decisions = search_decisions("keyword")
```

### Import from JSON

```bash
python3 memory_db.py import extracted.json
```

Format:
```json
{
  "observations": [{"type": "discovery", "title": "...", "narrative": "..."}],
  "decisions": [{"title": "...", "decision": "...", "rejected_alternatives": ["..."], "rationale": "..."}],
  "summary": "One-line summary"
}
```

## How search works

FTS5 can't tokenize Chinese or mixed CJK-English text. So we use dual-path search:

1. **FTS5** — handles English words separated by spaces/punctuation
2. **LIKE** — catches Chinese, mixed content, partial matches

Results are merged and deduped. You don't need to think about it.

## Design principles

- **Zero dependencies** — Python 3.8+ and SQLite (system built-in)
- **Record "why"** — decisions with rejected alternatives matter more than raw logs
- **Don't over-record** — if it's not worth searching for later, don't write it
- **Search must work** — dual-path ensures CJK and English both work

## As an OpenClaw Skill

```bash
cp -r self-evolution ~/.openclaw/skills/
python3 memory_db.py init
```

See `SKILL.md` for integration details.

## Inspired by

- [claude-mem](https://github.com/thedotmack/claude-mem) — structured memory design
- [Lore](https://arxiv.org/abs/2603.15566) — decision recording with rejected alternatives

## License

MIT
