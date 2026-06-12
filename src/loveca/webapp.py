"""FastAPI application for the local visual rules debugger."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from loveca.cards.images import resolve_cached_image
from loveca.decks.analyzer import DeckFileError, parse_deck
from loveca.simulation.engine import RuleEngineError, generate_legal_actions
from loveca.simulation.models import ActionRequest
from loveca.simulation.runtime import MatchNotFoundError, MatchRuntimeError
from loveca.simulation.service import MatchService, MatchSetupError
from loveca.simulation.effects import DEFAULT_EFFECT_REGISTRY


PROJECT_ROOT = Path(__file__).parents[2]


class PlayerSetup(BaseModel):
    name: str
    deck: dict[str, Any] | None = None
    deck_path: str | None = None


class CreateMatchRequest(BaseModel):
    player_1: PlayerSetup
    player_2: PlayerSetup
    seed: int | None = None


class ApiSettings(BaseModel):
    card_database_path: Path
    runtime_database_path: Path
    image_cache_dir: Path
    web_dist_dir: Path
    allowed_deck_root: Path = Field(default=PROJECT_ROOT)
    effect_registry_path: Path = Field(default=DEFAULT_EFFECT_REGISTRY)


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
    )


def create_app(settings: ApiSettings | None = None) -> FastAPI:
    resolved = settings or default_settings()
    service = MatchService(
        resolved.card_database_path,
        resolved.runtime_database_path,
        resolved.effect_registry_path,
    )
    app = FastAPI(
        title="LoveCA Visual Rules Debugger",
        version="0.3.0a1",
    )
    app.state.settings = resolved
    app.state.match_service = service

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "rule_version": "1.06",
            "card_database": str(resolved.card_database_path),
        }

    @app.get("/api/matches")
    def list_matches() -> list[dict[str, Any]]:
        return service.repository.list_matches()

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
            return result.model_dump()
        except (DeckFileError, MatchSetupError, OSError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/matches/{match_id}")
    def get_match(match_id: str) -> dict[str, Any]:
        try:
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
    def legal_actions(match_id: str) -> list[dict[str, Any]]:
        try:
            state = service.repository.get_state(match_id)
            return [action.model_dump() for action in generate_legal_actions(state)]
        except MatchNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/matches/{match_id}/actions")
    def submit_action(match_id: str, action: ActionRequest) -> dict[str, Any]:
        try:
            return service.apply(match_id, action).model_dump()
        except MatchNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuleEngineError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/matches/{match_id}/replay")
    def replay(match_id: str) -> dict[str, Any]:
        try:
            return service.repository.replay(match_id)
        except MatchNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except MatchRuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/api/card-images/{card_id}")
    def card_image(card_id: str) -> FileResponse:
        path = resolve_cached_image(resolved.image_cache_dir, card_id)
        if path is None:
            raise HTTPException(status_code=404, detail="card image is not cached")
        return FileResponse(path)

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
