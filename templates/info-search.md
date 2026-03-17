# Information Search Template

## Template

```
## Task
Search and compile information about: {topic}

## Output Requirements
- Format: {markdown|json|table}
- Save to: {output_path}
- Minimum: 20 items (aim for 25+)
- Fields per item: {field_list}

## Search Sources
{source_1_with_specific_urls_or_apis}
{source_2}
{source_3}

## Search Keywords
- "{keyword_1}"
- "{keyword_2}"
- "{keyword_3}"

## Quality Rules
- Deduplicate by {dedup_field}
- Sort by {sort_field} descending
- Mark items matching {highlight_criteria} with 🔥
- Discard items that {discard_criteria}

## Output Format

# {topic} — {date}

| # | {col1} | {col2} | {col3} | {col4} |
|---|--------|--------|--------|--------|
| 1 | ...    | ...    | ...    | ...    |

## Key Highlights
- **[Item](url)** — Why it matters (2-3 sentences)

Do not skip any step. Reply "{topic} search complete, N items" when done.
```

## Tips

- Always specify minimum item count (20+)
- Give exact URLs and API endpoints, don't make the agent figure them out
- Include dedup and sort rules to ensure quality
- Ask for highlights on the most important items
