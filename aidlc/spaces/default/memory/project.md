# Project-Level Rules

> LoveCA-specific specialisation loaded after `org.md` and `team.md`.

## Way of Working

- Existing `docs/` and `specs/` files remain the product and architecture
  sources of truth. AI-DLC intent artifacts reference them and record deltas;
  they do not create competing roadmaps or schemas.
- Conversation language: Simplified Chinese. Preserve official Japanese card
  names, effect text, and rule terminology where accuracy requires it.

## Walking Skeleton

- A new engine capability must prove one real card or one complete rule path
  end to end before broad registry expansion.

## Testing Posture

- Rule Engine and Effect DSL work must include exact card/effect identity,
  trigger timing, state transition, rollback, and Replay checks.
- Frontend work must run Vitest and production build; mobile interaction changes
  also require the maintained mobile viewport smoke where applicable.
- Database/importer work must verify the locked card database manifest.
- AI-DLC vendor changes must pass `python scripts/aidlc_vendor.py verify`.

## Deployment

- Hosted Online uses the existing GitHub Pages/Worker/FastAPI boundary. Do not
  add accounts, authoritative anti-cheat, or permanent user data without a new
  approved design.
- Preview, backend image, Worker, and VPS deployment triggers must be reviewed
  independently before merge or dispatch.

## Code Style

- Prefer established local helpers and typed domain models over ad hoc payload
  or string processing.
- Keep changes scoped to the owning module and avoid unrelated metadata churn.

## Tech Stack

- Python 3.11+ with FastAPI, Pydantic, SQLite, and pytest.
- React/TypeScript/Vite/Vitest for the web UI.
- Deterministic Python Rule Engine is authoritative; UI and Simple AI consume
  LegalAction output and never mutate GameState directly.

## Decided

- DECIDED: official Japanese comprehensive rules and exact card text are the
  authoritative rule basis (existing project guidance, 2026-09-01).
- DECIDED: unsupported or FAQ-sensitive effects remain explicit manual or
  unsupported behavior rather than speculative automation (existing Phase 5/6
  guidance, 2026-09-01).
- DECIDED: runtime SQLite schema and decklist format are compatibility-sensitive
  and require explicit migration design before change (existing architecture,
  2026-09-01).

## Scope Overrides

- Use `express` only for documentation, copy, or genuinely low-risk isolated UI
  fixes. Use `bugfix` for reproducible defects, `feature` for normal product or
  engine work, `infra` for CI/CD and hosting, and `classic` for cross-cutting
  Rule Engine, protocol, schema, or release-gate changes.

## Forbidden

- NEVER modify Card Schema v2, runtime SQLite schema, or decklist format as a
  side effect of unrelated work (affirmed 2026-09-01).
- NEVER silently skip a mandatory effect or claim registry coverage without a
  representative executable test (affirmed 2026-09-01).

## Mandated

- ALWAYS bind executable effects by exact identity and text revision evidence
  (affirmed 2026-09-01).
- ALWAYS preserve hidden-information boundaries across local, AI, Replay, and
  Hosted Online views (affirmed 2026-09-01).

## Corrections

<!-- The AI-DLC learning gate appends reviewed project corrections here. -->
