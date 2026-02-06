"""LLM Manager — unified interface for offline (Ollama) and online (OpenAI-compatible) LLM calls."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from backend.database import SessionLocal
from backend.models.app_settings import AppSettings

logger = logging.getLogger("auditforge.llm")

# LLM generation parameters — low temperature for deterministic structured output
LLM_TEMPERATURE = 0.1
LLM_MAX_TOKENS = 8192


class LLMManager:
    """Single interface for all LLM operations."""

    def get_current_config(self) -> dict[str, str]:
        """Read LLM settings from the app_settings table."""
        db = SessionLocal()
        try:
            rows = db.query(AppSettings).all()
            cfg = {r.key: r.value for r in rows}
        finally:
            db.close()
        return {
            "mode": cfg.get("llm_mode", "offline"),
            "offline_model": cfg.get("llm_offline_model", "qwen2.5:14b"),
            "ollama_url": cfg.get("llm_ollama_url", "http://localhost:11434"),
            "online_provider": cfg.get("llm_online_provider", ""),
            "online_api_key": cfg.get("llm_online_api_key_encrypted", ""),
            "online_model": cfg.get("llm_online_model", ""),
            "category_detection": cfg.get("llm_category_detection", "true"),
        }

    async def invoke(self, prompt: str, system_prompt: str | None = None, timeout: float = 300.0) -> str:
        """Send a prompt and get a text response."""
        config = self.get_current_config()
        if config["mode"] == "offline":
            return await self._invoke_ollama(prompt, system_prompt, config, timeout)
        else:
            return await self._invoke_online(prompt, system_prompt, config, timeout)

    async def invoke_json(self, prompt: str, system_prompt: str | None = None, timeout: float = 300.0) -> Any:
        """Send a prompt and parse the response as JSON, with one retry on failure."""
        raw = await self.invoke(prompt, system_prompt, timeout)
        try:
            return self._parse_json(raw)
        except (json.JSONDecodeError, ValueError):
            logger.warning("First JSON parse failed, retrying with correction prompt")
            retry_prompt = (
                f"Your previous response was not valid JSON. "
                f"Please fix and return ONLY valid JSON:\n\n{raw}"
            )
            raw2 = await self.invoke(retry_prompt, system_prompt, timeout)
            return self._parse_json(raw2)

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
                return {
                    "available": has_key and has_model,
                    "mode": "online",
                    "model": config["online_model"],
                    "provider": config["online_provider"],
                    "error": None if (has_key and has_model) else "Missing API key or model name",
                }
        except Exception as exc:
            return {
                "available": False,
                "mode": config["mode"],
                "model": config.get("offline_model") or config.get("online_model"),
                "error": str(exc),
            }

    # ── Private methods ──

    async def _invoke_ollama(self, prompt: str, system_prompt: str | None, config: dict, timeout: float) -> str:
        """Call local Ollama."""
        url = f"{config['ollama_url']}/api/generate"
        payload: dict[str, Any] = {
            "model": config["offline_model"],
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": LLM_TEMPERATURE, "num_predict": LLM_MAX_TOKENS},
        }
        if system_prompt:
            payload["system"] = system_prompt
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json().get("response", "")

    async def _invoke_online(self, prompt: str, system_prompt: str | None, config: dict, timeout: float) -> str:
        """Call OpenAI-compatible API."""
        provider = config.get("online_provider", "openai")
        base_urls = {
            "openai": "https://api.openai.com/v1",
            "anthropic": "https://api.anthropic.com/v1",
        }
        base_url = base_urls.get(provider, "https://api.openai.com/v1")
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        headers = {
            "Authorization": f"Bearer {config['online_api_key']}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": config["online_model"],
            "messages": messages,
            "temperature": LLM_TEMPERATURE,
            "max_tokens": LLM_MAX_TOKENS,
        }
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(f"{base_url}/chat/completions", json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]

    @staticmethod
    def _parse_json(text: str) -> Any:
        """Extract and parse JSON from LLM response text, handling markdown code blocks."""
        # Try to find JSON in markdown code blocks first
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
        if match:
            return json.loads(match.group(1).strip())
        # Try finding JSON array or object directly
        for start_char, end_char in [("[", "]"), ("{", "}")]:
            start = text.find(start_char)
            end = text.rfind(end_char)
            if start != -1 and end != -1 and end > start:
                return json.loads(text[start : end + 1])
        # Last resort: try parsing the whole thing
        return json.loads(text.strip())


# Singleton
llm_manager = LLMManager()
