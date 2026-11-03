"""Small, dependency-free LLM client.

Pick a provider with LLM_PROVIDER=anthropic|openai|gemini and set its API key.
With LLM_PROVIDER=none (or a missing key) the system uses its rule-based engine instead.
"""
import json
import logging
import re

import httpx

from .config import settings

log = logging.getLogger(__name__)

DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-5-5",
    "openai": "gpt-4o",
    "gemini": "gemini-2.5-flash",
}


class LLMError(RuntimeError):
    pass


def provider() -> str:
    p = settings.LLM_PROVIDER
    keys = {"anthropic": settings.ANTHROPIC_API_KEY, "openai": settings.OPENAI_API_KEY,
            "gemini": settings.GEMINI_API_KEY}
    return p if p in keys and keys[p] else "none"


def enabled() -> bool:
    return provider() != "none"


def model_name() -> str:
    p = provider()
    return settings.LLM_MODEL or DEFAULT_MODELS.get(p, "")


def engine_label() -> str:
    return f"llm:{provider()}:{model_name()}" if enabled() else "rules"


def complete_json(system: str, user: str, max_tokens: int = 4000) -> dict:
    """Ask the model for a JSON object and parse it. Raises LLMError on failure."""
    p = provider()
    if p == "none":
        raise LLMError("No LLM configured")
    try:
        if p == "anthropic":
            text = _anthropic(system, user, max_tokens)
        elif p == "openai":
            text = _openai(system, user, max_tokens)
        else:
            text = _gemini(system, user, max_tokens)
    except httpx.HTTPError as exc:
        raise LLMError(f"{p} request failed: {exc}") from exc
    return parse_json(text)


def parse_json(text: str) -> dict:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start:end + 1])
            except json.JSONDecodeError:
                pass
    raise LLMError("Model did not return valid JSON")


def _anthropic(system: str, user: str, max_tokens: int) -> str:
    r = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": settings.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json={"model": model_name(), "max_tokens": max_tokens, "system": system, "temperature": 0,
              "messages": [{"role": "user", "content": user}]},
        timeout=settings.LLM_TIMEOUT,
    )
    _raise(r, "anthropic")
    data = r.json()
    return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")


def _openai(system: str, user: str, max_tokens: int) -> str:
    r = httpx.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
        json={"model": model_name(), "temperature": 0, "max_tokens": max_tokens,
              "response_format": {"type": "json_object"},
              "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
        timeout=settings.LLM_TIMEOUT,
    )
    _raise(r, "openai")
    return r.json()["choices"][0]["message"]["content"]


def _gemini(system: str, user: str, max_tokens: int) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name()}:generateContent"
    r = httpx.post(
        url,
        headers={"x-goog-api-key": settings.GEMINI_API_KEY},
        json={"systemInstruction": {"parts": [{"text": system}]},
              "contents": [{"role": "user", "parts": [{"text": user}]}],
              "generationConfig": {"temperature": 0, "maxOutputTokens": max_tokens,
                                   "responseMimeType": "application/json"}},
        timeout=settings.LLM_TIMEOUT,
    )
    _raise(r, "gemini")
    cands = r.json().get("candidates", [])
    if not cands:
        raise LLMError("Gemini returned no candidates")
    return "".join(p.get("text", "") for p in cands[0].get("content", {}).get("parts", []))


def _raise(r: httpx.Response, name: str) -> None:
    if r.status_code >= 400:
        # Never log the request body (it contains patient data); the error text is enough.
        raise LLMError(f"{name} API error {r.status_code}: {r.text[:300]}")
