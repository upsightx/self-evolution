# 🧬 Self-Evolution Engine for AI Agents

A lightweight self-evolution system that helps AI agents learn from experience and continuously improve. Stripped down to what actually gets used.

## Modules

| Module | Purpose |
|--------|---------|
| `memory_db` | Structured memory (observations/decisions/summaries) with FTS5 dual-path search |
| `feedback_loop` | Task outcome recording, failure pattern analysis, improvement suggestions |
| `memory_lru` | Hot/cold memory tracking, archive suggestions |
| `model_router` | Multi-model routing based on task_type × success_rate × cost |
| `db_common` | Shared SQLite connection (WAL mode) |

## Architecture

```
┌──────────────┬───────────────┐
│   Memory     │   Strategy    │
├──────────────┼───────────────┤
│ memory_db    │ model_router  │
│ memory_lru   │ feedback_loop │
└──────┬───────┴───────┬───────┘
       │               │
       └───────┬───────┘
               │
        ┌──────┴──────┐
        │  memory.db  │
        │(SQLite+FTS5)│
        └─────────────┘
```

## Quick Start

```bash
cd modules

# Initialize database
python3 memory_db.py init

# Search memories
python3 memory_db.py search "model selection"

# Analyze failure patterns
python3 feedback_loop.py analyze

# Check model routing recommendations
python3 model_router.py table

# View memory hot/cold heatmap
python3 memory_lru.py heatmap
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `SELF_EVOLUTION_DB` | No | Override default DB path (default: `./memory.db`) |

## Design Principles

- **Zero external dependencies** — Python 3.8+ and SQLite only
- **Dual-path search** — FTS5 for English + LIKE fallback for CJK
- **Decisions record rejected alternatives** — Remember WHY, not just WHAT
- **Queries never crash** — Return empty on failure; writes can raise
- **Keep what's used, delete what's not** — Started with 18 modules, kept 5

## License

MIT
