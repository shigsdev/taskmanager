# ADR-035: Daily digest email over authenticated SMTP (replacing SendGrid)

Date: 2026-07-02

Status: ACCEPTED (operator-approved 2026-07-02; transport = Gmail SMTP with
an App Password)

## Context

The daily task digest was delivered through SendGrid's HTTP API
(`digest_service._sendgrid_send`). SendGrid **retired its free plan in
July 2025**; the account is now paused with zero credits, so every 07:00
America/New_York scheduled send fails with HTTP 401 *"Maximum credits
exceeded"* (surfaced on `/healthz` via the #286/#288
`digest_last_send` warn). SendGrid's cheapest paid tier ($19.95/mo for
50k emails) is poor value for a single-user tool sending ~31 emails/month.

We evaluated three replacements (backlog #289):

1. **Brevo** (free tier, 300/day) — a like-for-like ESP. Blocked by the
   Feb-2024 Gmail/Yahoo/Microsoft sender rules: sending *from* a free
   `@gmail.com`/`@yahoo.com` address through Brevo fails DKIM/DMARC
   alignment (Brevo signs as `brevo.com`, not the from-domain), so the
   mail is rejected/spam-filtered. Compliant use requires owning and
   authenticating a domain (DNS records) — real setup for no payoff on a
   personal to-self digest.
2. **Authenticated SMTP via the operator's existing Google account** —
   Google itself sends the mail, so DKIM/DMARC align natively. No domain,
   no sender verification, no ESP account. Uses a Gmail **App Password**
   (requires 2-Step Verification). Free within Gmail's ~500/day limit.
3. **Amazon SES / Resend / etc.** — all now require domain authentication
   for the same 2024 rules; larger setup than SMTP for this use case.

The operator chose **option 2**.

## Decision

Send the digest over **authenticated SMTP + STARTTLS** using Python's
stdlib `smtplib` + `email.message.EmailMessage`, in a new
`digest_service._smtp_send`. Configuration is by environment variable:

- `SMTP_HOST` (default `smtp.gmail.com`)
- `SMTP_PORT` (default `587`, STARTTLS submission)
- `SMTP_USERNAME` — the Gmail address (SMTP login)
- `SMTP_PASSWORD` — a Gmail **App Password** (16 chars; 2SV required)
- `DIGEST_FROM_EMAIL` — defaults to `SMTP_USERNAME` (Gmail requires the
  From to be the authenticated account or a verified alias)
- `DIGEST_TO_EMAIL` — recipient (unchanged)

`send_digest` returns `False` (a skip) when the credentials are missing,
and `_smtp_send` raises `EgressError` on any SMTP failure so it
propagates through the same global-error-handler + `record_send_result`
path as before (ADR-031). The surfaced error carries the SMTP status
code (e.g. 535) but **never the password** (CLAUDE.md log-hygiene) — the
`smtplib` call is wrapped and re-raised as `type(e).__name__` + code only.

The multipart body (HTML + plain-text alternative) is preserved.

### Why NOT `egress.safe_call_api`

CLAUDE.md's cascade rule routes new *external API callers* through
`egress.safe_call_api` (ADR-023). That guard is HTTP(S)-specific — it
pins the resolved IP against SSRF and scrubs headers on a
user-controllable URL. The SMTP send is a **different protocol/port to a
fixed, operator-configured relay**, not a user-supplied URL, so the
egress protections do not apply and cannot wrap an `smtplib`
connection. Using `smtplib` directly is therefore the correct seam; this
ADR records that deliberate deviation so a future reviewer doesn't
"fix" it by forcing it through egress.

## Consequences

**Easy:**
- The digest works again with zero recurring cost and no ESP account.
- DKIM/DMARC compliance is inherited from Google — no domain, no DNS.
- One fewer third-party dependency: the `sendgrid` SDK is removed from
  `requirements.txt` (nothing imports it after this change).

**Hard / trade-offs:**
- **A new credential in the threat model**: `SMTP_PASSWORD` (a Gmail App
  Password). It's scoped to mail-send on the operator's Google account
  and revocable independently (delete the App Password in Google
  Account settings) without touching the main Google login. Never
  logged. Bounded blast radius; accepted for a single-user app.
- **Gmail send limits** (~500/day) are far above the ~1/day need, but
  cap any future high-volume use — revisit if the app ever sends bulk.
- **The recurring GitHub-Actions audit/backup workflows still email via
  `SENDGRID_API_KEY`** (a separate GH secret, not the app's Railway
  env). Those alert emails hit the same dead SendGrid account and are
  now degraded (the workflows still run; only the failure-notification
  email fails). Migrating them to SMTP is a follow-up backlog item — out
  of scope here to keep this change to the user-facing digest.

## Alternatives considered

- **Brevo / another ESP** — rejected: the 2024 sender rules make a free
  from-address non-compliant without domain authentication (see Context).
- **Buy + authenticate a domain, stay on an ESP** — rejected for now:
  real DNS setup and ongoing cost for a personal to-self digest. SMTP via
  the existing Google account achieves compliant delivery for free.
- **Keep SendGrid on a paid tier** — rejected: $240/yr for ~370
  emails/yr.

## Related

- ADR-023 — egress wrapper for external HTTP callers (the seam this
  change deliberately does not use, and why).
- ADR-031 — global error handler; `_smtp_send` raises `EgressError` so
  failures shape into JSON 502 and get recorded for `/healthz`.
- #286 / #288 — `digest_last_send` outcome record + scrub that makes a
  silent scheduled-send failure a visible `/healthz` signal.
- #289 — the backlog item that scoped this provider switch.
