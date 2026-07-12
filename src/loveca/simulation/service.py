"""Application service coordinating deck validation, match setup, and persistence."""

from __future__ import annotations

import random
import secrets
import uuid
from pathlib import Path
from time import perf_counter

from loveca.decks.analyzer import DeckList, analyze_deck, load_deck
from loveca.simulation.ai import SimpleAIBlocker, SimpleAIController, SimpleAIPolicy
from loveca.simulation.catalog import MatchPlayerInput, build_match_cards
from loveca.simulation.effects import DEFAULT_EFFECT_REGISTRY
from loveca.simulation.engine import IllegalActionError
from loveca.simulation.models import (
    ActionRequest,
    ActionResult,
    ControllerPolicyVersion,
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
        controller_policy_versions: dict[str, ControllerPolicyVersion] | None = None,
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
            controller_policy_versions=_new_match_controller_policy_versions(
                controllers,
                controller_policy_versions,
            ),
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
        ai_continuation_active = False
        last_ai_player_id: str | None = None
        for _index in range(max_ai_actions):
            if state.phase == "complete":
                break
            decision_player_ids = {
                action.player_id
                for action in legal_actions
                if action.player_id in ai_player_ids
            }
            if decision_player_ids:
                controlled_player_ids = {sorted(decision_player_ids)[0]}
            elif ai_continuation_active:
                fallback_player_id = (
                    last_ai_player_id
                    if last_ai_player_id in ai_player_ids
                    else state.active_player_id
                    if state.active_player_id in ai_player_ids
                    else sorted(ai_player_ids)[0]
                )
                controlled_player_ids = {fallback_player_id}
            else:
                controlled_player_ids = set(ai_player_ids)
            policy_version = _controller_policy_version(
                state,
                controlled_player_ids,
            )
            controller = SimpleAIController(
                SimpleAIPolicy(
                    manual_effect_policy="skip",
                    policy_version=policy_version,
                )
            )
            decision_started = perf_counter()
            decision = controller.choose_action(
                state,
                legal_actions,
                controlled_player_ids=controlled_player_ids,
                allow_player_neutral_actions=ai_continuation_active,
            )
            decision_duration_ms = (perf_counter() - decision_started) * 1000
            if decision is None:
                break
            if isinstance(decision, SimpleAIBlocker):
                blocker = _ai_blocked_event(
                    state,
                    reason=decision.reason,
                    player_id=decision.player_ids[0]
                    if decision.player_ids and isinstance(decision.player_ids[0], str)
                    else None,
                    data={
                        "legal_action_types": decision.legal_action_types,
                        "player_ids": decision.player_ids,
                    },
                )
                self.repository.append_system_events(match_id, [blocker])
                events.append(blocker)
                break
            ai_metadata = decision.action.payload.get("ai_decision")
            if isinstance(ai_metadata, dict):
                ai_metadata["duration_ms"] = round(decision_duration_ms, 3)
            try:
                applied = self.repository.apply(match_id, decision.action)
            except Exception as exc:  # noqa: BLE001 - isolate controller failures from the match.
                blocker = _ai_blocked_event(
                    state,
                    reason=(
                        "ai_illegal_action"
                        if isinstance(exc, IllegalActionError)
                        else "ai_action_error"
                    ),
                    player_id=decision.action.player_id,
                    data={
                        "action_type": decision.action.action_type,
                        "action_payload": {
                            key: value
                            for key, value in decision.action.payload.items()
                            if key != "ai_decision"
                        },
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "decision_reason": decision.reason,
                    },
                )
                self.repository.append_system_events(match_id, [blocker])
                events.append(blocker)
                break
            state = applied.state
            legal_actions = applied.legal_actions
            events.extend(applied.events)
            ai_continuation_active = True
            if decision.action.player_id in ai_player_ids:
                last_ai_player_id = decision.action.player_id
        else:
            blocker = _ai_blocked_event(
                state,
                reason="ai_action_cap_reached",
                player_id=None,
                data={"max_ai_actions": max_ai_actions},
            )
            self.repository.append_system_events(match_id, [blocker])
            events.append(blocker)
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


def _new_match_controller_policy_versions(
    controllers: dict[str, ControllerType] | None,
    requested: dict[str, ControllerPolicyVersion] | None = None,
) -> dict[str, ControllerPolicyVersion]:
    normalized = _normalize_controllers(controllers)
    return {
        player_id: (
            requested.get(player_id, "simple_ai_v1")
            if requested
            else "simple_ai_v1"
        )
        for player_id, controller in normalized.items()
        if controller == "simple_ai"
    }


def _controller_policy_version(
    state: MatchState,
    controlled_player_ids: set[str],
) -> ControllerPolicyVersion:
    versions = {
        state.controller_policy_versions.get(player_id, "simple_ai_v0")
        for player_id in controlled_player_ids
    }
    return "simple_ai_v1" if versions == {"simple_ai_v1"} else "simple_ai_v0"


def _ai_blocked_event(
    state: MatchState,
    *,
    reason: str,
    player_id: str | None,
    data: dict[str, object] | None = None,
) -> GameEvent:
    return GameEvent(
        event_type="ai_blocked",
        player_id=player_id,
        data={
            "reason": reason,
            "state_revision": state.revision,
            "phase": state.phase,
            "turn_number": state.turn_number,
            **(data or {}),
            "pending_effects": _pending_effect_context(state),
            "pending_choice": state.pending_choice.model_dump() if state.pending_choice else None,
        },
        source="system",
    )


def _pending_effect_context(state: MatchState) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for invocation in state.pending_effects[:5]:
        effect = state.effect_definitions.get(invocation.effect_id)
        source = state.cards.get(invocation.source_card_instance_id)
        items.append(
            {
                "invocation_id": invocation.invocation_id,
                "effect_id": invocation.effect_id,
                "source_card_instance_id": invocation.source_card_instance_id,
                "source_card_code": source.card.card_code if source else None,
                "source_card_name_ja": source.card.name_ja if source else None,
                "label_ja": effect.label_ja if effect else None,
                "trigger": effect.trigger if effect else None,
                "timing": effect.timing if effect else None,
                "simulation_support": effect.simulation_support if effect else None,
                "is_optional": effect.is_optional if effect else None,
            }
        )
    return items
