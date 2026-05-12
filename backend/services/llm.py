import json
import re
from typing import Any

from openai import OpenAI

from backend.utils.config import resolved_llm_provider, settings


def _parse_json_loose(content: str) -> dict[str, Any]:
    content = (content or "").strip()
    try:
        out = json.loads(content)
        if isinstance(out, dict):
            return out
    except json.JSONDecodeError:
        pass
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", content)
    if fence:
        try:
            out = json.loads(fence.group(1).strip())
            if isinstance(out, dict):
                return out
        except json.JSONDecodeError:
            pass
    m = re.search(r"\{[\s\S]*\}", content)
    if m:
        try:
            out = json.loads(m.group())
            if isinstance(out, dict):
                return out
        except json.JSONDecodeError:
            pass
    return {}


def _client_and_model() -> tuple[OpenAI, str]:
    provider = resolved_llm_provider()
    if provider == "groq":
        return (
            OpenAI(api_key=settings.groq_api_key, base_url=settings.groq_base_url),
            settings.groq_model,
        )
    return OpenAI(api_key=settings.openai_api_key), settings.openai_model


def chat_json(system: str, user: str, temperature: float = 0.2) -> dict[str, Any]:
    client, model = _client_and_model()
    kwargs: dict[str, Any] = {
        "model": model,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    try:
        resp = client.chat.completions.create(
            **kwargs,
            response_format={"type": "json_object"},
        )
    except Exception:
        resp = client.chat.completions.create(**kwargs)

    content = resp.choices[0].message.content or "{}"
    parsed = _parse_json_loose(content)
    return parsed if parsed else {"error": "invalid_json", "raw": content[:2000]}


def chat_text(system: str, user: str, temperature: float = 0.3) -> str:
    client, model = _client_and_model()
    resp = client.chat.completions.create(
        model=model,
        temperature=temperature,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return (resp.choices[0].message.content or "").strip()


def extract_json_array(text: str) -> list[dict[str, Any]]:
    """Fallback: parse JSON array from model output if json_object mode wasn't used."""
    text = text.strip()
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "items" in data:
            return list(data["items"])
    except json.JSONDecodeError:
        pass
    m = re.search(r"\[[\s\S]*\]", text)
    if m:
        return json.loads(m.group())
    return []
