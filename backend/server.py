"""
RECURSIVE.BBS — a code-builder app whose bots emit real, runnable code projects.

Pipeline (per build):
  1. Generator bot   :: detect domain → emit a folder of real working files
  2. Critic          :: review those files (line count, endpoint coverage, etc.)
  3. Rater           :: score across 5 dimensions
  4. User            :: download the .zip, vote thumbs up/down (feeds future builds)
"""
from __future__ import annotations

import io
import logging
import os
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.cors import CORSMiddleware

from blueprints import build_project, critique_files, rate_files
import nim_augment

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
# Models
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


class BuildFile(BaseModel):
    path: str
    content: str


class Build(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    generation: int = 1
    parent_id: Optional[str] = None
    user_prompt: str
    bot: dict = Field(default_factory=dict)         # describes the code-building bot
    app: dict = Field(default_factory=dict)         # describes the produced app
    files: list[BuildFile] = Field(default_factory=list)
    critic_notes: str = ""
    reward: RewardScores = Field(default_factory=RewardScores)
    composite_score: float = 0.0
    user_vote: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class BuildRequest(BaseModel):
    prompt: str
    parent_id: Optional[str] = None


class FeedbackRequest(BaseModel):
    vote: int


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------
def _slugify(s: str) -> str:
    import re

    s = re.sub(r"[^a-zA-Z0-9._-]+", "-", s).strip("-")
    return s or "build"


async def _exemplars() -> list[dict]:
    docs = (
        await db.builds.find({}, {"_id": 0})
        .sort("composite_score", -1)
        .limit(3)
        .to_list(3)
    )
    return docs


# --------------------------------------------------------------------------------------
# FastAPI
# --------------------------------------------------------------------------------------
app = FastAPI(title="RECURSIVE.BBS")
api = APIRouter(prefix="/api")


@api.get("/")
async def root():
    return {
        "system": "RECURSIVE.BBS",
        "version": "0.3.0",
        "nim_enabled": nim_augment.ENABLED,
    }


@api.get("/status")
async def status():
    total = await db.builds.count_documents({})
    return {"total_builds": total, "nim_enabled": nim_augment.ENABLED}


@api.post("/builds", response_model=Build)
async def create_build(req: BuildRequest):
    if not req.prompt.strip():
        raise HTTPException(400, "prompt is required")

    # ---- self-improvement: pull top-rated prior builds as exemplars ------------------
    exemplars = await _exemplars()

    # ---- the bot generates a real folder of code --------------------------------------
    proj = build_project(req.prompt, exemplars=exemplars)

    # ---- NVIDIA NIM augmentation (parallel; gracefully falls back on any failure) -----
    aug = await nim_augment.augment(req.prompt, proj)

    # If GLM produced a DESIGN.md, attach it as an extra file in the project
    nim_used = []
    if aug.get("design"):
        proj.setdefault("files", []).append({"path": "DESIGN.md", "content": aug["design"]})
        nim_used.append("glm-5.1")
    proj.setdefault("bot", {})["nim_models"] = nim_used  # mutated below as more succeed

    # ---- critic: real LLM prose if available, else heuristic --------------------------
    if aug.get("critique"):
        critic_text = aug["critique"]
        nim_used.append("minimax-m2.7")
    else:
        critic_text = critique_files(proj)

    # ---- rater: real reward model if available, else heuristic ------------------------
    if aug.get("scores"):
        scores = aug["scores"]
        nim_used.append("glm-5.1-judge")
    else:
        scores = rate_files(proj)
    reward = RewardScores(**scores)
    proj["bot"]["nim_models"] = nim_used

    # ---- lineage / generation ---------------------------------------------------------
    if req.parent_id:
        parent = await db.builds.find_one({"id": req.parent_id}, {"_id": 0})
        generation = (parent.get("generation", 1) + 1) if parent else 1
    else:
        last = await db.builds.find_one(
            {}, {"_id": 0, "generation": 1}, sort=[("generation", -1)]
        )
        generation = ((last or {}).get("generation", 0) or 0) + 1

    build = Build(
        generation=generation,
        parent_id=req.parent_id,
        user_prompt=req.prompt,
        bot=proj.get("bot", {}),
        app=proj.get("app", {}),
        files=[BuildFile(**f) for f in proj.get("files", [])],
        critic_notes=critic_text,
        reward=reward,
        composite_score=reward.composite,
    )
    doc = build.model_dump()
    doc["created_at"] = doc["created_at"].isoformat()
    await db.builds.insert_one(doc)
    return build


@api.get("/builds", response_model=List[Build])
async def list_builds(limit: int = 50):
    docs = (
        await db.builds.find({}, {"_id": 0, "files": 0})  # skip heavy files in list
        .sort("created_at", -1)
        .limit(limit)
        .to_list(limit)
    )
    for d in docs:
        if isinstance(d.get("created_at"), str):
            d["created_at"] = datetime.fromisoformat(d["created_at"])
        d.setdefault("files", [])
    return docs


@api.get("/builds/{build_id}", response_model=Build)
async def get_build(build_id: str):
    doc = await db.builds.find_one({"id": build_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "build not found")
    if isinstance(doc.get("created_at"), str):
        doc["created_at"] = datetime.fromisoformat(doc["created_at"])
    return doc


@api.get("/builds/{build_id}/download")
async def download_build(build_id: str):
    doc = await db.builds.find_one({"id": build_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "build not found")
    files = doc.get("files", [])
    if not files:
        raise HTTPException(404, "no files in this build")

    folder = _slugify(doc.get("app", {}).get("name") or doc.get("bot", {}).get("name") or "build")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.writestr(f"{folder}/{f['path']}", f["content"])
        # bonus: bundle a build manifest
        manifest = {
            "id": doc.get("id"),
            "generation": doc.get("generation"),
            "user_prompt": doc.get("user_prompt"),
            "bot": doc.get("bot"),
            "app": doc.get("app"),
            "reward": doc.get("reward"),
            "composite_score": doc.get("composite_score"),
            "critic_notes": doc.get("critic_notes"),
            "created_at": doc.get("created_at"),
        }
        import json as _json
        zf.writestr(f"{folder}/.recursive-bbs.json", _json.dumps(manifest, indent=2))
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{folder}.zip"'},
    )


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
        await db.builds.find({}, {"_id": 0, "files": 0})
        .sort("composite_score", -1)
        .limit(limit)
        .to_list(limit)
    )
    for d in docs:
        if isinstance(d.get("created_at"), str):
            d["created_at"] = datetime.fromisoformat(d["created_at"])
        d.setdefault("files", [])
    return docs


@api.get("/lineage")
async def lineage():
    docs = (
        await db.builds.find(
            {},
            {"_id": 0, "id": 1, "parent_id": 1, "generation": 1,
             "composite_score": 1, "bot.name": 1, "app.name": 1},
        )
        .sort("created_at", 1)
        .to_list(500)
    )
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
