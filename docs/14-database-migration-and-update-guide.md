# Database Migration and Update Guide

This guide describes how local environments should handle SQLite database setup,
rebuilds, and future data updates.

Hosted release builds use a locked repository-owned card database:
`data/loveca.sqlite3`. Maintainers regenerate and commit this file together with
`data/loveca-db-manifest.json` after official source review. CI, Docker images,
and GitHub Pages data export use that committed DB directly; ordinary users
should not import their own divergent card DB for hosted compatibility.

## Database Types

The project currently uses two local SQLite database categories.

### Card Catalog Database

Default path:

```text
data/loveca.sqlite3
```

Purpose:

- Stores imported official card data.
- Uses Schema v2.
- Is the authoritative locked card DB when committed in the repository.
- Can be rebuilt by maintainers from official normalized artifacts.

### Runtime Match Database

Default path:

```text
data/matches.sqlite3
```

Purpose:

- Stores local visual rules debugger matches.
- Stores actions, events, snapshots, and replay data.
- Is disposable local development data.
- Automatically keeps only the most recent 25 matches.

Hosted Docker deployments store this runtime database under
`runtime/matches.sqlite3` so the mounted runtime volume never hides the locked
card database copied into the image.

## General Rules

- Do not manually edit SQLite rows unless performing a documented maintenance operation.
- Do not mix card catalog data and runtime match data in the same database.
- Prefer reproducible rebuilds over ad hoc mutation for the card catalog.
- Treat official Japanese card data as canonical.
- Commit only the reviewed locked card DB and manifest.
- Keep runtime/user databases out of Git.

## Fresh Environment Setup

1. Install Python and web dependencies.

```powershell
python -m pip install -e ".[dev]"
cd web
npm install
cd ..
```

2. Use the committed card catalog database for normal development.

The repository already contains `data/loveca.sqlite3`. Only run the importer
flow below when you are intentionally refreshing the authoritative DB.

## Maintainer Card DB Refresh

1. Initialize or replace the card catalog database.

```powershell
loveca cards init --database data/loveca.sqlite3
```

2. Fetch official card data into a local normalized artifact.

```powershell
loveca cards import-official `
  --output-root data/imports/official `
  --delay 1
```

3. Import the normalized artifact into SQLite.

```powershell
loveca cards import `
  --database data/loveca.sqlite3 `
  --input data/imports/official/normalized/cards-official.json `
  --normalization data_sources/card-entity-normalization.json `
  --report logs/import-full.md
```

4. Regenerate and verify the locked manifest.

```powershell
python scripts/card-db-manifest.py generate
python scripts/card-db-manifest.py verify
```

5. Commit both `data/loveca.sqlite3` and `data/loveca-db-manifest.json`.

## Local Web UI

Build and serve the web UI:

```powershell
cd web
npm run build
cd ..
loveca web serve `
  --database data/loveca.sqlite3 `
  --matches data/matches.sqlite3 `
  --image-cache data/card_images `
  --host 127.0.0.1 `
  --port 8765
```

## Incremental Card Updates

Use incremental import when official card releases add a new card set.

1. Fetch only the target card set.

```powershell
loveca cards import-official `
  --output-root data/imports/official-bp06 `
  --mode incremental-set `
  --card-set BP06 `
  --delay 1
```

2. Validate the normalized artifact before importing.

```powershell
loveca cards validate `
  --input data/imports/official-bp06/normalized/cards-official.json `
  --normalization data_sources/card-entity-normalization.json `
  --card-set BP06 `
  --report logs/validate-bp06.md
```

3. Import the target card set.

```powershell
loveca cards import `
  --database data/loveca.sqlite3 `
  --input data/imports/official-bp06/normalized/cards-official.json `
  --normalization data_sources/card-entity-normalization.json `
  --card-set BP06 `
  --report logs/import-bp06.md
```

4. Review generated normalization candidates.

If the report indicates `completed_with_review`, inspect Work / Unit candidates before treating the update as complete.

## Rebuild Policy

Use a full rebuild when:

- The card schema version changes.
- Identifier normalization changes.
- Importer parsing behavior changes significantly.
- Local data is suspected to be corrupted.
- A development environment needs to be reset.

Recommended rebuild sequence:

1. Stop the web server.
2. Move the old database aside as a local backup.
3. Initialize a new database.
4. Import the latest normalized official artifact.
5. Re-run Deck Analyzer and catalog smoke checks.

Example:

```powershell
Move-Item data/loveca.sqlite3 data/loveca.backup.sqlite3
loveca cards init --database data/loveca.sqlite3
loveca cards import `
  --database data/loveca.sqlite3 `
  --input data/imports/official/normalized/cards-official.json `
  --normalization data_sources/card-entity-normalization.json `
  --report logs/import-rebuild.md
```

## Runtime Database Lifecycle

The runtime database is a local replay/debug cache.

Policy:

- Keep at most 25 recent matches.
- Keep only the most recent few state snapshots per match. Replay remains based
  on the initial state plus Action log, so old snapshots are disposable debug
  cache.
- Hosted API deployments restart daily at 04:00 JST and run runtime cleanup on
  startup. If an online room is interrupted by maintenance, create a new room.
- Deleting old matches also deletes their actions, events, and snapshots.
- Runtime data is not a source of truth.
- It is safe to delete `data/matches.sqlite3` when local replay history is not needed.

Manual cleanup option:

```powershell
Remove-Item data/matches.sqlite3
```

The next web server start will recreate it.

## Migration Expectations

When a future schema version is introduced:

- Add a new migration note to this guide.
- Prefer explicit version checks over silent mutation.
- Reject unsupported old schemas with a clear error.
- Provide either a documented rebuild path or a tested migration path.
- Update README setup instructions if commands change.
