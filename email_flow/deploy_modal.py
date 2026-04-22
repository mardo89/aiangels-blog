"""
email_flow/deploy_modal.py — Deploy the webhook + daily drip cron on Modal.

Deploy:
    modal deploy email_flow/deploy_modal.py

Secrets (create once in the Modal dashboard, then reference here):
    resend-prod            RESEND_API_KEY, RESEND_FROM, RESEND_TO,
                           RESEND_AUDIENCE_ID (optional),
                           EMAIL_WEBHOOK_SECRET, EMAIL_UNSUBSCRIBE_BASE

The drip scheduler runs once per hour. Each step only fires when delay_days
has elapsed, so hourly granularity is fine and handles late signups cleanly.

State (email_flow/subscribers.json) lives on a Modal Volume so it persists
across container restarts.
"""
from __future__ import annotations
import modal

app = modal.App("aiangels-email-flow")

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install("fastapi", "uvicorn", "requests", "python-dotenv", "pydantic[email]")
    .add_local_dir(".", remote_path="/root/app")
)

volume = modal.Volume.from_name("aiangels-email-state", create_if_missing=True)
trial_volume = modal.Volume.from_name("aiangels-trial-state", create_if_missing=True)
secret = modal.Secret.from_name("resend-prod")


@app.function(
    image=image,
    secrets=[secret],
    volumes={
        "/root/app/email_flow": volume,
        "/root/app/trial_flow": trial_volume,
    },
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
    volumes={
        "/root/app/email_flow": volume,
        "/root/app/trial_flow": trial_volume,
    },
    schedule=modal.Cron("0 * * * *"),  # every hour
)
def drip_cron():
    import os, sys
    sys.path.insert(0, "/root/app")
    from email_flow.flow import run_drips as signup_drips
    print(f"Signup drip run: {signup_drips()}")
    volume.commit()
    # Trial flow is parked — see email_flow/webhook.py ENABLE_TRIAL_FLOW flag.
    if os.environ.get("ENABLE_TRIAL_FLOW") == "1":
        from trial_flow.flow import run_drips as trial_drips
        print(f"Trial drip run: {trial_drips()}")
        trial_volume.commit()
