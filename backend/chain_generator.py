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

logger = logging.getLogger("chain")

NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY", "").strip()
NIM_BASE_URL = "https://integrate.api.nvidia.com/v1"
GEN_MODEL = "z-ai/glm-5.1"
CRITIC_MODEL = "minimaxai/minimax-m2.7"
RATER_MODEL = "nvidia/llama-3.3-nemotron-super-49b-v1.5"

_client = None
ENABLED = False
if NVIDIA_API_KEY:
    try:
        from openai import AsyncOpenAI

        _client = AsyncOpenAI(
            api_key=NVIDIA_API_KEY, base_url=NIM_BASE_URL, timeout=90.0, max_retries=0
        )
        ENABLED = True
    except Exception as exc:  # pragma: no cover
        logger.warning("chain init failed: %s", exc)


# ---------------------------------------------------------------------------
# LLM helper (handles reasoning_content fallback for thinking models)
# ---------------------------------------------------------------------------
async def _chat(model: str, messages: list[dict], **kwargs) -> Optional[str]:
    if not ENABLED or _client is None:
        return None
    try:
        r = await _client.chat.completions.create(model=model, messages=messages, **kwargs)
        msg = r.choices[0].message
        out = (msg.content or "").strip()
        if not out:
            reasoning = getattr(msg, "reasoning_content", None) or ""
            paras = [p.strip() for p in reasoning.split("\n\n") if p.strip()]
            out = paras[-1] if paras else reasoning.strip()
        return out
    except Exception as exc:
        logger.error("NIM %s call failed: %s", model, exc)
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
SYSTEM_PROMPT = """You are RECURSIVE.BBS, an evolution engine. You DESIGN a new code-builder application — an app that calls an LLM to generate code from input.

Given the chain so far, design the NEXT generation: a distinct code-builder differing in INPUT STYLE and OUTPUT STYLE from every prior gen.

Output STRICT JSON ONLY — no prose, no fences, no trailing commas. Be CREATIVE and SPECIFIC. Keep it tight:
{
  "name": "PascalCase, 1-2 words",
  "tagline": "one short line",
  "philosophy": "2 sentences. What makes this gen's approach to code generation distinct from its ancestors?",
  "input_style": "natural-language | structured-form | pseudocode | tests-first | diagram-DSL | Q-and-A-loop | sketch | voice-transcript | spec-by-example | type-signatures-first | constraints-as-code | etc",
  "output_style": "single-file | multi-file-repo | patch | git-rebase | docker-compose | scaffold | migration | inline-comments-only | bash-pipeline | etc",
  "system_prompt": "the system prompt the new gen's backend uses when it calls its own LLM (2-4 sentences, captures the philosophy)",
  "ui_hint": "1 sentence describing the frontend's distinctive interaction (e.g. 'a single textarea labeled tests' or 'two-column diff-style editor' or 'numbered Q-and-A prompts that build up the spec')"
}
"""


def _chain_brief(history: list[dict]) -> str:
    """Compact chain history for the next-gen prompt."""
    if not history:
        return "(no prior generations — you are generating Gen 2; the parent is RECURSIVE.BBS itself)"
    lines = []
    for g in history:
        lines.append(
            f"- Gen {g['gen']}: {g.get('name','?')} — input:{g.get('input_style','?')} "
            f"/ output:{g.get('output_style','?')}. {g.get('tagline','')}"
        )
    return "\n".join(lines)


async def generate_gen(history: list[dict], gen_number: int) -> Optional[dict]:
    """Ask GLM to DESIGN the next generation (tight JSON spec).

    Files are synthesized deterministically from the spec via _synthesize_files()
    — this guarantees syntactically valid code and keeps the LLM call fast.
    """
    user_msg = (
        f"Chain so far:\n{_chain_brief(history)}\n\n"
        f"Now design Gen {gen_number}. Pick INPUT and OUTPUT styles that NONE of the prior "
        f"gens used. Output strict JSON per the schema."
    )
    raw = await _chat(
        GEN_MODEL,
        [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user_msg}],
        temperature=0.85,
        max_tokens=900,
    )
    if not raw:
        return None
    parsed = _extract_json(raw)
    if not parsed.get("name"):
        logger.warning("gen %s: no name in parsed output. raw head: %r", gen_number, raw[:300])
        return None
    parsed["files"] = _synthesize_files(parsed)
    return parsed


# ---------------------------------------------------------------------------
# Deterministic file synthesis (turn the AI-designed spec into real code)
# ---------------------------------------------------------------------------
def _safe_str(s: str) -> str:
    return (s or "").replace('"""', '\\"\\"\\"')


def _synthesize_files(spec: dict) -> list[dict]:
    name = spec.get("name") or "GenApp"
    tagline = spec.get("tagline") or "a code-builder"
    philosophy = spec.get("philosophy") or ""
    input_style = spec.get("input_style") or "natural-language"
    output_style = spec.get("output_style") or "single-file"
    sys_prompt = spec.get("system_prompt") or (
        f"You are {name}, a code generator. Input style: {input_style}. "
        f"Output style: {output_style}. Produce only the code, no prose."
    )
    ui_hint = spec.get("ui_hint") or "a single textarea + Generate button"

    server_py = f'''"""
{name} — {tagline}
Code-builder gen produced by RECURSIVE.BBS.
Input style: {input_style}.  Output style: {output_style}.
"""
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

SYSTEM_PROMPT = """{_safe_str(sys_prompt)}"""

API_KEY = os.environ.get("NVIDIA_API_KEY", "").strip()
STUB_MODE = not API_KEY
_client = None
if not STUB_MODE:
    try:
        from openai import OpenAI
        _client = OpenAI(api_key=API_KEY, base_url="https://integrate.api.nvidia.com/v1", timeout=60)
    except Exception:
        STUB_MODE = True

app = FastAPI(title="{name}")
FRONTEND = Path(__file__).resolve().parent.parent / "frontend"


class GenReq(BaseModel):
    input: str


@app.get("/api/info")
def info():
    return {{
        "name": "{name}",
        "input_style": "{input_style}",
        "output_style": "{output_style}",
        "stub_mode": STUB_MODE,
    }}


@app.post("/api/generate")
def generate(req: GenReq):
    if STUB_MODE or _client is None:
        body = req.input.strip() or "hello world"
        return {{"code": f"# stub output for {{body!r}}\\n# input_style: {input_style}\\n# output_style: {output_style}\\nprint({{body!r}})\\n"}}
    try:
        r = _client.chat.completions.create(
            model="z-ai/glm-5.1",
            messages=[
                {{"role": "system", "content": SYSTEM_PROMPT}},
                {{"role": "user", "content": req.input}},
            ],
            temperature=0.6,
            max_tokens=1500,
        )
        msg = r.choices[0].message
        code = (msg.content or "").strip()
        if not code:
            code = (getattr(msg, "reasoning_content", "") or "").strip()
        return {{"code": code}}
    except Exception as exc:
        return {{"code": f"# generation failed: {{exc}}\\n"}}


if FRONTEND.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")

    @app.get("/")
    def index():
        return FileResponse(FRONTEND / "index.html")
'''

    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{name}</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  :root {{ --bg:#0a0a0a; --fg:#7cffb2; --mut:#5a5a5a; --line:#222; --acc:#ff79c6; }}
  *{{box-sizing:border-box}}
  body{{margin:0;background:var(--bg);color:var(--fg);font:14px ui-monospace,SFMono-Regular,Menlo,monospace;padding:24px;max-width:1100px;margin:0 auto}}
  header{{border-bottom:1px solid var(--line);padding-bottom:12px;margin-bottom:18px}}
  h1{{margin:0;color:var(--fg);font-size:18px;letter-spacing:.1em;text-transform:uppercase}}
  .pill{{display:inline-block;padding:2px 8px;border:1px solid var(--acc);color:var(--acc);font-size:11px;letter-spacing:.1em;text-transform:uppercase;margin-left:8px}}
  .muted{{color:var(--mut)}}
  textarea,input{{background:#111;color:var(--fg);border:1px solid var(--line);padding:10px;font:inherit;width:100%}}
  button{{background:transparent;color:var(--fg);border:1px solid var(--fg);padding:8px 14px;cursor:pointer;font:inherit;text-transform:uppercase;letter-spacing:.1em}}
  button:hover{{background:var(--fg);color:#000}}
  pre{{background:#000;padding:14px;border:1px solid var(--line);white-space:pre-wrap;max-height:60vh;overflow:auto}}
  .row{{display:flex;gap:10px;align-items:center;margin:10px 0}}
</style>
</head>
<body>
<header>
  <h1>{name}<span class="pill">{input_style} -&gt; {output_style}</span></h1>
  <div class="muted" style="margin-top:6px">{tagline}</div>
  <div class="muted" style="margin-top:4px;font-size:12px">{ui_hint}</div>
</header>

<div class="muted" style="font-size:12px;margin-bottom:6px">describe what you want as <strong>{input_style}</strong>:</div>
<textarea id="i" rows="8" placeholder="enter your {input_style} here…"></textarea>
<div class="row">
  <button id="b">Generate {output_style}</button>
  <span id="s" class="muted"></span>
</div>
<pre id="o" class="muted">[ output will appear here ]</pre>

<script>
const B = document.getElementById('b');
const S = document.getElementById('s');
B.onclick = async () => {{
  const input = document.getElementById('i').value;
  if (!input.trim()) return;
  B.disabled = true; S.textContent = 'thinking…';
  try {{
    const r = await fetch('/api/generate', {{
      method:'POST', headers:{{'Content-Type':'application/json'}}, body: JSON.stringify({{input}})
    }});
    const data = await r.json();
    document.getElementById('o').textContent = data.code || '(no output)';
  }} catch (e) {{
    document.getElementById('o').textContent = String(e);
  }} finally {{
    B.disabled = false; S.textContent = '';
  }}
}};
</script>
</body>
</html>
"""

    run_sh = """#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
python3 -m venv .venv 2>/dev/null || true
source .venv/bin/activate
pip install -q -r backend/requirements.txt
cd backend
exec uvicorn server:app --host 0.0.0.0 --port 8000
"""

    requirements_txt = "fastapi==0.115.0\nuvicorn[standard]==0.30.6\npydantic==2.9.2\nopenai==1.99.9\n"

    readme = f"""# {name}

> {tagline}

Generated by RECURSIVE.BBS.

**Philosophy:** {philosophy}

- Input style: `{input_style}`
- Output style: `{output_style}`

## Run

```bash
export NVIDIA_API_KEY=nvapi-…   # optional; falls back to STUB_MODE if missing
bash run.sh
```

Then open http://localhost:8000 — `{ui_hint}`.
"""

    return [
        {"path": "backend/server.py", "content": server_py},
        {"path": "backend/requirements.txt", "content": requirements_txt},
        {"path": "frontend/index.html", "content": html},
        {"path": "run.sh", "content": run_sh},
        {"path": "README.md", "content": readme},
    ]


# ---------------------------------------------------------------------------
# Critic + rater
# ---------------------------------------------------------------------------
def _gen_brief(gen: dict, max_files: int = 3, max_lines: int = 25) -> str:
    lines = [
        f"# {gen.get('name','app')} (Gen {gen.get('gen','?')})",
        f"tagline: {gen.get('tagline','')}",
        f"philosophy: {gen.get('philosophy','')}",
        f"input_style: {gen.get('input_style','')}",
        f"output_style: {gen.get('output_style','')}",
        "\n## File previews",
    ]
    for f in gen.get("files", [])[:max_files]:
        head = "\n".join(f["content"].splitlines()[:max_lines])
        lines.append(f"\n--- {f['path']} (head) ---\n{head}")
    return "\n".join(lines)


async def critique_gen(gen: dict) -> Optional[str]:
    raw = await _chat(
        CRITIC_MODEL,
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
        temperature=0.5,
        max_tokens=1200,
    )
    return raw.strip() if raw else None


async def score_gen(gen: dict) -> Optional[dict]:
    rubric = (
        "Score the generated code-builder app on 5 dimensions, each 0.0-4.0. Output ONLY this "
        'JSON: {"helpfulness":0.0,"correctness":0.0,"coherence":0.0,"complexity":0.0,"verbosity":0.0}'
    )
    raw = await _chat(
        RATER_MODEL,
        [
            {"role": "system", "content": rubric},
            {"role": "user", "content": _gen_brief(gen, max_lines=20)},
        ],
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
    chain_id: str, depth: int, on_gen, on_done
) -> dict:
    """Run the evolution loop and call `on_gen(gen_dict)` after each generation completes,
    and `on_done(chain_dict)` when finished. Used by the FastAPI background task."""
    depth = max(1, min(5, int(depth)))
    history: list[dict] = []
    generations: list[dict] = []
    fallback_used = False

    for i in range(depth):
        gen_number = i + 2
        gen = await generate_gen(history, gen_number)
        if not gen:
            fallback_used = True
            gen = _fallback_gen(gen_number, history)
        gen["gen"] = gen_number
        critic, scores = await asyncio.gather(
            critique_gen(gen), score_gen(gen), return_exceptions=False
        )
        gen["critic_notes"] = critic or "(critic unavailable for this generation)"
        gen["reward"] = scores or {
            "helpfulness": 0.0, "correctness": 0.0, "coherence": 0.0,
            "complexity": 0.0, "verbosity": 0.0,
        }
        gen["composite_score"] = composite(gen["reward"])
        generations.append(gen)
        history.append({
            "gen": gen_number, "name": gen.get("name"), "tagline": gen.get("tagline"),
            "input_style": gen.get("input_style"), "output_style": gen.get("output_style"),
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
                "tagline": gen.get("tagline"),
                "input_style": gen.get("input_style"),
                "output_style": gen.get("output_style"),
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
    name = f"FallbackGen{n}"
    server_py = f'''"""
{name} — placeholder gen (NIM was unreachable). Still a runnable FastAPI code-builder.
"""
import os
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from pydantic import BaseModel

try:
    from openai import OpenAI
    _key = os.environ.get("NVIDIA_API_KEY", "")
    _client = OpenAI(api_key=_key, base_url="https://integrate.api.nvidia.com/v1") if _key else None
except Exception:
    _client = None

app = FastAPI(title="{name}")
FRONTEND = Path(__file__).resolve().parent.parent / "frontend"

class GenReq(BaseModel):
    input: str

@app.post("/api/generate")
def generate(req: GenReq):
    if _client is None:
        return {{"code": f"# stub-{{req.input}}\\nprint('hello from {name}')\\n", "files": []}}
    r = _client.chat.completions.create(
        model="z-ai/glm-5.1",
        messages=[
            {{"role": "system", "content": "Output Python code only, no prose."}},
            {{"role": "user", "content": req.input}},
        ],
    )
    return {{"code": r.choices[0].message.content or "", "files": []}}

if FRONTEND.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")
    @app.get("/")
    def index():
        return FileResponse(FRONTEND / "index.html")
'''
    html = f"""<!doctype html><html><head><meta charset="utf-8"><title>{name}</title>
<style>body{{background:#0a0a0a;color:#7cffb2;font:14px ui-monospace;padding:20px}}
textarea,button{{background:#111;color:#7cffb2;border:1px solid #2a2a2a;padding:8px;font:inherit}}
button{{cursor:pointer}} pre{{background:#000;padding:12px;border:1px solid #2a2a2a;white-space:pre-wrap}}</style>
</head><body><h1>{name}</h1>
<textarea id=i rows=4 cols=80 placeholder="describe code to generate"></textarea><br>
<button onclick=go()>generate</button><pre id=o></pre>
<script>
async function go() {{
  const r = await fetch('/api/generate',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{input:document.getElementById('i').value}})}});
  document.getElementById('o').textContent = (await r.json()).code;
}}
</script></body></html>"""
    return {
        "name": name,
        "tagline": "fallback code-builder",
        "philosophy": "Minimal placeholder generated when the upstream LLM was unreachable.",
        "input_style": "natural-language",
        "output_style": "single-file",
        "files": [
            {"path": "backend/server.py", "content": server_py},
            {"path": "backend/requirements.txt", "content": "fastapi\nuvicorn[standard]\npydantic\nopenai\npython-dotenv\n"},
            {"path": "frontend/index.html", "content": html},
            {"path": "run.sh", "content": "#!/usr/bin/env bash\nset -e\ncd \"$(dirname \"$0\")\"\npython3 -m venv .venv 2>/dev/null || true\nsource .venv/bin/activate\npip install -q -r backend/requirements.txt\ncd backend\nexec uvicorn server:app --host 0.0.0.0 --port 8000\n"},
            {"path": "README.md", "content": f"# {name}\n\nFallback gen (no LLM available at evolve-time).\n\n## Run\n```bash\nbash run.sh\n```\n"},
        ],
    }
