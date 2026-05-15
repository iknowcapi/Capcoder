"""Backend tests for RECURSIVE.BBS endpoints (stub mode)."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://self-learning-maker.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# ---- root / status ---------------------------------------------------------
def test_root(client):
    r = client.get(f"{API}/")
    assert r.status_code == 200
    d = r.json()
    assert d["system"] == "RECURSIVE.BBS"
    assert isinstance(d["stub_mode"], bool)
    assert d["models"]["generator"] == "z-ai/glm-5.1"
    assert d["models"]["critic"] == "minimaxai/minimax-m2.7"
    assert d["models"]["rater"] == "nvidia/llama-3.1-nemotron-70b-reward"


def test_status(client):
    r = client.get(f"{API}/status")
    assert r.status_code == 200
    d = r.json()
    assert "stub_mode" in d and "total_builds" in d
    assert isinstance(d["total_builds"], int)


# ---- builds CRUD-ish -------------------------------------------------------
def test_create_build_full_shape(client):
    r = client.post(f"{API}/builds", json={"prompt": "TEST_a kanban for vinyl collectors"})
    assert r.status_code == 200, r.text
    b = r.json()
    for k in ("id", "generation", "user_prompt", "meta_builder_spec",
              "app_spec", "critic_notes", "reward", "composite_score", "stub"):
        assert k in b, f"missing {k}"
    assert b["stub"] is True
    assert isinstance(b["meta_builder_spec"].get("primitives"), list)
    assert b["meta_builder_spec"].get("dna_signature", "").startswith("0x")
    assert b["meta_builder_spec"].get("name")
    assert b["meta_builder_spec"].get("domain")
    assert isinstance(b["app_spec"].get("apis"), list)
    assert isinstance(b["critic_notes"], str) and len(b["critic_notes"]) > 0
    for f in ("helpfulness", "correctness", "coherence", "complexity", "verbosity"):
        assert isinstance(b["reward"][f], (int, float))
    pytest.build_id = b["id"]
    pytest.build_score = b["composite_score"]


def test_create_build_no_prompt(client):
    r = client.post(f"{API}/builds", json={"prompt": "   "})
    assert r.status_code == 400


def test_list_builds_sorted(client):
    r = client.get(f"{API}/builds")
    assert r.status_code == 200
    items = r.json()
    assert isinstance(items, list) and len(items) >= 1
    # newest first
    ts = [x["created_at"] for x in items]
    assert ts == sorted(ts, reverse=True)


def test_get_build(client):
    r = client.get(f"{API}/builds/{pytest.build_id}")
    assert r.status_code == 200
    assert r.json()["id"] == pytest.build_id


def test_get_build_404(client):
    r = client.get(f"{API}/builds/does-not-exist")
    assert r.status_code == 404


# ---- feedback --------------------------------------------------------------
def test_feedback_upvote(client):
    r = client.post(f"{API}/builds/{pytest.build_id}/feedback", json={"vote": 1})
    assert r.status_code == 200
    d = r.json()
    assert d["user_vote"] == 1
    assert abs(d["composite_score"] - (pytest.build_score + 0.25)) < 0.01
    pytest.build_score = d["composite_score"]


def test_feedback_downvote(client):
    r = client.post(f"{API}/builds/{pytest.build_id}/feedback", json={"vote": -1})
    assert r.status_code == 200
    d = r.json()
    assert d["user_vote"] == -1
    assert abs(d["composite_score"] - (pytest.build_score - 0.25)) < 0.01


# ---- leaderboard / lineage -------------------------------------------------
def test_leaderboard_sorted(client):
    r = client.get(f"{API}/leaderboard")
    assert r.status_code == 200
    items = r.json()
    scores = [x["composite_score"] for x in items]
    assert scores == sorted(scores, reverse=True)


def test_lineage_shape(client):
    r = client.get(f"{API}/lineage")
    assert r.status_code == 200
    d = r.json()
    assert "nodes" in d and isinstance(d["nodes"], list)
    for n in d["nodes"]:
        assert "id" in n and "generation" in n


# ---- self-improvement (inherited_from) -------------------------------------
def test_self_improvement_inheritance(client):
    # upvote current build hard to ensure it's top exemplar
    for _ in range(3):
        client.post(f"{API}/builds/{pytest.build_id}/feedback", json={"vote": 1})
    r2 = client.post(f"{API}/builds", json={"prompt": "TEST_a marketplace for indie typefaces"})
    assert r2.status_code == 200
    b2 = r2.json()
    # not guaranteed to inherit (depends on primitive dedup), but if present should reference an existing id
    inh = b2["meta_builder_spec"].get("inherited_from")
    if inh:
        assert isinstance(inh, str) and len(inh) > 0


# ---- fork ------------------------------------------------------------------
def test_fork_increments_generation(client):
    parent = client.post(f"{API}/builds", json={"prompt": "TEST_parent build"}).json()
    child = client.post(f"{API}/builds", json={
        "prompt": "TEST_child build mutation",
        "parent_id": parent["id"],
    }).json()
    assert child["parent_id"] == parent["id"]
    assert child["generation"] == parent["generation"] + 1
