"""Application service coordinating deck validation, match setup, and persistence."""

from __future__ import annotations

import random
import secrets
import uuid
from pathlib import Path

from loveca.decks.analyzer import DeckList, analyze_deck, load_deck
from loveca.simulation.ai import SimpleAIBlocker, SimpleAIController, SimpleAIPolicy
from loveca.simulation.catalog import MatchPlayerInput, build_match_cards
from loveca.simulation.effects import DEFAULT_EFFECT_REGISTRY
from loveca.simulation.models import (
    ActionRequest,
    ActionResult,
    ControllerType,
    GameEvent,
    MatchState,
)
from loveca.simulation.runtime import (
    DEFAULT_ACTIVE_MATCH_TTL_HOURS,
    MAX_RETAINED_MATCHES,
    MAX_SNAPSHOTS_PER_MATCH,
    MatchRepository,
)


class MatchSetupError(RuntimeError):
    """Raised when a match cannot be created from the supplied decks."""


class MatchService:
    def __init__(
        self,
        card_database_path: Path,
        runtime_database_path: Path,
        effect_registry_path: Path = DEFAULT_EFFECT_REGISTRY,
        *,
        max_retained_matches: int = MAX_RETAINED_MATCHES,
        max_snapshots_per_match: int = MAX_SNAPSHOTS_PER_MATCH,
        active_match_ttl_hours: int = DEFAULT_ACTIVE_MATCH_TTL_HOURS,
    ) -> None:
        self.card_database_path = card_database_path
        self.effect_registry_path = effect_registry_path
        self.repository = MatchRepository(
            runtime_database_path,
            max_retained_matches=max_retained_matches,
            max_snapshots_per_match=max_snapshots_per_match,
            active_match_ttl_hours=active_match_ttl_hours,
        )

    def create_match(
        self,
        *,
        first_name: str,
        first_deck: DeckList,
        second_name: str,
        second_deck: DeckList,
        seed: int | None = None,
        match_id: str | None = None,
        first_player_id: str | None = None,
        controllers: dict[str, ControllerType] | None = None,
    ) -> ActionResult:
        for label, deck in (("player_1", first_deck), ("player_2", second_deck)):
            analysis = analyze_deck(self.card_database_path, deck)
            if not analysis.is_legal:
                messages = "; ".join(issue.message for issue in analysis.issues)
                raise MatchSetupError(f"{label} deck is illegal: {messages}")
        resolved_id = match_id or str(uuid.uuid4())
        resolved_seed = seed if seed is not None else secrets.randbits(63)
        players = (
            MatchPlayerInput("player_1", first_name, first_deck),
            MatchPlayerInput("player_2", second_name, second_deck),
        )
        cards, player_states, registry_version, effects = build_match_cards(
            self.card_database_path,
            players,
            self.effect_registry_path,
        )
        state = MatchState(
            match_id=resolved_id,
            seed=resolved_seed,
            players=player_states,
            cards=cards,
            controllers=_normalize_controllers(controllers),
            effect_registry_version=registry_version,
            effect_definitions=effects,
        )
        resolved_first_player_id = first_player_id or _random_first_player_id(resolved_seed)
        if resolved_first_player_id not in state.players:
            raise MatchSetupError("first_player_id must be player_1 or player_2")
        created = self.repository.create_match(
            state,
            card_database_path=self.card_database_path,
        )
        created_result = self.repository.apply(
            created.state.match_id,
            ActionRequest(
                action_type="choose_first_player",
                expected_revision=created.state.revision,
                payload={
                    "first_player_id": resolved_first_player_id,
                    "automatic": first_player_id is None,
                    "selection_method": "random_seeded"
                    if first_player_id is None
                    else "explicit",
                },
            ),
        )
        return self.advance_ai(created.state.match_id, created_result)

    def create_match_from_paths(
        self,
        *,
        first_name: str,
        first_deck_path: Path,
        second_name: str,
        second_deck_path: Path,
        seed: int | None = None,
    ) -> ActionResult:
        return self.create_match(
            first_name=first_name,
            first_deck=load_deck(first_deck_path),
            second_name=second_name,
            second_deck=load_deck(second_deck_path),
            seed=seed,
        )

    def apply(self, match_id: str, action: ActionRequest) -> ActionResult:
        return self.advance_ai(match_id, self.repository.apply(match_id, action))

    def advance_ai(
        self,
        match_id: str,
        result: ActionResult,
        *,
        max_ai_actions: int = 256,
    ) -> ActionResult:
        state = result.state
        controllers = _normalize_controllers(state.controllers)
        ai_player_ids = {
            player_id
            for player_id, controller in controllers.items()
            if controller == "simple_ai"
        }
        if not ai_player_ids:
            return result

        events = list(result.events)
        legal_actions = result.legal_actions
        controller = SimpleAIController(SimpleAIPolicy(manual_effect_policy="skip"))
        for _index in range(max_ai_actions):
            if state.phase == "complete":
                break
            decision = controller.choose_action(
                state,
                legal_actions,
                controlled_player_ids=ai_player_ids,
            )
            if decision is None:
                break
            if isinstance(decision, SimpleAIBlocker):
                events.append(
                    GameEvent(
                        event_type="ai_blocked",
                        player_id=decision.player_ids[0]
                        if decision.player_ids
                        and isinstance(decision.player_ids[0], str)
                        else None,
                        data={
                            "reason": decision.reason,
                            "legal_action_types": decision.legal_action_types,
                            "player_ids": decision.player_ids,
                        },
                        source="system",
                    )
                )
                break
            applied = self.repository.apply(match_id, decision.action)
            state = applied.state
            legal_actions = applied.legal_actions
            events.extend(applied.events)
        else:
            events.append(
                GameEvent(
                    event_type="ai_blocked",
                    player_id=None,
                    data={
                        "reason": "ai_action_cap_reached",
                        "max_ai_actions": max_ai_actions,
                    },
                    source="system",
                )
            )
        return ActionResult(state=state, events=events, legal_actions=legal_actions)


def _random_first_player_id(seed: int) -> str:
    return ("player_1", "player_2")[random.Random(f"{seed}:first_player").randrange(2)]


def _normalize_controllers(
    controllers: dict[str, ControllerType] | None,
) -> dict[str, ControllerType]:
    normalized: dict[str, ControllerType] = {
        "player_1": "human",
        "player_2": "human",
    }
    if controllers:
        for player_id in ("player_1", "player_2"):
            value = controllers.get(player_id)
            if value in {"human", "simple_ai"}:
                normalized[player_id] = value
    return normalized
