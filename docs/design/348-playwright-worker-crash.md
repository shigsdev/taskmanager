# Spec #348 — the local Playwright worker crash is a Node/libuv bug; refuse an affected Node

**Filed:** 2026-09-30 ("the local Playwright suite flakes roughly once per full run")
**Picked:** 2026-10-08 — user chose to chase the root cause before any retry
workaround.
**Test tooling only** — no app code, no template/static change → no Phase 6, no
`CACHE_VERSION` bump. Nothing deploys differently, but the merge is a normal
code push, so deploy validation + prod smoke still run.

---

## 1. Root cause (found 2026-10-08)

The live #348 signature is `Error: worker process exited unexpectedly
(code=3221226505)` — 0xC0000409 — on a different, unrelated `pages.spec.js`
test each time, reported as `(0ms)`. Hit 4 of ~13 full gate runs on
2026-10-08; also seen on the old machine 2026-10-01.

Ruled out by measurement: memory (workers flat at ~250 MB), the tests
themselves, `PLAYWRIGHT_WORKERS=1`, ExpressVPN / McAfee / Citrix, Node or V8
fatal errors (`process.abort()` exits 134, not 0xC0000409; no stderr even with
`PW_RUNNER_DEBUG=1`). Windows Error Reporting stays silent because libuv calls
`SetErrorMode(SEM_NOGPFAULTERRORBOX)` (`src/win/core.c`), so a LocalDumps key
never fires for node.exe.

Caught with `cdb` attached to each worker, then a full dump of the frozen
process:

```
Security check failure or stack buffer overrun - code c0000409 (second chance)
Subcode: 0x2 FAST_FAIL_STACK_COOKIE_CHECK_FAILURE
  uv tcp connect epilogue (cookie at [rsp+1E8h]) ← uv_tcp_connect ← TCPWrap::Connect ← JS
```

That is the known Windows bug in the libuv bundled with **Node 24.15.0**: a
loopback TCP connect writes 8 bytes past a stack buffer, over the /GS cookie
(libuv/libuv#5274; root-caused in NuimanLP/srisurart-pos-flutter#166 as
`uv__is_fast_loopback_fail_supported()` calling `RtlGetVersion` with an
uninitialised `dwOSVersionInfoSize`). Every Playwright `request.*` to
`localhost:5111/5112` takes that path. **Fixed in Node 24.16.0+ and 26.1.0+**
(that PR: 5 crashes in 9 runs on 24.15.0 → 0 in 8 on 24.21.0). CI runs Node 20
on Linux — unaffected.

**Remediation (done by the user, 2026-10-08):** `winget upgrade
OpenJS.NodeJS.LTS` → Node 24.20.0.

## 2. The guard (this ship)

So it cannot return silently on any machine:

- `tests/node_version_guard.js` — pure `nodeLoopbackBugReason(version,
  platform)`: returns a one-line reason string for an affected combination,
  `null` otherwise. Affected = `win32` AND (24.x below 24.16, any 25.x, or
  26.0.x). Every other platform, and every other version, is `null` — 22.x is
  said to lack the fix but there is no evidence it has the bug, so it is not
  blocked.
- `tests/playwright-globalSetup.js` calls it and **throws** with the reason, the
  `winget upgrade OpenJS.NodeJS.LTS` command and a pointer to #348, so the run
  (and the gate) stops before any test instead of flaking ~6 minutes in. Fail,
  not warn: a known-bad Node makes the gates flaky, which is exactly #348's
  harm (it trains the operator to re-run).
- `CLAUDE.md` "Local-dev gotchas": new entry with the cause and the fix.

## 3. Tests (`tests/js/unit/node_version_guard.test.js`)

- 24.15.0 / 24.0.0 / 25.2.1 / 26.0.3 on `win32` → a reason naming the version.
- 24.16.0 / 24.20.0 / 26.1.0 / 22.12.0 / 20.18.0 on `win32` → `null`.
- 24.15.0 on `linux` / `darwin` → `null` (Windows-only bug).
- Accepts a leading `v` (`process.version` form).

## 4. Evidence the fix works

Full gate suite × 3 on Node 24.20.0 with zero worker crashes (vs 4 crash runs
of ~13 on 24.15.0).

## 5. The other #348 signatures

The two reflection flakes in the row (`ERR_NETWORK_CHANGED` on `page.goto`;
the #341 autosave wait) did not reproduce in ~13 full runs on 2026-10-08.
`ERR_NETWORK_CHANGED` is Chromium seeing a network-adapter change mid-load —
environmental. Recorded as unreproduced in the row; no test change.
