# Spec #360 — the pytest gate sets its own `--basetemp`, so a broken `pytest-current` can't red it

Status: building (2026-10-09).

## 1. The bug (reproduced 2026-10-09)

`%LOCALAPPDATA%\Temp\pytest-of-<user>\pytest-current` is a broken reparse
point on this machine (`Attributes: Directory, ReparsePoint`, empty
`LinkType`/`Target`). With no `--basetemp`, pytest's numbered-dir cleanup
(`pytest_sessionfinish` → `cleanup_numbered_dir` → `cleanup_dead_symlinks` →
`os.unlink`) hits it and raises `PermissionError: [WinError 5]`:

```
python -m pytest tests/test_auth.py::TestRunDevBypassScript -q -p no:xdist --no-cov
→ exit 1, no "passed" line, only the PermissionError
```

8 passing tests, red exit. In the gate this lands before pytest-cov's summary,
so `run_all_gates.sh` prints `✗ pytest failed or coverage below floor` when
neither happened. The only defence today is the operator remembering to export
`PYTEST_ADDOPTS='--basetemp=…'` with forward slashes (CLAUDE.md gotcha).

## 2. Change

`run_all_gates.sh` gate 2 passes `--basetemp=<dir>` on the pytest command
line. With a basetemp, pytest uses that directory directly and never touches
the numbered dirs or `pytest-current`, so the cleanup that crashes never runs.

`<dir>` comes from a new helper, `scripts/pytest_basetemp.py <token>`, which
prints `<system temp dir>/taskmanager-pytest-<token>`:

- **Dedicated and per run** — token = the gate script's PID. `--basetemp`
  deletes and recreates its directory, so it must never be a directory that
  holds anything else, and a per-run name means two gate runs can't wipe each
  other's tmp trees (the lane-port guard only fires later, at gate 4).
- **Outside the repo** — under `tempfile.gettempdir()`. Inside the repo,
  pytest's tmp tree reds Jest (`testMatch: **/tests/js/**/*.test.js` picks up
  the fixture `test_bug_pattern_scan.py` writes).
- **Forward slashes, absolute** — no shell/shlex step can eat a `\` and turn
  it relative.
- **Portable** — no hardcoded user path; same helper on Windows / macOS / Linux.
- Token must be non-empty `[A-Za-z0-9_-]` (it becomes a path component; the
  gate deletes this directory afterwards). Anything else → exit 2.

The gate removes the directory after pytest finishes (pass or fail). If the
operator already set `--basetemp` in `PYTEST_ADDOPTS`, the gate leaves it
alone (theirs wins) and says so.

Not changed: `pyproject.toml` `addopts` (a committed path there would be
either non-portable or relative), ad-hoc `python -m pytest` runs (the
workaround stays documented for those), the /utilities coverage card (runs
on Railway, Linux).

## 3. Tests

- `tests/test_pytest_basetemp.py` — the helper's output is absolute, forward
  slashes only, under the system temp dir, NOT inside the repo, named for the
  token, distinct per token; bad tokens (empty, `../x`, `a/b`, spaces) exit 2.
  Run as a real subprocess like the gate does.
- Proof: the gate run with **no** `PYTEST_ADDOPTS` on this machine (broken
  `pytest-current` present) → pytest gate green, `ALL GATES GREEN`, and the
  basetemp dir is gone afterwards.

## 4. Docs

- CLAUDE.md "Windows pytest teardown" gotcha: the gate is now immune; the
  manual `PYTEST_ADDOPTS` export is only for ad-hoc pytest runs.
- `templates/architecture.html` gate 2 row (cascade row 14).
