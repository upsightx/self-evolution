#!/usr/bin/env python3
"""
Proposal Bridge — external-learning evidence → self-evolution candidates.

Responsibilities:
- Treat external-learning output as evidence first, not as proposals.
- Write curated evidence into X-Memory through memory_governor.
- Derive actionable proposal candidates only when target module and success metric are clear.
- Attach related evidence to existing proposals instead of creating duplicates.

Canonical flow: learning item → X-Memory evidence → hypothesis/candidate → proposal_lifecycle_manager.
"""
from __future__ import annotations

import sys
import json
from datetime import datetime

from bootstrap import ensure_workspace_on_path, ensure_xmemory_on_path, module_dir, module_workspace

# Shared bootstrap keeps path resolution consistent across modules.
_workspace = ensure_workspace_on_path()
_modules = module_dir()
ensure_xmemory_on_path()


def process_learning_items(items: list[dict]) -> dict:
    """Ingest learning output as evidence, then derive proposals only when actionable.

    Contract:
    - X-Memory stores external-learning facts/evidence.
    - proposal_lifecycle_manager stores only actionable proposals.
    - This bridge never treats one learning item as one proposal by default.
    """
    results = []
    evidence_count = 0
    proposals_created = 0
    attached = 0
    skipped = 0

    for item in items:
        evidence = _record_evidence(item)
        results.append(evidence)
        if not evidence.get("success"):
            skipped += 1
            continue
        evidence_count += 1

        candidate = _derive_proposal_candidate(item, evidence)
        if not candidate.get("actionable"):
            skipped += 1
            results.append({
                "id": evidence["id"],
                "action": "proposal_skipped",
                "success": True,
                "message": candidate.get("reason", "No actionable proposal derived"),
            })
            continue

        proposal = _upsert_proposal_candidate(candidate, evidence)
        results.append(proposal)
        if proposal.get("action") == "created_proposal" and proposal.get("success"):
            proposals_created += 1
        elif proposal.get("action") == "attached_evidence" and proposal.get("success"):
            attached += 1
        else:
            skipped += 1

    auto_triggered = False
    if proposals_created > 0:
        auto_triggered = _trigger_auto_evolve()

    summary = {
        "processed": len(items),
        "evidence_recorded": evidence_count,
        "proposals_created": proposals_created,
        "evidence_attached": attached,
        "skipped": skipped,
        "results": results,
        "orchestrator_triggered": auto_triggered,
    }
    print(f"[proposal_bridge] Processed {len(items)} items: evidence={evidence_count}, "
          f"proposals={proposals_created}, attached={attached}, skipped={skipped}")
    return summary


def process_learning_note(note: dict) -> dict:
    """Process a single learning item. Convenience wrapper."""
    result = process_learning_items([note])
    return result["results"][0] if result["results"] else {"success": False, "message": "No items"}


def _item_id(item: dict) -> str:
    base = item.get("id") or item.get("proposal_id") or item.get("url") or item.get("title") or datetime.now().isoformat()
    import hashlib
    return "learn_" + hashlib.sha1(str(base).encode("utf-8")).hexdigest()[:16]


def _summary(item: dict) -> str:
    return (item.get("reader_summary") or item.get("summary") or item.get("description") or item.get("title") or "")[:1200]


def _record_evidence(item: dict) -> dict:
    """Write final learning item to X-Memory as governed evidence."""
    item_id = _item_id(item)
    title = item.get("title") or item.get("summary") or item_id
    evidence_payload = {
        "schema": "external_learning_evidence.v1",
        "id": item_id,
        "url": item.get("url"),
        "github_url": item.get("github_url"),
        "source": item.get("source"),
        "published": item.get("published"),
        "screen_score": item.get("screen_score"),
        "screen_reason": item.get("screen_reason"),
        "reader_score": item.get("reader_score"),
        "reader_summary": item.get("reader_summary"),
        "reader_rationale": item.get("reader_rationale"),
        "reader_content_source": item.get("reader_content_source") or item.get("content_source"),
        "reader_content_cache_path": item.get("reader_content_cache_path") or item.get("content_cache_path"),
        "final_score": item.get("final_score"),
        "final_decision": item.get("final_decision") or item.get("decision"),
        "final_rationale": item.get("final_rationale") or item.get("rationale"),
    }
    facts = [x for x in [
        f"final_score={evidence_payload['final_score']}",
        f"reader_score={evidence_payload['reader_score']}",
        f"content_source={evidence_payload['reader_content_source']}",
        f"url={evidence_payload['url']}",
    ] if not x.endswith("=None")]
    concepts = _infer_concepts(item)
    try:
        from memory_governor import add_observation as gov_add
        result = gov_add(
            type="external_learning_evidence",
            title=f"[External Learning Evidence] {title[:100]}",
            narrative=json.dumps(evidence_payload, ensure_ascii=False, default=str),
            facts=facts,
            concepts=concepts,
            source="external_learning",
            verified=True,
            tags=["learning", "evidence"] + concepts[:5],
            task_type="external_learning",
            origin_module="external_learning_evidence_bridge",
            origin_ref=item_id,
        )
        return {
            "id": item_id,
            "action": "recorded_evidence" if result.get("action") == "created" else result.get("action", "recorded_evidence"),
            "success": result.get("success", False),
            "observation_id": result.get("observation_id"),
            "message": result.get("message", ""),
            "evidence_ref": f"observation:{result.get('observation_id')}",
        }
    except Exception as e:
        return {"id": item_id, "action": "record_evidence_failed", "success": False, "message": str(e)}


def _infer_concepts(item: dict) -> list[str]:
    text = " ".join(str(item.get(k, "")) for k in ["title", "description", "reader_summary", "final_rationale", "screen_reason"]).lower()
    concepts = []
    rules = [
        ("agent_rules", ["rule", "guardrail", "negative constraint", "do not", "规则"]),
        ("benchmark_driven", ["benchmark", "swe-bench", "terminal-bench", "评测"]),
        ("coding_agent", ["coding agent", "代码代理", "agent"]),
        ("memory_architecture", ["memory", "记忆"]),
        ("prompt_governance", ["prompt", "context priming", "提示"]),
    ]
    for concept, needles in rules:
        if any(n in text for n in needles):
            concepts.append(concept)
    return concepts or ["external_learning"]


def _derive_proposal_candidate(item: dict, evidence: dict) -> dict:
    """Convert evidence into an actionable proposal candidate only when target and metric are clear."""
    final_score = float(item.get("final_score") or item.get("score") or 0)
    reader_score = float(item.get("reader_score") or 0)
    text = " ".join(str(item.get(k, "")) for k in ["title", "description", "reader_summary", "final_rationale", "screen_reason"])
    low = text.lower()

    if max(final_score, reader_score) < 8.5:
        return {"actionable": False, "reason": "Evidence score below proposal threshold"}

    if any(x in low for x in ["rule", "guardrail", "context priming", "do not", "规则", "负向约束"]):
        return {
            "actionable": True,
            "proposal_key": "prompt_guardrail_audit",
            "title": "Audit agent rule files toward tested guardrails",
            "summary": "External evidence suggests coding-agent rules work mainly as context priming; negative guardrails outperform broad positive guidance.",
            "priority": "P1",
            "target_module": "agent_instructions",
            "target_scope": "AGENTS.md",
            "change_description": "Audit AGENTS/SKILL guidance: reduce vague positive advice, preserve tested do-not guardrails, and add regression checks for rule changes.",
            "hypothesis": "Replacing vague positive guidance with explicit guardrails will improve agent reliability and reduce instruction drift.",
            "success_metric": "Instruction audit completed with residue scan and at least one regression prompt/check covering guardrail behavior.",
        }

    if any(x in low for x in ["benchmark", "swe-bench", "terminal-bench", "benchmark-driven", "评测"]):
        return {
            "actionable": True,
            "proposal_key": "benchmark_driven_regression",
            "title": "Add benchmark-driven regression loop for evolution changes",
            "summary": "External evidence supports using benchmarks as the target function for agent migration and system evolution.",
            "priority": "P1",
            "target_module": "self_evolution",
            "target_scope": "modules",
            "change_description": "Define a lightweight regression suite for self-evolution/external-learning changes before automatic proposal advancement.",
            "hypothesis": "Benchmark-driven validation will catch broken bridges, JSON failures, and routing regressions earlier than manual inspection.",
            "success_metric": "A repeatable regression command covers evidence ingestion, proposal routing, and one real content-fetch path.",
        }

    return {"actionable": False, "reason": "No clear target module and success metric"}


def _upsert_proposal_candidate(candidate: dict, evidence: dict) -> dict:
    """Create one proposal per proposal_key, or attach new evidence to the existing proposal."""
    proposal_id = f"ext_{candidate['proposal_key']}"
    evidence_ref = evidence.get("evidence_ref") or evidence.get("id")
    description = json.dumps({
        "evidence_id": evidence.get("id"),
        "observation_id": evidence.get("observation_id"),
        "hypothesis": candidate.get("hypothesis"),
        "success_metric": candidate.get("success_metric"),
    }, ensure_ascii=False)
    try:
        from proposal_lifecycle_manager import create_proposal, get_proposal, attach_evidence
        existing = get_proposal(proposal_id)
        if existing:
            attached = attach_evidence(proposal_id, "external_learning_evidence", str(evidence_ref), description)
            attached.update({"id": evidence.get("id"), "action": "attached_evidence", "proposal_id": proposal_id})
            return attached

        result = create_proposal(
            proposal_id=proposal_id,
            title=candidate["title"],
            summary=candidate["summary"],
            category="external_learning_candidate",
            source_type="external_learning_evidence",
            source_ref=str(evidence_ref),
            priority=candidate.get("priority", "P1"),
            target_scope=candidate.get("target_scope", ""),
            target_module=candidate.get("target_module", ""),
            change_description=candidate.get("change_description", ""),
            initial_status="draft",
            evidence=[{
                "type": "external_learning_evidence",
                "ref": str(evidence_ref),
                "description": description,
            }],
        )
        result.update({"id": evidence.get("id"), "action": "created_proposal", "proposal_id": proposal_id})
        return result
    except Exception as e:
        return {"id": evidence.get("id"), "action": "proposal_failed", "success": False, "proposal_id": proposal_id, "message": str(e)}


def _trigger_auto_evolve() -> bool:
    """Advance proposals via orchestrator as the sole entry point."""
    try:
        from evolution_orchestrator import advance_proposals
        print("[proposal_bridge] advancing via orchestrator...")
        result = advance_proposals()
        if result["advanced"] > 0:
            print(f"[proposal_bridge] Orchestrator advanced {result['advanced']} proposals")
        return True
    except Exception as e:
        print(f"[proposal_bridge] orchestrator failed: {e}")
        return False


def scan_pending_observations() -> dict:
    """Scan external-learning evidence observations and route actionable candidates."""
    try:
        from db_common import get_db
        db = get_db()
        rows = db.execute("""
            SELECT o.id, o.title, o.narrative, o.tags, o.created_at
            FROM observations o
            LEFT JOIN memory_lineage l ON l.observation_id = o.id
            WHERE o.type = 'external_learning_evidence'
              AND o.source = 'external_learning'
              AND COALESCE(l.is_bridge_output, 0) = 0
            ORDER BY o.created_at DESC
            LIMIT 20
        """).fetchall()
        db.close()

        items = []
        for r in rows:
            try:
                meta = json.loads(r["narrative"]) if r["narrative"] else {}
            except (json.JSONDecodeError, TypeError):
                meta = {}
            meta.setdefault("id", f"obs_{r['id']}")
            meta.setdefault("title", r["title"])
            items.append(meta)

        if items:
            return process_learning_items(items)
        print("[proposal_bridge] No pending external learning evidence found")
        return {"processed": 0, "evidence_recorded": 0, "proposals_created": 0, "evidence_attached": 0, "skipped": 0, "results": [], "orchestrator_triggered": False}
    except Exception as e:
        print(f"[proposal_bridge] Scan failed: {e}")
        return {"processed": 0, "evidence_recorded": 0, "proposals_created": 0, "evidence_attached": 0, "skipped": 0, "results": [], "orchestrator_triggered": False}


# ============ CLI ============

def _cli():
    import argparse

    parser = argparse.ArgumentParser(description="Proposal Bridge: external-learning → self-evolution")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("scan", help="Scan pending observations and create proposals")

    p_process = sub.add_parser("process", help="Process a JSON file of learning items")
    p_process.add_argument("file", help="JSON file with learning items array")

    args = parser.parse_args()

    if args.command == "scan":
        result = scan_pending_observations()
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))

    elif args.command == "process":
        with open(args.file, "r", encoding="utf-8") as f:
            items = json.load(f)
        result = process_learning_items(items)
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))

    else:
        parser.print_help()


if __name__ == "__main__":
    _cli()
