---
name: self-evolution
description: |
  Self-Evolution Engine for AI Agents. Manages structured memory, intelligent scheduling,
  quality control (SAGE Critic), self-audit, and task extraction.

  **Use this Skill when**:
  (1) Heartbeat triggers — decide what to check and execute
  (2) Need to compress/organize/search memory
  (3) Weekly self-audit
  (4) Extract tasks from conversations
  (5) Complex tasks need Critic review
  (6) Session ends — record structured memory
---

# Self Evolution Engine

One skill to manage all self-maintenance and evolution capabilities.

---

## 1. Structured Memory System

### Database
`memory/structured/memory_db.py` — SQLite + FTS5, zero dependencies.

### Three Core Tables

| Table | Purpose | Key Fields |
|-------|---------|-----------|
| observations | Discoveries, lessons, changes | type, title, narrative, facts, concepts |
| decisions | Key decisions (Lore format) | decision, rejected_alternatives, rationale |
| session_summaries | Session summaries | request, learned, completed, next_steps |

### Progressive Disclosure Retrieval

```bash
# L1 Index (~50 tokens/result): id + title + type + date
python3 memory_db.py search "keyword"

# L2 Context (~200 tokens/result): + narrative + facts
python3 memory_db.py l2 1 2 3

# L3 Full (~500 tokens/result): all fields
python3 memory_db.py l3 1

# Search decisions
python3 memory_db.py decisions "keyword"

# Stats
python3 memory_db.py stats
```

### Retrieval Strategy
1. First: `memory_db.py search` for precise retrieval
2. Fallback: semantic search (memory_search) for fuzzy matching

---

## 2. Intelligent Heartbeat Scheduling

### Priority Scoring (1-5)

| Check Item | Base | Bonus Conditions |
|-----------|------|-----------------|
| Calendar | 2 | Meeting mentioned +2; >4h since last +1 |
| Messages | 2 | Unread mentions +2 |
| Version check | 1 | >24h since last +2 |
| Services | 1 | Last check failed +3 |
| Config sync | 1 | Night hours +3; not synced today +2 |
| External learning | 1 | >24h since last +2 |
| Memory compress | 1 | >7 days since last +2; >50 files +2 |
| Self-audit | 0 | Sunday +5; >7 days since last +3 |

Execute top 1-3 items by score.

### Notification Rules
- Notify: meeting <2h, important unread, service down, new version, task due today
- Silent: night (23:00-08:00), all normal, user busy

---

## 3. Memory Compression

### Auto-Extract (after important sessions)

Record to database:
1. **Decisions** → `add_decision(title, decision, rejected_alternatives, rationale)`
2. **Discoveries** → `add_observation('discovery', title, narrative, facts, concepts)`
3. **Lessons** → `add_observation('bugfix', title, narrative, facts, concepts)`
4. **Summary** → `add_session_summary(request, learned, completed, next_steps)`

### Periodic Compression (weekly)

For logs older than 7 days:
1. Sub-agent extracts structured info to database
2. Key info not in MEMORY.md → add to MEMORY.md
3. Older than 30 days → archive to `memory/archive/YYYY-MM/`

### Compression Agent Template
```
Extract structured information from this log as JSON:

{file_content}

Output format:
{
  "observations": [{"type": "...", "title": "...", "narrative": "...", "facts": [...], "concepts": [...]}],
  "decisions": [{"title": "...", "decision": "...", "rejected_alternatives": [...], "rationale": "..."}],
  "summary": "one-line summary"
}

Rules: Only extract long-term valuable info. Ignore debug logs. title ≤ 20 chars, narrative ≤ 100 chars.
```

---

## 4. Self-Audit (Weekly)

### Flow
1. **Collect**: Read last 7 days of memory/*.md
2. **Analyze**: Task completion, sub-agent success rate, lessons, repeated patterns
3. **Output**: Write to `memory/self-audit-YYYY-MM-DD.md`
4. **Improve**: Update MEMORY.md, create new Skills if needed

---

## 5. Task Extraction from Conversations

| Signal | Example | Action |
|--------|---------|--------|
| Strong | "Create a task for...", "Do X by tomorrow" | Create task directly |
| Medium | "This needs fixing", "Let's do X" | Confirm then create |
| Weak | "Maybe someday...", "Could consider..." | Log only |

---

## 6. Quality Control (SAGE Critic)

### When to Use
- After code development tasks
- After important documents/reports
- When sub-agent output quality is uncertain

### Critic Agent Template
```
You are a quality review Agent (Critic).

## Original Task
{original_task}

## Output Location
{output_path}

## Evaluation Dimensions
1. Completeness: All requirements met?
2. Correctness: Logic correct? Bugs?
3. Safety: Side effects?
4. Efficiency: Redundancy?
5. Maintainability: Clear and readable?

## Output
{"score": 1-10, "passed": true/false, "issues": [...], "suggestions": [...]}
```

### Two-Phase Review
1. Phase 1 (Main Agent): Spec compliance — requirements met, constraints respected
2. Phase 2 (Critic Agent): Quality — safety, efficiency, edge cases

---

## 7. Sub-Agent Templates

### Principles
- Critical info first, marked with ⚠️
- Provide exact file paths
- Explicitly list "do NOT do" items
- One agent, one task
- Task granularity: 2-5 minutes

### Template Index

| Template | Use Case |
|----------|----------|
| Code Development | Constraints → Task → File paths → Verification |
| Info Search | Task → Output requirements (≥20 items) → Search scope → Quality rules |
| Memory Compression | Log content → JSON extraction → Rules |
| Critic Review | Original task → Output → Evaluation → Verdict |
