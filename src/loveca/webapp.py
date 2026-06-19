"""FastAPI application for the local visual rules debugger."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from loveca import __version__
from loveca.cards.catalog import (
    CardCatalogError,
    get_catalog_card,
    list_catalog_cards,
    list_catalog_facets,
    list_review_candidates,
)
from loveca.cards.images import resolve_cached_image
from loveca.decks.analyzer import DeckFileError, analyze_deck, parse_deck
from loveca.decks.library import (
    DeckLibraryError,
    delete_saved_deck,
    list_saved_decks,
    load_saved_deck,
    rename_saved_deck,
    save_deck_payload,
    update_saved_deck,
)
from loveca.simulation.effects import DEFAULT_EFFECT_REGISTRY
from loveca.simulation.engine import RuleEngineError, generate_legal_actions
from loveca.simulation.models import (
    ActionRequest,
    ActionResult,
    GameEvent,
    LegalAction,
    MatchState,
)
from loveca.simulation.online import card_database_fingerprint, effect_registry_hash
from loveca.simulation.rooms import (
    RoomError,
    RoomNotFoundError,
    RoomRecord,
    RoomService,
    RoomStateError,
    RoomTokenError,
)
from loveca.simulation.runtime import (
    DEFAULT_ACTIVE_MATCH_TTL_HOURS,
    DEFAULT_MATCH_HISTORY_LIMIT,
    DEFAULT_MATCH_HISTORY_PAGE_SIZE,
    MAX_SNAPSHOTS_PER_MATCH,
    MatchNotFoundError,
    MatchRuntimeError,
)
from loveca.simulation.service import MatchService, MatchSetupError

PROJECT_ROOT = Path(__file__).parents[2]


def _saved_deck_identifier(path: Path) -> str:
    return path.name


class PlayerSetup(BaseModel):
    name: str
    deck: dict[str, Any] | None = None
    deck_path: str | None = None


class CreateMatchRequest(BaseModel):
    player_1: PlayerSetup
    player_2: PlayerSetup
    seed: int | None = None


class AnalyzeDeckRequest(BaseModel):
    deck: dict[str, Any]


class ShareDeckRequest(BaseModel):
    deck: dict[str, Any]


class CreateRoomRequest(BaseModel):
    player_name: str
    deck: dict[str, Any]
    seed: int | None = None


class JoinRoomRequest(BaseModel):
    player_name: str
    deck: dict[str, Any]


class RoomActionRequest(BaseModel):
    player_token: str
    action: ActionRequest


class LeaveRoomRequest(BaseModel):
    player_token: str


class AdminRuntimeCleanupRequest(BaseModel):
    retain_matches: int = Field(default=DEFAULT_MATCH_HISTORY_LIMIT, ge=1, le=1000)
    max_snapshots_per_match: int = Field(default=MAX_SNAPSHOTS_PER_MATCH, ge=1, le=50)
    older_than_hours: int | None = Field(default=None, ge=1, le=24 * 365)
    include_active_matches: bool = False
    vacuum: bool = False


class ApiSettings(BaseModel):
    card_database_path: Path
    runtime_database_path: Path
    image_cache_dir: Path
    web_dist_dir: Path
    deck_library_root: Path = Field(default=PROJECT_ROOT / "data/decks")
    allowed_deck_root: Path = Field(default=PROJECT_ROOT)
    effect_registry_path: Path = Field(default=DEFAULT_EFFECT_REGISTRY)
    allowed_origins: list[str] = Field(default_factory=list)
    room_ttl_hours: int = 24
    room_delete_grace_hours: int = 1
    match_history_limit: int = DEFAULT_MATCH_HISTORY_LIMIT
    max_snapshots_per_match: int = MAX_SNAPSHOTS_PER_MATCH
    active_match_ttl_hours: int = DEFAULT_ACTIVE_MATCH_TTL_HOURS
    admin_key: str | None = None
    public_match_endpoints: bool = True


def default_settings() -> ApiSettings:
    return ApiSettings(
        card_database_path=Path(
            os.environ.get("LOVECA_CARD_DB", PROJECT_ROOT / "data/loveca.sqlite3")
        ),
        runtime_database_path=Path(
            os.environ.get("LOVECA_MATCH_DB", PROJECT_ROOT / "data/matches.sqlite3")
        ),
        image_cache_dir=Path(
            os.environ.get("LOVECA_IMAGE_CACHE", PROJECT_ROOT / "data/card_images")
        ),
        web_dist_dir=Path(
            os.environ.get("LOVECA_WEB_DIST", PROJECT_ROOT / "web/dist")
        ),
        allowed_origins=_parse_allowed_origins(os.environ.get("LOVECA_ALLOWED_ORIGINS", "")),
        room_ttl_hours=int(os.environ.get("LOVECA_ROOM_TTL_HOURS", "24")),
        room_delete_grace_hours=int(
            os.environ.get("LOVECA_ROOM_DELETE_GRACE_HOURS", "1")
        ),
        match_history_limit=int(
            os.environ.get("LOVECA_MATCH_HISTORY_LIMIT", str(DEFAULT_MATCH_HISTORY_LIMIT))
        ),
        max_snapshots_per_match=int(
            os.environ.get(
                "LOVECA_MAX_SNAPSHOTS_PER_MATCH",
                str(MAX_SNAPSHOTS_PER_MATCH),
            )
        ),
        active_match_ttl_hours=int(
            os.environ.get(
                "LOVECA_ACTIVE_MATCH_TTL_HOURS",
                str(DEFAULT_ACTIVE_MATCH_TTL_HOURS),
            )
        ),
        admin_key=os.environ.get("LOVECA_ADMIN_KEY") or None,
        public_match_endpoints=_parse_bool(
            os.environ.get("LOVECA_PUBLIC_MATCH_ENDPOINTS"),
            default=True,
        ),
    )


def _deployment_metadata() -> dict[str, str]:
    keys = {
        "git_sha": "LOVECA_DEPLOY_GIT_SHA",
        "git_ref": "LOVECA_DEPLOY_GIT_REF",
        "github_run_id": "LOVECA_DEPLOY_GITHUB_RUN_ID",
        "image": "LOVECA_DEPLOY_IMAGE",
        "image_tag": "LOVECA_DEPLOY_IMAGE_TAG",
    }
    return {name: os.environ.get(env_name, "unknown") for name, env_name in keys.items()}


def create_app(settings: ApiSettings | None = None) -> FastAPI:
    resolved = settings or default_settings()
    service = MatchService(
        resolved.card_database_path,
        resolved.runtime_database_path,
        resolved.effect_registry_path,
        max_retained_matches=resolved.match_history_limit,
        max_snapshots_per_match=resolved.max_snapshots_per_match,
        active_match_ttl_hours=resolved.active_match_ttl_hours,
    )
    app = FastAPI(
        title="LoveCA Visual Rules Debugger",
        version=__version__,
    )
    if resolved.allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=resolved.allowed_origins,
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.state.settings = resolved
    app.state.match_service = service
    app.state.room_service = RoomService(
        service,
        resolved.runtime_database_path,
        ttl_hours=resolved.room_ttl_hours,
        delete_grace_hours=resolved.room_delete_grace_hours,
    )
    service.repository.prune_old_matches(resolved.match_history_limit)
    service.repository.prune_snapshots(resolved.max_snapshots_per_match)

    @app.get("/runtime-config.json")
    def runtime_config() -> dict[str, Any]:
        return {
            "mode": "release",
            "browserPreview": False,
            "apiBaseUrl": "",
            "publicMatchHistory": resolved.public_match_endpoints,
            "cardDatabaseFingerprint": card_database_fingerprint(
                resolved.card_database_path
            ),
        }

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "rule_version": "1.06",
            "card_database": str(resolved.card_database_path),
            "card_database_fingerprint": card_database_fingerprint(
                resolved.card_database_path
            ),
            "effect_registry_hash": effect_registry_hash(resolved.effect_registry_path),
            "deployment": _deployment_metadata(),
        }

    @app.get("/api/matches")
    def list_matches(
        page: int = Query(default=1, ge=1),
        per_page: int = Query(
            default=DEFAULT_MATCH_HISTORY_PAGE_SIZE,
            ge=1,
            le=DEFAULT_MATCH_HISTORY_PAGE_SIZE,
        ),
    ) -> dict[str, Any]:
        _reject_public_match_endpoints_disabled(app)
        return service.repository.list_matches(
            page=page,
            per_page=per_page,
            max_matches=resolved.match_history_limit,
            exclude_match_ids=app.state.room_service.repository.active_match_ids(),
        )

    @app.post("/api/matches")
    def create_match(request: CreateMatchRequest) -> dict[str, Any]:
        try:
            first_deck = _resolve_deck(request.player_1, resolved.allowed_deck_root)
            second_deck = _resolve_deck(request.player_2, resolved.allowed_deck_root)
            result = service.create_match(
                first_name=request.player_1.name,
                first_deck=first_deck,
                second_name=request.player_2.name,
                second_deck=second_deck,
                seed=request.seed,
            )
            payload = result.model_dump()
            payload["match_token"] = service.repository.issue_match_token(
                result.state.match_id
            )
            return payload
        except (DeckFileError, MatchSetupError, OSError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/rooms")
    def create_room(request: CreateRoomRequest) -> dict[str, Any]:
        try:
            room = app.state.room_service.create_room(
                host_name=request.player_name,
                host_deck=request.deck,
                seed=request.seed,
            )
            return _room_payload(
                service,
                room,
                player_id="player_1",
                player_token=room.host_token,
            )
        except (DeckFileError, RoomError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/rooms/{room_code}")
    def get_room(
        room_code: str,
        player_token: str | None = Query(default=None),
    ) -> dict[str, Any]:
        try:
            room, player_id = app.state.room_service.get_room_for_player(
                room_code,
                player_token,
            )
            return _room_payload(service, room, player_id=player_id)
        except RoomNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RoomTokenError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except RoomError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/rooms/{room_code}/join")
    def join_room(room_code: str, request: JoinRoomRequest) -> dict[str, Any]:
        try:
            room = app.state.room_service.join_room(
                room_code=room_code,
                guest_name=request.player_name,
                guest_deck=request.deck,
            )
            return _room_payload(
                service,
                room,
                player_id="player_2",
                player_token=room.guest_token,
            )
        except RoomNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (DeckFileError, MatchSetupError, RoomStateError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/rooms/{room_code}/leave")
    def leave_room(room_code: str, request: LeaveRoomRequest) -> dict[str, Any]:
        try:
            room = app.state.room_service.leave_room(
                room_code=room_code,
                token=request.player_token,
            )
            return _room_payload(service, room, player_id=None)
        except RoomNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RoomTokenError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except RoomError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/rooms/{room_code}/actions")
    def submit_room_action(room_code: str, request: RoomActionRequest) -> dict[str, Any]:
        try:
            _room, player_id = app.state.room_service.get_room_for_player(
                room_code,
                request.player_token,
            )
            result = app.state.room_service.apply_action(
                room_code=room_code,
                token=request.player_token,
                action=request.action,
            )
            return _action_result_payload(result, player_id=player_id)
        except RoomNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RoomTokenError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (RuleEngineError, RoomStateError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/rooms/{room_code}/replay")
    def room_replay(
        room_code: str,
        player_token: str = Query(),
    ) -> dict[str, Any]:
        try:
            room, _player_id = app.state.room_service.get_room_for_player(
                room_code,
                player_token,
            )
            if room.match_id is None:
                raise RoomStateError("room does not have an active match")
            return service.repository.replay(room.match_id)
        except RoomNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RoomTokenError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except RoomStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except MatchRuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/api/rooms/cleanup")
    def cleanup_rooms() -> dict[str, Any]:
        summary = app.state.room_service.cleanup_expired()
        return {
            "expired_count": summary.expired_count,
            "deleted_count": summary.deleted_count,
        }

    @app.post("/api/matches/cleanup")
    def cleanup_matches(
        retain: int = Query(default=DEFAULT_MATCH_HISTORY_LIMIT, ge=1, le=1000),
    ) -> dict[str, Any]:
        _reject_public_match_endpoints_disabled(app)
        return {
            "deleted_count": service.repository.prune_old_matches(retain),
            "snapshot_deleted_count": service.repository.prune_snapshots(
                resolved.max_snapshots_per_match
            ),
        }

    @app.get("/api/matches/{match_id}")
    def get_match(
        match_id: str,
        match_token: str | None = Query(default=None),
        x_loveca_match_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        try:
            _require_match_access(
                app,
                match_id,
                match_token=match_token,
                header_token=x_loveca_match_token,
            )
            state = service.repository.get_state(match_id)
            return {
                "state": state.model_dump(),
                "events": [
                    event.model_dump()
                    for event in service.repository.list_events(match_id)
                ],
                "legal_actions": [
                    action.model_dump() for action in generate_legal_actions(state)
                ],
            }
        except MatchNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/matches/{match_id}/legal-actions")
    def legal_actions(
        match_id: str,
        match_token: str | None = Query(default=None),
        x_loveca_match_token: str | None = Header(default=None),
    ) -> list[dict[str, Any]]:
        try:
            _require_match_access(
                app,
                match_id,
                match_token=match_token,
                header_token=x_loveca_match_token,
            )
            state = service.repository.get_state(match_id)
            return [action.model_dump() for action in generate_legal_actions(state)]
        except MatchNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/matches/{match_id}/actions")
    def submit_action(
        match_id: str,
        action: ActionRequest,
        match_token: str | None = Query(default=None),
        x_loveca_match_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        try:
            _require_match_access(
                app,
                match_id,
                match_token=match_token,
                header_token=x_loveca_match_token,
            )
            return service.apply(match_id, action).model_dump()
        except MatchNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuleEngineError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/matches/{match_id}/replay")
    def replay(
        match_id: str,
        match_token: str | None = Query(default=None),
        x_loveca_match_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        try:
            _require_match_access(
                app,
                match_id,
                match_token=match_token,
                header_token=x_loveca_match_token,
            )
            return service.repository.replay(match_id)
        except MatchNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except MatchRuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/api/admin/runtime/storage")
    def admin_runtime_storage(
        x_loveca_admin_key: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _require_admin(resolved, x_loveca_admin_key)
        return _runtime_storage_summary(resolved.runtime_database_path)

    @app.post("/api/admin/runtime/cleanup")
    def admin_runtime_cleanup(
        request: AdminRuntimeCleanupRequest,
        x_loveca_admin_key: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _require_admin(resolved, x_loveca_admin_key)
        deleted_by_retention = service.repository.prune_old_matches(request.retain_matches)
        deleted_by_age = 0
        if request.older_than_hours is not None:
            cutoff = (
                datetime.now(UTC) - timedelta(hours=request.older_than_hours)
            ).isoformat(timespec="seconds")
            deleted_by_age = service.repository.delete_matches_older_than(
                cutoff,
                include_active_matches=request.include_active_matches,
            )
        snapshot_deleted_count = service.repository.prune_snapshots(
            request.max_snapshots_per_match
        )
        _checkpoint_runtime_database(resolved.runtime_database_path)
        vacuumed = False
        if request.vacuum:
            _vacuum_runtime_database(resolved.runtime_database_path)
            vacuumed = True
        return {
            "deleted_count": deleted_by_retention + deleted_by_age,
            "deleted_by_retention": deleted_by_retention,
            "deleted_by_age": deleted_by_age,
            "snapshot_deleted_count": snapshot_deleted_count,
            "vacuumed": vacuumed,
            "storage": _runtime_storage_summary(resolved.runtime_database_path),
        }

    @app.get("/api/admin/deck-shares")
    def admin_deck_shares(
        x_loveca_admin_key: str | None = Header(default=None),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, Any]:
        _require_admin(resolved, x_loveca_admin_key)
        return _shared_deck_admin_summary(resolved.runtime_database_path, limit=limit)

    @app.get("/api/admin/runtime/progress")
    def admin_runtime_progress(
        x_loveca_admin_key: str | None = Header(default=None),
        limit: int = Query(default=500, ge=1, le=5000),
        top: int = Query(default=20, ge=1, le=100),
    ) -> dict[str, Any]:
        _require_admin(resolved, x_loveca_admin_key)
        return _runtime_progress_diagnostics(
            resolved.runtime_database_path,
            limit=limit,
            top_limit=top,
        )

    @app.get("/api/admin/runtime/progress-report")
    def admin_runtime_progress_report(
        x_loveca_admin_key: str | None = Header(default=None),
        limit: int = Query(default=500, ge=1, le=5000),
        top: int = Query(default=20, ge=1, le=100),
    ) -> Response:
        _require_admin(resolved, x_loveca_admin_key)
        diagnostics = _runtime_progress_diagnostics(
            resolved.runtime_database_path,
            limit=limit,
            top_limit=top,
        )
        return Response(
            _runtime_progress_markdown(diagnostics),
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="loveca-runtime-progress.md"'},
        )

    @app.get("/admin", response_class=HTMLResponse)
    def admin_page() -> str:
        return _admin_page_html()

    @app.get("/api/card-images/{card_id}")
    def card_image(card_id: str) -> FileResponse:
        path = resolve_cached_image(resolved.image_cache_dir, card_id)
        if path is None:
            raise HTTPException(status_code=404, detail="card image is not cached")
        return FileResponse(path)

    @app.post("/api/deck-shares")
    def create_deck_share(request: ShareDeckRequest) -> dict[str, Any]:
        try:
            deck = parse_deck(request.deck)
            return _create_deck_share(resolved.runtime_database_path, asdict(deck))
        except DeckFileError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/deck-shares/{share_id}")
    def get_deck_share(share_id: str) -> dict[str, Any]:
        try:
            return _load_deck_share(resolved.runtime_database_path, share_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/decks")
    def list_decks() -> list[dict[str, Any]]:
        try:
            return [
                {
                    "name": item.name,
                    "path": _saved_deck_identifier(item.path),
                    "version": item.version,
                    "main_card_count": item.main_card_count,
                    "energy_card_count": item.energy_card_count,
                }
                for item in list_saved_decks(resolved.deck_library_root)
            ]
        except DeckLibraryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/decks/{deck_id}")
    def get_deck(deck_id: str) -> dict[str, Any]:
        try:
            deck = load_saved_deck(resolved.deck_library_root, deck_id)
            return asdict(deck)
        except DeckLibraryError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/decks")
    def create_deck(request: dict[str, Any]) -> dict[str, Any]:
        try:
            deck = request.get("deck")
            if deck is None:
                deck = request
            path = save_deck_payload(
                deck,
                resolved.deck_library_root,
                name=request.get("name"),
                overwrite=bool(request.get("overwrite", False)),
            )
            return {
                "path": _saved_deck_identifier(path),
                "deck": asdict(load_saved_deck(resolved.deck_library_root, path.name)),
            }
        except (DeckLibraryError, DeckFileError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/decks/analyze")
    def analyze_deck_payload(request: AnalyzeDeckRequest) -> dict[str, Any]:
        try:
            deck = parse_deck(request.deck)
            return analyze_deck(resolved.card_database_path, deck).to_dict()
        except (DeckLibraryError, DeckFileError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.put("/api/decks/{deck_id}")
    def update_deck(deck_id: str, request: dict[str, Any]) -> dict[str, Any]:
        try:
            deck = request.get("deck")
            if deck is None:
                deck = request
            path = update_saved_deck(
                resolved.deck_library_root,
                deck_id,
                deck,
                name=request.get("name"),
                overwrite=bool(request.get("overwrite", True)),
            )
            return {
                "path": _saved_deck_identifier(path),
                "deck": asdict(load_saved_deck(resolved.deck_library_root, path.name)),
            }
        except (DeckLibraryError, DeckFileError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/decks/{deck_id}/rename")
    def rename_deck(deck_id: str, request: dict[str, Any]) -> dict[str, Any]:
        try:
            path = rename_saved_deck(resolved.deck_library_root, deck_id, str(request["name"]))
            return {
                "path": _saved_deck_identifier(path),
                "deck": asdict(load_saved_deck(resolved.deck_library_root, path.name)),
            }
        except (DeckLibraryError, DeckFileError, KeyError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/api/decks/{deck_id}")
    def remove_deck(deck_id: str) -> dict[str, Any]:
        try:
            delete_saved_deck(resolved.deck_library_root, deck_id)
            return {"status": "deleted"}
        except DeckLibraryError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/catalog/cards")
    def catalog_cards(
        q: str | None = None,
        card_type: str | None = None,
        product_code: str | None = None,
        work_key: str | None = None,
        unit_key: str | None = None,
        basic_heart_color: str | None = None,
        member_cost_min: int | None = None,
        member_cost_max: int | None = None,
        member_blade_min: int | None = None,
        member_blade_max: int | None = None,
        member_blade_heart_color: str | None = None,
        required_heart_color: str | None = None,
        required_heart_min: int | None = None,
        required_heart_max: int | None = None,
        live_score_min: int | None = None,
        live_score_max: int | None = None,
        has_live_blade_heart: bool | None = None,
        live_blade_heart_color: str | None = None,
        review_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        try:
            return list_catalog_cards(
                resolved.card_database_path,
                query=q,
                card_type=card_type,
                product_code=product_code,
                work_key=work_key,
                unit_key=unit_key,
                basic_heart_color=basic_heart_color,
                member_cost_min=member_cost_min,
                member_cost_max=member_cost_max,
                member_blade_min=member_blade_min,
                member_blade_max=member_blade_max,
                member_blade_heart_color=member_blade_heart_color,
                required_heart_color=required_heart_color,
                required_heart_min=required_heart_min,
                required_heart_max=required_heart_max,
                live_score_min=live_score_min,
                live_score_max=live_score_max,
                has_live_blade_heart=has_live_blade_heart,
                live_blade_heart_color=live_blade_heart_color,
                review_only=review_only,
                limit=limit,
                offset=offset,
            )
        except CardCatalogError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/catalog/facets")
    def catalog_facets() -> dict[str, Any]:
        try:
            return list_catalog_facets(resolved.card_database_path)
        except CardCatalogError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/catalog/cards/{card_code}")
    def catalog_card(card_code: str) -> dict[str, Any]:
        try:
            return get_catalog_card(resolved.card_database_path, card_code)
        except CardCatalogError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/catalog/review-candidates")
    def catalog_review_candidates(
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        try:
            return list_review_candidates(
                resolved.card_database_path,
                limit=limit,
                offset=offset,
            )
        except CardCatalogError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    if resolved.web_dist_dir.is_dir():
        assets = resolved.web_dist_dir / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{full_path:path}")
        def spa_fallback(full_path: str) -> FileResponse:
            candidate = (resolved.web_dist_dir / full_path).resolve()
            if (
                resolved.web_dist_dir.resolve() in candidate.parents
                and candidate.is_file()
            ):
                return FileResponse(candidate)
            return FileResponse(resolved.web_dist_dir / "index.html")

    return app


def _parse_allowed_origins(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_bool(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _require_admin(settings: ApiSettings, admin_key: str | None) -> None:
    if not settings.admin_key:
        raise HTTPException(status_code=404, detail="admin API is not enabled")
    if admin_key is None or admin_key != settings.admin_key:
        raise HTTPException(status_code=403, detail="invalid admin key")


def _reject_public_match_endpoints_disabled(app: FastAPI) -> None:
    if not app.state.settings.public_match_endpoints:
        raise HTTPException(status_code=404, detail="public match history is disabled")


def _runtime_storage_summary(runtime_database_path: Path) -> dict[str, Any]:
    exists = runtime_database_path.exists()
    file_bytes = runtime_database_path.stat().st_size if exists else 0
    if not exists:
        return {
            "database_path": str(runtime_database_path),
            "file_bytes": 0,
            "page_bytes": 0,
            "free_bytes": 0,
            "tables": [],
            "matches_by_status": [],
            "rooms_by_status": [],
            "top_matches_by_snapshot_bytes": [],
        }
    with sqlite3.connect(runtime_database_path) as connection:
        connection.row_factory = sqlite3.Row
        page_size = int(connection.execute("PRAGMA page_size").fetchone()[0])
        page_count = int(connection.execute("PRAGMA page_count").fetchone()[0])
        freelist_count = int(connection.execute("PRAGMA freelist_count").fetchone()[0])
        tables = [
            _table_storage_row(
                connection,
                table_name,
                columns,
            )
            for table_name, columns in (
                ("matches", ("initial_state_json", "current_state_json")),
                ("match_actions", ("payload_json",)),
                ("match_events", ("event_json",)),
                ("match_snapshots", ("state_json",)),
                ("hosted_rooms", ("host_deck_json", "guest_deck_json")),
                ("shared_decks", ("deck_json",)),
            )
        ]
        matches_by_status = _group_count(connection, "matches", "status")
        rooms_by_status = _group_count(connection, "hosted_rooms", "status")
        top_matches = []
        if _table_exists(connection, "match_snapshots"):
            top_matches = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT
                        m.match_id,
                        m.status,
                        m.revision,
                        m.updated_at,
                        COUNT(s.revision) AS snapshot_count,
                        COALESCE(SUM(LENGTH(s.state_json)), 0) AS snapshot_bytes
                    FROM matches m
                    LEFT JOIN match_snapshots s ON s.match_id = m.match_id
                    GROUP BY m.match_id
                    ORDER BY snapshot_bytes DESC
                    LIMIT 20
                    """
                ).fetchall()
            ]
    return {
        "database_path": str(runtime_database_path),
        "file_bytes": file_bytes,
        "page_bytes": page_size * page_count,
        "free_bytes": page_size * freelist_count,
        "tables": tables,
        "matches_by_status": matches_by_status,
        "rooms_by_status": rooms_by_status,
        "top_matches_by_snapshot_bytes": top_matches,
    }


def _table_storage_row(
    connection: sqlite3.Connection,
    table_name: str,
    columns: tuple[str, ...],
) -> dict[str, Any]:
    if not _table_exists(connection, table_name):
        return {
            "table": table_name,
            "rows": 0,
            "approx_json_bytes": 0,
        }
    row_count = int(connection.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0])
    expressions = " + ".join(f"COALESCE(LENGTH({column}), 0)" for column in columns)
    approx_bytes = int(
        connection.execute(
            f"SELECT COALESCE(SUM({expressions}), 0) FROM {table_name}"
        ).fetchone()[0]
    )
    return {
        "table": table_name,
        "rows": row_count,
        "approx_json_bytes": approx_bytes,
    }


def _group_count(
    connection: sqlite3.Connection,
    table_name: str,
    column_name: str,
) -> list[dict[str, Any]]:
    if not _table_exists(connection, table_name):
        return []
    return [
        {"value": row[0], "count": row[1]}
        for row in connection.execute(
            f"SELECT {column_name}, COUNT(*) FROM {table_name} GROUP BY {column_name}"
        ).fetchall()
    ]


def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
        is not None
    )


def _checkpoint_runtime_database(runtime_database_path: Path) -> None:
    if not runtime_database_path.exists():
        return
    with sqlite3.connect(runtime_database_path) as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")


def _vacuum_runtime_database(runtime_database_path: Path) -> None:
    if not runtime_database_path.exists():
        return
    with sqlite3.connect(runtime_database_path) as connection:
        connection.execute("VACUUM")


def _admin_page_html() -> str:
    return """
<!doctype html>
<html lang="ja">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>LoveCA Admin</title>
    <style>
      body { font-family: system-ui, sans-serif; margin: 2rem; background: #f7f8fb; color: #15171c; }
      main { max-width: 960px; margin: auto; display: grid; gap: 1rem; }
      section { background: white; border: 1px solid #d9dee8; border-radius: 8px; padding: 1rem; }
      label { display: grid; gap: .25rem; margin: .5rem 0; }
      input { font: inherit; padding: .5rem; }
      button { font: inherit; font-weight: 700; padding: .6rem .9rem; margin-right: .5rem; }
      pre { white-space: pre-wrap; background: #111827; color: #e5e7eb; padding: 1rem; border-radius: 6px; overflow: auto; }
      table { width: 100%; border-collapse: collapse; font-size: .92rem; }
      th, td { border-bottom: 1px solid #e5e7eb; padding: .5rem; text-align: left; vertical-align: top; }
      th { color: #4b5563; font-size: .82rem; }
      details { margin-top: .25rem; }
      .danger { color: #b91c1c; }
      .muted { color: #6b7280; font-size: .85rem; }
      .mono { font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: .82rem; }
      .deck-json { max-height: 16rem; }
      .report-actions { display: flex; gap: .5rem; flex-wrap: wrap; }
      .compact-list { margin: .5rem 0 0; padding-left: 1.25rem; }
    </style>
  </head>
  <body>
    <main>
      <h1>LoveCA Runtime Admin</h1>
      <section>
        <p>管理者キーを入力して runtime DB の容量確認と cleanup を実行します。</p>
        <label>Admin key <input id="adminKey" type="password" autocomplete="off" /></label>
        <button id="load">容量を確認</button>
      </section>
      <section>
        <h2>Cleanup</h2>
        <label>保持する match 数 <input id="retain" type="number" min="1" max="1000" value="25" /></label>
        <label>match ごとの snapshot 数 <input id="snapshots" type="number" min="1" max="50" value="3" /></label>
        <label>この時間より古い完了 match を削除（hours, 空欄なら無効） <input id="older" type="number" min="1" /></label>
        <label><input id="active" type="checkbox" /> active match も時間削除対象に含める（active room は保護）</label>
        <label><input id="vacuum" type="checkbox" /> VACUUM を実行する（重い処理）</label>
        <button id="cleanup" class="danger">Cleanup 実行</button>
      </section>
      <section>
        <h2>Shared decks</h2>
        <p class="muted">Shows uploaded decks and records from online rooms with the same deck contents.</p>
        <button id="loadDecks">Load shared decks</button>
        <div id="deckOutput" class="muted">Not loaded.</div>
      </section>
      <section>
        <h2>Progress diagnostics</h2>
        <p class="muted">Shows match phase distribution and effect cards that frequently remain pending or emit error/skip events.</p>
        <div class="report-actions">
          <button id="loadProgress">Load progress summary</button>
          <button id="downloadProgress">Download markdown report</button>
        </div>
        <div id="progressOutput" class="muted">Not loaded.</div>
      </section>
      <section>
        <h2>Result</h2>
        <pre id="output">Not loaded.</pre>
      </section>
    </main>
    <script>
      const output = document.getElementById("output");
      const deckOutput = document.getElementById("deckOutput");
      const progressOutput = document.getElementById("progressOutput");
      const key = () => document.getElementById("adminKey").value;
      const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;",
      }[char]));
      const rate = (value) => value === null || value === undefined ? "-" : `${Math.round(value * 1000) / 10}%`;
      function renderDeckShares(payload) {
        if (!payload.items || payload.items.length === 0) {
          deckOutput.textContent = "No shared decks.";
          return;
        }
        deckOutput.innerHTML = `
          <p class="muted">matching: ${escapeHtml(payload.matching_method)} / total: ${payload.total}</p>
          <table>
            <thead>
              <tr>
                <th>Deck</th><th>Share ID</th><th>Cards</th><th>Uses</th><th>Record</th><th>Last used</th>
              </tr>
            </thead>
            <tbody>
              ${payload.items.map((item) => `
                <tr>
                  <td>
                    <strong>${escapeHtml(item.deck_name)}</strong>
                    <div class="muted">created ${escapeHtml(item.created_at)}</div>
                    <details>
                      <summary>deck JSON</summary>
                      <pre class="deck-json">${escapeHtml(JSON.stringify(item.deck, null, 2))}</pre>
                    </details>
                  </td>
                  <td class="mono">${escapeHtml(item.share_id)}</td>
                  <td>Main ${item.main_card_count}<br />Energy ${item.energy_card_count}</td>
                  <td>${item.uses}<br /><span class="muted">unfinished ${item.unfinished_uses}</span></td>
                  <td>${item.wins}-${item.losses}-${item.draws}<br /><strong>${rate(item.win_rate)}</strong></td>
                  <td>${escapeHtml(item.last_played_at || "-")}</td>
                </tr>
              `).join("")}
            </tbody>
          </table>`;
      }
      function renderProgress(payload) {
        const phaseItems = (payload.phase_distribution || []).slice(0, 8);
        const stuckItems = (payload.top_stuck_effects || []).slice(0, 8);
        progressOutput.innerHTML = `
          <p class="muted">matches: ${payload.match_count} / generated: ${escapeHtml(payload.generated_at)}</p>
          <h3>Top phases</h3>
          <ul class="compact-list">${phaseItems.map((item) => `<li>${escapeHtml(item.value)}: ${item.count}</li>`).join("") || "<li>-</li>"}</ul>
          <h3>Top effects</h3>
          <table>
            <thead><tr><th>Effect</th><th>Card</th><th>Count</th><th>Reasons</th></tr></thead>
            <tbody>${stuckItems.map((item) => `
              <tr>
                <td class="mono">${escapeHtml(item.effect_id)}</td>
                <td class="mono">${escapeHtml(item.card_code || "-")}</td>
                <td>${item.count}</td>
                <td>${escapeHtml((item.reasons || []).map((reason) => `${reason.value}:${reason.count}`).join(", ") || "-")}</td>
              </tr>
            `).join("") || '<tr><td colspan="4">No stuck effects.</td></tr>'}</tbody>
          </table>`;
      }
      async function downloadProgressReport() {
        const response = await fetch("/api/admin/runtime/progress-report", {
          headers: { "X-LoveCA-Admin-Key": key() },
        });
        const text = await response.text();
        if (!response.ok) throw new Error(text || response.statusText);
        const blob = new Blob([text], { type: "text/markdown;charset=utf-8" });
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = "loveca-runtime-progress.md";
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
      }
      async function adminFetch(url, options = {}) {
        const response = await fetch(url, {
          ...options,
          headers: {
            "Content-Type": "application/json",
            "X-LoveCA-Admin-Key": key(),
            ...(options.headers || {}),
          },
        });
        const text = await response.text();
        if (!response.ok) throw new Error(text || response.statusText);
        return text ? JSON.parse(text) : {};
      }
      document.getElementById("load").onclick = async () => {
        try {
          output.textContent = JSON.stringify(await adminFetch("/api/admin/runtime/storage"), null, 2);
        } catch (error) {
          output.textContent = String(error);
        }
      };
      document.getElementById("loadDecks").onclick = async () => {
        try {
          renderDeckShares(await adminFetch("/api/admin/deck-shares"));
        } catch (error) {
          deckOutput.textContent = String(error);
        }
      };
      document.getElementById("loadProgress").onclick = async () => {
        try {
          renderProgress(await adminFetch("/api/admin/runtime/progress"));
        } catch (error) {
          progressOutput.textContent = String(error);
        }
      };
      document.getElementById("downloadProgress").onclick = async () => {
        try {
          await downloadProgressReport();
        } catch (error) {
          progressOutput.textContent = String(error);
        }
      };
      document.getElementById("cleanup").onclick = async () => {
        const older = document.getElementById("older").value;
        const payload = {
          retain_matches: Number(document.getElementById("retain").value || 25),
          max_snapshots_per_match: Number(document.getElementById("snapshots").value || 3),
          older_than_hours: older ? Number(older) : null,
          include_active_matches: document.getElementById("active").checked,
          vacuum: document.getElementById("vacuum").checked,
        };
        try {
          output.textContent = JSON.stringify(await adminFetch("/api/admin/runtime/cleanup", {
            method: "POST",
            body: JSON.stringify(payload),
          }), null, 2);
        } catch (error) {
          output.textContent = String(error);
        }
      };
    </script>
  </body>
</html>
"""


def _resolve_deck(player: PlayerSetup, allowed_root: Path):
    if player.deck is not None:
        return parse_deck(player.deck)
    if player.deck_path is None:
        raise DeckFileError("each player requires deck or deck_path")
    path = Path(player.deck_path)
    if not path.is_absolute():
        path = allowed_root / path
    resolved = path.resolve()
    root = allowed_root.resolve()
    if resolved != root and root not in resolved.parents:
        raise DeckFileError("deck_path must stay within the project workspace")
    from loveca.decks.analyzer import load_deck

    return load_deck(resolved)


def _ensure_deck_share_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS shared_decks (
            share_id TEXT PRIMARY KEY,
            deck_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )


def _create_deck_share(runtime_database_path: Path, deck: dict[str, Any]) -> dict[str, Any]:
    runtime_database_path.parent.mkdir(parents=True, exist_ok=True)
    share_id = str(uuid.uuid4())
    created_at = datetime.now(UTC).isoformat()
    deck_json = json.dumps(deck, ensure_ascii=False, sort_keys=True)
    with sqlite3.connect(runtime_database_path) as connection:
        _ensure_deck_share_table(connection)
        connection.execute(
            """
            INSERT INTO shared_decks (share_id, deck_json, created_at)
            VALUES (?, ?, ?)
            """,
            (share_id, deck_json, created_at),
        )
    return {
        "share_id": share_id,
        "deck": deck,
        "created_at": created_at,
    }


def _load_deck_share(runtime_database_path: Path, share_id: str) -> dict[str, Any]:
    try:
        normalized_share_id = str(uuid.UUID(share_id))
    except ValueError as exc:
        raise ValueError("share_id must be a UUID") from exc
    with sqlite3.connect(runtime_database_path) as connection:
        _ensure_deck_share_table(connection)
        row = connection.execute(
            """
            SELECT share_id, deck_json, created_at
            FROM shared_decks
            WHERE share_id = ?
            """,
            (normalized_share_id,),
        ).fetchone()
    if row is None:
        raise KeyError(f"shared deck not found: {normalized_share_id}")
    return {
        "share_id": row[0],
        "deck": json.loads(row[1]),
        "created_at": row[2],
    }


def _runtime_progress_diagnostics(
    runtime_database_path: Path,
    *,
    limit: int,
    top_limit: int,
) -> dict[str, Any]:
    generated_at = datetime.now(UTC).isoformat(timespec="seconds")
    diagnostics: dict[str, Any] = {
        "generated_at": generated_at,
        "source_limit": limit,
        "match_count": 0,
        "status_distribution": [],
        "phase_distribution": [],
        "turn_distribution": [],
        "pending_choice_distribution": [],
        "pending_effect_count_distribution": [],
        "stuck_matches": [],
        "top_stuck_effects": [],
        "effect_event_distribution": [],
        "event_sample_limit": 0,
    }
    if not runtime_database_path.exists():
        return diagnostics
    status_counts: dict[str, int] = {}
    phase_counts: dict[str, int] = {}
    turn_counts: dict[str, int] = {}
    pending_choice_counts: dict[str, int] = {}
    pending_effect_count_counts: dict[str, int] = {}
    effect_stats: dict[str, dict[str, Any]] = {}
    with sqlite3.connect(runtime_database_path) as connection:
        connection.row_factory = sqlite3.Row
        if not _table_exists(connection, "matches"):
            return diagnostics
        rows = connection.execute(
            """
            SELECT match_id, status, revision, current_state_json, created_at, updated_at
            FROM matches
            ORDER BY updated_at DESC, created_at DESC, match_id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        diagnostics["match_count"] = len(rows)
        for row in rows:
            status = _string_or_unknown(row["status"])
            _counter_add(status_counts, status)
            state = _json_object(row["current_state_json"])
            phase = _string_or_unknown(state.get("phase")) if state else "unparseable_state"
            turn_number = state.get("turn_number") if state else None
            _counter_add(phase_counts, phase)
            _counter_add(turn_counts, _turn_bucket(turn_number))
            pending_choice = state.get("pending_choice") if state else None
            pending_choice_type = None
            if isinstance(pending_choice, dict):
                pending_choice_type = _string_or_unknown(pending_choice.get("choice_type"))
                _counter_add(pending_choice_counts, pending_choice_type)
            pending_effects = state.get("pending_effects") if state else None
            if not isinstance(pending_effects, list):
                pending_effects = []
            _counter_add(pending_effect_count_counts, str(len(pending_effects)))
            pending_effect_ids: list[str] = []
            for invocation in pending_effects:
                if not isinstance(invocation, dict):
                    continue
                effect = _effect_summary_from_state(state, invocation)
                pending_effect_ids.append(effect["effect_id"])
                reason = (
                    "pending_manual_resolution"
                    if effect.get("simulation_support") == "manual_resolution"
                    else "pending_effect"
                )
                _record_effect_stat(
                    effect_stats,
                    effect=effect,
                    reason=reason,
                    match_id=str(row["match_id"]),
                )
            if (pending_choice_type or pending_effects) and len(diagnostics["stuck_matches"]) < top_limit:
                diagnostics["stuck_matches"].append(
                    {
                        "match_id": row["match_id"],
                        "status": status,
                        "phase": phase,
                        "turn_number": turn_number,
                        "revision": row["revision"],
                        "updated_at": row["updated_at"],
                        "pending_choice_type": pending_choice_type,
                        "pending_effect_count": len(pending_effects),
                        "pending_effect_ids": pending_effect_ids,
                    }
                )
        if _table_exists(connection, "match_events"):
            event_limit = min(max(limit * 50, top_limit * 10), 20000)
            diagnostics["event_sample_limit"] = event_limit
            _accumulate_effect_event_stats(connection, effect_stats, event_limit=event_limit)
    diagnostics["status_distribution"] = _counter_items(status_counts)
    diagnostics["phase_distribution"] = _counter_items(phase_counts)
    diagnostics["turn_distribution"] = _counter_items(turn_counts)
    diagnostics["pending_choice_distribution"] = _counter_items(pending_choice_counts)
    diagnostics["pending_effect_count_distribution"] = _counter_items(
        pending_effect_count_counts,
        sort_numeric=True,
    )
    diagnostics["top_stuck_effects"] = _effect_stat_items(effect_stats, top_limit)
    diagnostics["effect_event_distribution"] = _effect_event_distribution(effect_stats)
    return diagnostics


def _accumulate_effect_event_stats(
    connection: sqlite3.Connection,
    effect_stats: dict[str, dict[str, Any]],
    *,
    event_limit: int,
) -> None:
    tracked_event_types = (
        "effect_not_activatable",
        "effect_skipped_due_to_error",
        "effect_multi_player_choice_skipped",
        "effect_manual_resolution_completed",
        "manual_card_inspection_started",
        "manual_adjustment_applied",
    )
    placeholders = ", ".join("?" for _ in tracked_event_types)
    rows = connection.execute(
        f"""
        SELECT match_id, event_type, event_json
        FROM match_events
        WHERE event_type IN ({placeholders})
        ORDER BY rowid DESC
        LIMIT ?
        """,
        (*tracked_event_types, event_limit),
    ).fetchall()
    for row in rows:
        event = _json_object(row["event_json"])
        data = event.get("data") if event else None
        if not isinstance(data, dict):
            data = {}
        effect_id = data.get("effect_id")
        if not isinstance(effect_id, str) or not effect_id:
            continue
        effect = {
            "effect_id": effect_id,
            "card_code": _card_code_from_effect_id(effect_id),
            "card_id": None,
            "card_name_ja": None,
            "label_ja": None,
            "simulation_support": None,
            "trigger": None,
        }
        _record_effect_stat(
            effect_stats,
            effect=effect,
            reason=str(row["event_type"]),
            match_id=str(row["match_id"]),
        )


def _effect_summary_from_state(
    state: dict[str, Any],
    invocation: dict[str, Any],
) -> dict[str, Any]:
    effect_id = _string_or_unknown(invocation.get("effect_id"))
    source_instance_id = invocation.get("source_card_instance_id")
    effect_definitions = state.get("effect_definitions")
    effect = effect_definitions.get(effect_id) if isinstance(effect_definitions, dict) else None
    if not isinstance(effect, dict):
        effect = {}
    cards = state.get("cards")
    source_card = None
    if isinstance(cards, dict) and isinstance(source_instance_id, str):
        source_instance = cards.get(source_instance_id)
        if isinstance(source_instance, dict):
            source_card = source_instance.get("card")
    if not isinstance(source_card, dict):
        source_card = {}
    return {
        "effect_id": effect_id,
        "card_code": _first_string(effect.get("card_code"), source_card.get("card_code"), _card_code_from_effect_id(effect_id)),
        "card_id": _first_string(source_card.get("card_id"), source_instance_id),
        "card_name_ja": _first_string(source_card.get("name_ja")),
        "label_ja": _first_string(effect.get("label_ja")),
        "simulation_support": _first_string(effect.get("simulation_support")),
        "trigger": _first_string(effect.get("trigger"), invocation.get("trigger_event")),
    }


def _record_effect_stat(
    stats: dict[str, dict[str, Any]],
    *,
    effect: dict[str, Any],
    reason: str,
    match_id: str,
) -> None:
    effect_id = _string_or_unknown(effect.get("effect_id"))
    item = stats.setdefault(
        effect_id,
        {
            "effect_id": effect_id,
            "card_code": effect.get("card_code"),
            "card_id": effect.get("card_id"),
            "card_name_ja": effect.get("card_name_ja"),
            "label_ja": effect.get("label_ja"),
            "simulation_support": effect.get("simulation_support"),
            "trigger": effect.get("trigger"),
            "count": 0,
            "reasons": {},
            "example_match_ids": [],
        },
    )
    for field in ("card_code", "card_id", "card_name_ja", "label_ja", "simulation_support", "trigger"):
        if item.get(field) in {None, "unknown"} and effect.get(field):
            item[field] = effect[field]
    item["count"] += 1
    _counter_add(item["reasons"], reason)
    if match_id not in item["example_match_ids"] and len(item["example_match_ids"]) < 5:
        item["example_match_ids"].append(match_id)


def _effect_stat_items(stats: dict[str, dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    items = sorted(
        stats.values(),
        key=lambda item: (-int(item["count"]), str(item["effect_id"])),
    )[:limit]
    return [
        {
            **item,
            "reasons": _counter_items(item["reasons"]),
        }
        for item in items
    ]


def _effect_event_distribution(stats: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for item in stats.values():
        reasons = item.get("reasons")
        if not isinstance(reasons, dict):
            continue
        for reason, count in reasons.items():
            if str(reason).startswith("pending_"):
                continue
            _counter_add(counts, str(reason), int(count))
    return _counter_items(counts)


def _runtime_progress_markdown(diagnostics: dict[str, Any]) -> str:
    lines = [
        "# LoveCA Runtime Progress Report",
        "",
        f"Generated at: `{_md(diagnostics.get('generated_at'))}`",
        f"Matches sampled: `{diagnostics.get('match_count', 0)}` / source limit `{diagnostics.get('source_limit')}`",
        f"Event sample limit: `{diagnostics.get('event_sample_limit', 0)}`",
        "",
        "## Match Progress",
        "",
    ]
    lines.extend(_markdown_distribution("Status", diagnostics.get("status_distribution", [])))
    lines.extend(_markdown_distribution("Phase", diagnostics.get("phase_distribution", [])))
    lines.extend(_markdown_distribution("Turn", diagnostics.get("turn_distribution", [])))
    lines.extend(_markdown_distribution("Pending choice", diagnostics.get("pending_choice_distribution", [])))
    lines.extend(_markdown_distribution("Pending effect count", diagnostics.get("pending_effect_count_distribution", [])))
    lines.extend([
        "## Top Stuck Effects",
        "",
        "| Count | Effect | Card | Support | Trigger | Reasons | Examples |",
        "| ---: | --- | --- | --- | --- | --- | --- |",
    ])
    for item in diagnostics.get("top_stuck_effects", []):
        reasons = ", ".join(
            f"{_md(reason['value'])}:{reason['count']}" for reason in item.get("reasons", [])
        )
        examples = ", ".join(_md(match_id) for match_id in item.get("example_match_ids", []))
        lines.append(
            "| {count} | `{effect}` | `{card}` {name} | {support} | {trigger} | {reasons} | {examples} |".format(
                count=item.get("count", 0),
                effect=_md(item.get("effect_id")),
                card=_md(item.get("card_code")),
                name=_md(item.get("card_name_ja") or ""),
                support=_md(item.get("simulation_support")),
                trigger=_md(item.get("trigger")),
                reasons=reasons or "-",
                examples=examples or "-",
            )
        )
    lines.extend([
        "",
        "## Currently Blocked Matches",
        "",
        "| Match | Status | Phase | Turn | Revision | Pending choice | Pending effects | Updated |",
        "| --- | --- | --- | ---: | ---: | --- | --- | --- |",
    ])
    for item in diagnostics.get("stuck_matches", []):
        lines.append(
            "| `{match}` | {status} | {phase} | {turn} | {revision} | {choice} | {effects} | {updated} |".format(
                match=_md(item.get("match_id")),
                status=_md(item.get("status")),
                phase=_md(item.get("phase")),
                turn=_md(item.get("turn_number")),
                revision=_md(item.get("revision")),
                choice=_md(item.get("pending_choice_type") or "-"),
                effects=_md(", ".join(item.get("pending_effect_ids", [])) or "-"),
                updated=_md(item.get("updated_at")),
            )
        )
    lines.append("")
    return "\n".join(lines)


def _markdown_distribution(title: str, items: list[dict[str, Any]]) -> list[str]:
    lines = [f"### {title}", "", "| Value | Count |", "| --- | ---: |"]
    if not items:
        lines.append("| - | 0 |")
    else:
        for item in items:
            lines.append(f"| {_md(item.get('value'))} | {item.get('count', 0)} |")
    lines.append("")
    return lines


def _counter_add(counter: dict[str, int], key: str, amount: int = 1) -> None:
    counter[key] = counter.get(key, 0) + amount


def _counter_items(
    counter: dict[str, int],
    *,
    sort_numeric: bool = False,
) -> list[dict[str, Any]]:
    def sort_key(item: tuple[str, int]) -> tuple[int, int | str]:
        value, count = item
        if sort_numeric:
            try:
                return (-count, int(value))
            except ValueError:
                return (-count, value)
        return (-count, value)

    return [
        {"value": value, "count": count}
        for value, count in sorted(counter.items(), key=sort_key)
    ]


def _json_object(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, str) or not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _turn_bucket(value: Any) -> str:
    try:
        turn = int(value)
    except (TypeError, ValueError):
        return "unknown"
    if turn <= 1:
        return "1"
    if turn <= 3:
        return "2-3"
    if turn <= 6:
        return "4-6"
    return "7+"


def _card_code_from_effect_id(effect_id: Any) -> str:
    if not isinstance(effect_id, str) or not effect_id:
        return "unknown"
    return effect_id.rsplit(":", 1)[0]


def _first_string(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value:
            return value
    return None


def _string_or_unknown(value: Any) -> str:
    return value if isinstance(value, str) and value else "unknown"


def _md(value: Any) -> str:
    return str(value if value is not None else "-").replace("|", "\\|").replace("\n", " ")


def _shared_deck_admin_summary(
    runtime_database_path: Path,
    *,
    limit: int,
) -> dict[str, Any]:
    if not runtime_database_path.exists():
        return {
            "items": [],
            "total": 0,
            "matching_method": "card_code_quantities",
        }
    with sqlite3.connect(runtime_database_path) as connection:
        connection.row_factory = sqlite3.Row
        _ensure_deck_share_table(connection)
        rows = connection.execute(
            """
            SELECT share_id, deck_json, created_at
            FROM shared_decks
            ORDER BY created_at DESC, share_id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        total = int(connection.execute("SELECT COUNT(*) FROM shared_decks").fetchone()[0])
        items: list[dict[str, Any]] = []
        items_by_key: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            deck = json.loads(row["deck_json"])
            main_count, energy_count = _deck_card_counts(deck)
            item: dict[str, Any] = {
                "share_id": row["share_id"],
                "created_at": row["created_at"],
                "deck_name": _deck_display_name(deck),
                "main_card_count": main_count,
                "energy_card_count": energy_count,
                "deck": deck,
                "uses": 0,
                "completed_uses": 0,
                "wins": 0,
                "losses": 0,
                "draws": 0,
                "unfinished_uses": 0,
                "unresolved_results": 0,
                "win_rate": None,
                "last_played_at": None,
            }
            items.append(item)
            items_by_key.setdefault(_deck_identity_key(deck), []).append(item)
        if items and _table_exists(connection, "hosted_rooms") and _table_exists(connection, "matches"):
            _accumulate_shared_deck_room_stats(connection, items_by_key)
        for item in items:
            completed = int(item["completed_uses"])
            item["win_rate"] = (item["wins"] / completed) if completed else None
    return {
        "items": items,
        "total": total,
        "matching_method": "card_code_quantities",
    }


def _accumulate_shared_deck_room_stats(
    connection: sqlite3.Connection,
    items_by_key: dict[str, list[dict[str, Any]]],
) -> None:
    rows = connection.execute(
        """
        SELECT
            r.room_code,
            r.match_id,
            r.host_deck_json,
            r.guest_deck_json,
            r.updated_at AS room_updated_at,
            m.status AS match_status,
            m.current_state_json,
            m.updated_at AS match_updated_at
        FROM hosted_rooms r
        LEFT JOIN matches m ON m.match_id = r.match_id
        WHERE r.match_id IS NOT NULL
        """
    ).fetchall()
    for row in rows:
        for player_id, deck_column in (
            ("player_1", "host_deck_json"),
            ("player_2", "guest_deck_json"),
        ):
            deck_json = row[deck_column]
            if not deck_json:
                continue
            try:
                key = _deck_identity_key(json.loads(deck_json))
            except (TypeError, ValueError):
                continue
            for item in items_by_key.get(key, []):
                _apply_shared_deck_match_result(
                    item,
                    player_id=player_id,
                    match_status=row["match_status"],
                    state_json=row["current_state_json"],
                    last_played_at=row["match_updated_at"] or row["room_updated_at"],
                )


def _apply_shared_deck_match_result(
    item: dict[str, Any],
    *,
    player_id: str,
    match_status: str | None,
    state_json: str | None,
    last_played_at: str | None,
) -> None:
    item["uses"] += 1
    if last_played_at and (
        item["last_played_at"] is None or last_played_at > item["last_played_at"]
    ):
        item["last_played_at"] = last_played_at
    if match_status != "complete" or not state_json:
        item["unfinished_uses"] += 1
        return
    try:
        state = json.loads(state_json)
    except ValueError:
        item["unresolved_results"] += 1
        return
    result = state.get("game_result") if isinstance(state, dict) else None
    if not isinstance(result, dict):
        item["unresolved_results"] += 1
        return
    outcome = result.get("outcome")
    winner_player_ids = {
        winner for winner in result.get("winner_player_ids", []) if isinstance(winner, str)
    }
    if outcome == "draw":
        item["completed_uses"] += 1
        item["draws"] += 1
    elif outcome == "win" and player_id in winner_player_ids:
        item["completed_uses"] += 1
        item["wins"] += 1
    elif outcome == "win":
        item["completed_uses"] += 1
        item["losses"] += 1
    else:
        item["unresolved_results"] += 1


def _deck_identity_key(deck: dict[str, Any]) -> str:
    return json.dumps(
        {
            "main_deck": _deck_identity_entries(deck.get("main_deck")),
            "energy_deck": _deck_identity_entries(deck.get("energy_deck")),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _deck_identity_entries(entries: Any) -> list[dict[str, Any]]:
    normalized = []
    if not isinstance(entries, list):
        return normalized
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        card_code = entry.get("card_code")
        if not isinstance(card_code, str):
            continue
        try:
            quantity = int(entry.get("quantity", 0))
        except (TypeError, ValueError):
            quantity = 0
        normalized.append({"card_code": card_code, "quantity": quantity})
    return sorted(normalized, key=lambda item: (item["card_code"], item["quantity"]))


def _deck_card_counts(deck: dict[str, Any]) -> tuple[int, int]:
    return (
        _deck_entry_count(deck.get("main_deck")),
        _deck_entry_count(deck.get("energy_deck")),
    )


def _deck_entry_count(entries: Any) -> int:
    if not isinstance(entries, list):
        return 0
    total = 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        try:
            total += int(entry.get("quantity", 0))
        except (TypeError, ValueError):
            continue
    return total


def _deck_display_name(deck: dict[str, Any]) -> str:
    name = deck.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return "Untitled deck"


def _match_payload(
    service: MatchService,
    match_id: str,
    *,
    player_id: str | None = None,
) -> dict[str, Any]:
    state = service.repository.get_state(match_id)
    legal_actions = generate_legal_actions(state)
    events = service.repository.list_events(match_id)
    return _match_state_payload(
        state,
        events=events,
        legal_actions=legal_actions,
        player_id=player_id,
    )


def _action_result_payload(result: ActionResult, *, player_id: str | None) -> dict[str, Any]:
    return _match_state_payload(
        result.state,
        events=result.events,
        legal_actions=result.legal_actions,
        player_id=player_id,
    )


def _match_state_payload(
    state: MatchState,
    *,
    events: list[GameEvent],
    legal_actions: list[LegalAction],
    player_id: str | None,
) -> dict[str, Any]:
    state_payload = state.model_dump()
    visible_actions = legal_actions
    if player_id is not None:
        _redact_opponent_hands(state_payload, player_id)
        visible_actions = [
            action
            for action in legal_actions
            if action.player_id is None or action.player_id == player_id
        ]
    return {
        "state": state_payload,
        "events": [event.model_dump() for event in events],
        "legal_actions": [action.model_dump() for action in visible_actions],
    }


def _redact_opponent_hands(state_payload: dict[str, Any], player_id: str) -> None:
    players = state_payload.get("players")
    cards = state_payload.get("cards")
    if not isinstance(players, dict) or not isinstance(cards, dict):
        return
    for opponent_id, player in players.items():
        if opponent_id == player_id or not isinstance(player, dict):
            continue
        hand = player.get("hand")
        if not isinstance(hand, list):
            continue
        for instance_id in hand:
            if isinstance(instance_id, str):
                cards.pop(instance_id, None)


def _reject_public_room_match(app: FastAPI, match_id: str) -> None:
    if app.state.room_service.repository.match_is_active_room_match(match_id):
        raise HTTPException(status_code=404, detail=f"match not found: {match_id}")


def _require_match_access(
    app: FastAPI,
    match_id: str,
    *,
    match_token: str | None,
    header_token: str | None,
) -> None:
    _reject_public_room_match(app, match_id)
    if app.state.settings.public_match_endpoints:
        return
    token = header_token or match_token
    if not app.state.match_service.repository.validate_match_token(match_id, token):
        raise HTTPException(status_code=403, detail="invalid match token")


def _room_payload(
    service: MatchService,
    room: RoomRecord,
    *,
    player_id: str | None,
    player_token: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "room_code": room.room_code,
        "status": room.status,
        "player_id": player_id,
        "match_id": room.match_id,
        "host_name": room.host_name,
        "guest_name": room.guest_name,
        "created_at": room.created_at,
        "updated_at": room.updated_at,
        "expires_at": room.expires_at,
        "host_last_seen_at": room.host_last_seen_at,
        "guest_last_seen_at": room.guest_last_seen_at,
        "closed_at": room.closed_at,
        "close_reason": room.close_reason,
        "match": None,
    }
    if player_token is not None:
        payload["player_token"] = player_token
    if room.match_id is not None and player_id is not None:
        payload["match"] = _match_payload(service, room.match_id, player_id=player_id)
    return payload
