# 🧬 Self-Evolution Engine for AI Agents

A structured self-evolution system that helps AI agents learn from experience, make better decisions, and continuously improve.

## What It Does

**Memory Layer** — Remember WHY, not just WHAT
- `memory_db` — Structured memory (observations/decisions/summaries) with FTS5 dual-path search
- `memory_embedding` — Semantic vector search (BGE-M3, 1024-dim)
- `memory_context` — Hybrid search context builder (keyword/semantic/hybrid)
- `memory_lru` — Hot/cold memory tracking with auto-access recording

**Strategy Layer** — Learn from patterns
- `model_router` — Multi-model routing (task_type × success_rate × cost → recommendation)
- `feedback_loop` — Task feedback analysis + failure pattern detection + template evolution
- `decision_review` — Decision tracking with rejected alternatives + periodic review + regret rate
- `skill_discovery` — Capability gap scanning from failures → skill recommendations

**Execution Layer** — Close the loop
- `orchestrator` — Heartbeat-based scheduler + unified status dashboard
- `agent_dispatch` — Pre-dispatch decision reference + post-completion recording (the glue)
- `record_agent_stat` — Agent success tracking with file locking + dual-write
- `auto_memory` — Auto-extract memories from conversations (rule-based Chinese NLP)

**Auxiliary**
- `data_accumulator` — Multi-source data merging (logs + stats + DB dedup)
- `todo_extractor` — Todo extraction (rules + LLM fallback)
- `template_manager` — YAML template management for sub-agent instructions
- `prompt_loader` — YAML prompt loader

## Architecture

```
┌─────────────────────────────────────────────────┐
│                 agent_dispatch                    │
│           (prepare → complete loop)               │
├────────────┬──────────────┬──────────────────────┤
│  Memory    │   Strategy   │     Execution         │
├────────────┼──────────────┼──────────────────────┤
│ memory_db  │ model_router │ orchestrator          │
│ embedding  │ feedback_loop│ record_agent_stat     │
│ context    │ decision_rev │ auto_memory           │
│ lru        │ skill_disc   │ data_accumulator      │
└────────────┴──────────────┴──────────────────────┘
         │           │              │
         └───────────┴──────────────┘
                     │
              ┌──────┴──────┐
              │  memory.db  │
              │ (SQLite+FTS5)│
              └─────────────┘
```

## Data Flow

```
Task arrives
    │
    ▼
agent_dispatch.prepare()
    ├── model_router.recommend() → best model
    ├── feedback_loop.improvements() → lessons from past failures
    └── memory_context.search() → relevant history
    │
    ▼
Sub-agent executes task
    │
    ▼
agent_dispatch.complete()
    ├── record_agent_stat → agent-stats.json + memory.db
    ├── feedback_loop.record → task_outcomes table
    ├── memory_db.add_observation → lesson (if failed)
    └── memory_lru.record_access → update hot/cold tracking
    │
    ▼
Heartbeat (periodic)
    ├── feedback_loop.analyze → detect failure patterns
    ├── model_router.table → update routing recommendations
    ├── memory_lru.suggest_archive → identify cold memories
    ├── skill_discovery.report → scan capability gaps
    └── decision_review → review past decisions
```

## Quick Start

```bash
# Initialize database
cd modules
python3 memory_db.py init

# Check system status
python3 orchestrator.py status

# Get dispatch recommendation before spawning a sub-agent
python3 agent_dispatch.py recommend "Write a Python web scraper"

# Record task completion
python3 agent_dispatch.py complete --task-type coding --model opus --success --label "scraper task"

# Run heartbeat (periodic maintenance)
python3 orchestrator.py heartbeat

# Search memories
python3 memory_db.py search "model selection"

# Run all tests
python3 tests/run_all.py
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `SILICONFLOW_API_KEY` | For semantic search | BGE-M3 embedding API |
| `SELF_EVOLUTION_DB` | No | Override default DB path |

## Design Principles

See [DESIGN.md](DESIGN.md) for the full specification. Key points:

- **Zero external dependencies** — Python 3.8+ and SQLite only (except PyYAML for templates)
- **Dual-path search** — FTS5 for English tokens + LIKE fallback for CJK content
- **Decisions record rejected alternatives** — Remember WHY you chose X over Y
- **Queries never crash** — Return empty on failure; writes can raise
- **Tests are separate** — All in `tests/`, none inline in production code

## Stats

- 18 production modules
- 15 test files
- ~4500 lines of code
- 15/15 tests passing

## License

MIT
