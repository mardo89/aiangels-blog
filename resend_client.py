#!/usr/bin/env python3
"""
resend_client.py — Thin wrapper around Resend (https://resend.com) for AI Angels.

Usage (library):
    from resend_client import send_email
    send_email(
        subject="Daily publish complete",
        html="<h1>2 PDFs live</h1><p>See report attached.</p>",
        to="info@aiangels.io",               # optional, falls back to RESEND_TO
        attachments=[("report.pdf", "/abs/path/report.pdf")],  # optional
    )

Usage (CLI):
    python3 resend_client.py test                       # Send a self-test email to RESEND_TO
    python3 resend_client.py send --to you@x.com \
        --subject "Hi" --html "<b>Hello</b>"
    python3 resend_client.py send --to you@x.com \
        --subject "Report" --text-file report.txt --attach file.pdf

Env (.env):
    RESEND_API_KEY   required
    RESEND_FROM      e.g. 'AI Angels <hello@aiangels.io>' — must be on a verified domain
    RESEND_TO        default recipient for test/daily reports
"""
import os
import sys
import json
import base64
import argparse
import mimetypes
from pathlib import Path
from typing import Iterable, Optional, Sequence, Union

import requests
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(dotenv_path=BASE_DIR / ".env", override=True)

RESEND_API = "https://api.resend.com/emails"
Attachment = Union[str, Path, tuple]  # path, or (filename, path)


class ResendError(RuntimeError):
    pass


def _encode_attachment(item: Attachment) -> dict:
    if isinstance(item, tuple):
        filename, path = item
    else:
        path = item
        filename = Path(path).name
    data = Path(path).read_bytes()
    return {
        "filename": filename,
        "content": base64.b64encode(data).decode("ascii"),
        "content_type": mimetypes.guess_type(filename)[0] or "application/octet-stream",
    }


def send_email(
    subject: str,
    html: Optional[str] = None,
    text: Optional[str] = None,
    to: Optional[Union[str, Sequence[str]]] = None,
    sender: Optional[str] = None,
    reply_to: Optional[str] = None,
    cc: Optional[Sequence[str]] = None,
    bcc: Optional[Sequence[str]] = None,
    tags: Optional[Iterable[tuple]] = None,
    attachments: Optional[Iterable[Attachment]] = None,
) -> dict:
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        raise ResendError("RESEND_API_KEY missing from environment/.env")
    sender = sender or os.environ.get("RESEND_FROM")
    if not sender:
        raise ResendError("sender not provided and RESEND_FROM not set")
    to = to or os.environ.get("RESEND_TO")
    if not to:
        raise ResendError("`to` not provided and RESEND_TO not set")
    if html is None and text is None:
        raise ResendError("provide html= or text=")

    payload = {
        "from": sender,
        "to": [to] if isinstance(to, str) else list(to),
        "subject": subject,
    }
    if html:
        payload["html"] = html
    if text:
        payload["text"] = text
    if reply_to:
        payload["reply_to"] = reply_to
    if cc:
        payload["cc"] = list(cc)
    if bcc:
        payload["bcc"] = list(bcc)
    if tags:
        payload["tags"] = [{"name": n, "value": v} for n, v in tags]
    if attachments:
        payload["attachments"] = [_encode_attachment(a) for a in attachments]

    resp = requests.post(
        RESEND_API,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )
    if resp.status_code >= 400:
        raise ResendError(f"Resend {resp.status_code}: {resp.text}")
    return resp.json()


def _cli():
    ap = argparse.ArgumentParser(description="Resend email client for AI Angels")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("test", help="Send a self-test email to RESEND_TO")

    s = sub.add_parser("send", help="Send an email")
    s.add_argument("--to", required=True)
    s.add_argument("--subject", required=True)
    s.add_argument("--html")
    s.add_argument("--text")
    s.add_argument("--html-file")
    s.add_argument("--text-file")
    s.add_argument("--attach", action="append", default=[], help="path to attachment (repeatable)")
    s.add_argument("--from", dest="sender")
    s.add_argument("--reply-to")

    args = ap.parse_args()

    if args.cmd == "test":
        result = send_email(
            subject="Resend connection test — AI Angels",
            html="<h2>✅ Resend is wired up</h2><p>Sent from <code>resend_client.py</code>.</p>",
            text="Resend is wired up. Sent from resend_client.py.",
            tags=[("source", "resend_client_test")],
        )
        print(json.dumps(result, indent=2))
        return

    html = args.html
    text = args.text
    if args.html_file:
        html = Path(args.html_file).read_text()
    if args.text_file:
        text = Path(args.text_file).read_text()

    result = send_email(
        subject=args.subject,
        html=html,
        text=text,
        to=args.to,
        sender=args.sender,
        reply_to=args.reply_to,
        attachments=args.attach or None,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    _cli()
