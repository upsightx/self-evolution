#!/usr/bin/env python3
"""Proposal Triage — route proposals to keep/delete/fuse actions."""
from __future__ import annotations

from bootstrap import ensure_workspace_on_path, ensure_xmemory_on_path

ensure_workspace_on_path()
ensure_xmemory_on_path()

from proposal_fusion import find_fusion_candidates, load_active_proposals
from proposal_janitor import cleanup_bad_proposals


def triage_proposals(limit: int = 100) -> dict:

    active = load_active_proposals(limit=limit)
    janitor = cleanup_bad_proposals(dry_run=True, limit=limit)
    fusions = find_fusion_candidates(active)

    delete_ids = {d["proposal_id"] for d in janitor["decisions"] if d["action"] == "delete"}
    covered_by_existing_fusion = set()
    existing_fusions = [p for p in active if (p.get("proposal_id", "") or "").startswith("fusion-")]
    active_ids = {p.get("proposal_id") for p in active}
    for fusion in existing_fusions:
        for item in (fusion.get("evidence") or []):
            e_type = item.get("evidence_type") or item.get("type")
            if e_type != "fusion_sources":
                continue
            ref = item.get("evidence_ref") or item.get("ref") or ""
            covered_by_existing_fusion.update(x for x in ref.split(",") if x and x in active_ids)

    fusion_sources = {pid for c in fusions for pid in c.get("source_ids", [])}
    delete_ids.update(covered_by_existing_fusion)

    keep = []
    for p in active:
        pid = p.get("proposal_id")
        if pid in delete_ids or pid in fusion_sources:
            continue
        keep.append(pid)

    return {
        "active_total": len(active),
        "delete": sorted(delete_ids),
        "fuse": fusions,
        "keep": keep,
    }


if __name__ == "__main__":
    import json
    result = triage_proposals()
    print(json.dumps(result, ensure_ascii=False, indent=2))
