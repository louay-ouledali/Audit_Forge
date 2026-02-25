from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query

from backend.ai.llm_manager import llm_manager

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


# ── LLM Cache endpoints ──

@router.get("/cache/stats")
def get_cache_stats():
    """Return cache statistics (total entries, total hits)."""
    return llm_manager.get_cache_stats()


@router.delete("/cache")
def clear_cache(task: Optional[str] = Query(None, description="Only clear entries for this task")):
    """Clear LLM response cache (all or filtered by task)."""
    deleted = llm_manager.clear_cache(task=task)
    return {"deleted": deleted, "task": task}
