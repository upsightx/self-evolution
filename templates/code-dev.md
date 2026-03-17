# Code Development Template

## Template

```
⚠️ Critical Constraints (MUST follow):
- {constraint_1}
- {constraint_2}
- DO NOT modify any file not listed below
- DO NOT install new dependencies without explicit approval

## Task
{one_line_description}

## Detailed Requirements
1. {step_1}
2. {step_2}
3. {step_3}

## File Paths
- Modify: {file_path_1}
- Modify: {file_path_2}
- Reference (read-only): {reference_path}

## Known Pitfalls
- {pitfall_1}
- {pitfall_2}

## Verification
- Run: {test_command}
- Expected: {expected_result}
- Manual check: {what_to_verify}

## TDD Process (if applicable)
1. Write test first describing expected behavior
2. Run test — confirm it FAILS (RED)
3. Write minimal implementation to pass (GREEN)
4. Refactor if needed (REFACTOR)
5. Code without tests will be rejected
```

## Tips

- Keep task scope to 2-5 minutes of work
- One agent per file — never let two agents modify the same file
- Provide code snippets for context, don't make the agent search
- List "DO NOT" items — negative constraints are more effective than positive ones
