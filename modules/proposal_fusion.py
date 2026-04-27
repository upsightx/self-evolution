#!/usr/bin/env python3
"""Proposal Fusion — combine mediocre related proposals into stronger candidates.

This module is conservative: it only generates fusion candidates. Creating or
changing proposals remains explicit.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
import re

from bootstrap import ensure_workspace_on_path, ensure_xmemory_on_path

ensure_workspace_on_path()
ensure_xmemory_on_path()

STOPWORDS = {
    "the", "and", "for", "with", "from", "this", "that", "into", "proposal",
    "improve", "fix", "能力", "提案", "系统", "优化", "改进", "问题", "建议",
}
FUSABLE_STATUSES = {"draft", "pending_review", "approved"}


@dataclass(frozen=True)
class FusionCandidate:
    source_ids: list[str]
    title: str
    rationale: str
    shared_terms: list[str]
    suggested_category: str
    confidence: float

    def to_dict(self) -> dict:
        return asdict(self)


def _tokens(text: str) -> set[str]:
    parts = re.findall(r"[A-Za-z0-9_\-/]+|[\u4e00-\u9fff]{2,}", text.lower())
    return {p for p in parts if len(p) >= 2 and p not in STOPWORDS}


def _proposal_text(p: dict) -> str:
    return " ".join(str(p.get(k, "") or "") for k in (
        "title", "summary", "category", "target_module", "target_scope", "change_description"
    ))


def _similarity(a: dict, b: dict) -> tuple[float, list[str]]:
    ta = _tokens(_proposal_text(a))
    tb = _tokens(_proposal_text(b))
    if not ta or not tb:
        return 0.0, []
    shared = sorted(ta & tb)
    score = len(shared) / max(len(ta | tb), 1)
    return score, shared


def _is_mediocre_but_fusable(p: dict) -> bool:
    status = p.get("status", "")
    proposal_id = p.get("proposal_id", "") or ""
    if status not in FUSABLE_STATUSES:
        return False
    if proposal_id.startswith("fusion-"):
        return False
    if p.get("priority") == "P0" and p.get("evidence"):
        return False
    return True


def find_fusion_candidates(proposals: list[dict], min_group: int = 2, max_group: int = 3) -> list[dict]:
    """Find related proposals that may be better as one fused proposal."""
    pool = [p for p in proposals if _is_mediocre_but_fusable(p)]
    candidates: list[FusionCandidate] = []
    used_keys = set()

    for i, base in enumerate(pool):
        scored = []
        shared_all = set()
        for j, other in enumerate(pool):
            if i == j:
                continue
            score, shared = _similarity(base, other)
            if score > 0:
                scored.append((score, other, shared))
                shared_all.update(shared)
        scored.sort(key=lambda x: x[0], reverse=True)
        group = [base] + [x[1] for x in scored[:max_group - 1]]
        if len(group) < min_group:
            continue
        ids = sorted(p.get("proposal_id", "") for p in group)
        key = tuple(ids)
        if key in used_keys:
            continue
        used_keys.add(key)
        shared_terms = sorted(set.intersection(*[_tokens(_proposal_text(p)) for p in group]) if group else set())
        if not shared_terms:
            shared_terms = sorted(shared_all)[:8]
        if not shared_terms:
            continue
        categories = [p.get("category", "general") or "general" for p in group]
        category = max(set(categories), key=categories.count)
        title_terms = ", ".join(shared_terms[:3])
        title = f"Fuse {len(group)} proposals around {title_terms}"
        rationale = (
            f"These proposals share terms {shared_terms[:8]} and may be stronger as "
            "one evidence-backed proposal instead of separate weak items."
        )
        confidence = min(0.9, 0.45 + 0.15 * len(group) + 0.03 * len(shared_terms))
        candidates.append(FusionCandidate(ids, title, rationale, shared_terms[:10], category, round(confidence, 2)))

    candidates.sort(key=lambda c: (-c.confidence, c.title))
    return [c.to_dict() for c in candidates]


def load_active_proposals(limit: int = 100) -> list[dict]:
    from proposal_lifecycle_manager import get_proposal, list_proposals
    proposals = []
    for status in sorted(FUSABLE_STATUSES):
        for p in list_proposals(status=status, limit=limit):
            proposals.append(get_proposal(p["proposal_id"]) or p)
    return proposals[:limit]


def create_fusion_proposal(candidate: dict, dry_run: bool = True) -> dict:
    """Create a new fused proposal from a candidate when explicitly requested."""
    if dry_run:
        return {"success": True, "dry_run": True, "candidate": candidate}

    from proposal_lifecycle_manager import create_proposal, attach_evidence
    source_ids = candidate.get("source_ids", [])
    import hashlib
    id_hash = hashlib.md5(",".join(sorted(source_ids)).encode()).hexdigest()[:12]
    proposal_id = f"fusion_{id_hash}"
    result = create_proposal(
        proposal_id=proposal_id,
        title=candidate.get("title", "Fused proposal")[:200],
        summary=candidate.get("rationale", ""),
        category=candidate.get("suggested_category", "fusion"),
        source_type="proposal_fusion",
        priority="P1",
        target_module="proposal_fusion",
        change_description=candidate.get("rationale", ""),
        initial_status="draft",
        created_by="proposal_fusion",
    )
    if result.get("success"):
        attach_evidence(proposal_id, "fusion_sources", ",".join(source_ids), candidate.get("rationale", ""))
    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Find proposal fusion candidates")
    parser.add_argument("--apply", action="store_true", help="Create fused proposal candidates")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    candidates = find_fusion_candidates(load_active_proposals(limit=args.limit))
    print(f"fusion_candidates={len(candidates)}")
    for c in candidates[:10]:
        print(f"{c['title']} confidence={c['confidence']} sources={','.join(c['source_ids'])}")
        print(f"  {c['rationale']}")
        if args.apply:
            print(f"  create: {create_fusion_proposal(c, dry_run=False)}")
