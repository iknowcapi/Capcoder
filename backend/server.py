"""
RECURSIVE.BBS — an application that builds bot-builders.

You push ONE button. The AI (NVIDIA NIM) hands off generation-to-generation
autonomously and emits a chain of complete, runnable code-builder applications.
You download the whole chain as a single .zip.
"""
from __future__ import annotations

import io
import json
import logging
import os
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
from fastapi import APIRouter, BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import Response, StreamingResponse
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.cors import CORSMiddleware

import chain_generator
import providers as _providers

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("recursive-bbs")

# ---------------------------------------------------------------------------
# Mongo
# ---------------------------------------------------------------------------
mongo_url = os.environ["MONGO_URL"]
db_name = os.environ["DB_NAME"]
mongo_client = AsyncIOMotorClient(mongo_url)
db = mongo_client[db_name]


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class Reward(BaseModel):
    helpfulness: float = 0.0
    correctness: float = 0.0
    coherence: float = 0.0
    complexity: float = 0.0
    verbosity: float = 0.0


class GenFile(BaseModel):
    path: str
    content: str


class Generation(BaseModel):
    model_config = ConfigDict(extra="allow")
    gen: int
    name: str = ""
    tagline: str = ""
    philosophy: str = ""
    improvement_note: str = ""
    accent_hex: str = ""
    accent2_hex: str = ""
    weights: dict = Field(default_factory=dict)
    files: list[GenFile] = Field(default_factory=list)
    critic_notes: str = ""
    reward: Reward = Field(default_factory=Reward)
    composite_score: float = 0.0


class Chain(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    depth: int
    status: str = "running"  # running | complete | failed
    fallback_used: bool = False
    generations: list[Generation] = Field(default_factory=list)
    created_at: datetime
    completed_at: Optional[datetime] = None


class EvolveRequest(BaseModel):
    depth: int = 3
    session_id: Optional[str] = None  # if set, uses saved settings; otherwise defaults


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _slug(s: str, fallback: str = "chain") -> str:
    s = re.sub(r"[^a-zA-Z0-9._-]+", "-", s or "").strip("-")
    return s or fallback


def _build_zip(chain_doc: dict, single_gen: Optional[int] = None) -> tuple[io.BytesIO, str]:
    """Build a zip containing the chain (or one specific gen)."""
    gens = chain_doc.get("generations", [])
    chain_slug = f"chain-{chain_doc['id'][:8]}"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if single_gen is not None:
            gen = next((g for g in gens if g.get("gen") == single_gen), None)
            if not gen:
                raise HTTPException(404, f"gen {single_gen} not in chain")
            folder = _slug(gen.get("name") or f"gen-{single_gen}", "gen")
            for f in gen.get("files", []):
                zf.writestr(f"{folder}/{f['path']}", f["content"])
            zf.writestr(f"{folder}/.recursive-bbs.json", json.dumps(_gen_manifest(gen), indent=2))
            return buf, f"{folder}.zip"

        # whole chain
        for g in gens:
            sub = f"gen-{g['gen']:02d}-{_slug(g.get('name','gen'), 'gen')}"
            for f in g.get("files", []):
                zf.writestr(f"{chain_slug}/{sub}/{f['path']}", f["content"])
            zf.writestr(
                f"{chain_slug}/{sub}/.recursive-bbs.json",
                json.dumps(_gen_manifest(g), indent=2),
            )
        # top-level chain manifest
        zf.writestr(f"{chain_slug}/CHAIN.md", _chain_markdown(chain_doc))
        zf.writestr(
            f"{chain_slug}/chain.json",
            json.dumps(
                {
                    "id": chain_doc["id"],
                    "depth": chain_doc["depth"],
                    "created_at": chain_doc.get("created_at"),
                    "generations": [_gen_manifest(g) for g in gens],
                },
                indent=2,
            ),
        )
    buf.seek(0)
    return buf, f"{chain_slug}.zip"


def _gen_manifest(g: dict) -> dict:
    return {
        "gen": g.get("gen"),
        "name": g.get("name"),
        "tagline": g.get("tagline"),
        "philosophy": g.get("philosophy"),
        "input_style": g.get("input_style"),
        "output_style": g.get("output_style"),
        "reward": g.get("reward"),
        "composite_score": g.get("composite_score"),
        "critic_notes": g.get("critic_notes"),
    }


def _chain_markdown(chain_doc: dict) -> str:
    lines = [
        f"# Chain {chain_doc['id']}",
        "",
        f"- depth: {chain_doc['depth']}",
        f"- created: {chain_doc.get('created_at')}",
        "- evolved by: NVIDIA NIM (GLM-5.1 generator, MiniMax-M2.7 critic, Nemotron-Super-49B rater)",
        "",
        "Every generation is itself a code-builder application: a FastAPI + HTML app that calls "
        "an LLM and produces source code from input. Run any of them with `bash run.sh`.",
        "",
        "## Generations",
        "",
    ]
    for g in chain_doc.get("generations", []):
        lines += [
            f"### Gen {g['gen']} — {g.get('name','?')}",
            f"*{g.get('tagline','')}*",
            "",
            f"- input style: `{g.get('input_style','?')}`",
            f"- output style: `{g.get('output_style','?')}`",
            f"- composite score: **{g.get('composite_score',0):.2f}**",
            "",
            f"**Philosophy:** {g.get('philosophy','')}",
            "",
            f"**Critic:** {g.get('critic_notes','')}",
            "",
            f"**Reward:** {json.dumps(g.get('reward',{}), separators=(', ', ':'))}",
            "",
            "---",
            "",
        ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# FastAPI
# ---------------------------------------------------------------------------
app = FastAPI(title="CapCode")
api = APIRouter(prefix="/api")


@api.get("/")
async def root():
    return {
        "system": "CapCode",
        "version": "2.0.0",
        "providers": {
            name: _providers.provider_available(name)
            for name in _providers.PROVIDERS
        },
        "defaults": _providers.DEFAULT_ASSIGNMENTS,
    }


@api.get("/status")
async def status():
    total = await db.chains.count_documents({})
    return {
        "total_chains": total,
        "providers": {
            name: _providers.provider_available(name)
            for name in _providers.PROVIDERS
        },
    }


@api.get("/providers/models")
async def catalog(refresh: bool = False):
    """Aggregated model catalog across all providers."""
    return {"models": await _providers.get_catalog(force=refresh),
            "defaults": _providers.DEFAULT_ASSIGNMENTS}


class SettingsPayload(BaseModel):
    planner: Optional[dict] = None
    architect: Optional[dict] = None
    builder: Optional[dict] = None
    reviewer: Optional[dict] = None
    corrector: Optional[dict] = None
    rater: Optional[dict] = None


@api.get("/settings")
async def get_settings(session_id: str):
    doc = await db.settings.find_one({"session_id": session_id}, {"_id": 0}) or {}
    roles = ("planner", "architect", "builder", "reviewer", "corrector", "rater")
    return {
        "session_id": session_id,
        **{r: doc.get(r) or _providers.DEFAULT_ASSIGNMENTS[r] for r in roles},
    }


@api.post("/settings")
async def save_settings(session_id: str, payload: SettingsPayload):
    update = {k: v for k, v in payload.model_dump().items() if v is not None}
    await db.settings.update_one(
        {"session_id": session_id},
        {"$set": {"session_id": session_id, **update}},
        upsert=True,
    )
    return await get_settings(session_id)


@api.post("/evolve", response_model=Chain)
async def evolve(req: EvolveRequest, background_tasks: BackgroundTasks):
    """One button. Kicks off chain evolution as a background task; returns the
    chain stub immediately. Poll GET /api/chains/{id} until status == 'complete'."""
    if not chain_generator.ENABLED:
        raise HTTPException(503, "No provider API key configured — cannot evolve a chain.")

    # resolve assignments from saved settings (or defaults)
    assignments = None
    if req.session_id:
        s = await db.settings.find_one({"session_id": req.session_id}, {"_id": 0})
        if s:
            roles = ("planner", "architect", "builder", "reviewer", "corrector", "rater")
            assignments = {r: s[r] for r in roles if s.get(r)}

    import uuid as _uuid

    chain_id = str(_uuid.uuid4())
    stub = {
        "id": chain_id,
        "depth": req.depth,
        "status": "running",
        "fallback_used": False,
        "generations": [],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
    }
    await db.chains.insert_one({**stub})

    async def on_gen(cid: str, gen: dict, fallback: bool):
        await db.chains.update_one(
            {"id": cid},
            {"$push": {"generations": gen}, "$set": {"fallback_used": fallback}},
        )

    async def on_done(cid: str, final: dict):
        await db.chains.update_one(
            {"id": cid},
            {"$set": {
                "status": "complete",
                "fallback_used": final["fallback_used"],
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }},
        )

    async def _runner():
        try:
            await chain_generator.evolve_chain_with_callback(
                chain_id, req.depth, on_gen, on_done, assignments=assignments
            )
        except Exception as exc:
            logger.exception("chain %s failed: %s", chain_id, exc)
            await db.chains.update_one(
                {"id": chain_id},
                {"$set": {"status": "failed", "error": str(exc)}},
            )

    background_tasks.add_task(_runner)
    # return the stub immediately
    stub_out = {**stub}
    stub_out["created_at"] = datetime.fromisoformat(stub_out["created_at"])
    return stub_out


@api.get("/chains", response_model=List[Chain])
async def list_chains(limit: int = 30):
    # exclude heavy file payloads in list view
    docs = (
        await db.chains.find(
            {},
            {
                "_id": 0,
                "generations.files": 0,
            },
        )
        .sort("created_at", -1)
        .limit(limit)
        .to_list(limit)
    )
    for d in docs:
        if isinstance(d.get("created_at"), str):
            d["created_at"] = datetime.fromisoformat(d["created_at"])
        if isinstance(d.get("completed_at"), str):
            d["completed_at"] = datetime.fromisoformat(d["completed_at"])
        for g in d.get("generations", []):
            g.setdefault("files", [])
    return docs


@api.get("/chains/{chain_id}", response_model=Chain)
async def get_chain(chain_id: str):
    doc = await db.chains.find_one({"id": chain_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "chain not found")
    for field in ("created_at", "completed_at"):
        if isinstance(doc.get(field), str):
            doc[field] = datetime.fromisoformat(doc[field])
    return doc


@api.get("/chains/{chain_id}/download")
async def download_chain(chain_id: str):
    doc = await db.chains.find_one({"id": chain_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "chain not found")
    if doc.get("status") != "complete":
        raise HTTPException(409, f"chain status is {doc.get('status')} — not ready to download")
    buf, fname = _build_zip(doc)
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@api.get("/chains/{chain_id}/download/{gen}")
async def download_gen(chain_id: str, gen: int):
    doc = await db.chains.find_one({"id": chain_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "chain not found")
    buf, fname = _build_zip(doc, single_gen=gen)
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@api.post("/chains/{chain_id}/workspace/{gen}")
async def open_in_vscode(chain_id: str, gen: int):
    """Materialize a generation's files to /workspaces so the local code-server
    (Emergent's built-in VSCode-in-browser) can open the folder."""
    doc = await db.chains.find_one({"id": chain_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "chain not found")
    gens = doc.get("generations", [])
    g = next((x for x in gens if x.get("gen") == gen), None)
    if not g:
        raise HTTPException(404, f"gen {gen} not in chain")

    import re as _re
    import pathlib

    slug = _re.sub(r"[^A-Za-z0-9]+", "-", g.get("name") or f"gen-{gen}").strip("-") or f"gen-{gen}"
    workspace_dir = pathlib.Path(f"/workspaces/{chain_id[:8]}/{slug}")
    workspace_dir.mkdir(parents=True, exist_ok=True)

    written = []
    for f in g.get("files", []):
        target = workspace_dir / f["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f["content"])
        # make .sh executable
        if target.suffix == ".sh":
            target.chmod(0o755)
        written.append(str(target.relative_to(workspace_dir)))

    return {
        "workspace_path": str(workspace_dir),
        "folder_query": f"?folder={workspace_dir}",
        "gen": gen,
        "name": g.get("name"),
        "files": written,
        # Users can open this folder in code-server (Emergent's built-in VSCode).
        # The exact code-server URL depends on the environment ingress; standard
        # Emergent layouts expose it via a port-1111 subdomain or /vscode path.
        "hint": "Open Emergent's code-server and use File > Open Folder → workspace_path, "
                "or append folder_query to the code-server URL.",
    }


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
