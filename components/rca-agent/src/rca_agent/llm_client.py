"""LLM chat completions — OpenAI or Ollama (OpenAI-compatible API)."""

from __future__ import annotations

from typing import Any

import httpx
import structlog

from rca_agent.config import settings

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
    max_tokens: int | None = None,
) -> tuple[str, str]:
    """
    Returns (content, model_used).
    Raises httpx.HTTPError / RuntimeError on failure.
    """
    provider = (settings.llm_provider or "openai").lower()
    max_tok = max_tokens if max_tokens is not None else settings.openai_max_tokens
    model = model_name()

    if provider == "ollama":
        base = settings.ollama_base_url.rstrip("/")
        url = f"{base}/v1/chat/completions"
        headers = {"Content-Type": "application/json"}
        # Ollama ignores auth; some proxies want a dummy bearer
        if settings.openai_api_key:
            headers["Authorization"] = f"Bearer {settings.openai_api_key}"
    else:
        url = "https://api.openai.com/v1/chat/completions"
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY not configured")
        headers = {
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        }

    payload: dict[str, Any] = {
        "model": model,
        "temperature": temperature,
        "messages": messages,
    }
    # Ollama OpenAI compat supports max_tokens; some builds prefer options.num_predict
    if provider == "ollama":
        payload["max_tokens"] = min(max_tok, 2048)
    else:
        payload["max_tokens"] = max_tok

    timeout = float(settings.rca_request_timeout_seconds)
    if provider == "ollama":
        timeout = max(timeout, float(settings.ollama_timeout_seconds))

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
