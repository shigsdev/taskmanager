# CLAUDE.md — Coding Standards and Quality Gates

Claude Code must read and follow this file on every session. Every commit must
pass the quality gates described here. When in doubt, simpler is better — the
previous system failed because of complexity overhead.

---

## Quality Gates (mandatory on every commit)

- **pytest** with 80% coverage floor — no commit goes in below this bar
- **ruff** for linting and static analysis — zero warnings
- **pre-commit hooks** block commits that fail either check
- Run the full gate locally before pushing: `pytest --cov && ruff check .`

---

## Testing Requirements

- **Flask route tests** — 200 / 400 / 422 cases for every endpoint
- **Database model tests** — CRUD operations, constraint validation, enum
  boundaries, foreign key behavior
- **Auth tests** — Google OAuth flow, unauthorized access rejection,
  single-user lockdown verification (email must match `AUTHORIZED_EMAIL`)
- **Email digest tests** — mock SendGrid, verify digest content and format,
  verify sensitive fields never leak into logs or output
- **Encryption tests** — verify sensitive fields are encrypted at rest and
  never logged in plaintext
- **Import parser tests** — OneNote text parsing, Excel goals parsing,
  duplicate detection, malformed input handling
- **Image scan tests** — mock Google Vision and Claude API, verify images
  never persist to disk or DB, verify task candidate parsing

---

## Security Rules

- Never log or print sensitive fields (email addresses, API keys, tokens,
  session cookies, OAuth state)
- Always encrypt sensitive config before storing in DB (Fernet)
- Always validate that the authenticated user matches `AUTHORIZED_EMAIL`
  before serving any data — enforce at the route decorator level
- Never commit `.env` or secrets to git — `.env` is in `.gitignore` from day one
- All user input sanitized before DB insertion
- Images are processed in memory only — never written to disk or DB
- Google Vision and Claude API calls are server-side only — browsers never
  talk to those APIs directly
- Session tokens expire after 24 hours of inactivity
- HTTPS enforced via Flask-Talisman in all environments except local dev

---

## Boundary Safety

- **Python → SQL**: always use SQLAlchemy ORM, never raw string queries
- **Python → HTML**: always use Jinja2 auto-escape (never disable it)
- **Python → Email**: sanitize task content before inserting into digest
- **Python → Shell**: no shell commands built from user input, ever
- **Browser → External APIs**: never — all third-party calls are server-side

---

## Naming Conventions

- **Routes**: kebab-case (`/weekly-review`, `/print-view`)
- **Python functions**: snake_case
- **DB columns**: snake_case
- **JS functions**: camelCase, prefixed by view area
  (`taskCard*`, `goalBadge*`, `inboxTriage*`)
- **Python classes**: PascalCase
- **Constants / env vars**: UPPER_SNAKE_CASE

---

## File Structure Conventions

- One route file per major feature area: `auth`, `tasks`, `goals`, `digest`,
  `import`, `scan`
- **Models** in `models.py` — no business logic, just schema
- **Business logic** in service files: `task_service.py`, `goal_service.py`,
  `digest_service.py`, `scan_service.py`
- **Templates** follow feature naming: `tasks/index.html`, `goals/index.html`
- **Static assets** grouped by purpose: `app.js`, `capture.js`, `style.css`

---

## Documentation Rules

- `BACKLOG.md` is updated every session — move items between sections, never
  delete them
- `ARCHITECTURE.md` is regenerated whenever system topology changes
- `README.md` reflects current setup steps and current feature list
- New environment variables must be documented in README.md the same commit
  they are introduced
