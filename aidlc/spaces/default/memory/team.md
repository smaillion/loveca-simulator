# Team-Level Rules

> Affirmed repository practices loaded after `org.md`. These rules are
> strict-additive and may not weaken broader safety or approval gates.

## Way of Working

- Use develop-based GitHub Flow and isolated worktrees for substantial or
  unrelated work.
- Keep online infrastructure, rule-engine changes, and preview-only changes in
  separate branches unless one reviewed design explicitly requires them
  together.
- Do not merge a remote pull request without explicit maintainer approval.

## Walking Skeleton

- Use a walking skeleton for new cross-process paths such as browser to Worker
  to FastAPI, new persistence lifecycles, and new rule execution families.
- Skip it for isolated documentation and low-risk presentation fixes.

## Testing Posture

- Methodology: risk-based test-after with regression-first bug fixes.
- Ordering: reproduce a bug when practical, implement the narrow change, run
  focused tests, then run the repository gate appropriate to the blast radius.
- Rule, effect, replay, hidden-information, database, and online protocol
  changes require deterministic state assertions in addition to UI coverage.

## Deployment

- Never assume that a successful build authorizes deployment.
- Check the workflow trigger and affected environment before approving a merge.
- Keep user data local unless a documented hosted API contract explicitly
  requires temporary server-side state.

## Code Style

- Follow the existing Python, TypeScript, React, CSS, and repository patterns.
- Use `rg` for search and `apply_patch` for manual edits.
- Keep comments concise and only where behavior is not self-explanatory.

## Forbidden

- NEVER revert unrelated user changes.
- NEVER count manual, prompt-only, or untested effects as executable coverage.
- NEVER let UI code infer trigger timing independently of the Rule Engine.
- NEVER expose opponent private cards to an AI observation or remote client.

## Mandated

- ALWAYS write user-facing progress and results in Chinese unless requested
  otherwise.
- ALWAYS keep `CHANGELOG.md` Japanese and Simplified Chinese bilingual.
- ALWAYS run `scripts/pre-push-check.ps1` before a requested push.
- ALWAYS preserve action validation, replay determinism, and rollback on an
  invalid action.

## Corrections

<!-- The AI-DLC learning gate appends reviewed team-wide corrections here. -->
