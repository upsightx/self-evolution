#!/usr/bin/env python3
"""Shared bootstrap helpers for self-evolution modules.

Keeps path setup logic in one place so modules do not each maintain their own
sys.path mutation contract.
"""
from __future__ import annotations

import sys
from pathlib import Path

_MODULES = Path(__file__).resolve().parent
_SELF_EVOLUTION = _MODULES.parent
_WORKSPACE = _SELF_EVOLUTION.parent
if not (_WORKSPACE / "runtime_config.py").exists() and (_SELF_EVOLUTION / "runtime_config.py").exists():
    # Fallback for standalone self-evolution checkouts.
    _WORKSPACE = _SELF_EVOLUTION


def ensure_workspace_on_path() -> Path:
    if str(_WORKSPACE) not in sys.path:
        sys.path.insert(0, str(_WORKSPACE))
    return _WORKSPACE


def ensure_xmemory_on_path() -> Path:
    workspace = ensure_workspace_on_path()
    from runtime_config import XMEMORY_PATH
    if str(XMEMORY_PATH) not in sys.path:
        sys.path.insert(0, str(XMEMORY_PATH))
    return Path(XMEMORY_PATH)


def module_workspace() -> Path:
    return _WORKSPACE


def module_dir() -> Path:
    return _MODULES
