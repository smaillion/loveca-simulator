# AI-DLC Development Workflow

## Purpose

This repository uses the Codex distribution of
[AWS Labs AI-DLC Workflows](https://github.com/awslabs/aidlc-workflows) to make
requirements, design decisions, tests, reviews, and release approvals easier to
trace. AI-DLC is a development process layer. It does not become part of the
LoveCA application runtime, match protocol, database, or browser bundle.

Pinned baseline:

- AI-DLC tag: `v2.7.0`
- upstream commit: `96b11d39028955d4f92375e783525db5275cdfd8`
- distribution: `dist/codex`
- license: MIT-0
- local vendor record: `third_party/aidlc-workflows/`

The immutable upstream files are hashed in `manifest.json` with text line
endings normalized to LF. Project-owned adaptations are listed separately so
normal project guidance cannot be overwritten silently during an upgrade.

## Prerequisites

- Codex CLI `0.145.0` or later
- Bun on `PATH`
- a Git repository and a fresh Codex session after installation or upgrade

Windows Bun installation:

```powershell
npm install -g bun
```

Verify the repository integration:

```powershell
python scripts/aidlc_vendor.py verify
bun .codex/tools/aidlc-utility.ts doctor
```

Codex project hooks require explicit trust. Review `.codex/hooks.json`, then
approve the hooks in a new interactive Codex session. The repository does not
pre-seed trust into a developer's global Codex configuration.

## Starting Work

Start a fresh Codex task and invoke the orchestrator explicitly:

```text
$aidlc compose "Describe the change and acceptance target"
$aidlc --status
```

The composed workflow stops at its human gates. Approval to continue a stage is
not approval to merge a remote pull request or deploy. Those actions always
require a separate maintainer decision.

Recommended scope selection:

| Scope | Use in this project |
|---|---|
| `express` | Documentation, copy, or an isolated low-risk UI correction |
| `bugfix` | Reproducible defect with a targeted regression test |
| `feature` | Normal UI, API, Effect DSL, Rule Engine, or AI capability |
| `refactor` | Behavior-preserving cleanup with regression coverage |
| `infra` | GitHub Actions, Docker, Worker, VPS, storage lifecycle |
| `security-patch` | Access control, secret handling, data exposure |
| `classic` | Cross-cutting rules, protocol, schema, compatibility, or release gates |

Use `$aidlc --help` for current flags. Use `$aidlc --doctor` when hooks, stage
files, worktrees, or intent state appear inconsistent.

## Artifact Ownership

Existing files remain authoritative:

- `docs/05-development-roadmap.md` and `docs/07-roadmap-expanded.md` own the
  product roadmap.
- `specs/` owns stable component and protocol contracts.
- `docs/13-effect-semantics-audit.md` owns Effect Registry support evidence.
- `docs/19-ai-rule-conformance-and-strategy-audit.md` owns maintained AI and
  official-rule acceptance results.
- `docs/15-project-guidance.md` owns repository-wide branch, release, language,
  and pre-push rules.

AI-DLC records live below `aidlc/spaces/default/intents/`. They capture one
change's requirements, decisions, reviews, audit shards, and evidence. They
must reference existing authoritative documents and write only the approved
delta; they must not create a second roadmap, schema, or effect registry.

The following AI-DLC paths are committed:

- method memory and reviewed project rules
- intent state and approved artifacts
- per-clone audit shards
- CodeKB and shared knowledge intended for the team

Per-user cursors, session state, sensor caches, diagnostics, and absolute local
document aliases are ignored by `.gitignore`.

## Required Gates

Every workflow is risk-sized, but these repository gates cannot be skipped:

| Change area | Minimum evidence |
|---|---|
| Rule Engine / Live judgment | Official rule reference, deterministic state transition, boundary regression, Replay |
| Effect Registry | Exact effect identity and text revision, executor test, integrity audit |
| Hidden information / Online | Both player views, token/access checks, stale revision rollback, Replay or state hash |
| Importer / card database | Normalization test, locked manifest verification, migration/update note when incompatible |
| Runtime SQLite lifecycle | Size/pruning test, compatibility check, cleanup evidence |
| Frontend interaction | Vitest, production build, affected desktop/mobile smoke |
| CI/CD / deployment | Trigger review, secret boundary, health check, rollback path |

Unsupported or ambiguous card behavior stays visible as manual or unsupported.
AI-DLC review does not grant `reviewed_executable` status by itself.

## Branch And Approval Flow

1. Inspect existing worktrees and user changes.
2. Create the feature branch from `develop`.
3. Run AI-DLC in that branch/worktree and commit its approved intent artifacts
   with the implementation.
4. Run focused tests, full applicable regression, and
   `scripts/pre-push-check.ps1`.
5. Push and open a PR to `develop` when requested.
6. Ask the maintainer before merging the remote PR.
7. Review downstream workflow triggers before merge; deployment remains a
   separate approval.

`preview` remains an independent public-preview branch and is never an AI-DLC
Construction base for normal product work.

## Updating AI-DLC

Do not edit immutable vendor files in place. When no AI-DLC workflow is active:

1. Read the upstream release and migration notes.
2. Replace the complete `.agents/` and `.codex/` distribution trees.
3. Reapply `.codex/config.toml`, `AGENTS.md`, `.gitignore`, and project memory
   adaptations.
4. Run plugin sync if required by the upstream release.
5. Regenerate and verify the vendor manifest:

```powershell
python scripts/aidlc_vendor.py generate --tag vX.Y.Z --commit <40-char-sha>
python scripts/aidlc_vendor.py verify
```

6. Run the official doctor and repository tests.
7. Reapprove hook trust if `.codex/hooks.json` changed.

The `AI-DLC Integrity` GitHub Actions workflow and local pre-push script reject
unexpected vendor drift.
