"""
tiers.py — trial and paid tier signup/management endpoints.

Contract these endpoints satisfy (already relied on by server.py's /evolve
and usage.py's check_budget):
  db.users doc fields:
    tier              — "free" | "trial" | "paid"
    trial_started_at  — ISO 8601 UTC, set once, first time tier becomes "trial"
    trial_used        — bool, set True the first time trial starts (one-time only)

No Stripe integration existed in this codebase before this file. Trial is
fully functional as-is (no external dependency). Paid checkout/webhook are
built against the Stripe API but WILL NOT WORK until you set:
    STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET, STRIPE_PRICE_ID_PAID
in your environment (Vercel), and `pip install stripe` (added to
requirements.txt). Until those are set, /api/tier/checkout will fail loudly
with a 500 rather than silently pretending to work.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger("tiers")

router = APIRouter(prefix="/api/tier")


# ---------------------------------------------------------------------------
# Wiring — server.py passes in its db handle, owner-resolution helper, and
# the app's api router prefix conventions via init(). Avoids a circular
# import (server.py imports this module, this module needs server.py's db).
# ---------------------------------------------------------------------------
_db = None
_owner_from_request = None


def init(db, owner_from_request):
    global _db, _owner_from_request
    _db = db
    _owner_from_request = owner_from_request


async def _require_signed_in(request: Request) -> str:
    owner = await _owner_from_request(request)
    if not owner.get("user_id"):
        raise HTTPException(401, "sign in required for trial/paid tiers")
    return owner["user_id"]


# ---------------------------------------------------------------------------
# TRIAL — no payment, one-time per account, 7-day clock starts on this call.
# ---------------------------------------------------------------------------
@router.post("/start-trial")
async def start_trial(request: Request):
    user_id = await _require_signed_in(request)
    user_doc = await _db.users.find_one({"user_id": user_id}) or {}

    if user_doc.get("trial_used"):
        raise HTTPException(409, "trial already used on this account")
    if user_doc.get("tier") == "paid":
        raise HTTPException(409, "already on paid tier")

    now = datetime.now(timezone.utc).isoformat()
    await _db.users.update_one(
        {"user_id": user_id},
        {"$set": {"tier": "trial", "trial_started_at": now, "trial_used": True}},
    )
    return {"tier": "trial", "trial_started_at": now}


@router.get("/status")
async def tier_status(request: Request):
    """Read-only status for the frontend to render (current tier, trial days
    remaining if applicable). Does not enforce anything — usage.check_budget()
    in the /evolve path is the actual enforcement."""
    owner = await _owner_from_request(request)
    if not owner.get("user_id"):
        return {"tier": "free", "trial_days_remaining": None}

    user_doc = await _db.users.find_one({"user_id": owner["user_id"]}) or {}
    tier = user_doc.get("tier", "free")
    days_remaining = None
    if tier == "trial" and user_doc.get("trial_started_at"):
        started = datetime.fromisoformat(user_doc["trial_started_at"])
        elapsed = (datetime.now(timezone.utc) - started).days
        days_remaining = max(0, 7 - elapsed)
        if days_remaining == 0:
            # Trial's clock ran out — reflect that in status even though
            # nothing has actively flipped the tier field back yet.
            tier = "free"
    return {"tier": tier, "trial_days_remaining": days_remaining}


# ---------------------------------------------------------------------------
# PAID — Stripe checkout + webhook. Skeleton only; needs real Stripe keys
# and a real price ID before this does anything but 500.
# ---------------------------------------------------------------------------
def _stripe():
    try:
        import stripe
    except ImportError:
        raise HTTPException(500, "stripe package not installed — add `stripe` to requirements.txt")
    key = os.environ.get("STRIPE_SECRET_KEY", "").strip()
    if not key:
        raise HTTPException(500, "STRIPE_SECRET_KEY not configured — paid tier checkout is not live yet")
    stripe.api_key = key
    return stripe


@router.post("/checkout")
async def create_checkout_session(request: Request):
    user_id = await _require_signed_in(request)
    stripe = _stripe()
    price_id = os.environ.get("STRIPE_PRICE_ID_PAID", "").strip()
    if not price_id:
        raise HTTPException(500, "STRIPE_PRICE_ID_PAID not configured")

    frontend_url = os.environ.get("FRONTEND_URL", "").rstrip("/")
    if not frontend_url:
        raise HTTPException(500, "FRONTEND_URL not configured — needed for Stripe redirect URLs")

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            client_reference_id=user_id,
            success_url=f"{frontend_url}/settings?upgraded=1",
            cancel_url=f"{frontend_url}/settings?upgrade_cancelled=1",
        )
    except Exception as exc:
        logger.error("stripe checkout session creation failed: %s", exc)
        raise HTTPException(502, f"stripe error: {exc}")

    return {"checkout_url": session.url}


@router.post("/webhook")
async def stripe_webhook(request: Request):
    """Stripe calls this directly (not the frontend). Register this URL
    (<your-domain>/api/tier/webhook) in the Stripe dashboard once you have a
    real account, and set STRIPE_WEBHOOK_SECRET from that same dashboard."""
    stripe = _stripe()
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "").strip()
    if not webhook_secret:
        raise HTTPException(500, "STRIPE_WEBHOOK_SECRET not configured")

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except Exception as exc:
        logger.warning("stripe webhook signature verification failed: %s", exc)
        raise HTTPException(400, "invalid webhook signature")

    etype = event.get("type", "")
    obj = event.get("data", {}).get("object", {})

    if etype == "checkout.session.completed":
        user_id = obj.get("client_reference_id")
        if user_id:
            await _db.users.update_one(
                {"user_id": user_id},
                {"$set": {"tier": "paid", "stripe_customer_id": obj.get("customer")}},
            )
            logger.info("user %s upgraded to paid via stripe checkout", user_id)

    elif etype in ("customer.subscription.deleted", "customer.subscription.updated"):
        # On cancellation or a status change away from active, revert to free.
        status = obj.get("status")
        customer_id = obj.get("customer")
        if customer_id and (etype == "customer.subscription.deleted" or status not in ("active", "trialing")):
            user_doc = await _db.users.find_one({"stripe_customer_id": customer_id})
            if user_doc:
                await _db.users.update_one(
                    {"user_id": user_doc["user_id"]},
                    {"$set": {"tier": "free"}},
                )
                logger.info("user %s reverted to free — subscription %s", user_doc["user_id"], etype)

    return {"received": True}
