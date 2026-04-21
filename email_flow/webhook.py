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

WEBHOOK_SECRET = os.environ.get("EMAIL_WEBHOOK_SECRET")

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
    _check(x_webhook_secret)
    payload = await request.json()
    if payload.get("type") != "INSERT":
        return {"skipped": "not an insert"}
    record = payload.get("record") or {}
    email = record.get("email")
    if not email:
        raise HTTPException(400, "no email in record")
    meta = record.get("raw_user_meta_data") or {}
    source = meta.get("provider") or "supabase"
    sub = enroll(email, None, source)
    return {"enrolled": True, "email": sub["email"]}


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
