#!/usr/bin/env python3
"""Compatibility wrapper for proposal governance.

Canonical governance logic now lives in proposal_lifecycle_manager. Keep this
module as a thin adapter so older imports still work while callers migrate.
"""
from __future__ import annotations

from bootstrap import ensure_workspace_on_path, ensure_xmemory_on_path

ensure_workspace_on_path()
ensure_xmemory_on_path()

import proposal_lifecycle_manager as lifecycle


def get_governance_actions(limit: int = 100) -> dict:
    return lifecycle.get_governance_actions(limit=limit)


def apply_governance_actions(limit: int = 100) -> dict:
    return lifecycle.apply_governance_actions(limit=limit)


if __name__ == "__main__":
    import json
    print(json.dumps(get_governance_actions(), ensure_ascii=False, indent=2))
