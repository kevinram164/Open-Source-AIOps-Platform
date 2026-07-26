"""LLM chat completions — OpenAI or Ollama (OpenAI-compatible API)."""

from __future__ import annotations

from typing import Any

import httpx
import structlog

from incident_api.config import settings

log = structlog.get_logger()


def llm_configured() -> bool:
    provider = (settings.llm_provider or "openai").lower()
    if provider == "ollama":
        return bool(settings.ollama_base_url)
    return bool(settings.openai_api_key)


def model_name() -> str:
    provider = (settings.llm_provider or "openai").lower()
    if provider == "ollama":
        return settings.ollama_model or settings.openai_model
    return settings.openai_model


async def chat_completions(
    *,
    messages: list[dict[str, str]],
    temperature: float = 0.2,
    max_tokens: int = 900,
) -> tuple[str, str]:
    """Returns (content, model_used)."""
    provider = (settings.llm_provider or "openai").lower()
    model = model_name()

    if provider == "ollama":
        base = settings.ollama_base_url.rstrip("/")
        url = f"{base}/v1/chat/completions"
        headers = {"Content-Type": "application/json"}
        if settings.openai_api_key:
            headers["Authorization"] = f"Bearer {settings.openai_api_key}"
# CPU 3B: keep output short — long gens hit ~2–3m walls (ERR_EMPTY_RESPONSE / 500)
        max_tokens = min(max_tokens, 250)
        timeout = float(settings.ollama_timeout_seconds)
    else:
        url = "https://api.openai.com/v1/chat/completions"
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY not configured")
        headers = {
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        }
        timeout = 60.0

    payload: dict[str, Any] = {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if provider == "ollama":
        # Prefer smaller window on CPU; avoid default parallel slot truncate
        payload["options"] = {"num_ctx": 4096, "num_predict": max_tokens}

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code >= 400:
            log.error(
                "llm_http_error",
                provider=provider,
                status=resp.status_code,
                body=resp.text[:500],
            )
            resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return content, model
