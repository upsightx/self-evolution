#!/usr/bin/env python3
"""Controlled Loop Router — advisory routing for self-evolution proposals.

This module is intentionally read-only. It recommends the next expert/action for a
proposal, but it does not transition proposal state or execute code.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from bootstrap import ensure_workspace_on_path, ensure_xmemory_on_path

ensure_workspace_on_path()
ensure_xmemory_on_path()

try:
    from evolution_executor import classify_change_risk
except Exception:  # pragma: no cover - fallback for standalone analysis
    def classify_change_risk(target_file: str, operation: str = "modify") -> str:
        return "medium"

FILE_SUFFIXES = (".py", ".md", ".json", ".yaml", ".yml")
ACTIVE_STATUSES = {"draft", "pending_review", "approved", "experimenting", "validated"}


@dataclass(frozen=True)
class RouteDecision:
    proposal_id: str
    status: str
    risk_level: str
    next_action: str
    expert: str
    reason: str
    requires_human_approval: bool

    def to_dict(self) -> dict:
        return asdict(self)


def has_file_target(target_scope: str) -> bool:
    """Return True when target_scope looks like a concrete file path."""
    target_scope = (target_scope or "").strip()
    return bool(target_scope and ("/" in target_scope or target_scope.endswith(FILE_SUFFIXES)))


def decide_next_action(proposal: dict) -> RouteDecision:
    """Recommend the next action for a proposal without mutating state."""
    pid = proposal.get("proposal_id", "")
    status = proposal.get("status", "draft")
    target_scope = proposal.get("target_scope", "") or ""
    evidence = proposal.get("evidence") or []
    file_target = has_file_target(target_scope)
    risk = classify_change_risk(target_scope) if file_target else "low"

    if status not in ACTIVE_STATUSES:
        return RouteDecision(pid, status, risk, "archive", "memory_governor",
                             "Proposal is terminal or inactive", False)

    if status == "draft":
        if evidence:
            return RouteDecision(pid, status, risk, "promote_to_review", "proposal_lifecycle_manager",
                                 "Draft has evidence and can enter review", False)
        return RouteDecision(pid, status, risk, "gather_evidence", "memory_governor",
                             "Draft needs evidence before review", False)

    if status == "pending_review":
        if file_target or risk == "high":
            return RouteDecision(pid, status, risk, "request_human_approval", "human",
                                 "Executable or high-risk proposal requires explicit approval", True)
        return RouteDecision(pid, status, risk, "approve_tracked_proposal", "proposal_lifecycle_manager",
                             "Non-executable proposal can be approved as tracked work", False)

    if status == "approved":
        if file_target:
            if risk == "low":
                return RouteDecision(pid, status, risk, "run_executor_dry_run", "evolution_executor",
                                     "Low-risk file proposal should dry-run before execution", False)
            return RouteDecision(pid, status, risk, "request_human_approval", "human",
                                 "Medium/high-risk file proposal needs approval before execution", True)
        return RouteDecision(pid, status, risk, "await_explicit_release", "proposal_lifecycle_manager",
                             "Tracked proposal should not auto-release from heartbeat", False)

    if status == "experimenting":
        try:
            from evidence_validator import choose_validation_track
            track = choose_validation_track(proposal)
        except Exception:
            track = "causal"
        if track == "evidence":
            return RouteDecision(pid, status, risk, "run_evidence_review", "evidence_validator",
                                 "Structural/safety proposal can be judged by direct evidence", False)
        return RouteDecision(pid, status, risk, "run_causal_validation", "causal_validator",
                             "Capability proposal needs longitudinal validation samples", False)

    if status == "validated":
        return RouteDecision(pid, status, risk, "release", "proposal_lifecycle_manager",
                             "Validated proposal is ready for explicit release", False)

    return RouteDecision(pid, status, risk, "manual_review", "human",
                         "No safe automatic route matched", True)


def route_many(proposals: list[dict]) -> list[dict]:
    """Return routing recommendations for multiple proposals."""
    return [decide_next_action(p).to_dict() for p in proposals]


def build_action_panel(proposals: list[dict], limit: int = 10) -> dict:
    """Build a compact action panel from routing recommendations."""
    decisions = route_many(proposals)[:limit]
    by_action: dict[str, int] = {}
    by_risk: dict[str, int] = {}
    human_required = []
    next_items = []

    for item in decisions:
        by_action[item["next_action"]] = by_action.get(item["next_action"], 0) + 1
        by_risk[item["risk_level"]] = by_risk.get(item["risk_level"], 0) + 1
        if item["requires_human_approval"]:
            human_required.append(item)
        next_items.append({
            "proposal_id": item["proposal_id"],
            "next_action": item["next_action"],
            "expert": item["expert"],
            "risk_level": item["risk_level"],
            "requires_human_approval": item["requires_human_approval"],
        })

    return {
        "total": len(decisions),
        "by_action": by_action,
        "by_risk": by_risk,
        "human_required": human_required,
        "next_items": next_items,
    }


def main() -> int:
    try:
        from proposal_lifecycle_manager import list_proposals
    except Exception as e:
        print(f"controlled_loop_router unavailable: {e}")
        return 1

    proposals = []
    for status in sorted(ACTIVE_STATUSES):
        proposals.extend(list_proposals(status=status, limit=20))

    panel = build_action_panel(proposals, limit=20)
    print(f"Action panel: total={panel['total']} by_risk={panel['by_risk']} by_action={panel['by_action']}")
    if panel['human_required']:
        print(f"Human approval required: {len(panel['human_required'])}")
    for decision in route_many(proposals)[:20]:
        print(
            f"[{decision['status']}] {decision['proposal_id']} -> "
            f"{decision['next_action']} ({decision['expert']}, risk={decision['risk_level']})"
        )
        print(f"  reason: {decision['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
