"""Backend tests for RECURSIVE.BBS code-builder bots (v0.2.0)."""
import ast
import io
import os
import zipfile

import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"


@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# ---- Root / status ----------------------------------------------------------
def test_root(session):
    r = session.get(f"{API}/")
    assert r.status_code == 200
    data = r.json()
    assert data["system"] == "RECURSIVE.BBS"
    assert data["version"] == "0.2.0"


def test_status(session):
    r = session.get(f"{API}/status")
    assert r.status_code == 200
    data = r.json()
    assert "total_builds" in data
    assert "stub_mode" not in data  # field removed


# ---- Builds (domain detection + structure) ----------------------------------
def _create(session, prompt, parent_id=None):
    payload = {"prompt": prompt}
    if parent_id:
        payload["parent_id"] = parent_id
    r = session.post(f"{API}/builds", json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def test_build_empty_prompt(session):
    r = session.post(f"{API}/builds", json={"prompt": "   "})
    assert r.status_code == 400


def test_build_kanban(session):
    b = _create(session, "a kanban board with drag-and-drop cards")
    assert b["bot"]["domain"] == "kanban"
    paths = [f["path"] for f in b["files"]]
    for expected in [
        "backend/server.py",
        "backend/requirements.txt",
        "frontend/index.html",
        "run.sh",
        "README.md",
    ]:
        assert expected in paths, f"missing {expected}"
    assert len(b["app"]["endpoints"]) == 8
    ent_names = {e["name"] for e in b["app"]["entities"]}
    assert {"Board", "Column", "Card"}.issubset(ent_names)
    assert b["composite_score"] > 2
    # stash for next tests
    pytest.kanban_build_id = b["id"]


def test_build_notes(session):
    b = _create(session, "a notes app with tags")
    assert b["bot"]["domain"] == "notes"
    server_py = next(f for f in b["files"] if f["path"] == "backend/server.py")
    assert "class Note(BaseModel)" in server_py["content"]


def test_build_habit(session):
    b = _create(session, "a habit tracker with streaks")
    assert b["bot"]["domain"] == "habit-tracker"


def test_build_chat(session):
    b = _create(session, "a chat app with rooms")
    assert b["bot"]["domain"] == "chat"


def test_build_generic(session):
    b = _create(session, "a todo list")
    assert b["bot"]["domain"] == "generic-crud"


# ---- List / get -------------------------------------------------------------
def test_list_builds_omits_files(session):
    r = session.get(f"{API}/builds")
    assert r.status_code == 200
    items = r.json()
    assert len(items) > 0
    # files field must be absent or empty list
    for it in items:
        assert not it.get("files"), "list endpoint must not include heavy 'files'"


def test_get_build_includes_files(session):
    bid = pytest.kanban_build_id
    r = session.get(f"{API}/builds/{bid}")
    assert r.status_code == 200
    data = r.json()
    assert data["files"]
    assert any(f["path"] == "backend/server.py" for f in data["files"])


# ---- Download zip -----------------------------------------------------------
def test_download_zip_and_python_validity(session):
    bid = pytest.kanban_build_id
    r = session.get(f"{API}/builds/{bid}/download")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/zip")
    cd = r.headers.get("content-disposition", "")
    assert "attachment" in cd and ".zip" in cd

    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = zf.namelist()
    # single top-level folder
    tops = {n.split("/", 1)[0] for n in names}
    assert len(tops) == 1, f"expected single top-level folder, got {tops}"
    folder = tops.pop()
    for needed in [
        f"{folder}/backend/server.py",
        f"{folder}/frontend/index.html",
        f"{folder}/run.sh",
        f"{folder}/README.md",
        f"{folder}/.recursive-bbs.json",
    ]:
        assert needed in names, f"zip missing {needed}"

    # parse generated server.py to confirm valid Python
    src = zf.read(f"{folder}/backend/server.py").decode()
    ast.parse(src)  # raises SyntaxError if invalid

    # confirm kanban routes present
    for route in ["/api/boards", "/api/columns", "/api/cards", "/api/cards/{card_id}/move"]:
        assert route in src, f"missing route {route}"


# ---- Feedback / leaderboard / lineage / fork --------------------------------
def test_feedback_increments_score(session):
    bid = pytest.kanban_build_id
    before = session.get(f"{API}/builds/{bid}").json()["composite_score"]
    r = session.post(f"{API}/builds/{bid}/feedback", json={"vote": 1})
    assert r.status_code == 200
    data = r.json()
    assert data["user_vote"] == 1
    assert round(data["composite_score"] - before, 3) == 0.25


def test_leaderboard_sorted(session):
    r = session.get(f"{API}/leaderboard")
    assert r.status_code == 200
    items = r.json()
    scores = [it["composite_score"] for it in items]
    assert scores == sorted(scores, reverse=True)


def test_lineage_nodes(session):
    r = session.get(f"{API}/lineage")
    assert r.status_code == 200
    data = r.json()
    assert "nodes" in data
    assert len(data["nodes"]) > 0
    # bot.name / app.name should be projected
    sample = data["nodes"][0]
    # mongo dot-projection returns nested dicts
    assert "id" in sample


def test_fork_build(session):
    parent_id = pytest.kanban_build_id
    parent = session.get(f"{API}/builds/{parent_id}").json()
    child = _create(session, "fork of kanban", parent_id=parent_id)
    assert child["parent_id"] == parent_id
    assert child["generation"] == parent["generation"] + 1
    assert child["bot"].get("inherited_from") is not None
