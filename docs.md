# Self-Evolution Engine

A zero-dependency framework for AI agent self-evolution.

## What's Included

```
self-evolution/
├── README.md              # Full documentation
├── memory_db.py           # Structured memory database (SQLite + FTS5)
├── SKILL.md               # OpenClaw Skill definition
├── LICENSE                # MIT License
├── .gitignore
├── templates/
│   ├── code-dev.md        # Code development sub-agent template
│   ├── info-search.md     # Information search template
│   ├── compress.md        # Memory compression template
│   └── critic.md          # SAGE Critic review template
└── examples/
    └── session_end.py     # Session-end auto-extraction example
```

## Quick Start

```bash
python3 memory_db.py init
python3 memory_db.py add discovery "First memory" "The system is alive"
python3 memory_db.py search "memory"
```

## Design Inspirations

- [claude-mem](https://github.com/thedotmack/claude-mem) — Structured memory + progressive disclosure
- [SAGE](https://arxiv.org/abs/2603.15255) — Multi-agent self-evolution loop
- [Lore](https://arxiv.org/abs/2603.15566) — Decision recording protocol
