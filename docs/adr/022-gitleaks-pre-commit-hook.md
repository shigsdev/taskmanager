# ADR-022: gitleaks pre-commit hook (native git hook)

Date: 2026-04-21
Status: ACCEPTED

## Context

Backlog #17, completing the scope that was stubbed during the
2026-04-18 audit hardening pass. At that time:

- `.gitleaks.toml` config was added with project-tuned allowlist
- `tools/gitleaks.exe` binary auto-installer added (`scripts/install_dev_tools.sh`)
- Gate 10 was wired into `scripts/run_all_gates.sh`

What was NOT done then: the "ideally" half of #17's scope — a **native
git pre-commit hook** that runs gitleaks against staged content
BEFORE a commit is written, not just before a push.

The gap matters because:

- The full gate (`run_all_gates.sh`) is invoked by human discipline.
  Miss the gate, you ship the leak into git history.
- Once a secret is in git history, rewriting is expensive and the
  credential MUST be rotated (the assumption is always "it's already
  been scraped by the attacker infrastructure that indexes public
  pushes"). Cheapest defense is "never write the commit."

This ADR documents the native-hook addition plus the overall two-layer
design (hook + gate) and the trade-offs of each.

## Decisions

### 1. `core.hooksPath = .githooks` — repo-tracked hooks

Standard git feature since 2.9 (2016). Points `.git/hooks/` at a
tracked directory so every contributor gets the same hooks without
manual copying, symlinks, or a third-party framework (`pre-commit.com`,
`husky`, etc.).

Why not `pre-commit.com` (the Python framework)? For a single-user
repo with one hook, pulling in a multi-hundred-dep framework for one
gitleaks invocation is overkill. A 40-line bash script is legible,
debuggable, and has zero supply-chain surface.

Why not `husky`? Same argument — node-based, designed for larger
teams, adds a dependency we don't otherwise need.

### 2. Hook runs `gitleaks git --staged`, not `detect` / `protect`

gitleaks 8.x deprecated the top-level `detect` and `protect`
subcommands in favor of `gitleaks git`, `gitleaks dir`, and
`gitleaks stdin`. `git --staged` scans the staged diff only (~200ms)
which is exactly the content that's about to be committed.

Using the modern subcommand future-proofs against a removal of the
legacy name in a future major. Gate 10 in `run_all_gates.sh` still
uses `detect --no-git` — kept intentionally separate to minimize
blast radius on this change; a separate sweep can migrate it later
if gitleaks drops the legacy spelling.

### 3. Skip-if-missing, not fail-if-missing

The hook locates gitleaks via PATH → `./tools/gitleaks.exe` →
`./tools/gitleaks`. If none resolves, the hook **prints a skip
message and exits 0** — it does not block the commit.

Reasoning: a fresh clone without `install_dev_tools.sh` run would
otherwise block every commit, which is a worse onboarding experience
than "this hook doesn't run until you install it." The full gate
(`run_all_gates.sh` gate 10) DOES fail-if-missing because that's the
must-pass-before-push layer — skipping the gate is an SOP violation;
skipping the hook is just a delayed catch.

### 4. `--redact` flag on both layers

gitleaks default output prints the matched secret. `--redact` hides
it. Important because:

- Terminal scrollback on a shared workstation
- Pasting hook output into a bug report or screenshot
- CI log capture

The finding metadata (file, line, rule ID) is enough to locate the
problem; the actual secret value shouldn't be re-exposed by the
tool that's trying to prevent exposure.

### 5. Emergency bypass via `--no-verify` is documented, not removed

Git's native escape hatch (`git commit --no-verify`) bypasses all
hooks. Could we detect and re-enforce at push time? Technically yes
(pre-push hook). Chose not to — because:

- The full gate before push (`run_all_gates.sh`) catches anything a
  `--no-verify` commit would have slipped through.
- A contributor who needs `--no-verify` for a legitimate reason
  (broken hook, emergency fix) shouldn't have to fight the tool.
- Single-user repo with known contributor — trust model supports it.

The hook error message spells out `--no-verify` as the bypass AND
labels it "emergency only" so the escape hatch is discoverable but
not the default path.

## Consequences

**Easy:**
- Zero cost to future commits: hook is ~200ms on this repo (57k bytes
  of staged content max for the worst observed commit so far).
- Idempotent install — `bash scripts/install_git_hooks.sh` can be
  re-run safely.
- `core.hooksPath` is a local-only config, so each contributor must
  run the installer once. No global git surgery.
- False positives are fixable in one file (`.gitleaks.toml`
  allowlist).

**Accepted trade-offs:**
- The hook CAN be bypassed with `--no-verify`. The full gate is the
  backstop; this is documented.
- Missing gitleaks binary = silently skipped hook. Trade-off chosen
  for fresh-clone ergonomics (ADR decision 3). The full gate fails
  hard on missing binary, so the two layers cover opposite corners.
- Two invocation points (hook + gate) means two places to update if
  the allowlist changes. Mitigated by both reading the same
  `.gitleaks.toml` — one source of truth.

## Alternatives considered

- **`pre-commit` framework (pre-commit.com)**: rejected. Heavy
  dependency for one hook; bash script is simpler.
- **`husky`**: rejected. Node-based, overkill for a repo-tracked hook.
- **Server-side pre-receive hook on GitHub**: not an option — GitHub
  doesn't expose pre-receive hooks on the Free tier. GitHub's
  built-in secret scanning runs post-push and notifies, which is
  too late to prevent the history-write.
- **Rely on gate 10 alone, skip the native hook**: rejected. The
  gate runs on human discipline; the hook runs unconditionally.
  Both exist for belt-and-braces.
- **`gitleaks pre-commit` / auto-install hook from `install_dev_tools.sh`**:
  rejected. Conflating "install the binary" with "modify git config"
  is a principle-of-least-surprise violation. Keep them separate;
  user opts in to each.

## Verification

- Pre-existing baseline: `gitleaks git -v` across 180 commits →
  0 leaks (nothing pre-existing to allowlist).
- Hook blocks known-bad content: staged a test file with a real-entropy
  GitHub PAT (`ghp_Ab...`) → hook exited 1 with "potential secret
  detected" and the commit did not land.
- Hook passes clean content: staged this ADR file + the hook itself →
  hook exited 0 with "no leaks found".
- Allowlist respected: `tools/`, `.venv/`, `tests/`, `CLAUDE.md`,
  `docs/adr/` paths continue to not trigger on their documentation-
  example secrets.
- Idempotence: running `bash scripts/install_git_hooks.sh` twice
  leaves `core.hooksPath = .githooks` and no extra state.
