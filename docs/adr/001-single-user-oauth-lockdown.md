# ADR-001: Single-user OAuth lockdown

Date: 2026-04-05
Status: ACCEPTED

## Context

This is a personal task manager — built for one user. Adding
multi-user infrastructure (per-user data partitioning, role-based
access, account management UI) would be substantial overhead for zero
benefit; the user is the only person who should ever log in.

But "personal app" doesn't mean "no auth." The app contains:

- Tasks and goals (potentially sensitive)
- Email digest configuration (would let an attacker hijack the
  daily summary email)
- Sensitive fields encrypted with `ENCRYPTION_KEY`
- An import feature that accepts file uploads

So we need auth, but the simplest model that works: one user, hard
allowlist.

## Decision

Use Google OAuth (via flask-dance) for sign-in, then check that the
authenticated user's email matches the configured `AUTHORIZED_EMAIL`
environment variable. Anyone else gets a 403 + cleared session.

The `login_required` decorator in `auth.py` enforces both gates:

1. Is there a Google session?
2. Does its email match `AUTHORIZED_EMAIL`?

Routes are gated at the decorator level, so adding a new route can't
accidentally skip the check (the test suite catches missing
decorators in `test_auth.py`).

## Consequences

**Easy:**
- Adding a new route is one decorator
- No multi-user data partitioning anywhere — every row in the DB
  belongs to the one user, no `user_id` foreign keys to maintain
- Auth state is just a Google OAuth session; nothing custom

**Hard:**
- Letting anyone else use the app would require a major refactor
- The `AUTHORIZED_EMAIL` is a single point of failure; if you mistype
  it on Railway, you lock yourself out (mitigated by `/healthz` env
  vars check)
- Can't share read-only views with collaborators

## Alternatives considered

- **Username/password (no OAuth)**: more code (signup, password
  reset, hashing) for less security
- **OAuth with no allowlist**: "anyone with a Google account can log
  in" — instantly turns the personal app into a public service
- **OAuth + per-user data**: full multi-tenant — way more code, no
  benefit
