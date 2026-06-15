# Browser-Only Preview and GitHub Pages Release

## 1. Purpose

This document defines the preview release plan for a static, low-cost browser
build hosted on GitHub Pages.

The preview goal is to let more players try the simulator without installing a
server or running FastAPI locally. It is explicitly **not** the online two-player
mode. Network battle remains a later track.

## 2. Product Boundary

The preview version should eventually support:

* opening the app from GitHub Pages
* browsing the bundled card catalog
* building and saving decks in the browser
* importing and exporting deck files
* starting local two-player rule verification from browser-owned data through the TypeScript browser engine defined by [021 Browser Engine and Local-Rule Online](../specs/021-browser-engine-and-local-online.spec.md)
* exporting play history / replay logs as files

The preview version should not require:

* online accounts
* a backend database server
* a relay server
* cloud deck storage
* authoritative server-side rule validation

## 3. Current Architecture Gap

The current React SPA calls FastAPI `/api/*` endpoints for:

* card catalog queries
* deck library persistence
* deck analysis
* match creation
* action submission
* replay export
* cached card image lookup

GitHub Pages cannot run FastAPI or SQLite. Therefore the browser-only preview
requires a dedicated browser runtime adapter before it can fully replace the
local server.

The GitHub Pages workflow added in this phase is a deployment foundation plus a
static catalog preview. When a parsed data package is bundled, the browser can
load the catalog, facets, card detail data, effect registry summaries, and
official image URLs without FastAPI. It also provides browser-local deck storage
and a TypeScript MVP deck analyzer. It does not by itself make Python-only rule
engine code execute in the browser.

## 4. Browser Runtime Target

The browser runtime should be a separate adapter layer behind the same UI-facing
API shape used by `web/src/api.ts`.

Target browser services:

* `BrowserCatalogStore`
  * reads `preview-data/manifest.json`
  * reads static card summary/detail JSON
  * applies catalog filters in TypeScript
  * is the first browser runtime adapter implemented for the preview
* `BrowserDeckLibrary`
  * stores saved decks in IndexedDB or localStorage
  * supports create, read, update, rename, delete
  * supports JSON import/export
  * initially uses localStorage for low-cost GitHub Pages preview builds
  * seeds 20 generated preview sample decks on first launch
  * includes MVP deck legality and attribute analysis in TypeScript
* `BrowserMatchRuntime`
  * stores match snapshots, events, and actions in IndexedDB
  * enforces revision checks locally
  * exports replay JSON
* `BrowserAssetResolver`
  * resolves official `image_url` values from the static card data package
  * never requires bundled card image files in the GitHub Pages artifact
  * falls back to text card faces when official images cannot be loaded

The preferred storage is IndexedDB for larger data and localStorage only for
small settings. If implementation complexity needs to stay low, the first
preview may use localStorage for deck data and match history with documented
size limits.

The first deck browser adapter uses localStorage because deck records are small,
easy to export as JSON, and do not require IndexedDB complexity yet. If tester
data grows or replay history becomes large, deck and replay persistence should
move to IndexedDB.

Deck storage is expected to stay small. A typical `decklist.v0` record stores
only `card_code`, quantity, optional preferred printing, and a deck name. Even
20 generated sample decks plus dozens of user decks should usually remain well
below common browser localStorage limits. The preview still provides JSON import
and export so users can back up, migrate, or share decks before clearing browser
storage.

## 5. Data Package Policy

The source policy still applies.

Public GitHub Pages builds may safely include:

* project source code
* UI assets created by this project
* schemas and manifests
* checksums
* parsed card metadata after review
* parsed effect registry data after review
* links to official sources
* official card image URLs

Public GitHub Pages builds require caution before bundling:

* full official effect text
* bulk official PDF text
* bulk official card database snapshots
* any downloaded official card image files

The intended preview package bundles parsed card data and parsed skill data only.
It must not include `data/card_images`, downloaded card images, or other copied
official image assets. Card faces in the browser preview should load from the
official `image_url` values stored in the parsed card data. If those URLs fail or
are blocked, the UI should use the existing text fallback card face.

The workflow therefore defaults to a placeholder data package. Bundling parsed
official card/effect data requires explicit workflow inputs and should only be
used after public release review. Bundling full official text remains a separate
explicit decision.

## 6. GitHub Pages Workflow

Workflow:

* `.github/workflows/pages-preview.yml`

Triggers:

* `push` to `preview`
* manual `workflow_dispatch`

Default behavior:

1. install Python and Node dependencies
2. run Python tests
3. run frontend tests
4. build the React app with GitHub Pages base path
5. export parsed preview data from committed `data/loveca.sqlite3`
6. deploy `web/dist` to GitHub Pages

Manual placeholder behavior:

* `workflow_dispatch` may set `include_official_card_data=false` to publish only
  a placeholder manifest for workflow debugging.

Preview branch data build behavior:

1. commit the reviewed preview SQLite database to `data/loveca.sqlite3` on the
   dedicated `preview` branch
2. build the React SPA with `VITE_BROWSER_PREVIEW=true`
3. export parsed card/effect JSON with `scripts/export-preview-data.py`
4. deploy the static data package together with the SPA

The `preview` branch intentionally owns the public browser preview snapshot. It
does not track every `develop` change and should be updated only when the preview
experience is ready to publish. This keeps GitHub Pages releases fast and avoids
running the official importer on every development update.

When official card releases change, rebuild the local SQLite database from the
official importer, review the generated preview data, then commit the updated
`data/loveca.sqlite3` to the `preview` branch. The workflow does not publish
downloaded card images; it exports official image URLs only.

The data export keeps official image URLs as references but does not download,
copy, or publish official card image files.

Full official text bundling requires:

* `include_official_text=true`
* `public_data_acknowledgement=REVIEWED_PUBLIC_DATA_POLICY`

This does not grant redistribution rights. It only prevents accidental public
publishing without a deliberate project-level review.

## 7. Local User Data

Browser preview user data should remain local.

Data owned by the user:

* saved decks
* current editing deck
* match history
* replay logs
* UI preferences

The preview must provide file export/import for deck data and replay data before
it is presented as suitable for broad testers.

Suggested export files:

* `decklist.v0.json`
* `loveca-deck-library.v0.json`
* `loveca-replay.v0.json`
* `loveca-browser-backup.v0.json`

## 8. Acceptance Criteria for First Public Preview

Before announcing the GitHub Pages preview as a playable match simulator:

* the app loads from GitHub Pages without a FastAPI server
* catalog browsing works from static JSON
* card images load from official `image_url` values, with text fallback
* deck create/save/load/delete works in browser storage
* browser deck analysis covers MVP legality and visible attribute summaries
* the first launch provides 20 sample decks for browsing and testing
* deck import/export works
* at least one local two-player match can be created from browser data
* action logs and replay export work from browser storage
* unsupported effects can still be skipped with explicit debug events
* static data package contents have passed public-release review

Until the browser engine exists, the GitHub Pages preview should be described as a catalog, deck builder, deck analysis, and import/export preview, not as a playable battle preview.

## 9. Future Relationship to Online Play

The browser-only preview and low-cost online mode should share:

* static app deployment
* local card data strategy
* deck import/export
* replay export
* compatibility fingerprints

Online mode later adds only the relay/protocol layer. It should not require
cloud card libraries, cloud decks, or authoritative server rule execution.
