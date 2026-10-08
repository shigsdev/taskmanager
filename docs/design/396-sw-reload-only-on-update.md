# Spec #396 — the page reloads when a NEW service worker takes over, never on the first install

**Filed:** 2026-10-08 (found by #394's prod smoke)
**Status:** user said "fix it" 2026-10-08 on the fix direction in the BACKLOG row
**UI-adjacent** (`templates/base.html` inline script) → Phase 6 + deploy.

---

## 1. The problem

`templates/base.html` registers the service worker and reloads the page on
every `controllerchange`. That reload exists for **updates**: a new SW replaces
an old one (straight away, or via the update banner), and the page reloads so it
runs on the new assets. But `static/sw.js`'s `activate` handler calls
`self.clients.claim()` (`sw.js:97`), which also fires `controllerchange` on a
page that **had no controller at all** — a first visit, or after site data was
cleared. So that page reloaded once, a second or two after it appeared:

- **Users:** anything typed or clicked in that moment was lost.
- **Tests:** anything evaluating on the page raced the reload — prod smoke's
  "architecture page renders Mermaid diagrams WITH the Service Worker active"
  failed 2 of 3 runs on 2026-10-08 ("Execution context was destroyed"), and the
  local SW helpers grew workarounds for the same race (#205, PR40 #106,
  #383/#348) on the assumption the reload was intended. Nothing records a
  decision that it is: `clients.claim()` already makes the first SW control the
  page without a reload.

Reproduced locally (2026-10-08): a fresh visit to `/` with the SW enabled saw
**2** page loads, 3/3 runs.

## 2. Behaviour after the fix

`base.html` records `hadController = !!navigator.serviceWorker.controller` when
the page loads. On `controllerchange`:

- no controller before → just note that one now exists (`hadController = true`)
  and **do not reload**;
- a controller before → reload, as today (still guarded against double-fire).

So a first visit is never reloaded, an update always is — including an update
that arrives later in the same page life after a first install.

## 3. Tests (`tests/e2e-sw/service_worker.spec.js`, SW-enabled project)

- **A first visit is not reloaded** — after unregistering any SW, count
  main-frame `load` events from `goto("/")` until the SW controls the page and
  things settle: exactly 1. Red before the fix (2, 3/3).
- **An update still reloads** — on a page the SW controlled from the start
  (`primeSw`), firing `controllerchange` reloads it. Green before and after:
  the update path is unchanged.
- All SW specs (`tests/e2e-sw` + `tests/e2e/service-worker.spec.js`) 39/39 over
  3 repeats with the fix. Their reload-tolerant helpers keep working — they wait
  for a reload that now simply does not come; simplifying them is not needed.

## 4. Phase 6

Every page in the UI-audit route list (20), **with the SW active** (no
`?nosw=1` — that is the path this changes), at 1280×800 and 375×812: exactly one
load, zero console errors, `scrollWidth ≤ innerWidth` — 40/40. Screenshots of
the board at both sizes render normally under SW control.

## 5. Out of scope

- No `sw.js` change (so no `CACHE_VERSION` bump) — the SW's behaviour is right;
  only the page's reaction was wrong.
- The update banner / `userIsBusy()` logic is untouched.
