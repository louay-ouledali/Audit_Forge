"""LLM Manager — unified interface for offline (Ollama) and online (OpenAI-compatible) LLM calls."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

import httpx

from backend.core.exceptions import LLMResponseError, LLMTimeoutError, LLMUnavailableError
from backend.database import SessionLocal
from backend.models.app_settings import AppSettings

logger = logging.getLogger("auditforge.llm")

# LLM generation parameters — low temperature for deterministic structured output
LLM_TEMPERATURE = 0.1
LLM_MAX_TOKENS = 4096  # Batch of 10 rules × ~300 tokens each

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
    TASK_NAMES = ("phase1_parsing", "phase2_commands", "verification", "reports", "analysis")

    def get_current_config(self, task: str | None = None) -> dict[str, str]:
        """Read LLM settings from the app_settings table.

        If *task* is provided (e.g. ``"phase2_commands"``), per-task model
        overrides are applied on top of the global config.
        """
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

        # Apply per-task model override if configured
        if task and task in self.TASK_NAMES:
            task_model = cfg.get(f"llm_task_{task}_model", "").strip()
            if task_model:
                if config["mode"] == "offline":
                    config["offline_model"] = task_model
                else:
                    config["online_model"] = task_model

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
        """Send a prompt and get a text response with retry and exponential backoff."""
        config = self.get_current_config(task=task)
        last_exc: Exception | None = None

        for attempt in range(1, max_retries + 1):
            try:
                if config["mode"] == "offline":
                    return await self._invoke_ollama(prompt, system_prompt, config, timeout, json_mode=json_mode)
                else:
                    return await self._invoke_online(prompt, system_prompt, config, timeout, json_mode=json_mode)
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

                # Actually test the connection with a lightweight models list call
                headers = {
                    "Authorization": f"Bearer {config['online_api_key']}",
                }
                try:
                    async with httpx.AsyncClient(timeout=10.0) as client:
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

    # ── Private methods ──

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
            "options": {"temperature": LLM_TEMPERATURE, "num_predict": LLM_MAX_TOKENS},
        }
        if json_mode:
            payload["format"] = "json"
        # Use separate timeouts: 30s to connect, full timeout for reading response
        timeouts = httpx.Timeout(timeout, connect=30.0)
        async with httpx.AsyncClient(timeout=timeouts) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
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
            "max_tokens": LLM_MAX_TOKENS,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        timeouts = httpx.Timeout(timeout, connect=30.0)
        async with httpx.AsyncClient(timeout=timeouts) as client:
            resp = await client.post(f"{base_url}/chat/completions", json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]

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
                    # Try fixing common LLM issues: trailing commas, single quotes
                    cleaned = re.sub(r",\s*([}\]])", r"\1", candidate)
                    try:
                        return json.loads(cleaned)
                    except json.JSONDecodeError:
                        pass
                    # Try fixing unescaped quotes inside string values
                    # Replace internal double quotes in values with single quotes
                    fixed = re.sub(
                        r'(?<=: ")(.*?)(?="[,\s}\]])',
                        lambda m: m.group(0).replace('"', "'"),
                        candidate,
                        flags=re.DOTALL,
                    )
                    try:
                        return json.loads(fixed)
                    except json.JSONDecodeError:
                        continue
        # Last resort: try parsing the whole thing
        return json.loads(text.strip())


# Singleton
llm_manager = LLMManager()
