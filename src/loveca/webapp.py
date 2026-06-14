"""FastAPI application for the local visual rules debugger."""

from __future__ import annotations

import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from loveca.cards.images import resolve_cached_image
from loveca.cards.catalog import (
    CardCatalogError,
    get_catalog_card,
    list_catalog_cards,
    list_catalog_facets,
    list_review_candidates,
)
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


class AnalyzeDeckRequest(BaseModel):
    deck: dict[str, Any]


class ApiSettings(BaseModel):
    card_database_path: Path
    runtime_database_path: Path
    image_cache_dir: Path
    web_dist_dir: Path
    deck_library_root: Path = Field(default=PROJECT_ROOT / "data/decks")
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
        version="0.4.0a2",
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

    @app.get("/api/decks")
    def list_decks() -> list[dict[str, Any]]:
        try:
            return [
                {
                    "name": item.name,
                    "path": str(item.path),
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
                "path": str(path),
                "deck": asdict(load_saved_deck(resolved.deck_library_root, str(path))),
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
                "path": str(path),
                "deck": asdict(load_saved_deck(resolved.deck_library_root, str(path))),
            }
        except (DeckLibraryError, DeckFileError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/decks/{deck_id}/rename")
    def rename_deck(deck_id: str, request: dict[str, Any]) -> dict[str, Any]:
        try:
            path = rename_saved_deck(resolved.deck_library_root, deck_id, str(request["name"]))
            return {
                "path": str(path),
                "deck": asdict(load_saved_deck(resolved.deck_library_root, str(path))),
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
