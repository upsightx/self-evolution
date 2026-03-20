#!/usr/bin/env python3
"""
Auto-extract memories from conversation text and save to memory_db.

Pure rule-based extraction (no LLM). Matches Chinese patterns like:
- Observations: "发现...", "原来...", "注意到...", "学到...", "教训...", "经验...", "结论...", "确认..."
- Decisions: "决定...", "选择...", "改用...", "换成...", "不再...", "以后...", "从现在起..."

Usage:
    python3 auto_memory.py "对话文本"
    python3 auto_memory.py --dry-run "对话文本"
    python3 auto_memory.py --from-file /path/to/file.md
"""

import re
import sys
import argparse
import difflib
from datetime import datetime, timedelta

# Patterns and their categories
OBSERVATION_PATTERNS = [
    r'发现[了：:\s]*(.*)',
    r'原来[：:\s]*(.*)',
    r'注意到[了：:\s]*(.*)',
    r'学到[了：:\s]*(.*)',
    r'教训[是：:\s]*(.*)',
    r'经验[是：:\s]*(.*)',
    r'结论[是：:\s]*(.*)',
    r'确认[了：:\s]*(.*)',
]

DECISION_PATTERNS = [
    r'决定[了：:\s]*(.*)',
    r'选择[了：:\s]*(.*)',
    r'改用[了：:\s]*(.*)',
    r'换成[了：:\s]*(.*)',
    r'不再[：:\s]*(.*)',
    r'以后[：:\s]*(.*)',
    r'从现在起[，,：:\s]*(.*)',
]

# Keywords for observation type classification
BUGFIX_KEYWORDS = ['bug', 'Bug', 'BUG', '错误', '失败', '报错', '异常', '崩溃', '修复']
DISCOVERY_KEYWORDS = ['发现', '原来']
LESSON_KEYWORDS = ['教训', '经验']

MIN_CONTENT_LENGTH = 10
MAX_CONTENT_LENGTH = 200  # Too long = probably a paragraph, not a memory

# Content that looks like log fragments, not real memories
NOISE_PATTERNS = re.compile(
    r'^[）)、，,\s]|'           # starts with punctuation/bracket
    r'^[a-zA-Z_]+\(|'          # starts with function call
    r'^\d+[行条个]|'            # starts with count
    r'^[\-\*]\s|'              # starts with list marker
    r'→|✅|❌|✓|☑'             # status markers
)


def _classify_observation(text, trigger):
    """Classify observation type based on content and trigger keyword."""
    combined = trigger + text
    for kw in BUGFIX_KEYWORDS:
        if kw in combined:
            return 'bugfix'
    for kw in DISCOVERY_KEYWORDS:
        if kw in trigger:
            return 'discovery'
    for kw in LESSON_KEYWORDS:
        if kw in trigger:
            return 'lesson'
    return 'change'


def _clean_content(text):
    """Clean extracted content: strip, remove trailing punctuation noise."""
    text = text.strip()
    # Remove trailing newlines and whitespace
    text = text.split('\n')[0].strip()
    return text


def _make_title(text, max_len=20):
    """Generate title from first max_len chars of text."""
    clean = text.strip()
    if len(clean) <= max_len:
        return clean
    return clean[:max_len] + '...'


def extract_memories(text):
    """Extract observations and decisions from conversation text.

    Pure rule-based, no LLM. Matches Chinese trigger patterns.

    Args:
        text: conversation text string

    Returns:
        dict with keys:
            observations: list of {type, title, narrative}
            decisions: list of {title, decision}
    """
    if not text or not text.strip():
        return {"observations": [], "decisions": []}

    observations = []
    decisions = []
    seen_narratives = set()
    seen_decisions = set()

    # Extract observations
    for pattern in OBSERVATION_PATTERNS:
        for match in re.finditer(pattern, text):
            content = _clean_content(match.group(1))
            if len(content) < MIN_CONTENT_LENGTH:
                continue
            if len(content) > MAX_CONTENT_LENGTH:
                continue
            if NOISE_PATTERNS.search(content):
                continue
            if content in seen_narratives:
                continue
            seen_narratives.add(content)

            # Determine trigger word for classification
            trigger = match.group(0)[:match.start(1) - match.start(0)]
            obs_type = _classify_observation(content, trigger)
            title = _make_title(content)

            observations.append({
                "type": obs_type,
                "title": title,
                "narrative": content,
            })

    # Extract decisions
    for pattern in DECISION_PATTERNS:
        for match in re.finditer(pattern, text):
            content = _clean_content(match.group(1))
            if len(content) < MIN_CONTENT_LENGTH:
                continue
            if len(content) > MAX_CONTENT_LENGTH:
                continue
            if NOISE_PATTERNS.search(content):
                continue
            if content in seen_decisions:
                continue
            # Check if this content is a substring of or contains an already-seen decision
            is_overlap = False
            for existing in list(seen_decisions):
                if content in existing or existing in content:
                    is_overlap = True
                    break
            if is_overlap:
                continue
            seen_decisions.add(content)

            title = _make_title(content)
            decisions.append({
                "title": title,
                "decision": content,
            })

    return {"observations": observations, "decisions": decisions}


def _is_duplicate(title, existing_titles, threshold=0.7):
    """Check if title is similar to any existing title using SequenceMatcher."""
    for existing in existing_titles:
        ratio = difflib.SequenceMatcher(None, title, existing).ratio()
        if ratio >= threshold:
            return True
    return False


def _get_recent_titles(days=7):
    """Get titles from memory_db for the last N days."""
    from memory_db import recent_by_days
    obs_titles = []
    dec_titles = []

    try:
        recent_obs = recent_by_days(days=days, table="observations")
        obs_titles = [r.get("title", "") for r in recent_obs if r.get("title")]
    except Exception:
        pass

    try:
        recent_decs = recent_by_days(days=days, table="decisions")
        dec_titles = [r.get("title", "") for r in recent_decs if r.get("title")]
    except Exception:
        pass

    return obs_titles, dec_titles


def auto_save(text, dry_run=False):
    """Extract memories from text and save to memory_db.

    Args:
        text: conversation text
        dry_run: if True, only return extracted results without saving

    Returns:
        dict: {
            "extracted": {observations: [...], decisions: [...]},
            "saved": {"observations": N, "decisions": N},
            "skipped_duplicates": N
        }
    """
    extracted = extract_memories(text)

    result = {
        "extracted": extracted,
        "saved": {"observations": 0, "decisions": 0},
        "skipped_duplicates": 0,
    }

    if dry_run:
        return result

    # Get recent titles for dedup
    recent_obs_titles, recent_dec_titles = _get_recent_titles(days=7)

    from memory_db import add_observation, add_decision

    # Save observations
    for obs in extracted["observations"]:
        if _is_duplicate(obs["title"], recent_obs_titles):
            result["skipped_duplicates"] += 1
            continue
        add_observation(
            type=obs["type"],
            title=obs["title"],
            narrative=obs["narrative"],
            source="auto_memory",
        )
        recent_obs_titles.append(obs["title"])
        result["saved"]["observations"] += 1

    # Save decisions
    for dec in extracted["decisions"]:
        if _is_duplicate(dec["title"], recent_dec_titles):
            result["skipped_duplicates"] += 1
            continue
        add_decision(
            title=dec["title"],
            decision=dec["decision"],
        )
        recent_dec_titles.append(dec["title"])
        result["saved"]["decisions"] += 1

    return result


def main():
    parser = argparse.ArgumentParser(description="Auto-extract and save memories from conversation text")
    parser.add_argument("text", nargs="?", help="Conversation text to process")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, don't save")
    parser.add_argument("--from-file", type=str, help="Read text from file")
    args = parser.parse_args()

    if args.from_file:
        with open(args.from_file, "r", encoding="utf-8") as f:
            text = f.read()
    elif args.text:
        text = args.text
    else:
        parser.print_help()
        sys.exit(1)

    result = auto_save(text, dry_run=args.dry_run)

    # Print extracted
    extracted = result["extracted"]
    if not extracted["observations"] and not extracted["decisions"]:
        print("No memories extracted.")
        return

    print(f"=== Extracted ===")
    for obs in extracted["observations"]:
        print(f"  [OBS/{obs['type']}] {obs['title']}")
        print(f"    {obs['narrative']}")
    for dec in extracted["decisions"]:
        print(f"  [DEC] {dec['title']}")
        print(f"    {dec['decision']}")

    if args.dry_run:
        print(f"\n(dry-run: nothing saved)")
    else:
        saved = result["saved"]
        skipped = result["skipped_duplicates"]
        print(f"\n=== Saved ===")
        print(f"  Observations: {saved['observations']}, Decisions: {saved['decisions']}, Skipped duplicates: {skipped}")


if __name__ == "__main__":
    main()
