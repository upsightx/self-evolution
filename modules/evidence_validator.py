#!/usr/bin/env python3
"""Evidence Validator — immediate review for structural and safety changes.

Use this for changes that can be judged by direct evidence: tests, compile
checks, dry-runs, diff sanity, and architecture contracts. Long-term capability
improvements should remain with causal_validator.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
import sys

from bootstrap import ensure_workspace_on_path, ensure_xmemory_on_path

_workspace = ensure_workspace_on_path()
ensure_xmemory_on_path()

try:
    from evolution_executor import classify_change_risk
except Exception:  # pragma: no cover
    def classify_change_risk(target_file: str, operation: str = "modify") -> str:
        return "medium"

STRUCTURAL_KEYWORDS = (
    "safety", "guard", "router", "orchestrator", "executor", "validator",
    "heartbeat", "config", "schema", "test", "dry-run", "dry run",
    "compile", "py_compile", "proposal", "lifecycle", "risk",
)
CAPABILITY_KEYWORDS = (
    "success rate", "capability", "model", "minimax", "coding/", "research/",
    "agent success", "benchmark", "performance",
)
PASSING_EVIDENCE_KEYWORDS = (
    "tests ok", "test ok", "passed", "py_compile", "dry-run confirmed",
    "auto-execute disabled", "diff sanity", "compiled",
)
FAILING_EVIDENCE_KEYWORDS = (
    "failed", "error", "traceback", "corrupt", "rollback", "syntax error",
)


@dataclass(frozen=True)
class EvidenceVerdict:
    proposal_id: str
    validation_track: str
    verdict: str
    confidence: float
    reason: str
    recommended_next_action: str

    def to_dict(self) -> dict:
        return asdict(self)


def choose_validation_track(proposal: dict) -> str:
    """Choose evidence or causal validation for a proposal."""
    text = " ".join(str(proposal.get(k, "")) for k in (
        "title", "summary", "category", "target_module", "target_scope", "change_description"
    )).lower()
    target_scope = str(proposal.get("target_scope", "") or "")

    if target_scope.endswith((".py", ".md", ".json", ".yaml", ".yml")) or "/" in target_scope:
        return "evidence"
    if any(k in text for k in STRUCTURAL_KEYWORDS):
        return "evidence"
    if any(k in text for k in CAPABILITY_KEYWORDS):
        return "causal"
    return "evidence"


def evaluate_proposal(proposal: dict) -> EvidenceVerdict:
    """Return an immediate evidence-based verdict without mutating state."""
    pid = proposal.get("proposal_id", "")
    track = choose_validation_track(proposal)
    if track == "causal":
        return EvidenceVerdict(pid, track, "needs_causal_samples", 0.7,
                               "Capability/performance proposal needs longitudinal samples",
                               "run_causal_validator")

    evidence_items = proposal.get("evidence") or []
    evidence_text = " ".join(str(item) for item in evidence_items).lower()
    summary_text = " ".join(str(proposal.get(k, "")) for k in (
        "title", "summary", "change_description"
    )).lower()
    combined = f"{summary_text} {evidence_text}"
    risk = classify_change_risk(str(proposal.get("target_scope", "") or ""))

    if any(k in combined for k in FAILING_EVIDENCE_KEYWORDS):
        return EvidenceVerdict(pid, track, "failed_by_evidence", 0.8,
                               "Evidence contains failure or rollback signals",
                               "mark_failed_or_review")

    pass_hits = sum(1 for k in PASSING_EVIDENCE_KEYWORDS if k in combined)
    if pass_hits >= 2 and risk != "high":
        return EvidenceVerdict(pid, track, "validated_by_evidence", 0.85,
                               "Multiple direct validation signals found",
                               "mark_validated")

    if pass_hits >= 2 and risk == "high":
        return EvidenceVerdict(pid, track, "needs_human_review", 0.8,
                               "High-risk change has evidence but still needs owner approval",
                               "request_human_approval")

    if pass_hits == 1:
        return EvidenceVerdict(pid, track, "needs_more_evidence", 0.6,
                               "Only one direct validation signal found",
                               "collect_more_evidence")

    return EvidenceVerdict(pid, track, "needs_more_evidence", 0.5,
                           "No direct validation evidence found",
                           "collect_more_evidence")


def collect_direct_evidence(proposal: dict, run_tests: bool = False) -> list[str]:
    """Collect cheap local evidence for an immediate review.

    This function is read-only except for running validation commands. It does
    not mutate proposal state.
    """
    import subprocess

    evidence = []
    target = str(proposal.get("target_scope", "") or "").strip()
    target_path = (_workspace / target).resolve() if target else None

    if target and target_path:
        try:
            target_path.relative_to(_workspace.resolve())
            if target_path.exists():
                evidence.append(f"target exists: {target}")
                if target.endswith(".py"):
                    result = subprocess.run(
                        [sys.executable, "-m", "py_compile", str(target_path)],
                        cwd=_workspace, capture_output=True, text=True, timeout=30,
                    )
                    if result.returncode == 0:
                        evidence.append("py_compile passed")
                    else:
                        evidence.append(f"py_compile failed: {(result.stderr or result.stdout)[:200]}")
                elif target.endswith(".json"):
                    import json as _json
                    try:
                        _json.loads(target_path.read_text(encoding="utf-8"))
                        evidence.append("json parse passed")
                    except Exception as e:
                        evidence.append(f"json parse failed: {e}")
            else:
                evidence.append(f"target missing: {target}")
        except Exception:
            evidence.append(f"target path invalid: {target}")

    run_all = _workspace / "tests" / "run_all.py"
    if run_tests and run_all.exists() and (target.endswith(".py") or "test" in str(proposal).lower()):
        result = subprocess.run(
            [sys.executable, str(run_all)],
            cwd=_workspace, capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0:
            evidence.append("tests ok")
        else:
            output = (result.stdout + "\n" + result.stderr)[-500:]
            evidence.append(f"tests failed: {output}")

    try:
        from proposal_lifecycle_manager import get_proposal
        full = get_proposal(proposal.get("proposal_id", ""))
        if full:
            transitions = full.get("transitions") or []
            evidence.append(f"transition_count={len(transitions)}")
            attached = full.get("evidence") or []
            evidence.append(f"attached_evidence_count={len(attached)}")
    except Exception:
        pass

    return evidence


def evaluate_with_collected_evidence(proposal: dict, run_tests: bool = False) -> EvidenceVerdict:
    """Collect direct evidence, then evaluate the enriched proposal."""
    collected = collect_direct_evidence(proposal, run_tests=run_tests)
    enriched = dict(proposal)
    enriched["evidence"] = list(proposal.get("evidence") or []) + collected
    return evaluate_proposal(enriched)


def evaluate_many(proposals: list[dict], collect: bool = False, run_tests: bool = False) -> list[dict]:
    if collect:
        return [evaluate_with_collected_evidence(p, run_tests=run_tests).to_dict() for p in proposals]
    return [evaluate_proposal(p).to_dict() for p in proposals]


if __name__ == "__main__":
    try:
        from proposal_lifecycle_manager import list_proposals
        proposals = []
        for status in ("approved", "experimenting", "validated", "pending_review"):
            proposals.extend(list_proposals(status=status, limit=20))
        for verdict in evaluate_many(proposals[:20], collect=True):
            print(
                f"{verdict['proposal_id']} -> {verdict['verdict']} "
                f"({verdict['validation_track']}, confidence={verdict['confidence']})"
            )
            print(f"  next: {verdict['recommended_next_action']} — {verdict['reason']}")
    except Exception as e:
        print(f"evidence_validator unavailable: {e}")
        raise SystemExit(1)
