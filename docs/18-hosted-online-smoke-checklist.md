# Hosted Online Smoke Checklist

This checklist is the standard validation flow before merging or deploying the
Hosted Online MVP.

The goal is to verify the low-cost hosted room flow, not to prove full rule
coverage. Rule-engine or effect-execution blockers discovered here should be
recorded and moved back to Phase 5 work.

## 1. Local Automated Validation

Run from the repository root:

```powershell
python -m pytest
```

Run from `web/`:

```powershell
npm run test -- --run
npm run build
```

If validating the browser preview build with hosted API wiring:

```powershell
$env:VITE_BROWSER_PREVIEW='true'
$env:VITE_PUBLIC_API_BASE_URL='https://example.invalid'
npm run build
```

Expected result:

* Python tests pass, with only documented skips.
* Frontend tests pass.
* Production build completes.
* No generated build metadata is committed unless intentionally changed.

## 2. Docker Validation

Run from the repository root on a machine with Docker available:

```powershell
docker build -t loveca-simulator-api:online-smoke .
```

Expected result:

* Image builds without downloading card images.
* Build does not require GitHub Pages preview artifacts.
* Runtime data paths remain configurable through environment variables.

## 3. API Smoke

Use a temporary runtime database or disposable VPS runtime data.

Endpoints to verify:

```text
GET  /api/health
POST /api/rooms
POST /api/rooms/{room_code}/join
GET  /api/rooms/{room_code}?player_token=...
POST /api/rooms/{room_code}/actions
GET  /api/rooms/{room_code}/replay?player_token=...
POST /api/rooms/cleanup
```

Minimum expected behavior:

* health returns `status=ok`
* health includes the locked card database path and fingerprint
* host receives `room_code`, `player_id=player_1`, and a player token
* guest can join by room code and receives `player_id=player_2`
* polling without a token hides match payload
* polling with a valid token returns match state
* valid room action advances revision
* stale revision action is rejected and does not mutate state
* wrong token is rejected
* replay export returns final state and action history
* cleanup endpoint returns a structured count

## 4. Browser Two-Session Smoke

Open two browser sessions or profiles against the same frontend/API pair.

Flow:

1. Host selects a deck and creates a room.
2. Guest enters the room code, selects a deck, and joins.
3. Confirm both sessions show the same room code and initial match state.
4. Host chooses first player.
5. Both players complete setup and mulligan.
6. Complete at least one first-turn Member play.
7. Continue to Live Set and the first Live judgment when possible.
8. Refresh one browser session and confirm polling restores current state.
9. Export replay from the room.

Record each run:

```text
date:
branch:
commit:
api_url:
frontend_url:
room_code:
seed:
host_deck:
guest_deck:
last_revision:
result:
blocker_category:
notes:
```

Blocker categories:

* API / deployment
* CORS / tunnel
* frontend operation
* rule engine
* effect execution
* data / deck

## 5. VPS, Caddy, And Worker Gateway Checks

Before asking external testers to join:

* Origin health is reachable at `${ORIGIN_API_BASE_URL}/api/health`.
* Gateway health is reachable at the Worker URL, for example `https://loveca-api.<account>.workers.dev/api/health`.
* `LOVECA_ALLOWED_ORIGINS` includes the frontend origin.
* GitHub Pages `runtime-config.json` uses the same public API URL in `apiBaseUrl`.
* repository variable `VITE_PUBLIC_API_BASE_URL` points at the Worker URL.
* runtime room data is disposable and TTL cleanup is enabled.
* logs do not include downloaded official card images or unrelated local files.
* restart procedure is documented for the current VPS.

The VPS should expose Caddy on ports 80/443 only. FastAPI stays bound to
`127.0.0.1:8765`, and Caddy only proxies `/api/*`.

## 6. Triage Rule

Do not fix broad rule coverage problems directly in the online branch.

Use the online branch for:

* room API correctness
* polling and action transport
* deploy and CORS issues
* online-specific UI blockers

Move these back to Phase 5 branches:

* unsupported card effects
* incorrect effect prompts
* manual-resolution gaps
* rule engine legality bugs not specific to online transport
