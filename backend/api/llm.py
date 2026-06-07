from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Query
from sqlalchemy import func

from backend.ai.llm_manager import LLMManager, llm_manager
from backend.database import SessionLocal
from backend.models.app_settings import AppSettings
from backend.models.token_usage import TokenUsage

router = APIRouter(prefix="/llm", tags=["llm"])


@router.get("/status")
async def get_llm_status():
    result = await llm_manager.check_availability()
    return result


@router.post("/test")
async def test_llm():
    import time
    try:
        start = time.time()
        response = await llm_manager.invoke("Say 'Hello! I am working correctly.' in exactly those words.")
        elapsed = int((time.time() - start) * 1000)
        config = llm_manager.get_current_config()
        return {
            "success": True,
            "response": response,
            "response_time_ms": elapsed,
            "model": config.get("offline_model") if config["mode"] == "offline" else config.get("online_model"),
        }
    except Exception as exc:
        return {"success": False, "error": str(exc), "response": None, "response_time_ms": 0}


# LLM Cache endpoints

@router.get("/cache/stats")
def get_cache_stats():
    """Return cache statistics (total entries, total hits)."""
    return llm_manager.get_cache_stats()


@router.delete("/cache")
def clear_cache(task: Optional[str] = Query(None, description="Only clear entries for this task")):
    """Clear LLM response cache (all or filtered by task)."""
    deleted = llm_manager.clear_cache(task=task)
    return {"deleted": deleted, "task": task}


# Model listing

@router.get("/models")
async def list_available_models():
    """Fetch available models from the configured LLM provider."""
    config = llm_manager.get_current_config()
    try:
        if config["mode"] == "offline":
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{config['ollama_url']}/api/tags")
                resp.raise_for_status()
                models = [m.get("name", "") for m in resp.json().get("models", [])]
                return {"models": sorted(models)}
        else:
            provider = config.get("online_provider", "")
            base_url = config.get("online_base_url", "").strip()
            if not base_url:
                base_url = LLMManager.PROVIDER_BASE_URLS.get(provider, "")
            api_key = config.get("online_api_key", "")

            if not api_key:
                return {"models": [], "error": "No API key configured"}

            async with httpx.AsyncClient(timeout=15.0) as client:
                if provider == "anthropic":
                    headers = {
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                    }
                    resp = await client.get(f"{base_url}/models", headers=headers)
                else:
                    headers = {"Authorization": f"Bearer {api_key}"}
                    resp = await client.get(f"{base_url}/models", headers=headers)

                resp.raise_for_status()
                data = resp.json()
                models = [m["id"] for m in data.get("data", []) if m.get("id")]
                return {"models": sorted(models)}
    except Exception as exc:
        return {"models": [], "error": str(exc)}


# Token usage tracking

@router.get("/token-usage")
def get_token_usage(period: str = Query("month", description="'month' or 'all'")):
    """Return aggregated token usage stats for the current billing period."""
    db = SessionLocal()
    try:
        # Determine time filter
        q = db.query(TokenUsage)
        if period == "month":
            now = datetime.now(timezone.utc)
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            q = q.filter(TokenUsage.timestamp >= month_start)

        # Totals
        totals = db.query(
            func.coalesce(func.sum(TokenUsage.input_tokens), 0),
            func.coalesce(func.sum(TokenUsage.output_tokens), 0),
            func.coalesce(func.sum(TokenUsage.total_tokens), 0),
        )
        if period == "month":
            now = datetime.now(timezone.utc)
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            totals = totals.filter(TokenUsage.timestamp >= month_start)
        row = totals.one()
        total_input, total_output, total_tokens = row

        # By provider
        by_provider_q = db.query(
            TokenUsage.provider,
            func.sum(TokenUsage.total_tokens),
        ).group_by(TokenUsage.provider)
        if period == "month":
            by_provider_q = by_provider_q.filter(TokenUsage.timestamp >= month_start)
        by_provider = [
            {"provider": p, "total_tokens": int(t)}
            for p, t in by_provider_q.all()
        ]

        # By task
        by_task_q = db.query(
            TokenUsage.task,
            func.sum(TokenUsage.total_tokens),
        ).group_by(TokenUsage.task)
        if period == "month":
            by_task_q = by_task_q.filter(TokenUsage.timestamp >= month_start)
        by_task = [
            {"task": t or "other", "total_tokens": int(tk)}
            for t, tk in by_task_q.all()
        ]

        # Budget info
        budget_row = db.query(AppSettings).filter(AppSettings.key == "llm_token_budget").first()
        budget = int(budget_row.value) if budget_row and budget_row.value else 0

        return {
            "total_input": int(total_input),
            "total_output": int(total_output),
            "total_tokens": int(total_tokens),
            "by_provider": by_provider,
            "by_task": by_task,
            "budget": budget,
            "budget_remaining": max(0, budget - int(total_tokens)) if budget > 0 else None,
            "period": period,
        }
    finally:
        db.close()


@router.delete("/token-usage")
def reset_token_usage():
    """Clear all token usage records."""
    db = SessionLocal()
    try:
        deleted = db.query(TokenUsage).delete()
        db.commit()
        return {"deleted": deleted}
    except Exception:
        db.rollback()
        return {"deleted": 0}
    finally:
        db.close()
