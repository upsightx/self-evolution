#!/usr/bin/env python3
"""Proposal Janitor — remove clearly bad or test-only proposals.

Deletion is intentionally conservative. High-risk or ambiguous proposals are not
deleted by this module; they remain for human/evidence review.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from bootstrap import ensure_workspace_on_path, ensure_xmemory_on_path

ensure_workspace_on_path()
ensure_xmemory_on_path()

TERMINAL_STATUSES = {"cancelled", "rejected", "deprecated", "failed"}
ACTIVE_STATUSES = {"draft", "pending_review", "approved", "experimenting", "validated"}


@dataclass(frozen=True)
class JanitorDecision:
    proposal_id: str
    action: str
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


def classify_proposal_for_cleanup(proposal: dict) -> JanitorDecision:
    """Classify whether a proposal is safe to delete."""
    pid = proposal.get("proposal_id", "") or ""
    title = (proposal.get("title", "") or "").lower()
    summary = (proposal.get("summary", "") or "").lower()
    status = proposal.get("status", "") or ""
    created_by = proposal.get("created_by", "") or ""
    evidence = proposal.get("evidence") or []

    if pid.startswith("test_"):
        return JanitorDecision(pid, "delete", "test proposal residue")

    if status == "cancelled" and created_by in {"auto_evolve", "system", "main_agent"}:
        return JanitorDecision(pid, "delete", "cancelled system-generated proposal")

    if status in {"rejected", "deprecated"} and not evidence:
        return JanitorDecision(pid, "delete", "terminal rejected/deprecated proposal without evidence")

    if status == "draft" and created_by == "auto_evolve" and not evidence:
        text = f"{title} {summary}"
        if "test" in text or "dry-run" in text or "dry run" in text:
            return JanitorDecision(pid, "delete", "dry-run draft without evidence")
        return JanitorDecision(pid, "cancel", "auto_evolve draft without evidence needs cancellation before deletion")

    if status in ACTIVE_STATUSES:
        return JanitorDecision(pid, "keep", "active proposal requires review")

    if status in TERMINAL_STATUSES:
        return JanitorDecision(pid, "keep", "terminal proposal retained for audit")

    return JanitorDecision(pid, "keep", "no cleanup rule matched")


def delete_proposal(proposal_id: str) -> dict:
    """Compatibility wrapper; lifecycle manager owns physical deletion."""
    from proposal_lifecycle_manager import delete_proposal as lifecycle_delete_proposal

    return lifecycle_delete_proposal(proposal_id)


def cleanup_bad_proposals(dry_run: bool = True, limit: int = 100) -> dict:
    """Clean up proposals classified as safe-to-delete.

    Args:
        dry_run: When True, only report decisions.
        limit: Max proposals to inspect.
    """
    from proposal_lifecycle_manager import get_proposal, list_proposals, transition

    candidates = []
    for status in ["cancelled", "rejected", "deprecated", "draft"]:
        candidates.extend(list_proposals(status=status, limit=limit))

    decisions = []
    deleted = []
    cancelled = []
    for p in candidates[:limit]:
        full = get_proposal(p["proposal_id"]) or p
        decision = classify_proposal_for_cleanup(full)
        decisions.append(decision.to_dict())
        if dry_run:
            continue
        if decision.action == "delete":
            result = delete_proposal(decision.proposal_id)
            if result.get("success"):
                deleted.append(decision.proposal_id)
        elif decision.action == "cancel":
            result = transition(decision.proposal_id, "cancelled", actor="proposal_janitor", reason=decision.reason)
            if result.get("success"):
                cancelled.append(decision.proposal_id)

    return {
        "dry_run": dry_run,
        "inspected": len(candidates[:limit]),
        "decisions": decisions,
        "deleted": deleted,
        "cancelled": cancelled,
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Clean bad/test proposal residue")
    parser.add_argument("--apply", action="store_true", help="Actually delete/cancel proposals")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    result = cleanup_bad_proposals(dry_run=not args.apply, limit=args.limit)
    print(f"dry_run={result['dry_run']} inspected={result['inspected']} deleted={len(result['deleted'])} cancelled={len(result['cancelled'])}")
    for d in result["decisions"][:30]:
        if d["action"] != "keep":
            print(f"{d['proposal_id']}: {d['action']} — {d['reason']}")
