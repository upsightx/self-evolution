#!/usr/bin/env python3
"""
Example: Auto-extract structured memory at the end of a session.

Run this after an important session to record what happened.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from memory_db import *

# Initialize if needed
if not os.path.exists(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "memory.db")):
    init_db()

# --- Example: Record a session's key outcomes ---

# 1. Record decisions made during the session
add_decision(
    title="Chose SQLite over PostgreSQL for memory",
    decision="Use SQLite + FTS5 for structured memory storage",
    rejected_alternatives=[
        "PostgreSQL (too heavy for single-agent use)",
        "ChromaDB (extra dependency, overkill for precise search)",
        "Plain text files (no efficient search)"
    ],
    rationale="Zero dependencies, system-built-in, FTS5 covers our search needs"
)

# 2. Record discoveries
add_observation(
    type="discovery",
    title="Progressive disclosure saves 50-75% tokens",
    narrative="Instead of returning full records, use 3-layer retrieval: "
              "L1 (index) -> L2 (context) -> L3 (full). "
              "Only go deeper when needed.",
    facts=["L1 costs ~50 tokens/result", "L3 costs ~500 tokens/result"],
    concepts=["retrieval", "token-optimization", "progressive-disclosure"]
)

# 3. Record lessons learned (bugfix type)
add_observation(
    type="bugfix",
    title="Always test in Docker before deploying",
    narrative="Deployed directly to host, torch CUDA dependency broke the system. "
              "Should have tested in isolated container first.",
    facts=["torch CUDA is 2GB+", "hdbscan needs Cython<3"],
    concepts=["deployment", "docker", "isolation"]
)

# 4. Record session summary
add_session_summary(
    request="Set up structured memory system for AI agent",
    investigated="claude-mem design, SAGE framework, Lore protocol",
    learned="Structured memory + progressive retrieval is more efficient than flat files",
    completed="SQLite+FTS5 database, memory compression skill, Critic templates",
    next_steps="Accumulate data, validate retrieval quality, explore agency-agents"
)

# 5. Check what we have
print("Session recorded! Current stats:")
print(stats())
