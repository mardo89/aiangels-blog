"""
email_flow/deploy_modal.py — Deploy the webhook + daily drip cron on Modal.

Deploy:
    modal deploy email_flow/deploy_modal.py

Secret (create once):
    modal secret create resend-prod \
      RESEND_API_KEY=... RESEND_FROM="AI Angels <info@aiangels.io>" \
      EMAIL_WEBHOOK_SECRET=... EMAIL_UNSUBSCRIBE_BASE=...

State (subscribers.json) is kept on Modal Volumes mounted at /state/*
— a path outside the code tree so the volume overlay works cleanly.
The flow modules honor EMAIL_FLOW_STATE_DIR / TRIAL_FLOW_STATE_DIR envs.
"""
from __future__ import annotations
import modal

app = modal.App("aiangels-email-flow")

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install("fastapi", "uvicorn", "requests", "python-dotenv", "pydantic[email]")
    .add_local_dir(".", remote_path="/root/app")
    .env({
        "EMAIL_FLOW_STATE_DIR": "/state/signup",
        "TRIAL_FLOW_STATE_DIR": "/state/trial",
    })
)

signup_volume = modal.Volume.from_name("aiangels-email-state", create_if_missing=True)
trial_volume = modal.Volume.from_name("aiangels-trial-state", create_if_missing=True)
secret = modal.Secret.from_name("resend-prod")


@app.function(
    image=image,
    secrets=[secret],
    volumes={
        "/state/signup": signup_volume,
        "/state/trial": trial_volume,
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
        "/state/signup": signup_volume,
        "/state/trial": trial_volume,
    },
    schedule=modal.Cron("0 * * * *"),  # every hour
)
def drip_cron():
    import os, sys
    sys.path.insert(0, "/root/app")
    from email_flow.flow import run_drips as signup_drips
    print(f"Signup drip run: {signup_drips()}")
    signup_volume.commit()
    if os.environ.get("ENABLE_TRIAL_FLOW") == "1":
        from trial_flow.flow import run_drips as trial_drips
        print(f"Trial drip run: {trial_drips()}")
        trial_volume.commit()
