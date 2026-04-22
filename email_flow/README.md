# AI Angels — Signup Email Flow

Welcome + drip automation for everyone who signs up at aiangels.io.

## Flow

| Step | When | Subject | Skip if |
|------|------|---------|---------|
| `welcome` | instant | Welcome to AI Angels 💗 | — |
| `tips` | +1 day | 3 ways to make her feel real | — |
| `social` | +3 days | 5,000+ users — here's what they're saying | — |
| `upgrade` | +7 days | Unlock voice, memory + unlimited chat | `upgraded` |
| `winback` | +14 days | She's been thinking about you | `upgraded` |

Edit `email_flow/flow.py` (`FLOW` list) to change timing/subjects. Templates are HTML files under `email_flow/templates/`.

## Files

- `resend_client.py` — shared Resend sender (used by this flow + anything else)
- `email_flow/flow.py` — core: `enroll()`, `run_drips()`, `unsubscribe()`, `mark_upgraded()`
- `email_flow/webhook.py` — FastAPI endpoints for signup/unsubscribe/upgrade/drip
- `email_flow/deploy_modal.py` — Modal deployment (webhook as ASGI app + hourly cron)
- `email_flow/templates/*.html` — email bodies (`{{name}}` and `{{unsubscribe_url}}` placeholders)
- `email_flow/subscribers.json` — state store (gitignored)

## Env vars (`.env`)

```
RESEND_API_KEY=re_...
RESEND_FROM=AI Angels <info@aiangels.io>
RESEND_TO=info@aiangels.io                       # fallback for test/reports
RESEND_AUDIENCE_ID=                              # optional — syncs contacts to Resend Audience
EMAIL_WEBHOOK_SECRET=<random-32-chars>           # required for webhook auth
EMAIL_UNSUBSCRIBE_BASE=https://api.aiangels.io/unsubscribe   # where unsubscribe links point
```

## Local CLI

```bash
python3 -m email_flow.flow enroll --email x@y.com --name Mark
python3 -m email_flow.flow drips         # send any due follow-ups (cron this hourly)
python3 -m email_flow.flow list
python3 -m email_flow.flow unsubscribe --email x@y.com
python3 -m email_flow.flow upgrade --email x@y.com
```

## Deploy (Modal)

GitHub Actions is banned on this account — use Modal.

1. Create a Modal secret named `resend-prod` with every env var above.
2. `modal deploy email_flow/deploy_modal.py`
3. Modal returns a public URL like `https://<workspace>--aiangels-email-flow-web.modal.run`.
   Call it `$EMAIL_API`.

## Wire from xangels (Next.js)

**Option A — Supabase Auth Hook (zero frontend changes).**
In the Supabase dashboard → Database → Webhooks:

- Table: `auth.users`
- Events: `Insert`
- URL: `$EMAIL_API/supabase-auth`
- HTTP header: `x-webhook-secret: <EMAIL_WEBHOOK_SECRET>`

That's it — every new signup triggers the welcome email.

**No personalization.** Templates don't use first names — headlines read cleanly for everyone regardless of signup method (Google OAuth, email/password, magic link). If you want to add names later, put `{{name}}` back in templates and pass it through `enroll(email, name, source)`.

**Option B — call from a server action / API route.**
After `supabase.auth.signUp()` succeeds:

```ts
await fetch(`${process.env.EMAIL_API}/enroll`, {
  method: 'POST',
  headers: {
    'content-type': 'application/json',
    'x-webhook-secret': process.env.EMAIL_WEBHOOK_SECRET!,
  },
  body: JSON.stringify({
    email: user.email,
    name: user.user_metadata?.full_name,
    source: 'web',
  }),
});
```

**Stopping the upgrade nudge when a user subscribes.**
In your Stripe/NowPayments success webhook, fire:

```ts
await fetch(`${process.env.EMAIL_API}/upgraded`, {
  method: 'POST',
  headers: {
    'content-type': 'application/json',
    'x-webhook-secret': process.env.EMAIL_WEBHOOK_SECRET!,
  },
  body: JSON.stringify({ email: user.email }),
});
```

**Unsubscribe links** in every email already point at `$EMAIL_UNSUBSCRIBE_BASE?token=...`. Point that host at the Modal webhook's `/unsubscribe` route (or proxy through aiangels.io).

## Pre-flight checklist

- [ ] Verify `aiangels.io` in Resend → **Domains** (SPF + DKIM records live in DNS).
- [ ] Create Resend → **Audience** → copy ID into `RESEND_AUDIENCE_ID` (optional but recommended).
- [ ] Generate `EMAIL_WEBHOOK_SECRET`: `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`.
- [ ] Deploy to Modal.
- [ ] Configure Supabase webhook OR call `/enroll` from the Next.js signup path.
- [ ] Test end-to-end: sign up with a real inbox and confirm the welcome arrives.
