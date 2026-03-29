"""Forge Copilot — API routes with agentic tool-calling loop."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.ai.copilot_prompts import COPILOT_SYSTEM, COPILOT_TOOL_RESULTS
from backend.ai.llm_manager import llm_manager
from backend.core.copilot_engine import run_copilot_pipeline
from backend.core.copilot_tools import (
    COPILOT_TOOLS,
    count_rules_handler,
    create_rules_batch_handler,
    edit_rules_batch_handler,
)
from backend.database import SessionLocal, get_db
from backend.models.benchmark import Benchmark
from backend.models.copilot_conversation import CopilotConversation
from backend.models.rule import Rule

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/copilot", tags=["copilot"])

# ── Schemas ──────────────────────────────────────────────────


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None


class ApproveRequest(BaseModel):
    rule_ids: list[int]
    action: str  # "approve" | "reject"


class ApproveWithEditsRequest(BaseModel):
    rule_id: int
    edits: dict[str, str]
    action: str = "approve"


class GenerateBenchmarkRequest(BaseModel):
    description: str
    platform: str | None = None
    platform_family: str | None = None


class BatchEditConfirmRequest(BaseModel):
    rule_ids: list[int]
    field_name: str
    new_value: str
    confirmed: bool = False


# ── Conversation Store (DB-backed) ───────────────────────────

_CONV_TTL = 30 * 60  # 30 minutes
_CONV_MAX_MESSAGES = 20


def _get_conversation(conv_id: str, db: Session) -> list[dict]:
    """Get conversation history from DB."""
    row = db.query(CopilotConversation).filter(
        CopilotConversation.conversation_id == conv_id,
    ).first()
    if not row:
        return []
    # Check TTL
    if row.updated_at:
        age = (datetime.now(timezone.utc) - row.updated_at.replace(tzinfo=timezone.utc)).total_seconds()
        if age > _CONV_TTL:
            db.delete(row)
            db.commit()
            return []
    try:
        return json.loads(row.messages_json or "[]")
    except (json.JSONDecodeError, TypeError):
        return []


def _save_message(conv_id: str, benchmark_id: int, role: str, content: str, db: Session):
    """Append a message to conversation history in DB."""
    row = db.query(CopilotConversation).filter(
        CopilotConversation.conversation_id == conv_id,
    ).first()
    if not row:
        row = CopilotConversation(
            conversation_id=conv_id,
            benchmark_id=benchmark_id,
            messages_json="[]",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(row)
        db.flush()

    try:
        msgs = json.loads(row.messages_json or "[]")
    except (json.JSONDecodeError, TypeError):
        msgs = []
    msgs.append({"role": role, "content": content})
    # Keep only last N messages
    if len(msgs) > _CONV_MAX_MESSAGES:
        msgs = msgs[-_CONV_MAX_MESSAGES:]
    row.messages_json = json.dumps(msgs)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()


def cleanup_expired_conversations():
    """Delete conversations older than TTL. Called from lifespan loop."""
    db = SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=_CONV_TTL)
        db.query(CopilotConversation).filter(
            CopilotConversation.updated_at < cutoff,
        ).delete(synchronize_session=False)
        db.commit()
    except Exception:
        logger.debug("Conversation cleanup error (non-fatal)")
    finally:
        db.close()


# ── Helpers ──────────────────────────────────────────────────


def _get_benchmark_or_404(benchmark_id: int, db: Session) -> Benchmark:
    bm = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not bm:
        raise HTTPException(status_code=404, detail="Benchmark not found")
    return bm


def _build_system_prompt(bm: Benchmark, db: Session, conv_history: list[dict]) -> str:
    """Build the LLM system prompt with context and conversation history."""
    rule_count = db.query(Rule).filter(Rule.benchmark_id == bm.id).count()
    prompt = COPILOT_SYSTEM.format(
        benchmark_name=bm.name,
        benchmark_id=bm.id,
        platform=bm.platform,
        platform_family=bm.platform_family,
        rule_count=rule_count,
    )
    if conv_history:
        prompt += "\n\n## Conversation so far:\n"
        for msg in conv_history[-10:]:
            role = msg["role"].upper()
            prompt += f"\n{role}: {msg['content'][:500]}\n"
    return prompt


async def _execute_tool(tool_name: str, params: dict, db: Session, benchmark_id: int) -> Any:
    """Execute a copilot tool by name with a 60s timeout."""
    tool = COPILOT_TOOLS.get(tool_name)
    if not tool:
        return {"error": f"Unknown tool: {tool_name}"}

    handler = tool["handler"]
    try:
        # All handlers take (db, benchmark_id, **params)
        if asyncio.iscoroutinefunction(handler):
            return await asyncio.wait_for(
                handler(db, benchmark_id, **params), timeout=60
            )
        else:
            return await asyncio.wait_for(
                asyncio.to_thread(handler, db, benchmark_id, **params), timeout=60
            )
    except asyncio.TimeoutError:
        logger.warning("Tool %s timed out after 60s", tool_name)
        return {"error": f"Tool {tool_name} timed out after 60 seconds"}
    except TypeError as e:
        logger.warning("Tool %s call failed: %s", tool_name, e)
        return {"error": f"Invalid parameters for {tool_name}: {str(e)}"}
    except Exception as e:
        logger.exception("Tool %s execution failed", tool_name)
        return {"error": f"Tool {tool_name} failed: {str(e)}"}


# ── LLM Response Validation ──────────────────────────────────


class ToolCallSchema(BaseModel):
    name: str
    params: dict[str, Any] = {}


class CopilotLLMResponse(BaseModel):
    tool_calls: list[ToolCallSchema] = []
    response: str = ""


def _validate_llm_response(raw: Any) -> CopilotLLMResponse:
    """Validate and normalize LLM response. Gracefully degrades on bad shape."""
    if isinstance(raw, str):
        return CopilotLLMResponse(response=raw)

    # Bare list (e.g. LLM returned [{"name": ...}] without wrapper) — treat as tool_calls
    if isinstance(raw, list):
        try:
            calls = [ToolCallSchema(**tc) for tc in raw if isinstance(tc, dict)]
            calls = [tc for tc in calls if tc.name in COPILOT_TOOLS]
            if calls:
                return CopilotLLMResponse(tool_calls=calls, response="")
        except Exception:
            pass
        # Unrecoverable list — return empty response (don't leak repr)
        return CopilotLLMResponse(response="")

    if not isinstance(raw, dict):
        # Never leak Python repr to user
        logger.warning("LLM returned unexpected type %s", type(raw).__name__)
        return CopilotLLMResponse(response="")

    try:
        resp = CopilotLLMResponse(**raw)
        # Filter out hallucinated tool names
        resp.tool_calls = [tc for tc in resp.tool_calls if tc.name in COPILOT_TOOLS]
        return resp
    except Exception:
        # Extract response text if present; never fall back to str(raw) which leaks internals
        return CopilotLLMResponse(response=raw.get("response", ""))


# ── Chat endpoint (agentic loop) ─────────────────────────────


@router.post("/{benchmark_id}/chat")
async def copilot_chat(
    benchmark_id: int,
    payload: ChatRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Main chat endpoint — agentic loop with LLM tool calling."""
    bm = _get_benchmark_or_404(benchmark_id, db)
    conv_id = payload.conversation_id or str(uuid.uuid4())

    # Get conversation history
    history = _get_conversation(conv_id, db)
    _save_message(conv_id, benchmark_id, "user", payload.message, db)

    # Build system prompt
    system_prompt = _build_system_prompt(bm, db, history)

    # Agentic loop: LLM → tools → LLM (max 5 iterations for multi-step workflows)
    all_actions: list[dict] = []
    response_text = ""
    max_iterations = 5

    user_prompt = payload.message

    for iteration in range(max_iterations):
        # LLM call with single retry
        llm_response = None
        for attempt in range(2):
            try:
                llm_response = await llm_manager.invoke_json(
                    user_prompt, system_prompt=system_prompt, task="copilot"
                )
                break
            except Exception as e:
                if attempt == 0:
                    logger.warning("LLM call failed (attempt 1), retrying: %s", e)
                    await asyncio.sleep(2)
                else:
                    logger.warning("LLM call failed (attempt 2): %s", e)

        if llm_response is None:
            # Context-aware fallback: try zero-LLM tools
            response_text = await _context_aware_fallback(payload.message, bm, db, benchmark_id, all_actions)
            break

        # Validate response shape
        parsed = _validate_llm_response(llm_response)

        # Keep the latest non-empty LLM response (don't overwrite good text with blank)
        if parsed.response.strip():
            response_text = parsed.response

        if not parsed.tool_calls:
            break

        # Execute tools
        tool_results = []
        for tc in parsed.tool_calls:
            name = tc.name
            params = tc.params
            logger.info("Copilot tool call: %s(%s)", name, json.dumps(params, default=str)[:200])

            result = await _execute_tool(name, params, db, benchmark_id)
            tool_results.append({
                "tool": name,
                "params": params,
                "result": result,
            })
            all_actions.append({"tool": name, "params": params, "result": result})

        # If this is the last iteration, don't call LLM again
        if iteration >= max_iterations - 1:
            break

        # Feed tool results back to LLM for a human-readable response
        results_text = json.dumps(tool_results, default=str, indent=2)[:4000]
        user_prompt = COPILOT_TOOL_RESULTS.format(tool_results=results_text)

    # Guard: if response_text is still empty after the loop, synthesize from tool results
    if not response_text.strip() and all_actions:
        response_text = _synthesize_response_from_actions(all_actions)
    elif not response_text.strip():
        response_text = (
            f"I'm Forge Copilot for benchmark **{bm.name}**. "
            f"How can I help you with your {bm.platform} rules?"
        )

    # Save copilot response to conversation
    _save_message(conv_id, benchmark_id, "copilot", response_text, db)

    # Get current pending rules
    pending = (
        db.query(Rule)
        .filter(Rule.benchmark_id == benchmark_id, Rule.pending_review == True)
        .all()
    )
    pending_rules = [
        {
            "id": r.id,
            "section_number": r.section_number,
            "title": r.title,
            "severity": r.severity,
            "confidence": r.copilot_confidence,
            "source_benchmark": r.copilot_source_benchmark,
        }
        for r in pending
    ]

    return {
        "response": response_text,
        "intent": "agentic",
        "actions": all_actions,
        "pending_rules": pending_rules,
        "conversation_id": conv_id,
    }


def _synthesize_response_from_actions(actions: list[dict]) -> str:
    """Build a readable response from tool results when LLM gives no text."""
    lines: list[str] = []
    for a in actions:
        tool = a.get("tool", "")
        result = a.get("result", {})
        if isinstance(result, dict) and "error" in result:
            lines.append(f"**{tool}**: {result['error']}")
        elif tool == "count_rules" and isinstance(result, dict):
            lines.append(
                f"**Rule count**: {result.get('total_rules', '?')} total, "
                f"{result.get('with_commands', '?')} with commands"
            )
        elif tool == "get_pipeline_status" and isinstance(result, dict):
            p1 = result.get("phase1_status", "?")
            p2 = result.get("phase2_status", "?")
            p3 = result.get("phase3_status", "?")
            lines.append(f"**Pipeline**: Phase 1={p1}, Phase 2={p2}, Phase 3={p3}")
        elif tool == "list_rules" and isinstance(result, list):
            lines.append(f"Found **{len(result)}** rule(s).")
            for r in result[:5]:
                if isinstance(r, dict):
                    lines.append(f"- {r.get('section_number', '?')} — {r.get('title', '?')} ({r.get('severity', '?')})")
            if len(result) > 5:
                lines.append(f"  ...and {len(result) - 5} more")
        elif tool == "search_rules" and isinstance(result, list):
            lines.append(f"Found **{len(result)}** matching rule(s).")
            for r in result[:5]:
                if isinstance(r, dict):
                    lines.append(f"- {r.get('section_number', '?')} — {r.get('title', '?')}")
        elif tool == "get_rule_details" and isinstance(result, dict) and "id" in result:
            lines.append(
                f"**{result.get('section_number', '?')}** — {result.get('title', '?')}\n"
                f"  Severity: {result.get('severity', '?')}, Source: {result.get('source', '?')}"
            )
            cmd = result.get("command")
            if isinstance(cmd, dict):
                lines.append(f"  Command: `{(cmd.get('audit_command') or '')[:120]}`")
        elif isinstance(result, dict):
            # Generic dict — show key fields
            summary = ", ".join(f"{k}={v}" for k, v in list(result.items())[:4])
            lines.append(f"**{tool}**: {summary}")
        elif isinstance(result, list):
            lines.append(f"**{tool}**: {len(result)} result(s)")
        else:
            lines.append(f"**{tool}**: completed")
    return "\n".join(lines) if lines else "I processed your request but have no details to show."


async def _context_aware_fallback(
    message: str, bm: Benchmark, db: Session, benchmark_id: int, all_actions: list[dict],
) -> str:
    """When LLM is unavailable, try zero-LLM tools via intent routing."""
    from backend.core.copilot_engine import route_intent
    from backend.core.copilot_tools import (
        count_rules_handler as _count,
        get_pipeline_status_handler as _pipeline,
        search_rules_handler as _search,
        suggest_gaps_handler as _gaps,
    )

    intent = route_intent(message, {"benchmark_name": bm.name, "platform": bm.platform})

    try:
        if intent.name == "search_rules":
            query = intent.entities.get("extracted", message)
            result = _search(db, benchmark_id, query=query)
            if result:
                lines = [f"Found {len(result)} rule(s) (LLM offline, showing DB results):"]
                for r in result[:5]:
                    lines.append(f"- **{r['section_number']}** {r['title']} ({r['severity']})")
                all_actions.append({"tool": "search_rules", "params": {"query": query}, "result": result})
                return "\n".join(lines)

        elif intent.name == "suggest_gaps":
            result = _gaps(db, benchmark_id)
            gaps = result.get("missing_categories", [])
            if gaps:
                return f"Coverage analysis ({result.get('coverage_percentage', '?')}% covered). Missing: {', '.join(g.replace('_', ' ') for g in gaps)}"
            return f"Good coverage — no obvious gaps found ({result.get('coverage_percentage', 100)}% covered)."

        elif intent.name in ("create_benchmark", "add_rules"):
            result = _count(db, benchmark_id)
            return (
                f"Benchmark **{bm.name}** has {result['total_rules']} rules "
                f"({result['with_commands']} with commands). "
                f"LLM is currently unavailable for rule creation — please try again shortly."
            )
    except Exception:
        pass

    # Generic fallback
    return (
        f"I'm Forge Copilot, your assistant for benchmark **{bm.name}**. "
        f"The AI model is currently unavailable, but I can still help with:\n"
        f"- **Search** existing rules across all benchmarks\n"
        f"- **Check pipeline status** and migration readiness\n"
        f"- **Analyze coverage gaps** in your benchmark\n"
        f"- **Count rules** and see severity breakdown\n\n"
        f"What would you like to do?"
    )


# ── Generate benchmark (full pipeline) ──────────────────────


@router.post("/{benchmark_id}/generate-benchmark")
async def generate_benchmark_rules(
    benchmark_id: int,
    payload: GenerateBenchmarkRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Trigger the full multi-agent rule generation pipeline."""
    bm = _get_benchmark_or_404(benchmark_id, db)

    platform = payload.platform or bm.platform
    platform_family = payload.platform_family or bm.platform_family

    result = await run_copilot_pipeline(
        benchmark_id=benchmark_id,
        description=payload.description,
        platform=platform,
        platform_family=platform_family,
        db=db,
    )

    # Auto-create pending rules from pipeline output
    pending_rules = result.get("pending_rules", [])
    if pending_rules:
        batch_result = create_rules_batch_handler(
            db, benchmark_id, rules=pending_rules
        )
        result["created"] = batch_result
        # Update total_rules
        bm.total_rules = db.query(Rule).filter(
            Rule.benchmark_id == benchmark_id
        ).count()
        db.commit()

    return result


# ── Approval endpoints ───────────────────────────────────────


@router.post("/{benchmark_id}/approve")
def approve_rules(
    benchmark_id: int,
    payload: ApproveRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Approve or reject pending rules."""
    bm = _get_benchmark_or_404(benchmark_id, db)

    rules = (
        db.query(Rule)
        .filter(
            Rule.id.in_(payload.rule_ids),
            Rule.benchmark_id == benchmark_id,
            Rule.pending_review == True,
        )
        .all()
    )

    if not rules:
        raise HTTPException(status_code=404, detail="No pending rules found with those IDs")

    if payload.action == "approve":
        for rule in rules:
            rule.pending_review = False
        db.commit()
        # Update total_rules count
        bm.total_rules = db.query(Rule).filter(
            Rule.benchmark_id == benchmark_id, Rule.pending_review == False
        ).count()
        db.commit()
        return {"approved": len(rules)}

    elif payload.action == "reject":
        for rule in rules:
            db.query(Rule).filter(Rule.id == rule.id).delete()
        db.commit()
        bm.total_rules = db.query(Rule).filter(
            Rule.benchmark_id == benchmark_id, Rule.pending_review == False
        ).count()
        db.commit()
        return {"rejected": len(rules)}

    raise HTTPException(status_code=400, detail="Action must be 'approve' or 'reject'")


@router.post("/{benchmark_id}/approve-with-edits")
def approve_with_edits(
    benchmark_id: int,
    payload: ApproveWithEditsRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Apply edits and approve a pending rule in one step."""
    bm = _get_benchmark_or_404(benchmark_id, db)

    rule = (
        db.query(Rule)
        .filter(
            Rule.id == payload.rule_id,
            Rule.benchmark_id == benchmark_id,
            Rule.pending_review == True,
        )
        .first()
    )
    if not rule:
        raise HTTPException(status_code=404, detail="Pending rule not found")

    # Apply edits
    for field_name, value in payload.edits.items():
        if hasattr(rule, field_name) and field_name in ("title", "description", "severity", "section_number"):
            setattr(rule, field_name, value)

    rule.pending_review = False
    db.commit()
    bm.total_rules = db.query(Rule).filter(
        Rule.benchmark_id == benchmark_id, Rule.pending_review == False
    ).count()
    db.commit()
    return {"approved": True, "rule_id": rule.id, "edits_applied": list(payload.edits.keys())}


# ── Pending rules listing ────────────────────────────────────


@router.get("/{benchmark_id}/pending")
def get_pending_rules(
    benchmark_id: int,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Get all pending review rules for a benchmark."""
    _get_benchmark_or_404(benchmark_id, db)

    rules = (
        db.query(Rule)
        .filter(Rule.benchmark_id == benchmark_id, Rule.pending_review == True)
        .order_by(Rule.section_number)
        .all()
    )

    return {
        "count": len(rules),
        "rules": [
            {
                "id": r.id,
                "section_number": r.section_number,
                "title": r.title,
                "description": (r.description or "")[:300],
                "severity": r.severity,
                "source": r.source,
                "confidence": r.copilot_confidence,
                "source_benchmark": r.copilot_source_benchmark,
            }
            for r in rules
        ],
    }


# ── Batch edit confirm ───────────────────────────────────────


@router.post("/{benchmark_id}/confirm-batch-edit")
def confirm_batch_edit(
    benchmark_id: int,
    payload: BatchEditConfirmRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Preview or confirm a batch edit."""
    _get_benchmark_or_404(benchmark_id, db)
    return edit_rules_batch_handler(
        db,
        benchmark_id,
        rule_ids=payload.rule_ids,
        field_name=payload.field_name,
        new_value=payload.new_value,
        confirmed=payload.confirmed,
    )
