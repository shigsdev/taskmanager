# Architecture Decision Records

Each ADR is a short, dated, append-only record of a significant
architecture decision. When a decision changes, write a new ADR that
SUPERSEDES the old one — never edit the old ADR's content (only its
status header).

Why ADRs and not just code comments:

- Decisions get scattered across many files; one ADR concentrates the
  reasoning in one place
- Code comments age silently when code changes; ADRs explicitly
  enumerate consequences and alternatives, so when "the consequences
  no longer hold" it's a clear signal to write a new ADR
- A future-you (or future-Claude) reading code can grep for "ADR-NNN"
  references in code comments and immediately get the full context

## When to write an ADR

Write an ADR when:

- You're making a security-sensitive design choice (auth scope, secret
  handling, input validation)
- You're choosing between two non-obvious alternatives
- You're documenting a constraint that influences future code (e.g.
  "we don't follow HTTP redirects on outbound fetches")
- You're explaining a decision whose rationale would surprise someone
  reading just the code

Don't write an ADR for:

- Style choices that have a single right answer
- Trivial refactors
- Bug fixes that don't change architecture

## When to supersede an ADR

When a previous decision becomes wrong or incomplete:

1. Don't edit the old ADR's body — only change its `Status:` header
   to `SUPERSEDED by ADR-NNN`
2. Write a new ADR with the next number, link back to the old one in
   its Context section, explain what changed and why

## File naming

`NNN-short-kebab-case-title.md` — three-digit zero-padded for natural sort.

## Template

```markdown
# ADR-NNN: <short title>

Date: YYYY-MM-DD
Status: ACCEPTED | SUPERSEDED by ADR-NNN | DEPRECATED

## Context

What was the situation? What forces were at play? Keep it short.

## Decision

What did we choose? Single sentence ideal.

## Consequences

What does this make easy? What does it make hard? What are the
trade-offs we accepted?

## Alternatives considered

What did we look at and reject? Why?
```
