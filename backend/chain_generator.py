"""
Chain-of-code-builders generator.

Each call to evolve_chain() asks NVIDIA NIM to produce a chain of N distinct
code-builder applications. Each gen is a real, runnable FastAPI+HTML project
that, when launched, ALSO calls an LLM to generate code in its own flavor.

There is no human input per generation — each gen's prompt is derived
automatically from the previous gen's description.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

import seed_template

logger = logging.getLogger("chain")

NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY", "").strip()
NIM_BASE_URL = "https://integrate.api.nvidia.com/v1"
GEN_MODEL = "z-ai/glm-5.1"
CRITIC_MODEL = "minimaxai/minimax-m2.7"
RATER_MODEL = "nvidia/llama-3.3-nemotron-super-49b-v1.5"

import providers as _providers

# Any provider having a key means we can evolve.
ENABLED = any(
    _providers.provider_available(p) for p in ("openrouter", "nvidia", "venice")
)


# ---------------------------------------------------------------------------
# LLM helper — dispatches to the correct provider per (provider, model) pair
# ---------------------------------------------------------------------------
_client_cache: dict[str, object] = {}


def _get_client(provider: str):
    if provider not in _client_cache:
        _client_cache[provider] = _providers.openai_client_for(provider)
    return _client_cache[provider]


async def _chat(
    model: str,
    messages: list[dict],
    provider: str = "nvidia",
    fallback: Optional[tuple[str, str]] = None,
    **kwargs,
) -> Optional[str]:
    """Call the given (provider, model). Falls back to `fallback=(provider,model)` on failure."""
    client = _get_client(provider)
    if client is None:
        if fallback:
            logger.info("provider %s unavailable, falling back to %s", provider, fallback[0])
            return await _chat(fallback[1], messages, provider=fallback[0], **kwargs)
        return None
    try:
        r = await client.chat.completions.create(model=model, messages=messages, **kwargs)
        msg = r.choices[0].message
        out = (msg.content or "").strip()
        if not out:
            reasoning = getattr(msg, "reasoning_content", None) or ""
            paras = [p.strip() for p in reasoning.split("\n\n") if p.strip()]
            out = paras[-1] if paras else reasoning.strip()
        return out
    except Exception as exc:
        logger.error("%s/%s call failed: %s", provider, model, exc)
        if fallback:
            logger.info("falling back to %s/%s", *fallback)
            return await _chat(fallback[1], messages, provider=fallback[0], **kwargs)
        return None


def _extract_json(raw: str) -> dict:
    raw = (raw or "").strip()
    if not raw:
        return {}
    # try fenced
    m = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", raw)
    cand = m.group(1) if m else None
    if cand is None:
        # find biggest balanced {...}
        start = raw.find("{")
        if start < 0:
            return {}
        depth = 0
        end = -1
        for i, c in enumerate(raw[start:], start=start):
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        cand = raw[start:end] if end > 0 else None
    if not cand:
        return {}
    try:
        return json.loads(cand)
    except Exception:
        # last resort: remove trailing commas
        try:
            cleaned = re.sub(r",\s*([}\]])", r"\1", cand)
            return json.loads(cleaned)
        except Exception:
            logger.warning("JSON parse failed on candidate: %s", cand[:200])
            return {}


# ---------------------------------------------------------------------------
# Generator prompt
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are RECURSIVE.BBS, an evolution engine. Each generation you design is a COMPLETE working replica of RECURSIVE.BBS — a real no-code code-builder application — with a distinct MUTATION vector applied.

The next gen you design will be turned into a full FastAPI + single-page-HTML folder (~350 lines of working code) via a canonical template. You do NOT write the code — you specify the mutation.

Output STRICT JSON ONLY. No prose. No fences. No trailing commas. Be creative but realistic:
{
  "name": "PascalCase, 1-2 words, distinct from every prior gen",
  "tagline": "one short line describing this gen's personality",
  "philosophy": "2 sentences. What this gen improves over its parent.",
  "improvement_note": "the concrete mutation applied — e.g. 'tighter scoring rubric that penalizes verbosity harder', 'inverted accent palette', 'added second critic pass for security', 'shifted weights toward correctness'",
  "accent_hex": "#rrggbb (primary phosphor color for the terminal UI)",
  "accent2_hex": "#rrggbb (secondary neon accent)",
  "weights": {
    "helpfulness": 0.30 to 0.45,
    "correctness": 0.25 to 0.40,
    "coherence":   0.15 to 0.25,
    "complexity":  0.05 to 0.15,
    "verbosity":  -0.10 to 0.00
  }
}

Weights should sum roughly to ~0.95 (verbosity is negative). Every gen MUST look and score meaningfully different from its ancestors.
"""


def _chain_brief(history: list[dict]) -> str:
    """Compact chain history for the next-gen prompt."""
    if not history:
        return (
            "(no prior descendants yet — you are designing Gen 2. "
            "The parent is RECURSIVE.BBS itself: dark BBS terminal UI, "
            "accent_hex=#7cffb2, accent2_hex=#ff79c6, standard weights "
            "helpfulness=0.35, correctness=0.30, coherence=0.20, complexity=0.10, verbosity=-0.05.)"
        )
    lines = []
    for g in history:
        lines.append(
            f"- Gen {g['gen']}: {g.get('name','?')} — {g.get('improvement_note','')}"
            f" [accent {g.get('accent_hex','?')}/{g.get('accent2_hex','?')}]"
        )
    return "\n".join(lines)


async def generate_gen(
    history: list[dict], gen_number: int, assignment: Optional[dict] = None
) -> Optional[dict]:
    """Ask the assigned generator model to design the next gen's MUTATION."""
    user_msg = (
        f"Chain so far:\n{_chain_brief(history)}\n\n"
        f"Now design Gen {gen_number}. Its mutation MUST differ meaningfully from every prior "
        f"gen (different accent colors, different scoring emphasis, different improvement note). "
        f"Output strict JSON per the schema."
    )
    a = assignment or _providers.DEFAULT_ASSIGNMENTS["generator"]
    fb = _providers.DEFAULT_ASSIGNMENTS["generator_fallback"]
    raw = await _chat(
        a["model"],
        [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user_msg}],
        provider=a["provider"],
        fallback=(fb["provider"], fb["model"]),
        temperature=0.9,
        max_tokens=700,
    )
    if not raw:
        return None
    parsed = _extract_json(raw)
    if not parsed.get("name"):
        logger.warning("gen %s: no name in parsed output. raw head: %r", gen_number, raw[:200])
        return None
    parsed["files"] = seed_template.render(parsed)
    return parsed


# ---------------------------------------------------------------------------
# Critic + rater
# ---------------------------------------------------------------------------
def _gen_brief(gen: dict, max_files: int = 3, max_lines: int = 25) -> str:
    lines = [
        f"# {gen.get('name','app')} (Gen {gen.get('gen','?')})",
        f"tagline: {gen.get('tagline','')}",
        f"philosophy: {gen.get('philosophy','')}",
        f"improvement_note: {gen.get('improvement_note','')}",
        f"accents: {gen.get('accent_hex','?')} / {gen.get('accent2_hex','?')}",
        f"weights: {gen.get('weights','?')}",
        "\n## File previews",
    ]
    for f in gen.get("files", [])[:max_files]:
        head = "\n".join(f["content"].splitlines()[:max_lines])
        lines.append(f"\n--- {f['path']} (head) ---\n{head}")
    return "\n".join(lines)


async def critique_gen(gen: dict, assignment: Optional[dict] = None) -> Optional[str]:
    a = assignment or _providers.DEFAULT_ASSIGNMENTS["critic"]
    fb = _providers.DEFAULT_ASSIGNMENTS["critic_fallback"]
    raw = await _chat(
        a["model"],
        [
            {
                "role": "system",
                "content": (
                    "You are a code reviewer. Identify 2-3 concrete weaknesses in this "
                    "generated code-builder app (missing endpoints, schema gaps, runtime "
                    "bugs, UX issues, weak prompt-handling). One paragraph, no markdown, "
                    "no preamble, under 100 words."
                ),
            },
            {"role": "user", "content": _gen_brief(gen)},
        ],
        provider=a["provider"],
        fallback=(fb["provider"], fb["model"]),
        temperature=0.5,
        max_tokens=1200,
    )
    return raw.strip() if raw else None


async def score_gen(gen: dict, assignment: Optional[dict] = None) -> Optional[dict]:
    a = assignment or _providers.DEFAULT_ASSIGNMENTS["rater"]
    fb = _providers.DEFAULT_ASSIGNMENTS["rater_fallback"]
    rubric = (
        "Score the generated code-builder app on 5 dimensions, each 0.0-4.0. Output ONLY this "
        'JSON: {"helpfulness":0.0,"correctness":0.0,"coherence":0.0,"complexity":0.0,"verbosity":0.0}'
    )
    raw = await _chat(
        a["model"],
        [
            {"role": "system", "content": rubric},
            {"role": "user", "content": _gen_brief(gen, max_lines=20)},
        ],
        provider=a["provider"],
        fallback=(fb["provider"], fb["model"]),
        temperature=0.1,
        max_tokens=3500,
    )
    if not raw:
        return None
    data = _extract_json(raw)
    if not data:
        return None
    keys = ("helpfulness", "correctness", "coherence", "complexity", "verbosity")
    return {k: float(data.get(k, 0.0)) for k in keys}


def composite(scores: dict) -> float:
    return round(
        0.35 * scores.get("helpfulness", 0)
        + 0.30 * scores.get("correctness", 0)
        + 0.20 * scores.get("coherence", 0)
        + 0.10 * scores.get("complexity", 0)
        - 0.05 * abs(scores.get("verbosity", 2) - 2.0),
        3,
    )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
async def evolve_chain_with_callback(
    chain_id: str, depth: int, on_gen, on_done, assignments: Optional[dict] = None
) -> dict:
    """Run the evolution loop and call `on_gen(gen_dict)` after each generation completes,
    and `on_done(chain_dict)` when finished. `assignments` is a dict:
        {"generator": {"provider":"...","model":"..."},
         "critic":    {"provider":"...","model":"..."},
         "rater":     {"provider":"...","model":"..."}}
    Missing keys fall back to DEFAULT_ASSIGNMENTS.
    """
    depth = max(1, min(5, int(depth)))
    a = dict(_providers.DEFAULT_ASSIGNMENTS)
    for role in ("generator", "critic", "rater"):
        if assignments and assignments.get(role):
            a[role] = assignments[role]
    history: list[dict] = []
    generations: list[dict] = []
    fallback_used = False

    for i in range(depth):
        gen_number = i + 2
        gen = await generate_gen(history, gen_number, assignment=a["generator"])
        if not gen:
            fallback_used = True
            gen = _fallback_gen(gen_number, history)
        gen["gen"] = gen_number
        critic, scores = await asyncio.gather(
            critique_gen(gen, assignment=a["critic"]),
            score_gen(gen, assignment=a["rater"]),
            return_exceptions=False,
        )
        gen["critic_notes"] = critic or "(critic unavailable for this generation)"
        gen["reward"] = scores or {
            "helpfulness": 0.0, "correctness": 0.0, "coherence": 0.0,
            "complexity": 0.0, "verbosity": 0.0,
        }
        gen["composite_score"] = composite(gen["reward"])
        generations.append(gen)
        history.append({
            "gen": gen_number,
            "name": gen.get("name"),
            "improvement_note": gen.get("improvement_note", ""),
            "accent_hex": gen.get("accent_hex"),
            "accent2_hex": gen.get("accent2_hex"),
        })
        await on_gen(chain_id, gen, fallback_used)

    final = {
        "id": chain_id, "depth": depth, "fallback_used": fallback_used,
        "generations": generations,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await on_done(chain_id, final)
    return final


async def evolve_chain(depth: int = 3) -> dict:
    """Generate a chain of N code-builders (gen 2 through gen N+1). Returns full chain doc."""
    depth = max(1, min(5, int(depth)))
    chain_id = str(uuid.uuid4())
    history: list[dict] = []
    generations: list[dict] = []
    fallback_used = False

    for i in range(depth):
        gen_number = i + 2  # Gen 1 is RECURSIVE.BBS itself
        gen = await generate_gen(history, gen_number)
        if not gen:
            # fallback: minimal deterministic stub so the chain still produces something
            fallback_used = True
            gen = _fallback_gen(gen_number, history)

        gen["gen"] = gen_number
        # critic + rater in parallel
        critic, scores = await asyncio.gather(
            critique_gen(gen),
            score_gen(gen),
            return_exceptions=False,
        )
        gen["critic_notes"] = critic or "(critic unavailable for this generation)"
        gen["reward"] = scores or {
            "helpfulness": 0.0,
            "correctness": 0.0,
            "coherence": 0.0,
            "complexity": 0.0,
            "verbosity": 0.0,
        }
        gen["composite_score"] = composite(gen["reward"])
        generations.append(gen)
        history.append(
            {
                "gen": gen_number,
                "name": gen.get("name"),
                "improvement_note": gen.get("improvement_note", ""),
                "accent_hex": gen.get("accent_hex"),
                "accent2_hex": gen.get("accent2_hex"),
            }
        )

    return {
        "id": chain_id,
        "depth": depth,
        "fallback_used": fallback_used,
        "generations": generations,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Fallback (only used if the LLM call fails outright)
# ---------------------------------------------------------------------------
def _fallback_gen(n: int, history: list[dict]) -> dict:
    """Deterministic mutation applied via the same seed template."""
    import random as _rand

    rng = _rand.Random(n * 37 + len(history))
    palettes = [
        ("#7cffb2", "#ff79c6"), ("#39ffea", "#ffea00"),
        ("#ff8c66", "#bbf7d0"), ("#c084fc", "#fde047"),
        ("#f472b6", "#67e8f9"),
    ]
    a1, a2 = rng.choice(palettes)
    mutation = {
        "name": f"AutoGen{n}",
        "tagline": "a deterministically mutated replica",
        "philosophy": "Auto-mutated descendant produced when the upstream LLM was unreachable.",
        "improvement_note": "shifted accent palette and rebalanced scoring weights deterministically",
        "accent_hex": a1,
        "accent2_hex": a2,
        "weights": {
            "helpfulness": round(0.35 + rng.uniform(-0.05, 0.05), 2),
            "correctness": round(0.30 + rng.uniform(-0.05, 0.05), 2),
            "coherence":   round(0.20 + rng.uniform(-0.05, 0.05), 2),
            "complexity":  round(0.10 + rng.uniform(-0.03, 0.05), 2),
            "verbosity":  round(-0.05 + rng.uniform(-0.03, 0.03), 2),
        },
    }
    mutation["files"] = seed_template.render(mutation)
    return mutation
