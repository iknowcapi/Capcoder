"""
CapCode — recursive bot-builder pipeline.

STRICT topology (as requested by the user):
    Human target prompt
        -> TEACHER bot   (rigid, strict, uses top-verified prior chains as exemplars)
        -> ARTIST  bot   (creative, novel product design following the Teacher's brief)
        -> PRODUCT       (rendered downloadable code folder + one correction pass on failure)
        -> RATER         (5-dim scorecard)

No 6-role dev-team. No plan/architect/builder split. One human input, three bots.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

import seed_template
import executor as _exec
import providers as _providers

logger = logging.getLogger("chain")

# Any provider having a key means we can evolve.
ENABLED = any(_providers.provider_available(p) for p in ("openrouter", "nvidia", "venice"))


# ---------------------------------------------------------------------------
# LLM helper
# ---------------------------------------------------------------------------
_client_cache: dict[str, object] = {}


def _get_client(provider: str):
    if provider not in _client_cache:
        _client_cache[provider] = _providers.openai_client_for(provider)
    return _client_cache[provider]


async def _chat(model: str, messages: list[dict], provider: str = "nvidia",
                fallback: Optional[tuple[str, str]] = None, **kwargs) -> Optional[str]:
    client = _get_client(provider)
    if client is None:
        if fallback:
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
            return await _chat(fallback[1], messages, provider=fallback[0], **kwargs)
        return None


def _extract_json(raw: str) -> dict:
    raw = (raw or "").strip()
    if not raw:
        return {}
    m = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", raw)
    cand = m.group(1) if m else None
    if cand is None:
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
        try:
            return json.loads(re.sub(r",\s*([}\]])", r"\1", cand))
        except Exception:
            logger.warning("JSON parse failed: %s", cand[:200])
            return {}


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------
SYSTEM_TEACHER = """You are the TEACHER — Bot 1 in CapCode's two-bot chain. Rigid, strict, provider-educated. Given the HUMAN TARGET (the app they want built), you design a spec for the ARTIST BOT that will actually construct it. You do NOT design the product yourself — you design the second bot's brief.

Detect the correct stack from the target (python/fastapi, node/vite/react, rust/cargo, go, webgl/html). Default to python-fastapi if unclear.

You are shown TOP-VERIFIED PRIOR CHAINS as exemplars (human-marked as "works"). Learn from their patterns.

Output STRICT JSON only:
{
  "name": "TeacherSpec-<short-name>",
  "target": "<echo of the human's target>",
  "stack": "python-fastapi | node-vite | rust | go | webgl",
  "artist_brief": "3-5 sentences briefing the Artist on what to build",
  "must_have": ["3-5 concrete requirements the product MUST satisfy"],
  "should_avoid": ["2-3 anti-patterns"],
  "accent_hex": "#rrggbb",
  "accent2_hex": "#rrggbb"
}
"""

SYSTEM_ARTIST = """You are the ARTIST — Bot 2 in CapCode's two-bot chain. Creative, sharp, novel. Given the Teacher's spec you design the actual PRODUCT (the thing the human asked for). Make it stand out while satisfying every must_have.

Output STRICT JSON only:
{
  "name": "PascalCase product name",
  "tagline": "one line",
  "philosophy": "2 sentences — your creative angle",
  "improvement_note": "how you satisfied the Teacher's must_have while adding novelty",
  "stack": "<echo the teacher's stack>",
  "accent_hex": "#rrggbb",
  "accent2_hex": "#rrggbb",
  "weights": {"helpfulness":0.35,"correctness":0.30,"coherence":0.20,"complexity":0.10,"verbosity":-0.05}
}
"""

SYSTEM_CORRECTOR = """You are the CORRECTOR. The generated app FAILED TO START. Given the product spec + real stderr, output the CORRECTED spec JSON (same schema). Focus on the smallest change that makes it LOAD."""

SYSTEM_RATER = ('Score on 5 dims (each 0.0-4.0). Output ONLY: '
                '{"helpfulness":0.0,"correctness":0.0,"coherence":0.0,"complexity":0.0,"verbosity":0.0}')


# ---------------------------------------------------------------------------
# Bot steps
# ---------------------------------------------------------------------------
async def _call_role(role: str, messages: list[dict], assignment: Optional[dict], **kwargs) -> Optional[str]:
    a = assignment or _providers.DEFAULT_ASSIGNMENTS[role]
    fb = _providers.DEFAULT_ASSIGNMENTS.get(f"{role}_fallback", {"provider": "nvidia", "model": "z-ai/glm-5.1"})
    return await _chat(a["model"], messages, provider=a["provider"],
                       fallback=(fb["provider"], fb["model"]), **kwargs)


async def teacher_step(target: str, exemplars: list[dict], assignment: Optional[dict] = None) -> dict:
    exemplar_block = "\n\n".join(
        f"[verified — target: {e.get('target','?')} — product: {e.get('name','?')}]\n"
        f"artist_brief was: {e.get('artist_brief','?')}"
        for e in exemplars[:3]
    ) or "(no verified exemplars yet — apply first principles)"
    raw = await _call_role(
        "teacher",
        [{"role": "system", "content": SYSTEM_TEACHER},
         {"role": "user", "content":
             f"HUMAN TARGET:\n{target}\n\nTOP-VERIFIED PRIOR CHAINS:\n{exemplar_block}\n\n"
             f"Design the Teacher spec as strict JSON."}],
        assignment, temperature=0.4, max_tokens=800,
    )
    parsed = _extract_json(raw or "") or {}
    parsed.setdefault("target", target)
    parsed.setdefault("name", f"TeacherSpec-{target[:20]}")
    parsed.setdefault("stack", "python-fastapi")
    parsed.setdefault("artist_brief", f"Build: {target}. Keep it minimal and runnable.")
    parsed.setdefault("must_have", ["compiles/starts", "single-command run", "clear README"])
    parsed.setdefault("should_avoid", ["over-engineering"])
    parsed.setdefault("accent_hex", "#7cffb2")
    parsed.setdefault("accent2_hex", "#ff79c6")
    return parsed


async def artist_step(teacher_spec: dict, assignment: Optional[dict] = None) -> dict:
    raw = await _call_role(
        "artist",
        [{"role": "system", "content": SYSTEM_ARTIST},
         {"role": "user", "content":
             f"TEACHER SPEC:\n{json.dumps(teacher_spec, indent=2)}\n\n"
             f"Design the product as strict JSON."}],
        assignment, temperature=0.8, max_tokens=500,
    )
    parsed = _extract_json(raw or "") or {}
    # ensure required fields exist
    parsed.setdefault("name", f"Product-{teacher_spec.get('target','app')[:20]}")
    parsed.setdefault("tagline", "an app built by CapCode")
    parsed.setdefault("philosophy", "Minimal, working, downloadable.")
    parsed.setdefault("improvement_note", "meets the Teacher's brief")
    parsed.setdefault("stack", teacher_spec.get("stack", "python-fastapi"))
    parsed.setdefault("accent_hex", teacher_spec.get("accent_hex", "#7cffb2"))
    parsed.setdefault("accent2_hex", teacher_spec.get("accent2_hex", "#ff79c6"))
    parsed.setdefault("weights", {"helpfulness": 0.35, "correctness": 0.30,
                                  "coherence": 0.20, "complexity": 0.10, "verbosity": -0.05})
    return parsed


async def correct_step(spec: dict, stderr: str, assignment: Optional[dict] = None) -> dict:
    prompt = (f"Spec:\n{json.dumps({k: spec.get(k) for k in ('name','philosophy','improvement_note','stack','weights')}, indent=2)}"
              f"\n\nSTDERR:\n{stderr[-1500:]}\n\nOutput the corrected spec JSON.")
    raw = await _call_role(
        "artist",  # corrector reuses the artist's model
        [{"role": "system", "content": SYSTEM_CORRECTOR},
         {"role": "user", "content": prompt}],
        assignment, temperature=0.3, max_tokens=800,
    )
    fixed = _extract_json(raw or "") if raw else {}
    if fixed and fixed.get("name"):
        return {**spec, **{k: v for k, v in fixed.items() if k != "files"}}
    return spec


async def rate_step(spec: dict, exec_result: dict, assignment: Optional[dict] = None) -> dict:
    brief = json.dumps({
        "name": spec.get("name"), "philosophy": spec.get("philosophy"),
        "improvement_note": spec.get("improvement_note"),
        "exec_started": exec_result.get("started"),
        "exec_error_tail": (exec_result.get("stderr") or "")[-300:],
    }, indent=2)
    raw = await _call_role(
        "rater",
        [{"role": "system", "content": SYSTEM_RATER},
         {"role": "user", "content": brief}],
        assignment, temperature=0.1, max_tokens=2000,
    )
    data = _extract_json(raw or "") if raw else {}
    keys = ("helpfulness", "correctness", "coherence", "complexity", "verbosity")
    if not data:
        # deterministic fallback based on whether it ran
        started = bool(exec_result.get("started"))
        base = 2.8 if started else 1.2
        return {k: base for k in keys}
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
    chain_id: str,
    target_prompt: str,
    on_gen,
    on_done,
    assignments: Optional[dict] = None,
    exemplars: Optional[list[dict]] = None,
) -> dict:
    """One chain = one product build:
       Human target -> Teacher spec -> Artist product -> Executor (+ 1 correction) -> Rater.
    """
    a = dict(_providers.DEFAULT_ASSIGNMENTS)
    for role in ("teacher", "artist", "rater"):
        if assignments and assignments.get(role):
            a[role] = assignments[role]

    exemplars = exemplars or []
    fallback_used = False

    # 1) TEACHER
    teacher_spec = await teacher_step(target_prompt, exemplars, assignment=a["teacher"])

    # 2) ARTIST
    artist_spec = await artist_step(teacher_spec, assignment=a["artist"])

    # 3) BUILD PRODUCT (deterministic template render, driven by artist_spec + teacher.stack)
    product = dict(artist_spec)
    product["target_prompt"] = target_prompt
    product["teacher_spec"] = teacher_spec
    product["artist_spec"] = {k: v for k, v in artist_spec.items() if k != "files"}
    product["files"] = seed_template.render(product, stack=product.get("stack") or teacher_spec.get("stack"))

    # 4) EXECUTOR
    workspace = _exec.materialize(chain_id, product)
    exec_result = await _exec.run_workspace(workspace, timeout=20, port_to_check=8123)
    product["exec"] = exec_result

    # 5) ONE correction pass if it failed to start
    if not exec_result.get("started") and exec_result.get("stderr"):
        fallback_used = True
        product = await correct_step(product, exec_result["stderr"], assignment=a["artist"])
        product["files"] = seed_template.render(product, stack=product.get("stack"))
        workspace = _exec.materialize(chain_id, product)
        exec_result = await _exec.run_workspace(workspace, timeout=20, port_to_check=8124)
        product["exec"] = exec_result

    # 6) RATER
    scores = await rate_step(product, exec_result, assignment=a["rater"])
    product["reward"] = scores
    product["composite_score"] = composite(scores)
    product["gen"] = 1
    product["critic_notes"] = (
        f"Ran: {exec_result.get('started')}. "
        f"Exit: {exec_result.get('exit_code')}. "
        f"Port listening: {exec_result.get('port_listening')}."
    )
    product["assignments"] = {k: a[k] for k in ("teacher", "artist", "rater")}

    await on_gen(chain_id, product, fallback_used)

    final = {
        "id": chain_id,
        "target_prompt": target_prompt,
        "depth": 1,
        "fallback_used": fallback_used,
        "generations": [product],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await on_done(chain_id, final)
    return final
