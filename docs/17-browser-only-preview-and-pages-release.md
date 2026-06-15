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
* starting local two-player rule verification from browser-owned data
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
official image URLs without FastAPI. It does not by itself make Python-only rule
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

* `push` to `develop`
* manual `workflow_dispatch`

Default behavior:

1. install Python and Node dependencies
2. run Python tests
3. run frontend tests
4. build the React app with GitHub Pages base path
5. write a placeholder `preview-data/manifest.json`
6. deploy `web/dist` to GitHub Pages

Manual data build behavior:

1. run the official importer in GitHub Actions
2. import normalized card data into a temporary SQLite database
3. export parsed card/effect JSON with `scripts/export-preview-data.py`
4. deploy the static data package together with the SPA

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

Before announcing the GitHub Pages preview as playable:

* the app loads from GitHub Pages without a FastAPI server
* catalog browsing works from static JSON
* card images load from official `image_url` values, with text fallback
* deck create/save/load/delete works in browser storage
* deck import/export works
* at least one local two-player match can be created from browser data
* action logs and replay export work from browser storage
* unsupported effects can still be skipped with explicit debug events
* static data package contents have passed public-release review

## 9. Future Relationship to Online Play

The browser-only preview and low-cost online mode should share:

* static app deployment
* local card data strategy
* deck import/export
* replay export
* compatibility fingerprints

Online mode later adds only the relay/protocol layer. It should not require
cloud card libraries, cloud decks, or authoritative server rule execution.
