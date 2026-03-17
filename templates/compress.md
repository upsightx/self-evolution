# Memory Compression Template

Use this template to extract structured information from raw daily logs.

## Template

```
You are a memory compression Agent. Extract structured information from the following log.

⚠️ Rules:
- Only extract information with LONG-TERM value
- Ignore temporary debug logs, routine status checks, casual chat
- Focus on: decisions, lessons learned, discoveries, bugs fixed, features built
- title: max 20 characters
- narrative: max 100 characters

## Log Content

{file_content}

## Output Format (JSON)

{
  "observations": [
    {
      "type": "discovery|bugfix|decision|feature|refactor|change",
      "title": "Short title",
      "narrative": "What happened and why it matters",
      "facts": ["Concrete fact 1", "Concrete fact 2"],
      "concepts": ["concept-tag-1", "concept-tag-2"]
    }
  ],
  "decisions": [
    {
      "title": "Decision title",
      "decision": "What was decided",
      "rejected_alternatives": ["Option B that was rejected", "Option C"],
      "rationale": "Why this option was chosen"
    }
  ],
  "summary": "One-line summary of the day"
}

Write the JSON to {output_path}
```

## Type Guide

| Type | When to Use | Example |
|------|------------|---------|
| `decision` | Architecture or strategy choice | "Chose SQLite over PostgreSQL" |
| `bugfix` | Bug fix or lesson from failure | "torch CUDA dependency too heavy" |
| `feature` | New capability built | "Added FTS5 search to memory" |
| `refactor` | Code/structure improvement | "Merged 4 skills into 1" |
| `discovery` | New knowledge learned | "MiniMax more stable than GLM5" |
| `change` | General change (default) | "Updated config file" |

## After Extraction

Import the JSON into the database:

```bash
python3 memory_db.py import extracted.json
```
