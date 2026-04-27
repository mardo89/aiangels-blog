"""
email_flow/deploy_modal.py — Deploy webhook + hourly drip cron on Modal.

State lives in Modal Dicts (atomic claim primitive — no Volume race possible):
    aiangels-signup-subs       email → subscriber profile
    aiangels-signup-claims     "{email}:{step}" → {sent_at, resend_id}
    (discount flow Dicts created lazily when ENABLE_DISCOUNT_FLOW=1)

Deploy:
    modal deploy email_flow/deploy_modal.py

Secret (already created):
    modal secret create resend-prod RESEND_API_KEY=... RESEND_FROM=...
                                   EMAIL_WEBHOOK_SECRET=... EMAIL_UNSUBSCRIBE_BASE=...
"""
from __future__ import annotations
import modal

app = modal.App("aiangels-email-flow")

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install("fastapi", "uvicorn", "requests", "python-dotenv", "pydantic[email]")
    .add_local_dir(".", remote_path="/root/app")
)

secret = modal.Secret.from_name("resend-prod")


@app.function(
    image=image,
    secrets=[secret],
    min_containers=1,
)
@modal.asgi_app()
def web():
    import sys
    sys.path.insert(0, "/root/app")
    from email_flow.webhook import app as fastapi_app
    return fastapi_app


@app.function(
    image=image,
    secrets=[secret],
    # schedule=modal.Cron("0 * * * *"),  # PAUSED until backfill prior-step fix verified
)
def drip_cron():
    import os, sys
    sys.path.insert(0, "/root/app")
    from email_flow.flow import run_drips as signup_drips
    print(f"Signup drip run: {signup_drips()}")
    if os.environ.get("ENABLE_DISCOUNT_FLOW") == "1":
        from discount_flow.flow import run_drips as discount_drips
        print(f"Discount drip run: {discount_drips()}")
