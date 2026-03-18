# 🧬 Self-Evolution Engine for AI Agents

Structured memory, intelligent scheduling, quality control, and self-audit tools for AI agents.

## Core: memory_db.py

SQLite + FTS5 structured memory database. Zero dependencies. Remember **WHY**, not just WHAT.

```bash
# Search (dual-path: FTS5 + LIKE, works for both English and Chinese)
python3 memory_db.py search "deployment"
python3 memory_db.py decisions "model selection"

# Write
python3 memory_db.py add discovery "Title" "Description"
python3 memory_db.py decision "Title" "Decision" "Rejected alternative" "Rationale"

# Stats
python3 memory_db.py stats
```

Three tables:
- **observations** — what happened (typed: discovery/bugfix/feature/refactor/decision/change)
- **decisions** — what you chose, what you rejected, and why
- **session_summaries** — what was done, what was learned

## Tools

| File | Purpose |
|------|---------|
| `memory_db.py` | Core structured memory database |
| `import_legacy.py` | Import existing markdown memory files into the database |
| `record_agent_stat.py` | Track sub-agent success rates by model and task type |
| `self-evolution-checklist.md` | Self-evolution audit checklist |

## Agent Templates

`agent-templates/` contains reusable instruction templates for sub-agents:
- SAGE 4-role mechanism (Solver/Critic/Planner/Challenger)
- Critic review template with 3-dimension scoring
- 6 task type templates (coding, research, skill creation, etc.)
- Decision recording format (with rejected_alternatives)

## Skills

`skills/` contains OpenClaw-compatible agent skills:

- **external-learning** — Automated external learning system. Dispatches parallel sub-agents to collect info from GitHub Trending, Hacker News, arXiv, financing news, Product Hunt. Keyword-based filtering, value scoring, dedup.
- **deploy-helper** — Safe deployment SOP. Docker-first testing, common pitfall cheat sheet, production migration checklist.

## Design Principles

1. **Remember WHY** — Every decision records rejected alternatives and rationale
2. **Keyword-based filtering** — No vague metrics like "relevance > 0.7", use concrete keyword matching
3. **Dual-path search** — FTS5 for English tokens + LIKE fallback for CJK content
4. **Model selection by complexity** — Complex tasks (refactor/audit) → strong model; simple tasks (info gathering) → cheap model
5. **One agent, one job** — Never let two agents modify the same file

## License

MIT
