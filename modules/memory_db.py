#!/usr/bin/env python3
"""
Memory DB Adapter for self-evolution modules.

This is a THIN ADAPTER that delegates ALL operations to X-Memory's memory_db.py.
self-evolution does NOT own the memory schema — X-Memory is the single source of truth.

Any module in self-evolution that does `from memory_db import X` will get
the real X-Memory implementation via this adapter.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure X-Memory is importable
_workspace = Path(__file__).resolve().parent.parent
if str(_workspace) not in sys.path:
    sys.path.insert(0, str(_workspace))

try:
    from runtime_config import XMEMORY_PATH
    _xm = str(XMEMORY_PATH)
except ImportError:
    _xm = str(_workspace / "X\u8bb0\u5fc6")

if _xm not in sys.path:
    sys.path.insert(0, _xm)

# ============ Re-export everything from X-Memory's memory_db ============
# This ensures `from memory_db import init_db, add_observation, ...` works
# identically whether called from X-Memory or self-evolution context.

# We must avoid circular imports: this file IS memory_db in modules/ context,
# so we import from the actual X-Memory path directly.
import importlib.util

_real_memory_db_path = Path(_xm) / "memory_db.py"
if not _real_memory_db_path.exists():
    raise ImportError(f"X-Memory memory_db.py not found at {_real_memory_db_path}")

_spec = importlib.util.spec_from_file_location("_xmemory_db", str(_real_memory_db_path))
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

# Re-export all public names
init_db = _mod.init_db
add_observation = _mod.add_observation
add_decision = _mod.add_decision
add_session_summary = _mod.add_session_summary
search = _mod.search
search_decisions = getattr(_mod, 'search_decisions', None)
get = _mod.get
stats = _mod.stats
count_by_type = _mod.count_by_type
recent_by_days = _mod.recent_by_days
import_json = _mod.import_json
add_task_outcome = _mod.add_task_outcome
remember = _mod.remember
recall = _mod.recall
init_v6_stack = _mod.init_v6_stack
embed_text = _mod.embed_text
build_embeddings = _mod.build_embeddings
semantic_search = _mod.semantic_search
search_with_context = getattr(_mod, 'search_with_context', None)
search_with_metadata = getattr(_mod, 'search_with_metadata', None)
MemoryDB = _mod.MemoryDB
main = _mod.main

if __name__ == "__main__":
    main()
