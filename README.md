<p align="center">
  <h1 align="center">🧬 Self-Evolution Engine</h1>
  <p align="center">
    A lightweight framework that enables AI agents to learn from experience and continuously self-improve.
  </p>
  <p align="center">
    <a href="https://github.com/upsightx/self-evolution/blob/main/LICENSE"><img src="https://img.shields.io/github/license/upsightx/self-evolution" alt="License"></a>
    <img src="https://img.shields.io/badge/python-3.8%2B-blue" alt="Python 3.8+">
    <img src="https://img.shields.io/badge/dependencies-zero-green" alt="Zero Dependencies">
    <img src="https://img.shields.io/badge/storage-SQLite-lightgrey" alt="SQLite">
    <img src="https://img.shields.io/github/last-commit/upsightx/self-evolution" alt="Last Commit">
  </p>
</p>

---

## The Problem

Most AI agents start from scratch every session. They don't remember past mistakes, can't tell which model works best for which task, and never learn from failure.

Self-Evolution gives agents seven capabilities:

| # | Capability | What it does |
|---|-----------|-------------|
| 1 | **Structured Memory** | Persist experiences, decisions (with rejected alternatives), and lessons across restarts |
| 2 | **Failure Pattern Analysis** | Automatically detect recurring failures and generate actionable improvement proposals |
| 3 | **A/B Experiment Validation** | Turn proposals into rollback-safe experiments with real data-driven conclusions |
| 4 | **Causal Attribution** | Prevent false positives from single-run flukes — outputs `uncertain` when sample size is insufficient |
| 5 | **Adaptive Strategy** | Auto-switch evolution strategy (aggressive / conservative / repair) based on system health signals |
| 6 | **External Learning** | Proactively scan 8+ sources (arXiv, HN, GitHub Trending, etc.) with two-stage filtering |
| 7 | **Hot/Cold Memory Management** | Track access frequency, auto-suggest archival of cold data |

## Architecture

Three-layer design with clear separation of concerns:

```
┌──────────────────────────────────────────────────────┐
│  Evolution Layer                                      │
│  evolution_strategy · evolution_executor               │
│  Strategy selection · Signal detection · Experiments   │
│  Adaptive reflection frequency                         │
├──────────────────────────────────────────────────────┤
│  Analysis Layer                                       │
│  feedback_loop · causal_validator                      │
│  Failure pattern analysis · Improvement proposals      │
│  4-dimension weighted attribution                      │
├──────────────────────────────────────────────────────┤
│  Memory Layer                                         │
│  memory_db · memory_store · memory_retrieval           │
│  memory_service · memory_embedding · memory_lru        │
│  Structured storage · FTS5 search · Semantic retrieval │
│  Hot/cold management · File registry                   │
└──────────────────────────────────────────────────────┘
```

### Core Loop

```
feedback_loop detects failure pattern
        │
        ▼
evolution_executor generates candidate experiment
        │
        ▼
    Create experiment → Activate
        │
        ▼
    Task results recorded during execution
        │
        ▼
    causal_validator runs when sample size is met
        │
        ▼
    effective → persist    uncertain → continue    ineffective → rollback
```

`evolution_strategy` continuously monitors system signals and switches strategy accordingly.

## Project Structure

```
self-evolution/
├── modules/
│   ├── db_common.py            # SQLite connection manager (WAL mode)
│   ├── memory_db.py            # Core memory DB — FTS5 dual-path search (CJK + Latin)
│   ├── memory_store.py         # Write layer — tags, time, task-type filtering
│   ├── memory_retrieval.py     # Smart retrieval — query rewriting, time decay, dynamic thresholds
│   ├── memory_service.py       # Unified API: remember / recall / reflect
│   ├── memory_embedding.py     # Optional semantic search via SiliconFlow BGE-M3 (free, no GPU)
│   ├── memory_lru.py           # Access frequency tracking, archive suggestions
│   ├── file_registry.py        # File/document metadata ledger
│   ├── feedback_loop.py        # Task outcome recording, failure analysis, improvement proposals
│   ├── causal_validator.py     # Pure-function attribution — 4 dimensions, 3-tier verdict
│   ├── evolution_executor.py   # Experiment lifecycle: draft → active → concluded/cancelled
│   ├── evolution_strategy.py   # 5 strategy presets, 6 signal types, adaptive reflection
│   ├── agent_bridge.py         # One-call integration for sub-agent results
│   └── DESIGN.md               # Internal design spec & coding conventions
├── skills/
│   └── external-learning/      # Two-stage learning skill (broad scan → deep read)
│       ├── SKILL.md
│       └── references/         # Source-specific templates (arXiv, HN, GitHub, etc.)
├── DESIGN.md                   # High-level design document
├── LICENSE                     # MIT
└── README.md
```

**~4,350 lines of Python** across 14 modules. No external dependencies.

## Quick Start

### Installation

```bash
git clone https://github.com/upsightx/self-evolution.git
cd self-evolution
```

No `pip install` needed — pure stdlib Python.

### Initialize

```bash
python3 modules/memory_db.py init
```

### Record Task Outcomes

```bash
# Record a success
python3 modules/feedback_loop.py record coding gpt-4 1 --notes "Refactor succeeded"

# Record a failure
python3 modules/feedback_loop.py record coding gpt-4 0 --notes "Agent described plan but didn't execute"
```

### Analyze Failure Patterns

```bash
python3 modules/feedback_loop.py analyze
```

### Check System Signals & Strategy

```bash
python3 modules/evolution_strategy.py signals
python3 modules/evolution_strategy.py strategy
```

### Run an Experiment

```bash
# Create
python3 modules/evolution_executor.py create \
  --source feedback_loop --task-type coding \
  --problem "Sub-agent describes plan but doesn't execute" \
  --proposal "Add mandatory execution directive in first paragraph of prompt"

# Validate (when enough samples collected)
python3 modules/causal_validator.py validate 1
```

### Python Integration

```python
from agent_bridge import record_agent_result

# One call after each sub-agent completes
record_agent_result(
    task_type="coding",
    model="gpt-4",
    success=True,
    description="Refactored user module",
    critic_score=85,
)
```

### Configuration

```bash
# Custom database path (default: modules/ directory)
export SELF_EVOLUTION_DB=/path/to/your/memory.db

# Optional: enable semantic search (free SiliconFlow BGE-M3 API)
export SILICONFLOW_API_KEY=your_key_here
python3 modules/memory_db.py embed
```

## Evolution Strategies

The system auto-selects a strategy based on runtime signals:

| Strategy | Fix | Optimize | Innovate | Trigger |
|----------|-----|----------|----------|---------|
| `balanced` | 20% | 30% | 50% | System healthy |
| `innovate` | 5% | 15% | 80% | Stagnation or repair loop detected |
| `harden` | 40% | 40% | 20% | Recent major changes |
| `repair_only` | 80% | 20% | 0% | High failure rate |
| `steady_state` | 60% | 30% | 10% | Evolution saturated |

**Signal types:** `high_failure_rate` · `repair_loop` · `elevated_failure_rate` · `recent_big_change` · `capability_gap` · `stagnation` · `all_healthy`

## Causal Attribution

Experiment conclusions are data-driven, not gut-feel:

- **Sample threshold:** < 3 runs → `uncertain` (refuses to conclude)
- **4-dimension weighted score:**
  - Success rate (0.4) + Rework rate (0.25) + Critic score (0.25) + Duration (0.1)
- **Three-tier verdict:** `effective` / `uncertain` / `ineffective`
- **Design principle:** Saying "I don't know" beats false confidence

## External Learning

Two-stage pipeline scanning 8+ sources:

```
Broad Scan (parallel sub-agents)
    → Deep Read (main agent reads original sources)
        → Landing Assessment (auto-filter noise)
```

**Sources:** GitHub Trending · Hacker News · arXiv · TechCrunch · 量子位 · Product Hunt · Papers With Code · Industry Deep Dives

Each deep-read note includes: source confidence level (summary / original / multi-source verified), secondary validation, and landing assessment (related modules / change scope / priority). P0 items auto-enter the experiment queue.

## Database Schema

Single-file SQLite with WAL mode. Handles 100k+ records without performance issues.

| Table | Purpose |
|-------|---------|
| `observations` | Observations, discoveries, lessons learned |
| `decisions` | Decision records with rejected alternatives and rationale |
| `session_summaries` | Session summaries for continuity |
| `task_outcomes` | Task execution results (success/fail, model, scores) |
| `experiments` | Evolution experiments with full lifecycle tracking |
| `embeddings` | Vector index for semantic search (optional) |

## Design Principles

- **Zero dependencies** — Python 3.8+ and SQLite only. No LangChain, no LlamaIndex.
- **Full persistence** — All state in SQLite. Survives restarts, crashes, and redeployments.
- **Rollback-safe** — Every experiment can be cancelled or rolled back.
- **Honest uncertainty** — Insufficient samples → `uncertain`. Never over-claims.
- **Crash-resistant queries** — Read operations return empty on failure; writes return `None` with warnings.

## Use Cases

Self-Evolution is framework-agnostic. It works with any agent system that can call Python functions.

**Good fit:**
- Multi-agent orchestration systems that dispatch sub-agents
- Long-running agent deployments that accumulate operational data
- Any agent that would benefit from learning which prompts, models, or strategies work best

**Not designed for:**
- Single-turn chatbots (no operational history to learn from)
- Pure RAG pipelines (use vector DBs instead)
- Distributed multi-node shared memory (single SQLite file)

**Production-validated** on [OpenClaw](https://github.com/openclaw/openclaw) with 4,300+ lines of Python running daily workloads.

## FAQ

**Q: How does this differ from LangChain Memory / Mem0?**
They solve conversational context memory (what was said). Self-Evolution solves experiential learning (what worked, what failed, and why). They're complementary — use both if needed.

**Q: How do I enable semantic search?**
Optional feature using [SiliconFlow](https://siliconflow.cn) BGE-M3 embeddings (free tier, no GPU required). Set `SILICONFLOW_API_KEY` and run `python3 modules/memory_db.py embed`. Without it, the system falls back to FTS5 keyword search — still effective for most use cases.

**Q: Will it slow down at scale?**
SQLite + FTS5 + WAL handles 100k+ records comfortably. `memory_lru` automatically identifies cold data and suggests archival to keep the working set lean.

**Q: Can I use a different embedding provider?**
`memory_embedding.py` is a thin wrapper (~200 lines). Swap the API call to any provider that returns float vectors. The rest of the system doesn't care.

## Roadmap

- [ ] `tests/` — Comprehensive test suite with CI
- [ ] `pyproject.toml` — Proper packaging for `pip install`
- [ ] Dashboard — Terminal UI for experiment monitoring
- [ ] Multi-DB support — PostgreSQL adapter for team deployments
- [ ] Plugin system — Custom signal detectors and strategy presets

## Contributing

Contributions are welcome. Please read [`DESIGN.md`](DESIGN.md) for coding conventions before submitting PRs.

```bash
# Run tests before submitting
python3 tests/run_all.py

# Code style: follow existing patterns in modules/
# - Type hints on all function signatures
# - Docstrings with "What it does / What it doesn't do"
# - CLI subcommand pattern for new modules
```

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| v1–v5 | 2026-03-17 | Memory system + feedback loop + LRU + Critic review |
| v6 | 2026-03-20 | Retrieval layer rewrite (query rewriting + time decay + dynamic thresholds) |
| v7 | 2026-03-28 | Evolution executor + causal validator + strategy engine |
| v7.1 | 2026-03-28 | Agent bridge + time-aware retrieval |
| v7.2 | 2026-03-28 | External learning module + landing assessment pipeline |

## Acknowledgments

Design ideas inspired by (concept reference only, no code copied):

- [Capability-Evolver](https://github.com/EvoMap/evolver) (MIT) — Strategy presets, signal detection, adaptive reflection
- [FreeTodo](https://github.com/FreeU-group/FreeTodo) (FreeU Community License) — Structured task context management

## License

[MIT](LICENSE) © 2026 UpsightX
