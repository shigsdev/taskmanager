# Git credentials — leak detection + token rotation

This runbook covers what to do when a GitHub Personal Access Token (PAT)
ends up embedded in your local `.git/config`, why it happens, and how to
prevent it.

## The leak shape

Bad — token in plaintext in `.git/config`:

```
[remote "origin"]
    url = https://shigsdev:github_pat_11B76...@github.com/shigsdev/taskmanager.git
```

Anyone with read access to your `.git/config` (laptop theft, OneDrive
sync replica, screen-share recording, AI assistant session) can extract
the token. The token then carries whatever scopes it was created with —
typically `repo` (full read/write on every private repo you own) or
`actions:write`.

Good — no embedded creds:

```
[remote "origin"]
    url = git@github.com:shigsdev/taskmanager.git
    # OR
    url = https://github.com/shigsdev/taskmanager.git
```

Detection: gate 11 in `scripts/run_all_gates.sh`
(`No embedded credentials in git remote URLs`) runs `git config
--get-regexp '^remote\..*\.url$'` and fails on any
`https://[anything]@…` shape. Token portion is redacted to `****` before
printing so the secret never lands in shell scrollback or CI logs.

## How it gets there

Most common causes (rough order of probability):

1. **AI assistant or tutorial fix.** When `git push` fails with
   `Authentication failed`, a quick fix some tools / blog posts
   recommend is:
   ```
   git remote set-url origin https://USER:TOKEN@github.com/owner/repo.git
   ```
   This works for the next push but leaves the token in the config
   permanently. Every subsequent `git push` preserves the URL.

2. **`git clone` with the token in the URL** —
   `git clone https://TOKEN@github.com/...` — same root cause; the
   origin URL is set from the clone URL.

3. **Some GUI tools / IDE plugins** that store auth this way to avoid
   the OS credential prompt. Less common since Windows Credential
   Manager became Git's default.

## Rotation procedure (when leak is detected)

### 1. Identify the affected token

The masked URL from gate 11's failure output (or `git remote -v`) tells
you the username. Match it against your token list at
https://github.com/settings/tokens.

### 2. Revoke

- Open https://github.com/settings/tokens (classic PATs) OR
  https://github.com/settings/personal-access-tokens (fine-grained).
- Find the offending token (its **Last used** timestamp helps
  identify).
- Click **Delete** (classic) or **Revoke** (fine-grained).
- DO NOT just regenerate — the goal is to break any pending use of
  the leaked token, including scripts you forgot about.

### 3. Re-set the remote without embedded creds

Pick one path:

**A — SSH (preferred for daily dev)**:

```
git remote set-url origin git@github.com:shigsdev/taskmanager.git
```

Requires an SSH key registered at
https://github.com/settings/keys. Auth is per-key, no token to leak.
The SSH key sits in `~/.ssh/` and can be passphrase-protected by your
OS keyring.

**B — HTTPS + credential helper**:

```
git remote set-url origin https://github.com/shigsdev/taskmanager.git
git config --global credential.helper manager
```

On the next `git push`, Git prompts once and stores the credential in
the OS-managed store (Windows Credential Manager / macOS Keychain /
Linux libsecret). The credential never lands in `.git/config`.

### 4. Re-validate

```
bash scripts/run_all_gates.sh
```

Gate 11 should now pass:

```
✓ no embedded credentials in git remote URLs
```

### 5. Audit for other copies

The leaked token may exist in places besides `.git/config`:

- **Shell scrollback** — `history` may contain the literal URL if you
  ever ran `git remote -v`, `git config -l`, or pasted it. Clear with
  `history -c` (bash) or `Clear-History` (PowerShell).
- **OneDrive / cloud sync versions** — `.git/config` is typically
  synced if the repo lives under OneDrive/Dropbox. Right-click in
  Explorer → Version history shows prior versions; the cloud retains
  them for the retention window (~30 days for OneDrive personal).
  After token rotation, these old versions can no longer be used
  for auth even if recovered.
- **Screenshots / pasted output** — if you ever shared `git remote -v`
  output (Slack, GitHub issue, AI chat), the token may live there.
  Rotation invalidates any such copy.
- **CI logs** — GitHub Actions auto-masks `${{ secrets.* }}` values
  but only those values; an embedded-URL token in `actions/checkout`
  config can slip through.

### 6. Generate a replacement (only what you need)

When you do need a token (e.g. for the #223 GitHub Actions dispatch
endpoints on `/utilities`):

- Prefer **fine-grained PATs** over classic.
- Repository access: **only the specific repo** that needs it.
- Permissions: **only the scope needed** (e.g. `Actions: read & write`
  for workflow dispatch; do NOT grant `Contents` if you don't need git
  push from this token).
- Expiration: **90 days max** — match the daily-backup PAT cadence so
  rotation becomes routine.
- Store the new token: in your **secrets manager** (1Password, Bitwarden,
  Railway env-var UI). NEVER in a `.git/config`, NEVER pasted into chat,
  NEVER committed.

## Prevention

Gate 11 catches the leak shape automatically on every
`bash scripts/run_all_gates.sh` run. Adding a remote URL with embedded
credentials — even unintentionally during an AI session — fails the
gate immediately at commit time, with a clear redacted preview of the
offending URL and the fix command.

Additional defenses already in the repo:

- **gitleaks** (gate 10) scans the working tree for committed secrets.
  It does NOT scan `.git/config` (local-only state) — gate 11 covers
  that blind spot.
- **`.gitignore`** excludes `.env*` and `.flaskenv` so credentials in
  environment files can't be committed.

## Incident: 2026-05-24

Discovered during a Claude session: `git remote -v` revealed a
fine-grained PAT (`github_pat_11B76MORI…`) embedded in the origin URL.
Token had been in `.git/config` for an unknown duration prior — the
file was last modified during routine pushes from the discovery
session, but the embedded URL pre-dated the session. Most likely
introduced by an earlier AI-assistant push-failure workaround.

Rotation completed same day. Gate 11 added the same day to prevent
recurrence.
