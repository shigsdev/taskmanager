# Spec #389 — the NUL-byte hygiene test never reads a local virtualenv

**Filed:** 2026-10-05 (new Windows machine's baseline gate run)
**Status:** approved to build 2026-10-06 (user picked #389); no open decisions
**Test-only change.** No app code, no UI, nothing deployed changes behaviour.

---

## 1. The problem

`tests/test_repo_hygiene.py` `_tracked_text_files()` walks the whole
working tree with `rglob("*")` and drops paths that sit under a
`SKIP_DIRS` name. `SKIP_DIRS` has `.venv` and `venv` but not `.venv-mac`,
the untracked Mac virtualenv that lives in the OneDrive copy of the repo.
So `test_no_nul_bytes_in_text_sources` reads ~2,300 third-party files
(pip, cryptography, ...) that we don't author. When OneDrive holds them as
cloud-only placeholders, `read_bytes()` raises
`OSError: [Errno 22] Invalid argument` and the gate fails with nothing
wrong in the repo.

`run_all_gates.sh` already passes `--exclude=.venv-mac` to semgrep, so the
two skip lists disagree.

## 2. Behaviour after the fix

- Any directory named `.venv` **or starting with `.venv`** (`.venv-mac`,
  `.venv-linux`, `.venv312`, ...) is skipped, alongside the existing
  `SKIP_DIRS` names. A prefix rule rather than one more literal name, so
  the next per-machine venv doesn't re-open this bug.
- Skipped directories are **pruned from the walk** (`os.walk` with an
  in-place `dirnames` filter) instead of walked and filtered afterwards.
  Nothing under them is listed, stat'ed or read — which also makes the
  test faster on a tree with a full virtualenv in it.
- Everything else is unchanged: same suffixes, same assertion, same
  message.

## 3. Test

`_tracked_text_files()` takes an optional `root` (defaults to
`REPO_ROOT`). A new test builds a throwaway tree in `tmp_path`:

- `src/ok.py` — must be yielded
- `.venv-mac/lib/site.py`, `.venv-linux/x.py`, `.venv/y.py`,
  `node_modules/z.js` — must NOT be yielded (the `.venv-mac` file holds a
  raw NUL, so if it were ever read the real test would flag it)

and asserts the yielded set is exactly `{src/ok.py}`.

## 4. Out of scope

- Switching to `git ls-files` (would miss brand-new, not-yet-added files,
  which is exactly when a stray NUL lands).
- The dead `"migrations/__pycache__"` entry in `SKIP_DIRS` (a two-part
  string never equals one path part; `__pycache__` already covers it) —
  removed as part of this change since the new prune works on single
  names only.

## 5. After it ships

`.venv-mac` no longer needs to be pinned "Always keep on this device" in
OneDrive.
