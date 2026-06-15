# Database Migration and Update Guide

This guide describes how local environments should handle SQLite database setup, rebuilds, and future data updates.

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
- Can be rebuilt from official normalized artifacts.
- Should be treated as a local cache of official Japanese source data.

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

## General Rules

- Do not manually edit SQLite rows unless performing a documented maintenance operation.
- Do not mix card catalog data and runtime match data in the same database.
- Prefer reproducible rebuilds over ad hoc mutation for the card catalog.
- Treat official Japanese card data as canonical.
- Keep local generated databases out of Git.

## Fresh Environment Setup

1. Install Python and web dependencies.

```powershell
python -m pip install -e ".[dev]"
cd web
npm install
cd ..
```

2. Initialize the card catalog database.

```powershell
loveca cards init --database data/loveca.sqlite3
```

3. Fetch official card data into a local normalized artifact.

```powershell
loveca cards import-official `
  --output-root data/imports/official `
  --delay 1
```

4. Import the normalized artifact into SQLite.

```powershell
loveca cards import `
  --database data/loveca.sqlite3 `
  --input data/imports/official/normalized/cards-official.json `
  --normalization data_sources/card-entity-normalization.json `
  --report logs/import-full.md
```

5. Build and serve the web UI.

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

