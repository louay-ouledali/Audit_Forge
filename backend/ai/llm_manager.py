"""LLM Manager — unified interface for offline (Ollama) and online (OpenAI-compatible) LLM calls."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from backend.core.exceptions import LLMResponseError, LLMTimeoutError, LLMUnavailableError
from backend.config import settings as app_config
from backend.database import SessionLocal
from backend.models.app_settings import AppSettings
from backend.utils.encryption import decrypt_value

logger = logging.getLogger("auditforge.llm")

# Shared httpx client — reuses connection pool across all LLM calls
_shared_client: httpx.AsyncClient | None = None


def _get_shared_client() -> httpx.AsyncClient:
    """Return the module-level shared httpx.AsyncClient, creating it if needed."""
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        _shared_client = httpx.AsyncClient(
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            timeout=httpx.Timeout(120.0, connect=10.0),
        )
    return _shared_client

# LLM generation parameters — low temperature for deterministic structured output
LLM_TEMPERATURE = 0.1
LLM_MAX_TOKENS = 4096  # Default; overridden by llm_max_tokens setting

# Retry configuration
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0  # seconds — multiplied by attempt number for backoff


class LLMManager:
    """Single interface for all LLM operations."""

    # Known provider base URLs (OpenAI-compatible chat/completions endpoints)
    PROVIDER_BASE_URLS: dict[str, str] = {
        "openai": "https://api.openai.com/v1",
        "anthropic": "https://api.anthropic.com/v1",
        "mistral": "https://api.mistral.ai/v1",
        "groq": "https://api.groq.com/openai/v1",
        "openrouter": "https://openrouter.ai/api/v1",
    }

    # Task names for per-task model customization
    TASK_NAMES = ("phase1_parsing", "phase2_commands", "verification", "reports", "analysis", "copilot")

    def get_current_config(self, task: str | None = None) -> dict[str, str]:
        """Read LLM settings from the app_settings table.

        If *task* is provided (e.g. ``"phase2_commands"``), per-task model
        overrides are applied on top of the global config.

        Config is cached for 60 seconds to avoid repeated DB queries.
        """
        import time as _time
        cache_key = task or "__global__"
        now = _time.monotonic()
        if (hasattr(self, "_config_cache") and cache_key in self._config_cache
                and now - self._config_cache[cache_key][1] < 60):
            return self._config_cache[cache_key][0]

        db = SessionLocal()
        try:
            rows = db.query(AppSettings).all()
            cfg = {r.key: r.value for r in rows}
        finally:
            db.close()

        config = {
            "mode": cfg.get("llm_mode", "offline"),
            "offline_model": cfg.get("llm_offline_model", "qwen2.5:7b"),
            "ollama_url": cfg.get("llm_ollama_url", "http://host.docker.internal:11434"),
            "online_provider": cfg.get("llm_online_provider", ""),
            "online_api_key": cfg.get("llm_online_api_key_encrypted", ""),
            "online_model": cfg.get("llm_online_model", ""),
            "online_base_url": cfg.get("llm_online_base_url", ""),
            "category_detection": cfg.get("llm_category_detection", "true"),
        }

        # Decrypt the API key if it's encrypted
        if config["online_api_key"]:
            try:
                config["online_api_key"] = decrypt_value(
                    config["online_api_key"], app_config.effective_encryption_key
                )
            except Exception:
                pass  # Use raw value as fallback (pre-encryption data)

        # Apply per-task model override if configured
        if task and task in self.TASK_NAMES:
            task_model = cfg.get(f"llm_task_{task}_model", "").strip()
            if task_model:
                if config["mode"] == "offline":
                    config["offline_model"] = task_model
                else:
                    config["online_model"] = task_model

        # Store in cache
        if not hasattr(self, "_config_cache"):
            self._config_cache: dict[str, tuple[dict, float]] = {}
        self._config_cache[cache_key] = (config, now)

        return config

    async def invoke(
        self,
        prompt: str,
        system_prompt: str | None = None,
        timeout: float = 300.0,
        max_retries: int = MAX_RETRIES,
        json_mode: bool = False,
        task: str | None = None,
    ) -> str:
        """Send a prompt and get a text response with retry and exponential backoff.

        Checks the LLM response cache first. On cache hit, returns the cached
        response immediately (zero latency, zero API cost).
        """
        config = self.get_current_config(task=task)

        # Token budget enforcement
        remaining = self._check_token_budget()
        if remaining is not None and remaining <= 0:
            raise LLMResponseError(
                "Monthly token budget exceeded. Adjust the limit in Settings.",
                detail=f"Budget remaining: {remaining}",
            )

        # Cache lookup (skip for interactive tasks like copilot)
        _no_cache_tasks = {"copilot"}
        skip_cache = task in _no_cache_tasks
        model_name = config.get("offline_model") if config["mode"] == "offline" else config.get("online_model", "")
        cache_key = self._make_cache_key(prompt, system_prompt, model_name, task)
        if not skip_cache:
            cached = self._cache_get(cache_key)
            if cached is not None:
                logger.debug("Cache HIT for task=%s key=%s", task, cache_key[:12])
                return cached

        last_exc: Exception | None = None

        for attempt in range(1, max_retries + 1):
            try:
                if config["mode"] == "offline":
                    result = await self._invoke_ollama(prompt, system_prompt, config, timeout, json_mode=json_mode)
                else:
                    result = await self._invoke_online(prompt, system_prompt, config, timeout, json_mode=json_mode)
                # Cache the successful response (skip for interactive tasks)
                if not skip_cache:
                    self._cache_put(cache_key, result, task, model_name, prompt)
                return result
            except httpx.TimeoutException as exc:
                last_exc = exc
                logger.warning(
                    "LLM timeout (attempt %d/%d): %s", attempt, max_retries, exc,
                )
                if attempt < max_retries:
                    delay = RETRY_BASE_DELAY * attempt
                    await asyncio.sleep(delay)
            except httpx.ConnectError as exc:
                last_exc = exc
                logger.warning(
                    "LLM connection failed (attempt %d/%d): %s", attempt, max_retries, exc,
                )
                if attempt < max_retries:
                    delay = RETRY_BASE_DELAY * attempt
                    await asyncio.sleep(delay)
            except httpx.HTTPStatusError as exc:
                # Don't retry client errors (4xx) — only server errors (5xx)
                if exc.response.status_code < 500:
                    raise LLMResponseError(
                        f"LLM returned HTTP {exc.response.status_code}",
                        detail=str(exc),
                    ) from exc
                last_exc = exc
                logger.warning(
                    "LLM server error %d (attempt %d/%d)",
                    exc.response.status_code, attempt, max_retries,
                )
                if attempt < max_retries:
                    delay = RETRY_BASE_DELAY * attempt
                    await asyncio.sleep(delay)

        # All retries exhausted
        if isinstance(last_exc, httpx.TimeoutException):
            raise LLMTimeoutError(
                f"LLM timed out after {max_retries} attempts",
                detail=str(last_exc),
            ) from last_exc
        if isinstance(last_exc, httpx.ConnectError):
            raise LLMUnavailableError(
                f"LLM unavailable after {max_retries} attempts",
                detail=str(last_exc),
            ) from last_exc
        raise LLMResponseError(
            f"LLM call failed after {max_retries} attempts",
            detail=str(last_exc),
        ) from last_exc

    async def invoke_json(self, prompt: str, system_prompt: str | None = None, timeout: float = 300.0, task: str | None = None) -> Any:
        """Send a prompt and parse the response as JSON.

        Uses Ollama's native JSON mode (format=json) to force valid JSON output.
        Falls back to text parsing with retry if needed.
        """
        if system_prompt is None:
            system_prompt = "Respond with valid JSON only. No explanations."
        # First attempt: use Ollama's native JSON mode
        raw = await self.invoke(prompt, system_prompt, timeout, json_mode=True, task=task)
        try:
            return self._parse_json(raw)
        except (json.JSONDecodeError, ValueError):
            logger.warning("JSON parse failed even with format=json (len=%d), retrying. RAW OUTPUT:\n%s", len(raw), raw[:800])
            # Retry once more with json_mode, rephrasing the ask
            retry_prompt = (
                "Return ONLY a valid JSON object or array. No other text.\n\n"
                + prompt[:3000]
            )
            raw2 = await self.invoke(retry_prompt, system_prompt, timeout, json_mode=True, task=task)
            try:
                return self._parse_json(raw2)
            except (json.JSONDecodeError, ValueError) as exc:
                raise LLMResponseError(
                    "LLM failed to return valid JSON after retry",
                    detail=raw2[:500],
                ) from exc

    async def invoke_json_with_history(
        self,
        messages: list[dict[str, str]],
        timeout: float = 300.0,
        task: str | None = None,
    ) -> Any:
        """Send a multi-turn conversation and parse the response as JSON.

        Accepts a list of chat messages (role/content dicts) instead of a single
        prompt string.  Both Ollama and online providers natively support this.
        """
        config = self.get_current_config(task=task)

        for attempt in range(2):
            try:
                if config["mode"] == "offline":
                    raw = await self._invoke_ollama_messages(messages, config, timeout)
                else:
                    raw = await self._invoke_online_messages(messages, config, timeout)
                try:
                    return self._parse_json(raw)
                except (json.JSONDecodeError, ValueError):
                    if attempt == 0:
                        logger.warning("JSON parse failed on multi-turn (len=%d), retrying", len(raw))
                        # Append a nudge message and retry
                        messages = messages + [
                            {"role": "user", "content": "Return ONLY valid JSON. No other text."}
                        ]
                        continue
                    raise LLMResponseError("LLM failed to return valid JSON", detail=raw[:500])
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                if attempt == 0:
                    logger.warning("Multi-turn LLM call failed (attempt 1): %s", exc)
                    await asyncio.sleep(2)
                    continue
                raise LLMUnavailableError(
                    "LLM unavailable after 2 attempts", detail=str(exc)
                ) from exc
        raise LLMResponseError("invoke_json_with_history failed unexpectedly")

    async def check_availability(self) -> dict[str, Any]:
        """Check if the configured LLM is reachable."""
        config = self.get_current_config()
        try:
            if config["mode"] == "offline":
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(f"{config['ollama_url']}/api/tags")
                    resp.raise_for_status()
                    models = resp.json().get("models", [])
                    model_names = [m.get("name", "") for m in models]
                    available = any(config["offline_model"] in n for n in model_names)
                    return {
                        "available": available,
                        "mode": "offline",
                        "model": config["offline_model"],
                        "ollama_url": config["ollama_url"],
                        "models": model_names,
                        "error": None if available else f"Model '{config['offline_model']}' not found",
                    }
            else:
                has_key = bool(config["online_api_key"])
                has_model = bool(config["online_model"])
                provider = config.get("online_provider", "")
                base_url = config.get("online_base_url", "").strip()
                if not base_url:
                    base_url = self.PROVIDER_BASE_URLS.get(provider, "")

                if not (has_key and has_model):
                    return {
                        "available": False,
                        "mode": "online",
                        "model": config["online_model"],
                        "provider": provider,
                        "base_url": base_url,
                        "error": "Missing API key or model name",
                    }

                # Actually test the connection with a lightweight call
                try:
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        if provider == "anthropic":
                            # Anthropic: send a minimal Messages API call
                            test_headers = {
                                "x-api-key": config["online_api_key"],
                                "anthropic-version": "2023-06-01",
                                "Content-Type": "application/json",
                            }
                            test_payload = {
                                "model": config["online_model"],
                                "max_tokens": 1,
                                "messages": [{"role": "user", "content": "Hi"}],
                            }
                            resp = await client.post(
                                f"{base_url}/messages",
                                json=test_payload,
                                headers=test_headers,
                            )
                        else:
                            # OpenAI-compatible: GET /models
                            headers = {
                                "Authorization": f"Bearer {config['online_api_key']}",
                            }
                            resp = await client.get(f"{base_url}/models", headers=headers)
                        resp.raise_for_status()
                    return {
                        "available": True,
                        "mode": "online",
                        "model": config["online_model"],
                        "provider": provider,
                        "base_url": base_url,
                        "error": None,
                    }
                except Exception as api_exc:
                    # Connection test failed but config looks valid —
                    # still mark as available since some endpoints don't
                    # support GET /models (e.g. Anthropic, some custom)
                    logger.debug("Online API /models endpoint check failed: %s", api_exc)
                    return {
                        "available": True,
                        "mode": "online",
                        "model": config["online_model"],
                        "provider": provider,
                        "base_url": base_url,
                        "error": None,
                        "warning": f"Config looks valid but connectivity check failed: {api_exc}",
                    }
        except Exception as exc:
            return {
                "available": False,
                "mode": config["mode"],
                "model": config.get("offline_model") or config.get("online_model"),
                "error": str(exc),
            }

    # Cache helpers

    @staticmethod
    def _make_cache_key(
        prompt: str,
        system_prompt: str | None,
        model: str | None,
        task: str | None,
    ) -> str:
        """Build a deterministic SHA-256 cache key."""
        parts = [
            system_prompt or "",
            prompt,
            model or "",
            task or "",
        ]
        raw = "\n---\n".join(parts)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _cache_get(cache_key: str) -> str | None:
        """Return cached response or *None* on miss.  Thread-safe (own session)."""
        from backend.models.llm_cache import LLMCache

        db = SessionLocal()
        try:
            row = db.query(LLMCache).filter(LLMCache.cache_key == cache_key).first()
            if row is None:
                return None
            row.hit_count = (row.hit_count or 0) + 1
            row.last_used_at = datetime.now(timezone.utc)
            db.commit()
            return row.response_text
        except Exception:
            db.rollback()
            return None
        finally:
            db.close()

    @staticmethod
    def _cache_put(
        cache_key: str,
        response_text: str,
        task: str | None,
        model: str | None,
        prompt: str,
    ) -> None:
        """Store an LLM response in the cache.  Thread-safe (own session)."""
        from backend.models.llm_cache import LLMCache

        db = SessionLocal()
        try:
            existing = db.query(LLMCache).filter(LLMCache.cache_key == cache_key).first()
            if existing:
                existing.response_text = response_text
                existing.last_used_at = datetime.now(timezone.utc)
            else:
                entry = LLMCache(
                    cache_key=cache_key,
                    task=task,
                    model=model,
                    prompt_preview=prompt[:200],
                    response_text=response_text,
                )
                db.add(entry)
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()

    @staticmethod
    def get_cache_stats() -> dict[str, Any]:
        """Return cache statistics."""
        from backend.models.llm_cache import LLMCache
        from sqlalchemy import func

        db = SessionLocal()
        try:
            total = db.query(func.count(LLMCache.id)).scalar() or 0
            total_hits = db.query(func.sum(LLMCache.hit_count)).scalar() or 0
            return {
                "total_entries": total,
                "total_hits": total_hits,
            }
        finally:
            db.close()

    @staticmethod
    def clear_cache(task: str | None = None) -> int:
        """Delete cache entries. If *task* is given, only that task's entries.

        Returns the number of deleted rows.
        """
        from backend.models.llm_cache import LLMCache

        db = SessionLocal()
        try:
            q = db.query(LLMCache)
            if task:
                q = q.filter(LLMCache.task == task)
            count = q.delete()
            db.commit()
            return count
        except Exception:
            db.rollback()
            return 0
        finally:
            db.close()

    # Token helpers

    def _get_max_tokens(self) -> int:
        """Read llm_max_tokens from DB settings, fall back to LLM_MAX_TOKENS."""
        db = SessionLocal()
        try:
            row = db.query(AppSettings).filter(AppSettings.key == "llm_max_tokens").first()
            return int(row.value) if row and row.value else LLM_MAX_TOKENS
        except Exception:
            return LLM_MAX_TOKENS
        finally:
            db.close()

    @staticmethod
    def _record_usage(provider: str, model: str, task: str | None, usage: dict | None) -> None:
        """Persist token usage from an LLM response."""
        if not usage:
            return
        from backend.models.token_usage import TokenUsage

        # Normalize field names across providers
        input_t = usage.get("input_tokens") or usage.get("prompt_tokens") or usage.get("prompt_eval_count") or 0
        output_t = usage.get("output_tokens") or usage.get("completion_tokens") or usage.get("eval_count") or 0
        total_t = usage.get("total_tokens") or (input_t + output_t)

        db = SessionLocal()
        try:
            db.add(TokenUsage(
                provider=provider, model=model, task=task,
                input_tokens=input_t, output_tokens=output_t, total_tokens=total_t,
            ))
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()

    @staticmethod
    def _check_token_budget() -> int | None:
        """Return remaining tokens this month, or None if no budget set."""
        from backend.models.token_usage import TokenUsage
        from sqlalchemy import func

        db = SessionLocal()
        try:
            row = db.query(AppSettings).filter(AppSettings.key == "llm_token_budget").first()
            if not row or not row.value or int(row.value) <= 0:
                return None
            budget = int(row.value)
            # Sum this month's usage
            now = datetime.now(timezone.utc)
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            used = db.query(func.coalesce(func.sum(TokenUsage.total_tokens), 0)).filter(
                TokenUsage.timestamp >= month_start,
            ).scalar()
            return budget - used
        except Exception:
            return None
        finally:
            db.close()

    # Private methods

    async def _invoke_ollama(
        self,
        prompt: str,
        system_prompt: str | None,
        config: dict,
        timeout: float,
        *,
        json_mode: bool = False,
    ) -> str:
        """Call local Ollama using the /api/chat endpoint for better instruction following."""
        url = f"{config['ollama_url']}/api/chat"
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload: dict[str, Any] = {
            "model": config["offline_model"],
            "messages": messages,
            "stream": False,
            "options": {"temperature": LLM_TEMPERATURE, "num_predict": self._get_max_tokens()},
        }
        if json_mode:
            payload["format"] = "json"
        timeouts = httpx.Timeout(timeout, connect=30.0)
        client = _get_shared_client()
        resp = await client.post(url, json=payload, timeout=timeouts)
        resp.raise_for_status()
        data = resp.json()

        # Ollama uses prompt_eval_count / eval_count
        self._record_usage("ollama", config["offline_model"], None, data)

        # /api/chat returns {"message": {"role": "assistant", "content": "..."}}
        return data.get("message", {}).get("content", "")

    async def _invoke_online(
        self,
        prompt: str,
        system_prompt: str | None,
        config: dict,
        timeout: float,
        *,
        json_mode: bool = False,
    ) -> str:
        """Call OpenAI-compatible API (OpenAI, Mistral, Groq, OpenRouter, or custom)."""
        provider = config.get("online_provider", "openai")

        # Anthropic uses a different protocol — dispatch separately
        if provider == "anthropic":
            return await self._invoke_anthropic(prompt, system_prompt, config, timeout, json_mode=json_mode)

        # Use custom base URL if configured, otherwise look up by provider name
        base_url = config.get("online_base_url", "").strip()
        if not base_url:
            base_url = self.PROVIDER_BASE_URLS.get(provider, "https://api.openai.com/v1")

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        headers = {
            "Authorization": f"Bearer {config['online_api_key']}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": config["online_model"],
            "messages": messages,
            "temperature": LLM_TEMPERATURE,
            "max_tokens": self._get_max_tokens(),
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        timeouts = httpx.Timeout(timeout, connect=30.0)
        client = _get_shared_client()
        resp = await client.post(f"{base_url}/chat/completions", json=payload, headers=headers, timeout=timeouts)
        resp.raise_for_status()
        data = resp.json()

        provider = config.get("online_provider", "openai")
        self._record_usage(provider, config["online_model"], None, data.get("usage"))

        return data["choices"][0]["message"]["content"]

    async def _invoke_ollama_messages(
        self,
        messages: list[dict[str, str]],
        config: dict,
        timeout: float,
    ) -> str:
        """Call Ollama /api/chat with a full multi-turn message list."""
        url = f"{config['ollama_url']}/api/chat"
        payload: dict[str, Any] = {
            "model": config["offline_model"],
            "messages": messages,
            "stream": False,
            "format": "json",
            "options": {"temperature": LLM_TEMPERATURE, "num_predict": self._get_max_tokens()},
        }
        timeouts = httpx.Timeout(timeout, connect=30.0)
        client = _get_shared_client()
        resp = await client.post(url, json=payload, timeout=timeouts)
        resp.raise_for_status()
        data = resp.json()

        self._record_usage("ollama", config["offline_model"], None, data)

        return data.get("message", {}).get("content", "")

    async def _invoke_online_messages(
        self,
        messages: list[dict[str, str]],
        config: dict,
        timeout: float,
    ) -> str:
        """Call OpenAI-compatible API with a full multi-turn message list."""
        provider = config.get("online_provider", "openai")

        # Anthropic uses a different protocol — dispatch separately
        if provider == "anthropic":
            return await self._invoke_anthropic_messages(messages, config, timeout)

        base_url = config.get("online_base_url", "").strip()
        if not base_url:
            base_url = self.PROVIDER_BASE_URLS.get(provider, "https://api.openai.com/v1")

        headers = {
            "Authorization": f"Bearer {config['online_api_key']}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": config["online_model"],
            "messages": messages,
            "temperature": LLM_TEMPERATURE,
            "max_tokens": self._get_max_tokens(),
            "response_format": {"type": "json_object"},
        }
        timeouts = httpx.Timeout(timeout, connect=30.0)
        client = _get_shared_client()
        resp = await client.post(f"{base_url}/chat/completions", json=payload, headers=headers, timeout=timeouts)
        resp.raise_for_status()
        data = resp.json()

        provider = config.get("online_provider", "openai")
        self._record_usage(provider, config["online_model"], None, data.get("usage"))

        return data["choices"][0]["message"]["content"]

    async def _invoke_anthropic(
        self,
        prompt: str,
        system_prompt: str | None,
        config: dict,
        timeout: float,
        *,
        json_mode: bool = False,
        task: str | None = None,
    ) -> str:
        """Call Anthropic Messages API."""
        base_url = config.get("online_base_url", "").strip()
        if not base_url:
            base_url = self.PROVIDER_BASE_URLS.get("anthropic", "https://api.anthropic.com/v1")

        headers = {
            "x-api-key": config["online_api_key"],
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": config["online_model"],
            "max_tokens": self._get_max_tokens(),
            "temperature": LLM_TEMPERATURE,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system_prompt:
            payload["system"] = system_prompt

        timeouts = httpx.Timeout(timeout, connect=30.0)
        client = _get_shared_client()
        resp = await client.post(f"{base_url}/messages", json=payload, headers=headers, timeout=timeouts)
        resp.raise_for_status()
        data = resp.json()

        # Record token usage
        self._record_usage(
            "anthropic", config["online_model"], task, data.get("usage"),
        )

        return data["content"][0]["text"]

    async def _invoke_anthropic_messages(
        self,
        messages: list[dict[str, str]],
        config: dict,
        timeout: float,
        task: str | None = None,
    ) -> str:
        """Call Anthropic Messages API with a full multi-turn message list."""
        base_url = config.get("online_base_url", "").strip()
        if not base_url:
            base_url = self.PROVIDER_BASE_URLS.get("anthropic", "https://api.anthropic.com/v1")

        # Extract system messages → top-level system param
        system_parts = []
        chat_messages = []
        for msg in messages:
            if msg.get("role") == "system":
                system_parts.append(msg["content"])
            else:
                chat_messages.append(msg)

        headers = {
            "x-api-key": config["online_api_key"],
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": config["online_model"],
            "max_tokens": self._get_max_tokens(),
            "temperature": LLM_TEMPERATURE,
            "messages": chat_messages,
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)

        timeouts = httpx.Timeout(timeout, connect=30.0)
        client = _get_shared_client()
        resp = await client.post(f"{base_url}/messages", json=payload, headers=headers, timeout=timeouts)
        resp.raise_for_status()
        data = resp.json()

        self._record_usage(
            "anthropic", config["online_model"], task, data.get("usage"),
        )

        return data["content"][0]["text"]

    @staticmethod
    def _parse_json(text: str) -> Any:
        """Extract and parse JSON from LLM response text, handling markdown code blocks."""
        # Fast path: try parsing the raw text directly first (works with format=json)
        stripped = text.strip()
        try:
            return json.loads(stripped)
        except (json.JSONDecodeError, ValueError):
            pass
        # Try to find JSON in markdown code blocks first
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                pass
        # Try finding JSON object or array directly — prefer objects over arrays
        for start_char, end_char in [("{", "}"), ("[", "]")]:
            start = text.find(start_char)
            end = text.rfind(end_char)
            if start != -1 and end != -1 and end > start:
                candidate = text[start : end + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    # Try fixing common LLM issues: trailing commas
                    cleaned = re.sub(r",\s*([}\]])", r"\1", candidate)
                    try:
                        return json.loads(cleaned)
                    except json.JSONDecodeError:
                        continue
        # Last resort: try parsing the whole thing
        return json.loads(text.strip())


# Singleton
llm_manager = LLMManager()
