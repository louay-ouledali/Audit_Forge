"""Forge Copilot — API routes with agentic tool-calling loop."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.ai.copilot_prompts import COPILOT_SYSTEM, COPILOT_TOOL_RESULTS, COPILOT_QUALITY_ANALYSIS
from backend.ai.llm_manager import llm_manager
from backend.ai.prompt_sanitizer import sanitize_field, sanitize_chat_message
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

# Schemas


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


# Conversation Store (DB-backed)

_CONV_TTL = 120 * 60  # 2 hours
_CONV_MAX_MESSAGES = 50


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


# Helpers


def _get_benchmark_or_404(benchmark_id: int, db: Session) -> Benchmark:
    bm = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not bm:
        raise HTTPException(status_code=404, detail="Benchmark not found")
    return bm


def _build_system_prompt(bm: Benchmark, db: Session) -> str:
    """Build the LLM system prompt with benchmark context (no conversation history)."""
    rule_count = db.query(Rule).filter(Rule.benchmark_id == bm.id).count()
    return COPILOT_SYSTEM.format(
        benchmark_name=sanitize_field(bm.name or "", max_length=200),
        benchmark_id=bm.id,
        platform=sanitize_field(bm.platform or "", max_length=100),
        platform_family=sanitize_field(bm.platform_family or "", max_length=100),
        rule_count=rule_count,
    )


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


# LLM Response Validation


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
        # Hallucination guard: reject fabricated verification tables
        if (not resp.tool_calls and '|' in resp.response
                and any(w in resp.response.lower() for w in ('verified', '✅', '✓', 'pass |', 'correct |'))):
            logger.warning("Hallucination guard: LLM fabricated verification table without tool calls")
            resp.response = ""
        return resp
    except Exception:
        # Extract response text if present; never fall back to str(raw) which leaks internals
        return CopilotLLMResponse(response=raw.get("response", ""))


# Chat endpoint (agentic loop)


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

    # Build system prompt (without conversation — those go as proper messages)
    system_prompt = _build_system_prompt(bm, db)

    all_actions: list[dict] = []
    response_text = ""

    # Phase 1: Check for forced workflows (anti-hallucination)
    forced = await _detect_forced_workflow(payload.message, bm, db, benchmark_id, system_prompt, history)
    if forced is not None:
        all_actions = forced["actions"]
        response_text = forced["response"]
    else:
        # Agentic loop: LLM -> tools -> LLM (max 5 iterations)
        max_iterations = 5
        user_prompt = sanitize_chat_message(payload.message)

        for iteration in range(max_iterations):
            # Build multi-turn messages
            chat_messages = [{"role": "system", "content": system_prompt}]
            for msg in history[-15:]:
                role = "assistant" if msg["role"] == "copilot" else msg["role"]
                chat_messages.append({"role": role, "content": msg["content"][:2000]})
            chat_messages.append({"role": "user", "content": user_prompt})

            # LLM call with single retry
            llm_response = None
            for attempt in range(2):
                try:
                    llm_response = await llm_manager.invoke_json_with_history(
                        chat_messages, task="copilot"
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
        # Always reference the user's actual message, not just generic greeting
        user_msg = payload.message[:100]
        response_text = (
            f"I had trouble processing your request: *\"{user_msg}\"*. "
            f"Could you rephrase that? I can help with reviewing commands, "
            f"editing rules, running pipeline operations, and more."
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


# Forced Workflows (anti-hallucination)

_FORCED_WORKFLOW_PATTERNS: list[tuple[str, str, list[str]]] = [
    # (name, regex_pattern, tool_names_to_force)
    (
        "command_review",
        r"(?:check|review|verify|inspect|audit|validate|are.*correct|quality).*(?:command|cmd|script|audit)",
        ["deep_quality_check"],
    ),
    (
        "command_review_alt",
        r"(?:command|cmd|script|audit).*(?:check|review|verify|correct|quality|good|bad|wrong)",
        ["deep_quality_check"],
    ),
    (
        "fix_commands",
        r"(?:fix|repair|correct|heal|regenerate).*(?:command|cmd|broken|error|bad)",
        ["deep_quality_check"],
    ),
    (
        "improve_descriptions",
        r"(?:improve|enhance|lengthen|expand|rewrite|update|better|more\s+(?:detail|length|verbose)).*(?:description|desc)",
        ["_workflow_improve_descriptions"],
    ),
    (
        "improve_descriptions_alt",
        r"(?:description|desc).*(?:poor|short|bad|brief|lacking|improve|better|more|length|detail)",
        ["_workflow_improve_descriptions"],
    ),
]


async def _detect_forced_workflow(
    message: str, bm: Benchmark, db: Session, benchmark_id: int, system_prompt: str,
    history: list[dict] | None = None,
) -> dict[str, Any] | None:
    """Check if the user message matches a forced-workflow pattern.

    If matched, executes the required tools server-side and formats the
    results via the LLM (or falls back to synthesis).  Returns None if
    no pattern matches (agentic loop should run instead).
    """
    msg_lower = message.lower()
    matched_name = None
    matched_tools: list[str] = []

    for name, pattern, tools in _FORCED_WORKFLOW_PATTERNS:
        if re.search(pattern, msg_lower):
            matched_name = name
            matched_tools = tools
            break

    if not matched_name:
        return None

    logger.info("Forced workflow matched: %s (tools=%s)", matched_name, matched_tools)

    all_actions: list[dict] = []
    tool_results: list[dict] = []

    for tool_name in matched_tools:
        # Check for special workflow functions
        if tool_name == "_workflow_improve_descriptions":
            return await _workflow_improve_descriptions(bm, db, benchmark_id, system_prompt)

        # Normal tool execution
        result = await _execute_tool(tool_name, {}, db, benchmark_id)
        entry = {"tool": tool_name, "params": {}, "result": result}
        tool_results.append(entry)
        all_actions.append(entry)

    # Ask LLM to format the results using conversation history for context
    results_text = json.dumps(tool_results, default=str, indent=2)[:6000]

    # Use the quality-specific prompt for quality checks
    if matched_name in ("command_review", "command_review_alt", "fix_commands"):
        format_prompt = COPILOT_QUALITY_ANALYSIS.format(
            benchmark_name=bm.name,
            platform=bm.platform,
            quality_results=results_text,
        )
    else:
        format_prompt = COPILOT_TOOL_RESULTS.format(tool_results=results_text)

    # Build multi-turn messages so LLM has conversation context
    chat_messages = [{"role": "system", "content": system_prompt}]
    if history:
        for msg in history[-10:]:
            role = "assistant" if msg["role"] == "copilot" else msg["role"]
            chat_messages.append({"role": role, "content": msg["content"][:2000]})
    chat_messages.append({"role": "user", "content": format_prompt})

    response_text = ""
    try:
        llm_result = await llm_manager.invoke_json_with_history(
            chat_messages, task="copilot"
        )
        parsed = _validate_llm_response(llm_result)
        response_text = parsed.response
    except Exception as e:
        logger.warning("LLM formatting failed for forced workflow: %s", e)

    if not response_text.strip():
        response_text = _synthesize_response_from_actions(all_actions)

    return {"actions": all_actions, "response": response_text}


async def _workflow_improve_descriptions(
    bm: Benchmark, db: Session, benchmark_id: int, system_prompt: str,
) -> dict[str, Any]:
    """Forced workflow: find rules with short descriptions and generate improved ones."""
    from backend.core.copilot_tools import list_rules_handler

    result = list_rules_handler(db, benchmark_id, limit=200)
    rules = result.get("rules", []) if isinstance(result, dict) else []

    short_rules = [
        r for r in rules
        if isinstance(r, dict) and len(r.get("description", "") or "") < 100
    ]

    if not short_rules:
        return {
            "actions": [{"tool": "list_rules", "params": {}, "result": {"total": len(rules)}}],
            "response": f"All {len(rules)} rules already have adequate descriptions (100+ characters each). "
                        "If you'd like me to rewrite specific rules, tell me which section numbers.",
        }

    # Generate improved descriptions via LLM (batches of 15)
    batch_size = 15
    improvements: list[dict] = []

    for batch_start in range(0, min(len(short_rules), 60), batch_size):
        batch = short_rules[batch_start:batch_start + batch_size]
        rules_text = "\n".join(
            f"- id={r['id']} | {r.get('section_number', '?')} | \"{r.get('title', '')}\" | "
            f"current_desc=\"{(r.get('description', '') or '')[:80]}\""
            for r in batch
        )
        gen_prompt = (
            f"Improve the descriptions for these {bm.platform} security audit rules. "
            f"Each description must be 1-3 sentences explaining: what the rule checks, "
            f"why it matters for security, and what a failing result means.\n\n"
            f"Rules:\n{rules_text}\n\n"
            f"Return JSON array: [{{\"id\": <rule_id>, \"description\": \"<improved>\"}}]"
        )
        try:
            gen_result = await llm_manager.invoke_json(gen_prompt, task="copilot")
            if isinstance(gen_result, list):
                improvements.extend(gen_result)
        except Exception as e:
            logger.warning("Description generation failed for batch: %s", e)

    if not improvements:
        return {
            "actions": [],
            "response": f"Found **{len(short_rules)}** rules with short descriptions but "
                        "the AI model couldn't generate improvements right now. Please try again.",
        }

    # Build a before/after preview
    rules_by_id = {r["id"]: r for r in short_rules}
    valid_improvements = []
    for imp in improvements:
        rid = imp.get("id")
        new_desc = imp.get("description", "")
        if rid in rules_by_id and new_desc and len(new_desc) > 20:
            valid_improvements.append({
                "rule_id": rid,
                "section": rules_by_id[rid].get("section_number", "?"),
                "title": rules_by_id[rid].get("title", "?"),
                "old_desc": (rules_by_id[rid].get("description", "") or "")[:60],
                "new_desc": new_desc,
            })

    if not valid_improvements:
        return {
            "actions": [],
            "response": "Couldn't generate valid improvements. Try asking me to improve specific rules by section number.",
        }

    lines = [
        f"Generated improved descriptions for **{len(valid_improvements)}** rules. "
        f"Here's a preview:\n",
        "| Section | Title | Before | After |",
        "|---------|-------|--------|-------|",
    ]
    for imp in valid_improvements[:15]:
        old = imp["old_desc"][:40] + ("..." if len(imp["old_desc"]) > 40 else "")
        new = imp["new_desc"][:60] + ("..." if len(imp["new_desc"]) > 60 else "")
        lines.append(f"| {imp['section']} | {imp['title'][:35]} | {old or '*(empty)*'} | {new} |")
    if len(valid_improvements) > 15:
        lines.append(f"| ... | *and {len(valid_improvements) - 15} more* | | |")

    lines.append("\nSay **\"apply\"** to apply these improvements, or **\"cancel\"** to discard them.")

    return {
        "actions": [
            {
                "tool": "_workflow_improve_descriptions",
                "params": {},
                "result": {
                    "preview_count": len(valid_improvements),
                    "improvements": valid_improvements,
                },
            }
        ],
        "response": "\n".join(lines),
    }


def _synthesize_response_from_actions(actions: list[dict]) -> str:
    """Build a readable response from tool results when LLM gives no text."""
    lines: list[str] = []
    for a in actions:
        tool = a.get("tool", "")
        result = a.get("result", {})
        if isinstance(result, dict) and "error" in result:
            lines.append(f"**{tool}**: {result['error']}")
        elif tool == "deep_quality_check" and isinstance(result, dict):
            total = result.get("total_analyzed", 0)
            ok = result.get("pass", 0)
            errs = result.get("errors", 0)
            warns = result.get("warnings", 0)
            missing = result.get("missing_commands", 0)
            summary = result.get("summary", "")
            lines.append("## Command Quality Report\n")
            lines.append(f"**{ok}/{total}** commands passed | **{errs}** errors | **{warns}** warnings")
            if missing:
                lines.append(f" | **{missing}** rules without commands")
            lines.append("")
            if summary:
                lines.append(f"**Summary**: {summary}\n")
            issues = result.get("issues", [])
            if issues:
                lines.append("### Issues Found\n")
                lines.append("| Section | Severity | Category | Message |")
                lines.append("|---------|----------|----------|---------|")
                for issue in issues[:20]:
                    sec = issue.get("section_number", "?")
                    sev = issue.get("severity", "?")
                    cat = issue.get("category", "?").replace("_", " ")
                    msg = issue.get("message", "?")[:60]
                    lines.append(f"| {sec} | {sev} | {cat} | {msg} |")
                if len(issues) > 20:
                    lines.append(f"\n*...and {len(issues) - 20} more issues*")
            low_conf = result.get("low_confidence", [])
            if low_conf:
                lines.append(f"\n### Low Confidence Commands ({len(low_conf)})\n")
                lines.append("These commands may be incorrect and need manual review:\n")
                for lc in low_conf[:10]:
                    lines.append(
                        f"- **{lc.get('section_number', '?')}** {lc.get('title', '')[:40]} "
                        f"- confidence: {lc.get('confidence_score', '?')} "
                        f"({lc.get('source', 'unknown')})"
                    )
            suggestions = result.get("review_suggestions", [])
            if suggestions:
                lines.append(f"\n### Suggestions ({len(suggestions)})\n")
                for s in suggestions[:10]:
                    lines.append(f"- **{s.get('section_number', '?')}**: {s.get('suggestion', '')}")
            samples = result.get("commands_sample", [])
            if samples and not issues:
                # Show command samples when there are no errors (so the report isn't empty)
                lines.append("\n### Command Samples\n")
                lines.append("| Section | Command | Expression | Confidence |")
                lines.append("|---------|---------|------------|------------|")
                for s in samples[:8]:
                    cmd_prev = (s.get("audit_command", "")[:50] + "...") if len(s.get("audit_command", "")) > 50 else s.get("audit_command", "")
                    expr = s.get("expected_output_regex", "-") or "-"
                    expr_prev = (expr[:30] + "...") if len(expr) > 30 else expr
                    lines.append(f"| {s.get('section_number', '?')} | `{cmd_prev}` | `{expr_prev}` | {s.get('confidence', '?')} |")
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


# Generate benchmark (full pipeline)


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


# Approval endpoints


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


# Pending rules listing


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


# Batch edit confirm


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
