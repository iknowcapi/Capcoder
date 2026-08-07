"""Ownership isolation tests for chains (FIX #2/#3/#4)."""
import os
import subprocess
import uuid

import pytest
import requests
from dotenv import dotenv_values

frontend_env = dotenv_values("/app/frontend/.env")
base_url = os.environ.get("REACT_APP_BACKEND_URL") or frontend_env.get("REACT_APP_BACKEND_URL")
if not base_url:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
BASE_URL = base_url.rstrip("/")

OWNER_A = f"TEST_ownerA_{uuid.uuid4()}"
OWNER_B = f"TEST_ownerB_{uuid.uuid4()}"
AUTH_USER = "user_TESTAUTH"
AUTH_TOKEN = "MY_TEST_TOKEN"


def mongo(js):
    r = subprocess.run(["mongosh", "--quiet", "--eval", f"use('test_database');{js}"],
                       capture_output=True, text=True, timeout=60)
    return r.stdout.strip()


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def chain_a(client):
    """Chain owned by OWNER_A (anonymous)."""
    r = client.post(f"{BASE_URL}/api/evolve",
                    headers={"X-Capcode-Session": OWNER_A},
                    json={"target_prompt": "TEST_ownership a simple hello page"},
                    timeout=60)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d.get("id")
    yield d["id"]
    mongo(f'db.chains.deleteMany({{anon_session_id: /TEST_owner/}});')


@pytest.fixture(scope="module")
def seeded_auth():
    """Seed user_TESTAUTH + MY_TEST_TOKEN per /app/auth_testing.md."""
    mongo(f"""
      db.users.deleteOne({{user_id:'{AUTH_USER}'}});
      db.user_sessions.deleteOne({{session_token:'{AUTH_TOKEN}'}});
      db.users.insertOne({{user_id:'{AUTH_USER}', email:'test.user.testauth@example.com',
        name:'Test Auth User', picture:'https://via.placeholder.com/150', created_at:new Date()}});
      db.user_sessions.insertOne({{user_id:'{AUTH_USER}', session_token:'{AUTH_TOKEN}',
        expires_at:new Date(Date.now()+7*24*60*60*1000), created_at:new Date()}});
    """)
    yield AUTH_TOKEN
    mongo(f"""db.users.deleteOne({{user_id:'{AUTH_USER}'}});
              db.user_sessions.deleteOne({{session_token:'{AUTH_TOKEN}'}});
              db.chains.deleteMany({{user_id:'{AUTH_USER}'}});""")


class TestOwnership:
    # (a)(b) creation + owner read
    def test_owner_a_can_read_own_chain(self, client, chain_a):
        r = client.get(f"{BASE_URL}/api/chains/{chain_a}", headers={"X-Capcode-Session": OWNER_A}, timeout=30)
        assert r.status_code == 200, r.text
        assert r.json()["id"] == chain_a

    def test_chain_doc_has_anon_session_id(self, chain_a):
        out = mongo(f"print(JSON.stringify(db.chains.findOne({{id:'{chain_a}'}},{{anon_session_id:1,user_id:1,_id:0}})))")
        assert OWNER_A in out, out
        assert '"user_id"' not in out, out

    # (c) non-owner gets 404
    def test_owner_b_gets_404(self, client, chain_a):
        r = client.get(f"{BASE_URL}/api/chains/{chain_a}", headers={"X-Capcode-Session": OWNER_B}, timeout=30)
        assert r.status_code == 404, r.status_code

    # (d)(e) list filtering
    def test_list_filtering(self, client, chain_a):
        rb = client.get(f"{BASE_URL}/api/chains", headers={"X-Capcode-Session": OWNER_B}, timeout=30)
        assert rb.status_code == 200
        assert rb.json() == []
        ra = client.get(f"{BASE_URL}/api/chains", headers={"X-Capcode-Session": OWNER_A}, timeout=30)
        assert ra.status_code == 200
        assert chain_a in [c["id"] for c in ra.json()]

    # (f) all sub-endpoints 404 for non-owner
    @pytest.mark.parametrize("method,path,body", [
        ("get", "/download", None),
        ("get", "/download/0", None),
        ("post", "/verify", None),
        ("get", "/stream", None),
        ("post", "/push", {"session_id": OWNER_B, "repo": "TEST_repo"}),
    ])
    def test_subendpoints_404_for_non_owner(self, client, chain_a, method, path, body):
        url = f"{BASE_URL}/api/chains/{chain_a}{path}"
        h = {"X-Capcode-Session": OWNER_B}
        r = client.request(method, url, headers=h, json=body, timeout=30)
        assert r.status_code == 404, f"{path} -> {r.status_code}"

    def test_workspace_endpoint_owner_scoped(self, client, chain_a):
        """workspace endpoint must be owner-scoped: a non-owner must get
        'chain not found', not a gen-level error / 200 with file listing."""
        r = client.post(f"{BASE_URL}/api/chains/{chain_a}/workspace/1",
                        headers={"X-Capcode-Session": OWNER_B}, timeout=30)
        assert r.status_code == 404, f"workspace leaked: {r.status_code} {r.text[:200]}"
        assert r.json().get("detail") == "chain not found", \
            f"workspace endpoint is NOT owner-filtered: {r.json()}"

    # (g) no identity -> 400
    def test_evolve_without_identity_400(self, client):
        r = client.post(f"{BASE_URL}/api/evolve", json={"target_prompt": "TEST_noident page"}, timeout=30)
        assert r.status_code == 400, r.status_code
        assert "no session identity" in r.json().get("detail", "")

    # (h) no identity list -> []
    def test_list_without_identity_empty(self, client):
        r = client.get(f"{BASE_URL}/api/chains", timeout=30)
        assert r.status_code == 200, r.text
        assert r.json() == []

    # (j) query-param fallback
    def test_query_param_owner_fallback(self, client, chain_a):
        r = requests.get(f"{BASE_URL}/api/chains/{chain_a}?session_id={OWNER_A}", timeout=30)
        assert r.status_code == 200, r.status_code
        r2 = requests.get(f"{BASE_URL}/api/chains/{chain_a}?session_id={OWNER_B}", timeout=30)
        assert r2.status_code == 404


class TestSignedInOwnership:
    # (i) signed-in path
    def test_auth_me_requires_session(self, client):
        r = requests.get(f"{BASE_URL}/api/auth/me", timeout=30)
        assert r.status_code == 401, r.status_code

    def test_auth_me_with_bearer(self, seeded_auth):
        r = requests.get(f"{BASE_URL}/api/auth/me",
                         headers={"Authorization": f"Bearer {seeded_auth}"}, timeout=30)
        assert r.status_code == 200, r.text
        assert r.json()["user_id"] == AUTH_USER

    def test_signed_in_chain_stamped_with_user_id(self, seeded_auth):
        r = requests.post(f"{BASE_URL}/api/evolve",
                          headers={"Authorization": f"Bearer {seeded_auth}"},
                          json={"target_prompt": "TEST_ownership signed-in page"}, timeout=60)
        assert r.status_code == 200, r.text
        cid = r.json()["id"]
        out = mongo(f"print(JSON.stringify(db.chains.findOne({{id:'{cid}'}},{{user_id:1,anon_session_id:1,_id:0}})))")
        assert AUTH_USER in out, out
        assert "anon_session_id" not in out, out
        # owner can read
        r2 = requests.get(f"{BASE_URL}/api/chains/{cid}",
                          headers={"Authorization": f"Bearer {seeded_auth}"}, timeout=30)
        assert r2.status_code == 200
        # random anon cannot
        r3 = requests.get(f"{BASE_URL}/api/chains/{cid}",
                          headers={"X-Capcode-Session": str(uuid.uuid4())}, timeout=30)
        assert r3.status_code == 404, r3.status_code


class TestSettingsAndPushContract:
    def test_settings_roundtrip_per_session(self, client):
        sid = f"TEST_settings_{uuid.uuid4()}"
        r = client.post(f"{BASE_URL}/api/settings?session_id={sid}",
                        json={"rater": {"provider": "openrouter", "model": "openai/gpt-3.5-turbo"}}, timeout=30)
        assert r.status_code in (200, 201), r.text
        g = client.get(f"{BASE_URL}/api/settings?session_id={sid}", timeout=30)
        assert g.status_code == 200, g.text
        assert g.json().get("session_id") == sid
        assert g.json().get("rater", {}).get("model") == "openai/gpt-3.5-turbo"
        mongo(f"db.settings.deleteMany({{session_id: /TEST_settings/}})")

    def test_push_missing_credentials(self, client, chain_a):
        """Owner push without github creds -> 400 or 409 (not complete yet)."""
        r = client.post(f"{BASE_URL}/api/chains/{chain_a}/push",
                        headers={"X-Capcode-Session": OWNER_A},
                        json={"session_id": OWNER_A, "repo": "TEST_repo"}, timeout=30)
        assert r.status_code in (400, 409), r.status_code
