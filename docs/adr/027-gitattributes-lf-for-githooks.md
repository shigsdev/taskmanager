# ADR-027: Force LF line endings for `.githooks/*` and shell scripts

Date: 2026-04-22
Status: ACCEPTED

## Context

Backlog #39. The native gitleaks pre-commit hook from ADR-022 (`#17`)
shipped to `.githooks/pre-commit`. On Mac, every fresh checkout
produced this error when committing:

```
env: bash\r: No such file or directory
```

Root cause: the hook file was being written to disk with CRLF line
endings, so the shebang `#!/usr/bin/env bash\n` became
`#!/usr/bin/env bash\r\n`. The `env` exec-loader takes everything
after `#!` literally as a path + args, so it tried to find an
interpreter named `bash\r` — which does not exist anywhere on PATH.

The full `run_all_gates.sh` gitleaks check was unaffected (different
codepath — runs as the gate via `bash scripts/run_all_gates.sh`,
where bash itself parses the file content rather than the kernel
exec loader looking at the shebang). So the bug was invisible from
the Windows author's machine.

### Why was it CRLF on Mac?

Pre-existing `.gitattributes` had:

```
* text=auto                         # default: native line endings on checkout
*.sh text eol=lf                    # explicit: LF for shell scripts
```

The hook lives at `.githooks/pre-commit` — extension-less. Neither
rule matched it directly, so the default `* text=auto` applied. With
`text=auto`, git uses the platform's default line endings on
checkout: CRLF on Windows (where the file was originally committed)
and LF on Mac for newly-checked-out files.

But on the Mac side, the user had at some point run a
`git config core.autocrlf` change OR a clone happened while
autocrlf was momentarily set, OR the file was committed FROM
Windows with CRLF baked in BEFORE this fix. Whichever the path,
the symptom was the same: Mac checkout produced CRLF, shebang
broke, hook silently disabled.

The fix is to add an explicit LF rule for the hook directory so
neither `text=auto` nor any contributor's local autocrlf setting
can override it.

## Decisions

### 1. Add `.githooks/* text eol=lf` to `.gitattributes`

Explicit rule that fires for the path pattern git hooks live at.
Wins over `* text=auto` because more-specific patterns take
precedence. Wins over local `core.autocrlf=true` because
`.gitattributes` is repo-tracked and authoritative for path-pattern
attributes.

Also added `*.bash text eol=lf` for completeness alongside the
existing `*.sh` rule — same exec-loader concern applies to any
script kernel-exec'd via shebang.

### 2. Renormalize the working tree as part of this commit

`git add --renormalize .` re-applies the `.gitattributes` rules to
every tracked file. For files already at LF (which the in-repo
versions of our hooks already were), this is a no-op. For any file
that had CRLF in the index, it would be rewritten to LF.

The commit produced no other file changes besides `.gitattributes`
itself — confirming nothing in the repo was actually CRLF at the
time of the fix. The fix is preventative against future commits
re-introducing CRLF (e.g. from a Windows machine without the
gitattributes rules merged yet).

### 3. Repo-level hygiene tests as the regression guard

`tests/test_repo_hygiene.py` adds 6 tests that read the actual
working-tree bytes:

- 4 parametrized tests, one per shell file, asserting `b"\r\n" not in raw`
- 1 test asserting `.gitattributes` contains both `*.sh text eol=lf`
  AND `.githooks/* text eol=lf`
- 1 test asserting the pre-commit hook starts with exactly
  `#!/usr/bin/env bash` (no trailing `\r`, no other interpreter)

These tests fail loudly if a future commit:
- removes the `.gitattributes` rules
- bypasses them (`git commit --no-verify` after a config override)
- introduces a new shell file at a path the rules don't cover

Tests live under `tests/` so they run in every gate invocation.

## Consequences

**Easy:**
- Zero behaviour change in the running app.
- Cross-platform parity for git hooks restored.
- Future Mac contributors can install `bash scripts/install_git_hooks.sh`
  and the hook will actually run.
- The hygiene tests catch the same bug class for ANY new shell file
  added to `LF_REQUIRED`.

**Accepted trade-offs:**
- `.gitattributes` is a config file most contributors don't read.
  The new rule has a comment explaining why it's there + an ADR
  reference. The hygiene tests are the real enforcement.
- Renormalization can produce surprise diffs in repositories with
  mixed history — for us, the repo was already clean so this was
  a non-event.

## Alternatives considered

- **Switch the hook from bash to python**: rejected. Python ALSO
  parses shebangs strictly on most platforms. Same `\r` problem.
  The fix has to be at the line-ending layer regardless.
- **Mac-side post-checkout hook to `dos2unix` the file**: rejected.
  Distribution problem (every contributor would have to install it),
  and it doesn't help if the broken file was committed FROM Mac to
  begin with.
- **Use `core.autocrlf=input` repo-wide via `git config --local`**:
  rejected. `.git/config` is per-clone, not tracked, so a fresh
  clone or new contributor wouldn't pick it up. `.gitattributes` IS
  tracked.
- **Shell-out the hook to `python -c '...'` so it doesn't have a
  shebang at all**: rejected. Same shebang requirement (the
  `python` invocation has its own shebang in `python` itself);
  also makes the hook unreadable.
- **Skip the test file**: rejected. Without the tests, the next
  CRLF regression would silently disable the hook on Mac again
  and only get caught by a Mac contributor failing to commit.

## Verification

- `xxd .githooks/pre-commit | head -3` confirms the file is LF
  (`6173 680a` for `bash\n`, no `0d`).
- `git add --renormalize .` produced no other changes — every
  shell file in the repo was already LF in the index.
- All 6 new tests in `tests/test_repo_hygiene.py` pass.
- Pre-commit hook itself ran on this commit (visible as the
  "0 commits scanned" gitleaks output during the commit) and
  passed cleanly — proving the LF version still execs on Windows
  too (where it was always working).
- Mac verification: deferred to whoever next pulls on Mac. The
  hygiene tests will fail there if the pull somehow re-introduces
  CRLF, surfacing the regression at gate time instead of at commit
  time.
