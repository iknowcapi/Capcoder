"""
RECURSIVE.BBS — backend for the self-improving 'app-builder that builds app-builders'.
Pipeline: user prompt -> GLM-5.1 (generator) -> MiniMax-M2.7 (critic) -> Nemotron-70B-Reward (rater)
Self-improvement: top-rated builds are fetched and injected as few-shot examples
into subsequent generator prompts.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional

from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI, HTTPException
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.cors import CORSMiddleware

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("recursive-bbs")

# --------------------------------------------------------------------------------------
# Mongo
# --------------------------------------------------------------------------------------
mongo_url = os.environ["MONGO_URL"]
db_name = os.environ["DB_NAME"]
mongo_client = AsyncIOMotorClient(mongo_url)
db = mongo_client[db_name]

# --------------------------------------------------------------------------------------
# NIM client (graceful stub mode if NVIDIA_API_KEY is missing)
# --------------------------------------------------------------------------------------
NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY", "").strip()
NIM_BASE_URL = "https://integrate.api.nvidia.com/v1"
GLM_MODEL = "z-ai/glm-5.1"
MINIMAX_MODEL = "minimaxai/minimax-m2.7"
REWARD_MODEL = "nvidia/llama-3.1-nemotron-70b-reward"

_nim_client = None
STUB_MODE = True
if NVIDIA_API_KEY:
    try:
        from openai import AsyncOpenAI

        _nim_client = AsyncOpenAI(api_key=NVIDIA_API_KEY, base_url=NIM_BASE_URL)
        STUB_MODE = False
        logger.info("NIM client initialized — live mode.")
    except Exception as exc:  # pragma: no cover
        logger.warning("Failed to init NIM client (%s); falling back to stub mode.", exc)
        STUB_MODE = True
else:
    logger.warning("NVIDIA_API_KEY missing — running in STUB MODE.")

# --------------------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------------------
class RewardScores(BaseModel):
    helpfulness: float = 0.0
    correctness: float = 0.0
    coherence: float = 0.0
    complexity: float = 0.0
    verbosity: float = 0.0

    @property
    def composite(self) -> float:
        return round(
            0.35 * self.helpfulness
            + 0.30 * self.correctness
            + 0.20 * self.coherence
            + 0.10 * self.complexity
            - 0.05 * abs(self.verbosity - 2.0),
            3,
        )


class Build(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    generation: int = 1
    parent_id: Optional[str] = None
    user_prompt: str
    meta_builder_spec: dict = Field(default_factory=dict)
    app_spec: dict = Field(default_factory=dict)
    critic_notes: str = ""
    reward: RewardScores = Field(default_factory=RewardScores)
    composite_score: float = 0.0
    user_vote: int = 0  # -1, 0, 1
    stub: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class BuildRequest(BaseModel):
    prompt: str
    parent_id: Optional[str] = None


class FeedbackRequest(BaseModel):
    vote: int  # -1 or 1


# --------------------------------------------------------------------------------------
# LLM helpers
# --------------------------------------------------------------------------------------
GENERATOR_SYSTEM = (
    "You are RECURSIVE.BBS — a meta app-builder generator. Given a user description, "
    "you output a strict JSON object with two keys: 'meta_builder' and 'app_spec'. "
    "'meta_builder' describes the *builder that builds this kind of app* (its modules, "
    "primitives, code-gen recipes). 'app_spec' is the concrete app description produced "
    "by that builder. Schemas:\n"
    "{\n"
    '  "meta_builder": {"name": str, "domain": str, "primitives": [str], '
    '"code_gen_recipes": [str], "dna_signature": str},\n'
    '  "app_spec": {"name": str, "tagline": str, "entities": [str], "screens": [str], '
    '"apis": [{"method": str, "path": str, "purpose": str}], "stack": [str]}\n'
    "}\n"
    "Return ONLY the JSON. No prose."
)


async def _call_chat(model: str, messages: list[dict]) -> str:
    if STUB_MODE or _nim_client is None:
        return ""
    resp = await _nim_client.chat.completions.create(
        model=model, messages=messages, temperature=0.7, max_tokens=2048
    )
    return resp.choices[0].message.content or ""


def _seed(salt: str, prompt: str) -> int:
    """Deterministic seed stable across process restarts."""
    h = hashlib.md5(f"{salt}::{prompt}".encode()).hexdigest()
    return int(h[:8], 16)


def _stub_generate(prompt: str, exemplars: list[dict]) -> dict:
    """Deterministic-ish fake generator that produces a believable spec."""
    seed = _seed("gen", prompt)
    rng = random.Random(seed)
    primitives_pool = [
        "schema-forge", "route-weaver", "ui-composer", "auth-spine", "stripe-rail",
        "vector-index", "queue-spool", "websocket-loom", "cron-orbit", "rbac-mesh",
        "file-vault", "i18n-prism", "rate-limiter", "audit-trail", "feature-flag",
    ]
    recipes_pool = [
        "scaffold(react+fastapi+mongo)", "emit(crud-endpoints)", "synth(zod-schemas)",
        "compose(shadcn-pages)", "wire(jwt-auth)", "graft(payments)", "seed(demo-data)",
    ]
    stacks_pool = ["React 19", "FastAPI", "MongoDB", "Tailwind", "shadcn/ui", "Motor", "Pydantic"]

    name_tokens = re.findall(r"[A-Za-z]+", prompt)[:3] or ["app"]
    base = "".join(t.capitalize() for t in name_tokens)
    domain_words = ["social", "fintech", "wellness", "edtech", "ops", "creator", "iot"]
    domain = rng.choice(domain_words)

    meta = {
        "name": f"{base}.builder.v{rng.randint(1, 9)}",
        "domain": domain,
        "primitives": rng.sample(primitives_pool, k=rng.randint(4, 7)),
        "code_gen_recipes": rng.sample(recipes_pool, k=rng.randint(3, 5)),
        "dna_signature": f"0x{rng.getrandbits(32):08x}",
    }

    entities_pool = ["User", "Session", "Item", "Order", "Message", "Event", "Workspace", "Token"]
    apis_pool = [
        ("POST", "/api/auth/login", "issue session token"),
        ("GET", "/api/items", "list items"),
        ("POST", "/api/items", "create item"),
        ("PATCH", "/api/items/{id}", "update item"),
        ("DELETE", "/api/items/{id}", "remove item"),
        ("GET", "/api/me", "current user"),
        ("POST", "/api/events", "track event"),
    ]
    chosen_apis = rng.sample(apis_pool, k=rng.randint(3, 5))
    app = {
        "name": base,
        "tagline": f"a {domain} app forged by {meta['name']}",
        "entities": rng.sample(entities_pool, k=rng.randint(3, 5)),
        "screens": rng.sample(
            ["Dashboard", "Auth", "Settings", "Detail", "Feed", "Inbox", "Billing"],
            k=rng.randint(3, 5),
        ),
        "apis": [{"method": m, "path": p, "purpose": pu} for m, p, pu in chosen_apis],
        "stack": rng.sample(stacks_pool, k=rng.randint(4, 6)),
    }

    if exemplars:
        # 'self-improvement': inherit one primitive from a top-rated ancestor
        top = exemplars[0]
        ancestor_prims = top.get("meta_builder_spec", {}).get("primitives", [])
        if ancestor_prims:
            inherited = rng.choice(ancestor_prims)
            if inherited not in meta["primitives"]:
                meta["primitives"].append(inherited)
            meta["inherited_from"] = top.get("id")

    return {"meta_builder": meta, "app_spec": app}


def _stub_critique(prompt: str, spec: dict) -> str:
    rng = random.Random(_seed("critic", prompt))
    notes = [
        f"meta_builder.primitives are reasonable but could absorb '{rng.choice(['cache-grid','obs-mesh','perm-tree'])}'.",
        f"app_spec covers {len(spec.get('app_spec', {}).get('apis', []))} endpoints; consider adding a /health probe.",
        "tagline reads like marketing — tighten to a single technical claim.",
        f"dna_signature {spec.get('meta_builder', {}).get('dna_signature','?')} should be persisted for lineage diffing.",
    ]
    return " // ".join(rng.sample(notes, k=3))


def _stub_reward(prompt: str, spec: dict) -> RewardScores:
    rng = random.Random(_seed("reward", prompt))
    return RewardScores(
        helpfulness=round(rng.uniform(1.5, 3.5), 2),
        correctness=round(rng.uniform(1.0, 3.5), 2),
        coherence=round(rng.uniform(2.0, 4.0), 2),
        complexity=round(rng.uniform(0.5, 2.5), 2),
        verbosity=round(rng.uniform(0.5, 2.5), 2),
    )


def _parse_reward(raw: str) -> RewardScores:
    scores: dict[str, float] = {}
    for pair in (p.strip() for p in raw.split(",") if ":" in p):
        k, v = pair.split(":", 1)
        try:
            scores[k.strip().lower()] = float(v.strip())
        except ValueError:
            continue
    return RewardScores(**{k: scores.get(k, 0.0) for k in RewardScores.model_fields})


def _extract_json(text: str) -> dict:
    """Pull first {...} block out of an LLM response."""
    text = text.strip()
    # try direct
    try:
        return json.loads(text)
    except Exception:
        pass
    # try fenced
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    # brace match
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return {}


# --------------------------------------------------------------------------------------
# FastAPI
# --------------------------------------------------------------------------------------
app = FastAPI(title="RECURSIVE.BBS")
api = APIRouter(prefix="/api")


@api.get("/")
async def root():
    return {
        "system": "RECURSIVE.BBS",
        "stub_mode": STUB_MODE,
        "models": {"generator": GLM_MODEL, "critic": MINIMAX_MODEL, "rater": REWARD_MODEL},
    }


@api.get("/status")
async def status():
    total = await db.builds.count_documents({})
    return {"stub_mode": STUB_MODE, "total_builds": total}


@api.post("/builds", response_model=Build)
async def create_build(req: BuildRequest):
    if not req.prompt.strip():
        raise HTTPException(400, "prompt is required")

    # ---- self-improvement: pull top-rated exemplars -----------------------------------
    top_docs = (
        await db.builds.find({}, {"_id": 0})
        .sort("composite_score", -1)
        .limit(3)
        .to_list(3)
    )
    exemplar_payload = [
        {
            "id": d["id"],
            "meta_builder_spec": d.get("meta_builder_spec", {}),
            "composite_score": d.get("composite_score", 0),
        }
        for d in top_docs
    ]

    # ---- generation -------------------------------------------------------------------
    parsed: dict = {}
    if not STUB_MODE:
        gen_messages: list[dict[str, Any]] = [{"role": "system", "content": GENERATOR_SYSTEM}]
        if exemplar_payload:
            gen_messages.append(
                {
                    "role": "system",
                    "content": (
                        "TOP-RATED PRIOR BUILDS (use their patterns as inspiration):\n"
                        + json.dumps(exemplar_payload, indent=2)
                    ),
                }
            )
        gen_messages.append({"role": "user", "content": req.prompt})
        try:
            raw = await _call_chat(GLM_MODEL, gen_messages)
            parsed = _extract_json(raw)
        except Exception as exc:
            logger.error("generator call failed: %s", exc)
            parsed = {}
    if not parsed:
        parsed = _stub_generate(req.prompt, exemplar_payload)

    meta_spec = parsed.get("meta_builder", {})
    app_spec = parsed.get("app_spec", {})

    # ---- critic -----------------------------------------------------------------------
    critic_text = ""
    if not STUB_MODE:
        try:
            critic_messages = [
                {
                    "role": "system",
                    "content": (
                        "You are the CRITIC. In <=3 short clauses separated by ' // ', "
                        "point out weaknesses in the meta-builder + app-spec JSON below. "
                        "No prose, no preamble."
                    ),
                },
                {"role": "user", "content": json.dumps(parsed)},
            ]
            critic_text = (await _call_chat(MINIMAX_MODEL, critic_messages)).strip()
        except Exception as exc:
            logger.error("critic call failed: %s", exc)
    if not critic_text:
        critic_text = _stub_critique(req.prompt, parsed)

    # ---- rater ------------------------------------------------------------------------
    reward = RewardScores()
    if not STUB_MODE:
        try:
            reward_messages = [
                {"role": "user", "content": req.prompt},
                {"role": "assistant", "content": json.dumps(parsed)},
            ]
            raw = await _call_chat(REWARD_MODEL, reward_messages)
            reward = _parse_reward(raw)
        except Exception as exc:
            logger.error("rater call failed: %s", exc)
    if reward.helpfulness == 0 and reward.correctness == 0:
        reward = _stub_reward(req.prompt, parsed)

    # ---- generation number ------------------------------------------------------------
    if req.parent_id:
        parent = await db.builds.find_one({"id": req.parent_id}, {"_id": 0})
        generation = (parent.get("generation", 1) + 1) if parent else 1
    else:
        last = await db.builds.find_one({}, {"_id": 0, "generation": 1}, sort=[("generation", -1)])
        generation = ((last or {}).get("generation", 0) or 0) + 1

    build = Build(
        generation=generation,
        parent_id=req.parent_id,
        user_prompt=req.prompt,
        meta_builder_spec=meta_spec,
        app_spec=app_spec,
        critic_notes=critic_text,
        reward=reward,
        composite_score=reward.composite,
        stub=STUB_MODE,
    )
    doc = build.model_dump()
    doc["created_at"] = doc["created_at"].isoformat()
    await db.builds.insert_one(doc)
    return build


@api.get("/builds", response_model=List[Build])
async def list_builds(limit: int = 50):
    docs = (
        await db.builds.find({}, {"_id": 0})
        .sort("created_at", -1)
        .limit(limit)
        .to_list(limit)
    )
    for d in docs:
        if isinstance(d.get("created_at"), str):
            d["created_at"] = datetime.fromisoformat(d["created_at"])
    return docs


@api.get("/builds/{build_id}", response_model=Build)
async def get_build(build_id: str):
    doc = await db.builds.find_one({"id": build_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "build not found")
    if isinstance(doc.get("created_at"), str):
        doc["created_at"] = datetime.fromisoformat(doc["created_at"])
    return doc


@api.post("/builds/{build_id}/feedback", response_model=Build)
async def feedback(build_id: str, req: FeedbackRequest):
    vote = 1 if req.vote > 0 else -1 if req.vote < 0 else 0
    doc = await db.builds.find_one({"id": build_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "build not found")
    new_composite = round(doc.get("composite_score", 0) + 0.25 * vote, 3)
    await db.builds.update_one(
        {"id": build_id},
        {"$set": {"user_vote": vote, "composite_score": new_composite}},
    )
    doc["user_vote"] = vote
    doc["composite_score"] = new_composite
    if isinstance(doc.get("created_at"), str):
        doc["created_at"] = datetime.fromisoformat(doc["created_at"])
    return doc


@api.get("/leaderboard", response_model=List[Build])
async def leaderboard(limit: int = 10):
    docs = (
        await db.builds.find({}, {"_id": 0})
        .sort("composite_score", -1)
        .limit(limit)
        .to_list(limit)
    )
    for d in docs:
        if isinstance(d.get("created_at"), str):
            d["created_at"] = datetime.fromisoformat(d["created_at"])
    return docs


@api.get("/lineage")
async def lineage():
    docs = await db.builds.find(
        {}, {"_id": 0, "id": 1, "parent_id": 1, "generation": 1, "composite_score": 1,
             "meta_builder_spec.name": 1}
    ).sort("created_at", 1).to_list(500)
    return {"nodes": docs}


app.include_router(api)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("shutdown")
async def shutdown_db():
    mongo_client.close()
