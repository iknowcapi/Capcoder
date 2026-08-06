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
SYSTEM_PLANNER = """You are the PLANNER. Given the chain history, write a tight PLAN describing what the NEXT gen should improve over its parents. Focus on WHAT changes and WHY, not HOW.

Output STRICT JSON only:
{
  "intent": "one sentence — what capability shift this gen embodies",
  "capability_focus": "which axis (visual identity | scoring rigor | philosophy | UX interaction | provider handling)",
  "constraints": "what must be preserved from parents"
}
"""

SYSTEM_ARCHITECT = """You are the ARCHITECT. Given the PLAN and chain history, output a concrete mutation SPEC. This spec is fed to a template renderer that writes real code.

Output STRICT JSON only:
{
  "name": "PascalCase, 1-2 words",
  "tagline": "one short line",
  "philosophy": "2 sentences",
  "improvement_note": "the concrete mutation applied",
  "accent_hex": "#rrggbb",
  "accent2_hex": "#rrggbb",
  "weights": {"helpfulness": 0.30-0.45, "correctness": 0.25-0.40, "coherence": 0.15-0.25, "complexity": 0.05-0.15, "verbosity": -0.10-0.00}
}
"""

SYSTEM_REVIEWER = """You are the REVIEWER. Identify 2-3 concrete weaknesses in the mutation spec (imbalanced weights, unclear improvement, palette clash, weak philosophy). One paragraph, no markdown, no preamble, under 100 words."""

SYSTEM_CORRECTOR = """You are the CORRECTOR. Given a spec and the reviewer's notes, output the SAME spec JSON with fixes applied. Preserve fields the reviewer didn't flag. Output STRICT JSON only, same schema as the input spec."""

# Legacy prompt retained for backwards-compat callers (unused after refactor).
SYSTEM_PROMPT = SYSTEM_ARCHITECT


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


async def _call_role(role: str, messages: list[dict], assignment: Optional[dict], **kwargs) -> Optional[str]:
    """Route a role call through its assigned provider/model with fallback."""
    a = assignment or _providers.DEFAULT_ASSIGNMENTS[role]
    fb = _providers.DEFAULT_ASSIGNMENTS.get(f"{role}_fallback", {"provider": "nvidia", "model": "z-ai/glm-5.1"})
    return await _chat(
        a["model"], messages, provider=a["provider"],
        fallback=(fb["provider"], fb["model"]), **kwargs,
    )


async def plan_step(history: list[dict], assignment: Optional[dict] = None) -> dict:
    raw = await _call_role(
        "planner",
        [{"role": "system", "content": SYSTEM_PLANNER},
         {"role": "user", "content": f"Chain so far:\n{_chain_brief(history)}\n\nWrite the PLAN as strict JSON."}],
        assignment, temperature=0.7, max_tokens=400,
    )
    return _extract_json(raw or "") or {"intent": "diverge in visual identity", "capability_focus": "visual identity", "constraints": "same core template"}


async def architect_step(plan: dict, history: list[dict], gen_number: int, assignment: Optional[dict] = None) -> Optional[dict]:
    user_msg = (
        f"Chain so far:\n{_chain_brief(history)}\n\n"
        f"PLAN:\n{json.dumps(plan, indent=2)}\n\n"
        f"Now output the mutation spec for Gen {gen_number}. Its accent_hex, weights and improvement_note "
        f"MUST differ meaningfully from every prior gen. Strict JSON."
    )
    raw = await _call_role(
        "architect",
        [{"role": "system", "content": SYSTEM_ARCHITECT}, {"role": "user", "content": user_msg}],
        assignment, temperature=0.9, max_tokens=700,
    )
    parsed = _extract_json(raw or "") if raw else {}
    return parsed if parsed.get("name") else None


async def review_step(spec: dict, assignment: Optional[dict] = None) -> Optional[str]:
    raw = await _call_role(
        "reviewer",
        [{"role": "system", "content": SYSTEM_REVIEWER},
         {"role": "user", "content": json.dumps({k: spec.get(k) for k in ("name","philosophy","improvement_note","accent_hex","accent2_hex","weights")}, indent=2)}],
        assignment, temperature=0.5, max_tokens=1200,
    )
    return raw.strip() if raw else None


async def correct_step(spec: dict, review: str, assignment: Optional[dict] = None) -> dict:
    if not review or "no issue" in (review or "").lower():
        return spec
    raw = await _call_role(
        "corrector",
        [{"role": "system", "content": SYSTEM_CORRECTOR},
         {"role": "user", "content": f"Spec:\n{json.dumps(spec, indent=2)}\n\nReviewer notes:\n{review}\n\nOutput the corrected spec as strict JSON."}],
        assignment, temperature=0.4, max_tokens=800,
    )
    fixed = _extract_json(raw or "") if raw else {}
    # merge: keep original fields, override with corrections
    if fixed and fixed.get("name"):
        return {**spec, **fixed}
    return spec


async def rate_step(spec: dict, assignment: Optional[dict] = None) -> Optional[dict]:
    rubric = (
        "Score on 5 dims (each 0.0-4.0). Output ONLY: "
        '{"helpfulness":0.0,"correctness":0.0,"coherence":0.0,"complexity":0.0,"verbosity":0.0}'
    )
    raw = await _call_role(
        "rater",
        [{"role": "system", "content": rubric},
         {"role": "user", "content": _gen_brief(spec, max_lines=20)}],
        assignment, temperature=0.1, max_tokens=3500,
    )
    data = _extract_json(raw or "") if raw else {}
    if not data:
        return None
    keys = ("helpfulness", "correctness", "coherence", "complexity", "verbosity")
    return {k: float(data.get(k, 0.0)) for k in keys}


# Legacy aliases (kept for any external caller)
generate_gen = architect_step  # signature differs; kept only for import safety
critique_gen = review_step
score_gen = rate_step


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


async def critique_gen_deprecated(gen: dict, assignment: Optional[dict] = None) -> Optional[str]:
    return await review_step(gen, assignment=assignment)


async def score_gen_deprecated(gen: dict, assignment: Optional[dict] = None) -> Optional[dict]:
    return await rate_step(gen, assignment=assignment)


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
    """Six-stage pipeline per generation:
       planner → architect → builder(deterministic) → reviewer → corrector → rater.
    Each stage's model is picked from `assignments`, falling back to DEFAULT_ASSIGNMENTS.
    """
    depth = max(1, min(5, int(depth)))
    a = dict(_providers.DEFAULT_ASSIGNMENTS)
    for role in ("planner", "architect", "builder", "reviewer", "corrector", "rater"):
        if assignments and assignments.get(role):
            a[role] = assignments[role]

    history: list[dict] = []
    generations: list[dict] = []
    fallback_used = False

    for i in range(depth):
        gen_number = i + 2
        stages: dict = {}

        # 1) planner
        plan = await plan_step(history, assignment=a["planner"])
        stages["plan"] = plan

        # 2) architect
        spec = await architect_step(plan, history, gen_number, assignment=a["architect"])
        if not spec:
            fallback_used = True
            spec = _fallback_gen(gen_number, history)
        stages["architect_spec"] = {k: spec.get(k) for k in spec if k != "files"}

        # 3) reviewer
        review = await review_step(spec, assignment=a["reviewer"])
        stages["review"] = review or ""

        # 4) corrector (skipped if review is empty/positive)
        if review:
            spec = await correct_step(spec, review, assignment=a["corrector"])
            stages["corrected_spec"] = {k: spec.get(k) for k in spec if k != "files"}

        # 5) builder — deterministic template render (uses builder model choice for metadata only)
        spec["files"] = seed_template.render(spec)
        stages["builder"] = {
            "role_model": a["builder"],
            "files": [{"path": f["path"], "lines": len(f["content"].splitlines())}
                      for f in spec["files"]],
        }

        # 6) rater
        scores = await rate_step(spec, assignment=a["rater"])
        spec["reward"] = scores or {"helpfulness": 0.0, "correctness": 0.0,
                                    "coherence": 0.0, "complexity": 0.0, "verbosity": 0.0}
        spec["composite_score"] = composite(spec["reward"])
        spec["gen"] = gen_number
        spec["critic_notes"] = review or "(reviewer unavailable)"
        spec["pipeline"] = stages
        spec["assignments"] = {k: a[k] for k in ("planner","architect","builder","reviewer","corrector","rater")}

        generations.append(spec)
        history.append({
            "gen": gen_number, "name": spec.get("name"),
            "improvement_note": spec.get("improvement_note", ""),
            "accent_hex": spec.get("accent_hex"), "accent2_hex": spec.get("accent2_hex"),
        })
        await on_gen(chain_id, spec, fallback_used)

    final = {
        "id": chain_id, "depth": depth, "fallback_used": fallback_used,
        "generations": generations,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await on_done(chain_id, final)
    return final


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
