#!/usr/bin/env python3
"""
email_flow/webhook.py — FastAPI server exposing enrollment endpoints.

Run locally:
    uvicorn email_flow.webhook:app --host 0.0.0.0 --port 8787

Deploy (recommended): Modal — see email_flow/deploy_modal.py.

Endpoints:
    POST /enroll
        Body: {"email": "...", "name": "...", "source": "web"}
        Auth: x-webhook-secret header must equal $EMAIL_WEBHOOK_SECRET
        Idempotent — re-calls for the same email are a no-op.

    POST /supabase-auth
        Body: Supabase Auth webhook payload ({"type": "INSERT", "record": {...}})
        Auth: x-webhook-secret header must equal $EMAIL_WEBHOOK_SECRET

    GET  /unsubscribe?token=...
        Public — hit from the email unsubscribe link. Returns plain HTML.

    POST /upgraded
        Body: {"email": "..."}
        Auth: x-webhook-secret header. Call this from your Stripe/paywall webhook
        to stop the upgrade nudge + winback.

    POST /drips
        Auth: x-webhook-secret. Triggers the daily drip run (use instead of cron
        if you want a remote ping).

    GET  /health
"""
from __future__ import annotations
import os
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, EmailStr

from email_flow.flow import (
    enroll,
    run_drips,
    unsubscribe_by_token,
    mark_upgraded,
)
from trial_flow.flow import (
    subscribe as trial_subscribe,
    run_drips as trial_run_drips,
    mark_redeemed as trial_mark_redeemed,
    mark_redeemed_by_code as trial_mark_redeemed_by_code,
    mark_converted as trial_mark_converted,
    unsubscribe_by_token as trial_unsubscribe_by_token,
)

WEBHOOK_SECRET = os.environ.get("EMAIL_WEBHOOK_SECRET")
# Trial flow is parked until we rewire around xangels' promo_codes table.
# Set ENABLE_TRIAL_FLOW=1 in the environment to expose /trial/* routes.
ENABLE_TRIAL_FLOW = os.environ.get("ENABLE_TRIAL_FLOW", "0") == "1"

app = FastAPI(title="AI Angels Email Flow")


def _check(secret: Optional[str]) -> None:
    if not WEBHOOK_SECRET:
        raise HTTPException(500, "EMAIL_WEBHOOK_SECRET not configured")
    if secret != WEBHOOK_SECRET:
        raise HTTPException(401, "bad secret")


class EnrollBody(BaseModel):
    email: EmailStr
    name: Optional[str] = None
    source: str = "web"


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/enroll")
def post_enroll(body: EnrollBody, x_webhook_secret: Optional[str] = Header(None)):
    _check(x_webhook_secret)
    sub = enroll(body.email, body.name, body.source)
    return {"enrolled": True, "email": sub["email"], "drips_sent": sub["drips_sent"]}


@app.post("/supabase-auth")
async def post_supabase(request: Request, x_webhook_secret: Optional[str] = Header(None)):
    """
    Called by Supabase DB Webhook on auth.users changes.

    Fires welcome only when the user's email is confirmed:
      - INSERT with email_confirmed_at already set (Google OAuth — auto-confirmed)
      - UPDATE where email_confirmed_at transitions from NULL -> NOT NULL (email signup
        clicked the confirmation link)

    Unconfirmed INSERTs (email signup before verify) are intentionally skipped to
    protect sender reputation (~7% of email signups never confirm per Supabase data).
    """
    _check(x_webhook_secret)
    payload = await request.json()
    event = payload.get("type")
    record = payload.get("record") or {}
    old_record = payload.get("old_record") or {}
    email = record.get("email")
    if not email:
        raise HTTPException(400, "no email in record")

    confirmed_now = record.get("email_confirmed_at") is not None
    confirmed_before = old_record.get("email_confirmed_at") is not None

    if event == "INSERT":
        if not confirmed_now:
            return {"skipped": "insert-unconfirmed", "email": email}
    elif event == "UPDATE":
        if not confirmed_now or confirmed_before:
            return {"skipped": "not a confirmation transition", "email": email}
    else:
        return {"skipped": f"event={event}", "email": email}

    app_meta = record.get("raw_app_meta_data") or {}
    user_meta = record.get("raw_user_meta_data") or {}
    source = app_meta.get("provider") or user_meta.get("provider") or "supabase"
    sub = enroll(email, None, source)
    return {"enrolled": True, "email": sub["email"], "event": event}


@app.get("/unsubscribe", response_class=HTMLResponse)
def get_unsubscribe(token: str = ""):
    ok = unsubscribe_by_token(token) if token else False
    body = (
        "<h2>You're unsubscribed.</h2><p>You won't get more emails from AI Angels.</p>"
        if ok
        else "<h2>Link invalid or expired.</h2>"
    )
    return HTMLResponse(f"<!doctype html><html><body style='font-family:sans-serif;padding:40px;text-align:center'>{body}</body></html>")


class UpgradeBody(BaseModel):
    email: EmailStr


@app.post("/upgraded")
def post_upgraded(body: UpgradeBody, x_webhook_secret: Optional[str] = Header(None)):
    _check(x_webhook_secret)
    return {"ok": mark_upgraded(body.email)}


@app.post("/drips")
def post_drips(x_webhook_secret: Optional[str] = Header(None)):
    _check(x_webhook_secret)
    return run_drips()


# --- Trial flow ("3 days free Premium" popup) ------------------------------
# PARKED. xangels already has a live promo_codes + email system; these endpoints
# would duplicate it. Keep the code so it's one env flip away, but don't mount
# the routes when the flag is off.


class TrialSubscribeBody(BaseModel):
    email: EmailStr
    source: str = "popup"


class TrialRedeemBody(BaseModel):
    email: Optional[EmailStr] = None
    code: Optional[str] = None


if not ENABLE_TRIAL_FLOW:
    pass  # routes below are effectively disabled — see condition wrappers


@app.post("/trial/subscribe")
def post_trial_subscribe(body: TrialSubscribeBody):
    if not ENABLE_TRIAL_FLOW:
        raise HTTPException(503, "trial flow not enabled")
    """Public endpoint — called directly from the popup. No secret required
    (the popup is on aiangels.io; throttle upstream if abuse becomes an issue)."""
    sub = trial_subscribe(body.email, body.source)
    return {"ok": True, "code": sub["code"]}


@app.post("/trial/redeemed")
def post_trial_redeemed(body: TrialRedeemBody, x_webhook_secret: Optional[str] = Header(None)):
    """Called by xangels when a user redeems their code."""
    if not ENABLE_TRIAL_FLOW:
        raise HTTPException(503, "trial flow not enabled")
    _check(x_webhook_secret)
    if body.code:
        email = trial_mark_redeemed_by_code(body.code)
        return {"ok": bool(email), "email": email}
    if body.email:
        return {"ok": trial_mark_redeemed(body.email)}
    raise HTTPException(400, "provide email or code")


@app.post("/trial/converted")
def post_trial_converted(body: TrialRedeemBody, x_webhook_secret: Optional[str] = Header(None)):
    """Called by xangels (Stripe/NowPayments webhook) on first paid subscription."""
    if not ENABLE_TRIAL_FLOW:
        raise HTTPException(503, "trial flow not enabled")
    _check(x_webhook_secret)
    if not body.email:
        raise HTTPException(400, "email required")
    return {"ok": trial_mark_converted(body.email)}


@app.post("/trial/drips")
def post_trial_drips(x_webhook_secret: Optional[str] = Header(None)):
    if not ENABLE_TRIAL_FLOW:
        raise HTTPException(503, "trial flow not enabled")
    _check(x_webhook_secret)
    return trial_run_drips()


@app.get("/trial/unsubscribe", response_class=HTMLResponse)
def get_trial_unsubscribe(token: str = ""):
    if not ENABLE_TRIAL_FLOW:
        raise HTTPException(503, "trial flow not enabled")
    ok = trial_unsubscribe_by_token(token) if token else False
    body = (
        "<h2>You're unsubscribed.</h2><p>You won't get more Premium trial emails.</p>"
        if ok
        else "<h2>Link invalid or expired.</h2>"
    )
    return HTMLResponse(f"<!doctype html><html><body style='font-family:sans-serif;padding:40px;text-align:center'>{body}</body></html>")
