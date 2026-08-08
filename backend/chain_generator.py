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
import coverage as _coverage

logger = logging.getLogger("chain")

# Any provider having a key means we can evolve.
ENABLED = any(_providers.provider_available(p) for p in ("openrouter", "nvidia", "venice"))


# ---------------------------------------------------------------------------
# Per-chain stream broadcasters (SSE) — one asyncio.Queue per active chain
# ---------------------------------------------------------------------------
import asyncio
_stream_queues: dict[str, asyncio.Queue] = {}


def get_stream_queue(chain_id: str) -> asyncio.Queue:
    q = _stream_queues.get(chain_id)
    if q is None:
        q = asyncio.Queue()
        _stream_queues[chain_id] = q
    return q


def close_stream(chain_id: str):
    q = _stream_queues.pop(chain_id, None)
    if q is not None:
        try:
            q.put_nowait({"event": "done"})
        except Exception:
            pass


async def _emit(chain_id: Optional[str], event: str, data):
    if not chain_id:
        return
    q = _stream_queues.get(chain_id)
    if q is None:
        return
    try:
        q.put_nowait({"event": event, "data": data})
    except Exception:
        pass


# ---------------------------------------------------------------------------
# LLM helper
# ---------------------------------------------------------------------------
def _client_for(provider: str, user_keys: Optional[dict] = None):
    """Fresh client if user provided BYOK for this provider, else cached env client."""
    user_key = (user_keys or {}).get(provider) if user_keys else None
    if user_key:
        return _providers.openai_client_for(provider, api_key=user_key)
    if provider not in _client_cache:
        _client_cache[provider] = _providers.openai_client_for(provider)
    return _client_cache[provider]


_client_cache: dict[str, object] = {}


async def _chat(model: str, messages: list[dict], provider: str = "nvidia",
                fallback: Optional[tuple[str, str]] = None,
                user_keys: Optional[dict] = None,
                stream_chain_id: Optional[str] = None,
                stream_event: Optional[str] = None,
                **kwargs) -> Optional[str]:
    client = _client_for(provider, user_keys)
    if client is None:
        if fallback:
            return await _chat(fallback[1], messages, provider=fallback[0],
                               user_keys=user_keys,
                               stream_chain_id=stream_chain_id,
                               stream_event=stream_event, **kwargs)
        return None
    do_stream = bool(stream_chain_id and stream_event)
    try:
        if do_stream:
            # Streaming path — accumulate content, emit deltas over SSE.
            stream = await client.chat.completions.create(
                model=model, messages=messages, stream=True, **kwargs)
            buf = []
            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                piece = getattr(delta, "content", None) or ""
                if piece:
                    buf.append(piece)
                    await _emit(stream_chain_id, stream_event, piece)
            out = "".join(buf).strip()
            return out
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
            return await _chat(fallback[1], messages, provider=fallback[0],
                               user_keys=user_keys,
                               stream_chain_id=stream_chain_id,
                               stream_event=stream_event, **kwargs)
        return None


def _repair_truncated_json(raw: str, start: int) -> str | None:
    """When a model hits max_tokens mid-JSON, close the open string/braces so
    the partial output still parses. Returns a repaired candidate or None."""
    depth = 0
    in_str = False
    esc = False
    last_complete_end = -1
    for i in range(start, len(raw)):
        c = raw[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "{" or c == "[":
                depth += 1
            elif c == "}" or c == "]":
                depth -= 1
                if depth == 0:
                    last_complete_end = i + 1
    if last_complete_end > 0 and last_complete_end == len(raw):
        return None  # complete, no repair needed
    # Truncated. Close the open string (if any) then close remaining braces/brackets.
    # Track brace/bracket types to close them in reverse order.
    stack: list[str] = []
    in_str = False
    esc = False
    for i in range(start, len(raw)):
        c = raw[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "{":
                stack.append("}")
            elif c == "[":
                stack.append("]")
            elif c == "}" or c == "]":
                if stack:
                    stack.pop()
    if not stack and not in_str:
        return None
    tail = raw[start:]
    # Drop a trailing partial token like `"conten` or `"content": "hello wo` — cut at
    # the last comma or opening-brace so we don't leave a dangling field.
    # Strategy: if we're inside a string, close it. Then remove any dangling
    # `"key":` or trailing comma at end.
    if in_str:
        # find the position of the opening quote of the unfinished string
        # so we can drop the whole partial field to keep JSON valid.
        depth2 = 0
        in_s2 = False
        esc2 = False
        last_boundary = -1  # position of last comma or `{` or `[` at depth root
        open_quote_pos = -1
        for j in range(len(tail)):
            c = tail[j]
            if in_s2:
                if esc2:
                    esc2 = False
                elif c == "\\":
                    esc2 = True
                elif c == '"':
                    in_s2 = False
            else:
                if c == '"':
                    in_s2 = True
                    if j > 0:
                        open_quote_pos = j
                elif c in ("{", "[", ","):
                    last_boundary = j
                elif c in ("}", "]"):
                    pass
        # Prefer cutting at the last boundary before the unclosed string.
        cut = last_boundary if 0 <= last_boundary < open_quote_pos else open_quote_pos
        if cut > 0:
            tail = tail[:cut]
    # strip trailing dangling `"key":` or `,` or whitespace
    tail = re.sub(r"[\s,]*\"?[A-Za-z_][A-Za-z0-9_]*\"?\s*:\s*$", "", tail)
    tail = re.sub(r"[\s,]+$", "", tail)
    # Recompute what still needs closing.
    stack = []
    in_str = False
    esc = False
    for c in tail:
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "{":
                stack.append("}")
            elif c == "[":
                stack.append("]")
            elif c in ("}", "]") and stack:
                stack.pop()
    if in_str:
        tail += '"'
    tail += "".join(reversed(stack))
    return tail


def _extract_json(raw: str) -> dict:
    """Extract the first top-level JSON object from a model response.
    Tracks string state so braces inside string literals don't fool the parser.
    Also attempts repair on truncated (max_tokens hit) responses."""
    raw = (raw or "").strip()
    if not raw:
        return {}
    # If wrapped in a ```json fenced block, extract that first.
    m = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", raw)
    candidates = []
    if m:
        candidates.append(m.group(1))
    start = raw.find("{")
    if start >= 0:
        depth = 0
        in_str = False
        esc = False
        end = -1
        for i in range(start, len(raw)):
            c = raw[i]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
            else:
                if c == '"':
                    in_str = True
                elif c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
        if end > 0:
            candidates.append(raw[start:end])
        # ALSO try repairing truncated JSON
        repaired = _repair_truncated_json(raw, start)
        if repaired:
            candidates.append(repaired)
    for cand in candidates:
        try:
            return json.loads(cand, strict=False)
        except Exception:
            try:
                return json.loads(re.sub(r",\s*([}\]])", r"\1", cand), strict=False)
            except Exception:
                continue
    logger.warning("JSON parse failed. head: %s | tail: %s", raw[:200], raw[-200:])
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

SYSTEM_ARTIST = """You are the ARTIST — Bot 2 in CapCode's two-bot chain. Creative, sharp, novel. Given the Teacher's spec you WRITE THE ACTUAL SOURCE CODE for the app the human asked for. Do not describe. Do not hand-wave. Write real, runnable files.

Every string in `files[].content` MUST be complete source code — no "..." placeholders, no "TODO" stubs, no imports of packages you don't declare, no fake API keys. The app must start with a single `bash run.sh` and satisfy every must_have in the Teacher spec.

Stack-specific rules:
  - python-fastapi : include backend/server.py (FastAPI app with a real /api route that DOES the thing), backend/requirements.txt, run.sh (uvicorn on $APP_PORT). Optional frontend/index.html.
  - node-vite      : include src/main.jsx (real React with real state/fetch/UI for the request), index.html, package.json (with correct deps), vite.config.js, run.sh (npm install + vite --host --port $APP_PORT). NO server-side rendering.
  - rust           : include Cargo.toml, src/main.rs (real logic), run.sh (cargo run).
  - go             : include go.mod, main.go (real logic), run.sh (go run main.go).
  - webgl          : include a single self-contained index.html with real inline JS doing the requested thing, run.sh (python3 -m http.server $APP_PORT).

For anything that needs a public API (prices, weather, quotes, jokes, etc), pick a well-known keyless public endpoint (CoinGecko, wttr.in, jsonplaceholder, etc). Never invent endpoints.

Output STRICT JSON only — no prose before or after:
{
  "name": "PascalCase product name",
  "tagline": "one line",
  "philosophy": "2 sentences — your creative angle",
  "improvement_note": "how you satisfied the Teacher's must_have while adding novelty",
  "stack": "<echo the teacher's stack>",
  "accent_hex": "#rrggbb",
  "accent2_hex": "#rrggbb",
  "files": [
    {"path": "relative/path.ext", "content": "FULL FILE CONTENT — no ellipsis"},
    ...
  ],
  "weights": {"helpfulness":0.35,"correctness":0.30,"coherence":0.20,"complexity":0.10,"verbosity":-0.05}
}
"""

SYSTEM_CORRECTOR = """You are the CORRECTOR. The generated app FAILED TO START — given the source files and the real stderr, output the CORRECTED JSON (same schema as the Artist, including a `files` array). Focus on the smallest edits that make it start. Rewrite only the files that need to change; you may include unchanged files verbatim."""

SYSTEM_RATER = (
    "You are a strict code-quality rater. Given a short brief about a build, "
    "score it on FIVE dimensions, each on a 0.0-4.0 scale where 4.0 is excellent "
    "and 0.0 is broken. Base your score on the brief, not on any example. "
    "Dimensions:\n"
    "  helpfulness — does it plausibly do what the target asked?\n"
    "  correctness — did the app start and run?\n"
    "  coherence  — is the design consistent?\n"
    "  complexity — depth/ambition (higher = more ambitious).\n"
    "  verbosity  — length appropriateness (2.0 = right-sized).\n"
    "Output ONLY a JSON object with these five numeric keys, e.g. "
    '{"helpfulness":2.7,"correctness":3.2,"coherence":2.5,"complexity":1.9,"verbosity":2.1}. '
    "Pick real, differentiated numbers — do not repeat the example."
)


# ---------------------------------------------------------------------------
# Bot steps
# ---------------------------------------------------------------------------
async def _call_role(role: str, messages: list[dict], assignment: Optional[dict],
                     user_keys: Optional[dict] = None,
                     stream_chain_id: Optional[str] = None,
                     stream_event: Optional[str] = None,
                     **kwargs) -> Optional[str]:
    a = assignment or _providers.DEFAULT_ASSIGNMENTS[role]
    fb = _providers.DEFAULT_ASSIGNMENTS.get(f"{role}_fallback", {"provider": "nvidia", "model": "z-ai/glm-5.1"})
    return await _chat(a["model"], messages, provider=a["provider"],
                       fallback=(fb["provider"], fb["model"]),
                       user_keys=user_keys,
                       stream_chain_id=stream_chain_id,
                       stream_event=stream_event, **kwargs)


async def teacher_step(target: str, exemplars: list[dict], assignment: Optional[dict] = None,
                       user_keys: Optional[dict] = None, chain_id: Optional[str] = None) -> dict:
    exemplar_block = "\n\n".join(
        f"[verified — target: {e.get('target','?')} — product: {e.get('name','?')}]\n"
        f"artist_brief was: {e.get('artist_brief','?')}"
        for e in exemplars[:3]
    ) or "(no verified exemplars yet — apply first principles)"
    await _emit(chain_id, "stage", "teacher")
    raw = await _call_role(
        "teacher",
        [{"role": "system", "content": SYSTEM_TEACHER},
         {"role": "user", "content":
             f"HUMAN TARGET:\n{target}\n\nTOP-VERIFIED PRIOR CHAINS:\n{exemplar_block}\n\n"
             f"Design the Teacher spec as strict JSON."}],
        assignment, user_keys=user_keys,
        stream_chain_id=chain_id, stream_event="teacher_delta",
        temperature=0.4, max_tokens=800,
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


class ArtistFailedError(Exception):
    """Raised when the Artist cannot produce a real file set after retries."""


async def artist_step(teacher_spec: dict, exemplar_files: Optional[list[dict]] = None,
                      assignment: Optional[dict] = None,
                      user_keys: Optional[dict] = None,
                      chain_id: Optional[str] = None) -> dict:
    parsed: dict = {}
    raw = ""
    exemplar_block = ""
    if exemplar_files:
        # For each exemplar we send the FULL content of its SMALLEST file
        # (usually the main entry — most instructive) plus the full file layout.
        # Total per exemplar is capped so the prompt stays sane.
        MAX_PER_EXEMPLAR = 6000
        parts = []
        for i, ex in enumerate(exemplar_files[:2], 1):
            files_by_size = sorted(
                [f for f in (ex.get("files") or []) if isinstance(f, dict) and f.get("content")],
                key=lambda f: len(f.get("content", "")),
            )
            if not files_by_size:
                continue
            layout = "\n".join(f"  - {f['path']} ({len(f.get('content',''))} chars)"
                               for f in ex.get("files", [])[:15])
            main = files_by_size[0]  # smallest = usually the entry point
            main_content = main.get("content", "")[:MAX_PER_EXEMPLAR]
            parts.append(
                f"### Verified exemplar {i}\n"
                f"target: {ex.get('target','?')}\n"
                f"stack: {ex.get('stack','?')}\n"
                f"file layout:\n{layout}\n"
                f"full content of {main['path']} (copy patterns, adapt to the new target):\n"
                f"```\n{main_content}\n```"
            )
        exemplar_block = "\n\n".join(parts)

    await _emit(chain_id, "stage", "artist")
    for attempt in range(3):
        directive = ("Write the source files as strict JSON. Include the FULL content of every "
                     "file — no ellipsis, no TODOs.")
        if attempt == 1:
            directive += (" Your last response was truncated — be TERSER. 3-4 files max, ≤150 lines each."
                          " Prioritize a working minimum over completeness.")
        if attempt == 2:
            directive += (" Third attempt. Output the tiniest possible working version — one main file,"
                          " ≤120 lines, plus run.sh. Skip README, skip niceties.")
        user_msg = f"TEACHER SPEC:\n{json.dumps(teacher_spec, indent=2)}\n\n"
        if exemplar_block:
            user_msg += (
                "PRIOR VERIFIED WORKING BUILDS FOR SIMILAR TARGETS (learn from these file structures):\n"
                f"{exemplar_block}\n\n"
            )
        user_msg += directive
        if attempt > 0:
            await _emit(chain_id, "stage", f"artist-retry-{attempt}")
        raw = await _call_role(
            "artist",
            [{"role": "system", "content": SYSTEM_ARTIST},
             {"role": "user", "content": user_msg}],
            assignment,
            user_keys=user_keys,
            stream_chain_id=chain_id, stream_event="artist_delta",
            temperature=(0.7, 0.4, 0.2)[attempt],
            max_tokens=(12000, 8000, 4000)[attempt],
        )
        parsed = _extract_json(raw or "") or {}
        logger.info("ARTIST attempt=%d raw_len=%d keys=%s files=%d",
                    attempt, len(raw or ""), list(parsed.keys()),
                    len(parsed.get("files") or []))
        if parsed.get("files"):
            break
        if not parsed:
            try:
                Path(f"/tmp/artist_raw_attempt{attempt}.txt").write_text(raw or "")
            except Exception:
                pass

    if not parsed.get("files"):
        raise ArtistFailedError(
            f"Artist produced no usable files after 3 attempts. "
            f"Last response was {len(raw or '')} chars — likely truncated or "
            f"model refused. Try a shorter target prompt or a different Artist model."
        )

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
    # Sanitize files array — reject entries missing path or content, drop obvious
    # placeholders, and REJECT any path that tries to escape the workspace via
    # `..`, absolute paths, or backslashes / null bytes (SEC-002). Reuse the
    # shared predicate from `executor` so the guard is identical in every place.
    clean_files: list[dict] = []
    for f in parsed.get("files") or []:
        if not isinstance(f, dict):
            continue
        path = (f.get("path") or "").strip().lstrip("/")
        content = f.get("content")
        if not path or not isinstance(content, str) or not content.strip():
            continue
        if not _exec._is_safe_relpath(path):
            logger.warning("rejected unsafe artist file path: %r", path)
            continue
        if "..." in content and content.count("...") > 3 and len(content) < 200:
            continue  # obvious stub
        clean_files.append({"path": path, "content": content})
    parsed["files"] = clean_files
    return parsed


async def correct_step(spec: dict, stderr: str, assignment: Optional[dict] = None,
                       user_keys: Optional[dict] = None) -> dict:
    file_dump = "\n\n".join(
        f"### {f['path']}\n```\n{f['content'][:2000]}\n```"
        for f in (spec.get("files") or [])[:10]
    ) or "(no files)"
    prompt = (
        f"Stack: {spec.get('stack')}\nName: {spec.get('name')}\n\n"
        f"CURRENT FILES:\n{file_dump}\n\n"
        f"STDERR (tail):\n{stderr[-1500:]}\n\n"
        f"Output the corrected JSON (Artist schema, including the full `files` array)."
    )
    raw = await _call_role(
        "artist",  # corrector reuses the artist's model
        [{"role": "system", "content": SYSTEM_CORRECTOR},
         {"role": "user", "content": prompt}],
        assignment, user_keys=user_keys, temperature=0.3, max_tokens=6000,
    )
    fixed = _extract_json(raw or "") if raw else {}
    if not fixed:
        return spec
    # merge: corrector's non-file fields overlay spec, corrector's files replace spec's files if present
    merged = {**spec, **{k: v for k, v in fixed.items() if k != "files"}}
    new_files = fixed.get("files")
    if isinstance(new_files, list) and new_files:
        clean = []
        for f in new_files:
            if not (isinstance(f, dict) and f.get("path") and isinstance(f.get("content"), str)):
                continue
            path = f["path"].strip().lstrip("/")
            if not _exec._is_safe_relpath(path):
                logger.warning("rejected unsafe corrector file path: %r", path)
                continue
            clean.append({"path": path, "content": f["content"]})
        if clean:
            merged["files"] = clean
    return merged


async def rate_step(spec: dict, exec_result: dict, assignment: Optional[dict] = None,
                    user_keys: Optional[dict] = None) -> dict:
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
        assignment, user_keys=user_keys, temperature=0.1, max_tokens=2000,
    )
    data = _extract_json(raw or "") if raw else {}
    keys = ("helpfulness", "correctness", "coherence", "complexity", "verbosity")

    def _deterministic() -> dict:
        started = bool(exec_result.get("started"))
        base = 2.8 if started else 1.2
        return {k: base for k in keys}

    if not data:
        return _deterministic()
    # Reject degenerate responses (all-zero, or model parroted an example).
    try:
        values = {k: float(data.get(k, 0.0)) for k in keys}
    except (TypeError, ValueError):
        return _deterministic()
    if all(v == 0.0 for v in values.values()):
        logger.warning("rater returned all-zero — using deterministic fallback")
        return _deterministic()
    # Clamp to spec range so a rogue model can't push composite absurdly high.
    for k in keys:
        values[k] = max(0.0, min(4.0, values[k]))
    return values


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
    exemplar_files: Optional[list[dict]] = None,
    user_keys: Optional[dict] = None,
) -> dict:
    """One chain = one product build:
       Human target -> Teacher spec -> Artist product -> Executor (+ 1 correction) -> Rater.
    Raises ArtistFailedError if the Artist can't produce real files after retries.
    """
    a = dict(_providers.DEFAULT_ASSIGNMENTS)
    for role in ("teacher", "artist", "rater"):
        if assignments and assignments.get(role):
            a[role] = assignments[role]

    exemplars = exemplars or []
    fallback_used = False

    try:
        # 1) TEACHER
        teacher_spec = await teacher_step(target_prompt, exemplars,
                                          assignment=a["teacher"],
                                          user_keys=user_keys,
                                          chain_id=chain_id)

        # 2) ARTIST — writes the real source files. Raises if all attempts truncate.
        artist_spec = await artist_step(teacher_spec, exemplar_files=exemplar_files,
                                        assignment=a["artist"],
                                        user_keys=user_keys,
                                        chain_id=chain_id)

        # 3) BUILD PRODUCT
        await _emit(chain_id, "stage", "materialize")
        product = dict(artist_spec)
        product["target_prompt"] = target_prompt
        product["teacher_spec"] = teacher_spec
        product["artist_spec"] = {k: v for k, v in artist_spec.items() if k != "files"}
        product["files"] = seed_template.render(product, stack=product.get("stack") or teacher_spec.get("stack"))

        # 4) EXECUTOR — longer timeout for stacks that need install/compile.
        await _emit(chain_id, "stage", "execute")
        stack_l = (product.get("stack") or "").lower()
        exec_timeout = 90 if any(k in stack_l for k in ("node", "vite", "react", "rust", "go")) else 25
        workspace = _exec.materialize(chain_id, product)
        exec_result = await _exec.run_workspace(workspace, timeout=exec_timeout, port_to_check=8123)
        product["exec"] = exec_result

        # 5) ONE correction pass if it failed to start
        if not exec_result.get("started") and exec_result.get("stderr"):
            fallback_used = True
            await _emit(chain_id, "stage", "corrector")
            product = await correct_step(product, exec_result["stderr"],
                                         assignment=a["artist"], user_keys=user_keys)
            product["files"] = seed_template.render(product, stack=product.get("stack"))
            workspace = _exec.materialize(chain_id, product)
            exec_result = await _exec.run_workspace(workspace, timeout=exec_timeout, port_to_check=8124)
            product["exec"] = exec_result

        # 6) RATER
        await _emit(chain_id, "stage", "rater")
        scores = await rate_step(product, exec_result, assignment=a["rater"], user_keys=user_keys)
        product["reward"] = scores

        # 6b) Deterministic feature-coverage — parses the code and target prompt
        # to check hard signals (list lengths, routes, UI verbs, network calls).
        cov = _coverage.score(target_prompt, product.get("files") or [])
        product["coverage"] = cov
        # Blend coverage into the composite when it's available so the final
        # score reflects real behaviour, not just the LLM rater's opinion.
        base = composite(scores)
        if cov.get("coverage") is not None:
            # Coverage scales 0..1 -> weight ~40% of the final score.
            product["composite_score"] = round(base * 0.6 + (cov["coverage"] * 4.0) * 0.4, 3)
        else:
            product["composite_score"] = base
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
        await _emit(chain_id, "stage", "complete")
        return final
    finally:
        close_stream(chain_id)
