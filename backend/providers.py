"""
providers.py — CapCode's model catalog aggregator.

Three OpenAI-compatible providers:
  - NVIDIA NIM         (https://integrate.api.nvidia.com/v1)
  - OpenRouter         (https://openrouter.ai/api/v1)   -- huge catalog
  - Venice             (https://api.venice.ai/api/v1)   -- privacy-first, uncensored

We aggregate available models into a single catalog with metadata:
  {id, provider, display_name, uncensored, coding, price_tier, price_per_1m, roles, free}

Coding models on OpenRouter are curated via a "coding-strong" name-prefix allowlist
(the API doesn't expose a coding tag). All Venice models are surfaced (per user
request), all treated as uncensored-friendly.
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

logger = logging.getLogger("providers")

# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------
PROVIDERS = {
    "nvidia": {
        "label": "NVIDIA NIM",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "api_key_env": "NVIDIA_API_KEY",
        "models_url": "https://integrate.api.nvidia.com/v1/models",
        # NVIDIA doesn't expose pricing on /models; pin the known-good models we support.
        "static_models": [
            {"id": "z-ai/glm-5.1", "coding": True, "uncensored": False, "roles": ["gen"]},
            {"id": "minimaxai/minimax-m2.7", "coding": True, "uncensored": False, "roles": ["critic"]},
            {"id": "nvidia/llama-3.3-nemotron-super-49b-v1.5", "coding": False, "uncensored": False, "roles": ["rater"]},
        ],
    },
    "openrouter": {
        "label": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "api_key_env": "OPENROUTER_API_KEY",
        "models_url": "https://openrouter.ai/api/v1/models",
    },
    "venice": {
        "label": "Venice",
        "base_url": "https://api.venice.ai/api/v1",
        "api_key_env": "VENICE_API_KEY",
        "models_url": "https://api.venice.ai/api/v1/models",
    },
}


def provider_key(name: str) -> Optional[str]:
    env = PROVIDERS.get(name, {}).get("api_key_env", "")
    return (os.environ.get(env, "") or "").strip() or None


def provider_available(name: str) -> bool:
    return bool(provider_key(name))


# ---------------------------------------------------------------------------
# Coding-model allowlist for OpenRouter (name-prefix / substring match)
# ---------------------------------------------------------------------------
_OR_CODING_HINTS = [
    "claude", "gpt-5", "gpt-4", "gpt-4o", "o1", "o3", "o4",
    "deepseek", "codestral", "qwen", "qwen3", "qwen-coder", "coder",
    "glm-", "gemini", "grok", "llama-3.3", "llama-3.1-70b", "llama-4",
    "mistral-large", "mixtral", "nova-pro", "yi-",
]


_OR_NON_CODING_HINTS = ["lyria", "whisper", "tts", "voice", "audio", "embed",
                        "vision", "image", "guardrails", "content-safety",
                        "reranker", "moderation", "translate", "-clip"]


def _looks_like_coding(model_id: str) -> bool:
    m = model_id.lower()
    if any(h in m for h in _OR_NON_CODING_HINTS):
        return False
    return any(h in m for h in _OR_CODING_HINTS) or "code" in m or "coder" in m


_UNCENSORED_HINTS = ["uncensored", "abliterated", "dolphin", "openhermes",
                     "nous-hermes", "wizardlm", "airoboros"]


def _looks_uncensored(model_id: str, description: str = "") -> bool:
    blob = f"{model_id} {description}".lower()
    return any(h in blob for h in _UNCENSORED_HINTS)


def _price_tier(price_per_1m: float) -> str:
    if price_per_1m <= 0:
        return "free"
    if price_per_1m < 1.0:
        return "$"
    if price_per_1m < 8.0:
        return "$$"
    return "$$$"


# ---------------------------------------------------------------------------
# Fetchers
# ---------------------------------------------------------------------------
async def _fetch_openrouter() -> list[dict]:
    key = provider_key("openrouter")
    if not key:
        return []
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                PROVIDERS["openrouter"]["models_url"],
                headers={"Authorization": f"Bearer {key}"},
            )
            r.raise_for_status()
            data = r.json().get("data", [])
    except Exception as exc:
        logger.warning("openrouter /models failed: %s", exc)
        return []
    out = []
    for m in data:
        mid = m.get("id") or ""
        if not mid:
            continue
        pricing = m.get("pricing") or {}
        try:
            prompt = float(pricing.get("prompt", 0) or 0) * 1_000_000
            completion = float(pricing.get("completion", 0) or 0) * 1_000_000
        except Exception:
            prompt = completion = 0.0
        avg = (prompt + completion) / 2.0
        is_free = prompt == 0 and completion == 0
        looks_coding = _looks_like_coding(mid)
        is_non_coding = any(h in mid.lower() for h in _OR_NON_CODING_HINTS)
        # Include: any coding model + any free model that isn't obviously non-coding
        if not looks_coding and not (is_free and not is_non_coding):
            continue
        # Treat free-and-not-obviously-non-coding as coding-eligible
        coding_flag = looks_coding or (is_free and not is_non_coding)
        out.append({
            "id": mid,
            "provider": "openrouter",
            "display_name": (m.get("name") or mid),
            "description": (m.get("description") or "")[:280],
            "coding": coding_flag,
            "uncensored": _looks_uncensored(mid, m.get("description") or ""),
            "context_len": m.get("context_length") or 0,
            "price_per_1m": round(avg, 4),
            "price_tier": "free" if is_free else _price_tier(avg),
            "free": is_free,
            "roles": ["gen", "critic", "rater"],
        })
    return out


async def _fetch_venice() -> list[dict]:
    key = provider_key("venice")
    if not key:
        return []
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                PROVIDERS["venice"]["models_url"],
                headers={"Authorization": f"Bearer {key}"},
            )
            r.raise_for_status()
            data = r.json().get("data", [])
    except Exception as exc:
        logger.warning("venice /models failed: %s", exc)
        return []
    out = []
    for m in data:
        mid = m.get("id") or ""
        if not mid:
            continue
        spec = m.get("model_spec") or {}
        pricing = spec.get("pricing") or {}
        try:
            inp = float(pricing.get("input", {}).get("usd", 0) or 0)
            outp = float(pricing.get("output", {}).get("usd", 0) or 0)
        except Exception:
            inp = outp = 0.0
        avg = (inp + outp) / 2.0
        traits = spec.get("traits") or []
        # Venice explicitly flags uncensored/functionCalling/reasoning traits.
        is_uncensored = ("default_uncensored" in traits) or ("uncensored" in mid.lower())
        # User asked for ALL uncensored Venice + coding agents.
        is_coding = any(t in traits for t in ("code", "coding")) or "code" in mid.lower() or "coder" in mid.lower()
        out.append({
            "id": mid,
            "provider": "venice",
            "display_name": (spec.get("name") or mid),
            "description": (spec.get("description") or "")[:280],
            "coding": is_coding,
            "uncensored": is_uncensored,
            "context_len": spec.get("availableContextTokens") or 0,
            "price_per_1m": round(avg, 4),
            "price_tier": _price_tier(avg),
            "free": avg == 0,
            "roles": ["gen", "critic", "rater"],
            "traits": traits,
        })
    # Per user: include ALL Venice uncensored + all coding agents.
    return [m for m in out if m["uncensored"] or m["coding"]] or out


async def _fetch_nvidia() -> list[dict]:
    # NVIDIA doesn't expose pricing/coding tags cleanly. Return our known-good static set.
    out = []
    for spec in PROVIDERS["nvidia"]["static_models"]:
        out.append({
            "id": spec["id"],
            "provider": "nvidia",
            "display_name": spec["id"],
            "description": "",
            "coding": spec["coding"],
            "uncensored": spec["uncensored"],
            "context_len": 0,
            "price_per_1m": 0.0,
            "price_tier": "free",  # NVIDIA's public tier is effectively free for these
            "free": True,
            "roles": spec["roles"],
        })
    return out


# ---------------------------------------------------------------------------
# Cache + public API
# ---------------------------------------------------------------------------
_CACHE: dict = {"models": None, "loaded_at": 0.0}
_CACHE_TTL_SEC = 300


async def get_catalog(force: bool = False) -> list[dict]:
    import time as _time

    now = _time.time()
    if not force and _CACHE["models"] is not None and (now - _CACHE["loaded_at"] < _CACHE_TTL_SEC):
        return _CACHE["models"]

    nv, orr, ve = await asyncio.gather(
        _fetch_nvidia(), _fetch_openrouter(), _fetch_venice(),
        return_exceptions=False,
    )
    catalog = [*nv, *orr, *ve]
    _CACHE["models"] = catalog
    _CACHE["loaded_at"] = now
    return catalog


DEFAULT_ASSIGNMENTS = {
    # Six-stage dev-team pipeline. Each role has its own model choice.
    "planner":   {"provider": "openrouter", "model": "nvidia/nemotron-3-super-120b-a12b:free"},
    "architect": {"provider": "openrouter", "model": "nvidia/nemotron-3-super-120b-a12b:free"},
    "builder":   {"provider": "openrouter", "model": "poolside/laguna-s-2.1:free"},
    "reviewer":  {"provider": "openrouter", "model": "google/gemma-4-31b-it:free"},
    "corrector": {"provider": "openrouter", "model": "poolside/laguna-s-2.1:free"},
    "rater":     {"provider": "openrouter", "model": "inclusionai/ling-3.0-flash:free"},
    # NIM fallbacks used automatically if the primary provider errors.
    "planner_fallback":   {"provider": "nvidia", "model": "z-ai/glm-5.1"},
    "architect_fallback": {"provider": "nvidia", "model": "z-ai/glm-5.1"},
    "builder_fallback":   {"provider": "nvidia", "model": "z-ai/glm-5.1"},
    "reviewer_fallback":  {"provider": "nvidia", "model": "minimaxai/minimax-m2.7"},
    "corrector_fallback": {"provider": "nvidia", "model": "z-ai/glm-5.1"},
    "rater_fallback":     {"provider": "nvidia", "model": "nvidia/llama-3.3-nemotron-super-49b-v1.5"},
}


def openai_client_for(provider: str):
    """Return an AsyncOpenAI client bound to the named provider, or None if key missing."""
    key = provider_key(provider)
    if not key or provider not in PROVIDERS:
        return None
    try:
        from openai import AsyncOpenAI
    except ImportError:
        return None
    base = PROVIDERS[provider]["base_url"]
    extra_headers = {}
    if provider == "openrouter":
        # OpenRouter recommends these attribution headers.
        extra_headers = {
            "HTTP-Referer": "https://capcode.emergent.host",
            "X-Title": "CapCode",
        }
    return AsyncOpenAI(
        api_key=key,
        base_url=base,
        default_headers=extra_headers,
        timeout=90.0,
        max_retries=0,
    )
