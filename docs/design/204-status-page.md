# #204 option E — an off-Railway status page

Options analysis: `docs/design/204-railway-resilience-options.md`. User
decision 2026-10-17: build option E only, and freeze C (service-worker
cached reads) and A (local read-only copy) until a second long outage. The
user approved publishing on GitHub Pages and turning Pages on.

## What it is

**https://shigsdev.github.io/taskmanager/**, a static page on GitHub
Pages, so it loads when Railway can't. While open it polls prod `/healthz`
from the browser every minute (and on **Check again**) and shows:

- **up / degraded / down**, from `status/status_helpers.js` `classify`:
  - down: unreachable, or an answer that isn't a health report, or a
    critical failure (503);
  - degraded: answered with a non-critical `fail:` check, which is named;
  - up: every check is ok, warn or skipped;
- **Last healthy**, kept in that device's localStorage, so after an outage
  it says how long the app has been unreachable;
- the deployed commit and `started_at`, plus links to the app and to
  Railway's own status page.

It shows no task data and holds no secrets; it reads only the public
health report.

## Pieces

| Piece | Where |
|---|---|
| Page + poller | `status/index.html` (self-contained CSS/JS, `noindex`) |
| Decision logic | `status/status_helpers.js`, dual export, Jest: `tests/js/unit/status_page.test.js` |
| CORS on `/healthz` for exactly `https://shigsdev.github.io` (also on 503, `Vary: Origin`) | `app.py` `healthz`, `STATUS_PAGE_ORIGIN`; pytest: `tests/test_healthz_cors.py`; ADR-040 |
| Deploy | `.github/workflows/status-page.yml`: on push to main touching `status/**` or the workflow, or by hand → `actions/upload-pages-artifact` + `deploy-pages` |
| Pages switched on | repo Settings → Pages → Source: GitHub Actions (`gh api … /pages build_type=workflow`), 2026-10-17, approved |

## Notes

- Railway's Watch Paths don't exclude `status/**`, so a status-only push
  also redeploys the app. That's harmless; `!status/**` can be added in the
  dashboard.
- The page fetches with `cache: "no-store"` and a 10-second timeout.
  Timeouts, CORS errors and network errors all count as "can't reach".
- Phase 6: from disk (`file://`), the page renders the down state, because
  prod only allows the Pages origin. After deploy, the real URL must read
  "The app is up." with the commit `/healthz` reports, at both widths.
