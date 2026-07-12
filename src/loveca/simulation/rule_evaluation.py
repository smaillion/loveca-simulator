"""Read-only rule-derived views for deterministic controller decisions.

The controller must not reimplement card modifiers or inspect hidden deck order.
This module exposes only effective public/owned values calculated with the rule
engine's existing helpers.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from loveca.simulation.engine import (
    _card_score,
    _effective_required_hearts,
    _member_base_blade,
    _member_heart_color_slots,
    _member_heart_count,
    _modifier_total,
    _static_numeric_bonus,
    _static_score_bonus,
    _target_modifier_total,
)
from loveca.simulation.models import (
    CardDefinition,
    EffectDefinition,
    LegalAction,
    MatchState,
)


@dataclass(frozen=True)
class EvaluatedMember:
    instance_id: str
    card_code: str
    cost: int
    hearts: tuple[tuple[str, int], ...]
    blade: int
    is_active: bool

    @property
    def heart_total(self) -> int:
        return sum(amount for _color, amount in self.hearts)


@dataclass(frozen=True)
class EvaluatedLive:
    instance_id: str
    card_code: str
    score: int
    required_hearts: tuple[tuple[str, int], ...]

    @property
    def required_total(self) -> int:
        return sum(amount for _color, amount in self.required_hearts)


@dataclass(frozen=True)
class RuleEvaluationSnapshot:
    player_id: str
    turn_number: int
    stage_members: tuple[EvaluatedMember, ...]
    stage_hearts: tuple[tuple[str, int], ...]
    active_blade_count: int
    active_energy_count: int
    score_bonus: int
    success_live_count: int
    opponent_success_live_count: int
    lives: tuple[EvaluatedLive, ...]
    expected_yell_hearts: tuple[tuple[str, float], ...]
    expected_yell_all_color: float

    def live(self, instance_id: str) -> EvaluatedLive | None:
        return next((item for item in self.lives if item.instance_id == instance_id), None)


@dataclass(frozen=True)
class ObservedPlayer:
    player_id: str
    hand: tuple[str, ...]
    hand_count: int
    main_deck_count: int
    energy_deck_count: int
    member_area: tuple[tuple[str, str | None], ...]
    energy_area: tuple[str, ...]
    live_area: tuple[str, ...]
    waiting_room: tuple[str, ...]
    resolution_area: tuple[str, ...]
    success_live_area: tuple[str, ...]


@dataclass(frozen=True)
class AIObservation:
    player_id: str
    phase: str
    turn_number: int
    revision: int
    active_player_id: str | None
    players: Mapping[str, ObservedPlayer]
    cards: Mapping[str, CardDefinition]
    effects: Mapping[str, EffectDefinition]
    evaluation: RuleEvaluationSnapshot

    def card(self, instance_id: str) -> CardDefinition | None:
        return self.cards.get(instance_id)


def build_rule_evaluation_snapshot(
    state: MatchState,
    player_id: str,
) -> RuleEvaluationSnapshot:
    player = state.players[player_id]
    members: list[EvaluatedMember] = []
    stage_hearts: Counter[str] = Counter()
    blade_count = _modifier_total(player, "blade")
    for instance_id in player.member_area.values():
        if instance_id is None:
            continue
        instance = state.cards[instance_id]
        hearts = tuple(
            sorted(
                (
                    color,
                    max(0, _member_heart_count(state, player_id, instance_id, color)),
                )
                for color in _member_heart_color_slots(state, player_id, instance_id)
            )
        )
        stage_hearts.update(dict(hearts))
        member_blade = 0
        if instance.orientation == "active":
            member_blade = max(
                0,
                _member_base_blade(state, player_id, instance_id)
                + _target_modifier_total(player, "blade", instance_id)
                + _static_numeric_bonus(
                    state,
                    player_id,
                    instance_id,
                    "gain_blade",
                ),
            )
            blade_count += member_blade
        members.append(
            EvaluatedMember(
                instance_id=instance_id,
                card_code=instance.card.card_code,
                cost=instance.card.cost or 0,
                hearts=hearts,
                blade=member_blade,
                is_active=instance.orientation == "active",
            )
        )

    live_ids = [
        instance_id
        for instance_id in (*player.hand, *player.live_area)
        if state.cards[instance_id].card.card_type == "live"
    ]
    lives = tuple(
        EvaluatedLive(
            instance_id=instance_id,
            card_code=state.cards[instance_id].card.card_code,
            score=_card_score(state, player_id, instance_id),
            required_hearts=tuple(
                sorted(
                    _effective_required_hearts(
                        player,
                        instance_id,
                        state.cards[instance_id].card.required_hearts,
                    ).items()
                )
            ),
        )
        for instance_id in dict.fromkeys(live_ids)
    )

    blade_heart_counts: Counter[str] = Counter()
    all_color_count = 0
    for instance_id in player.main_deck:
        card = state.cards[instance_id].card
        if card.blade_heart_color_slot:
            blade_heart_counts[card.blade_heart_color_slot] += 1
        for special in card.special_blade_hearts:
            if special.effect_type == "all_color":
                all_color_count += special.value or 1
    deck_count = len(player.main_deck)
    expected_hearts = tuple(
        sorted(
            (
                color,
                blade_count * amount / deck_count if deck_count else 0.0,
            )
            for color, amount in blade_heart_counts.items()
        )
    )
    expected_all = blade_count * all_color_count / deck_count if deck_count else 0.0
    opponent_success = max(
        (
            len(other.success_live_area)
            for other_id, other in state.players.items()
            if other_id != player_id
        ),
        default=0,
    )
    return RuleEvaluationSnapshot(
        player_id=player_id,
        turn_number=state.turn_number,
        stage_members=tuple(members),
        stage_hearts=tuple(sorted(stage_hearts.items())),
        active_blade_count=max(0, blade_count),
        active_energy_count=sum(
            state.cards[item].orientation == "active" for item in player.energy_area
        ),
        score_bonus=_modifier_total(player, "score") + _static_score_bonus(state, player_id),
        success_live_count=len(player.success_live_area),
        opponent_success_live_count=opponent_success,
        lives=lives,
        expected_yell_hearts=expected_hearts,
        expected_yell_all_color=expected_all,
    )


def build_ai_observation(
    state: MatchState,
    player_id: str,
    legal_actions: list[LegalAction],
) -> AIObservation:
    """Build a controller view without opponent hand identities or deck order."""

    visible_ids: set[str] = set()
    observed_players: dict[str, ObservedPlayer] = {}
    for observed_id, player in state.players.items():
        own = observed_id == player_id
        public_ids = {
            item
            for item in (
                *player.member_area.values(),
                *(
                    attached
                    for items in player.member_area_attachments.values()
                    for attached in items
                ),
                *player.energy_area,
                *player.live_area,
                *player.waiting_room,
                *player.resolution_area,
                *player.success_live_area,
            )
            if item is not None
        }
        visible_ids.update(public_ids)
        if own:
            visible_ids.update(player.hand)
        observed_players[observed_id] = ObservedPlayer(
            player_id=observed_id,
            hand=tuple(player.hand) if own else (),
            hand_count=len(player.hand),
            main_deck_count=len(player.main_deck),
            energy_deck_count=len(player.energy_deck),
            member_area=tuple(sorted(player.member_area.items())),
            energy_area=tuple(player.energy_area),
            live_area=tuple(player.live_area),
            waiting_room=tuple(player.waiting_room),
            resolution_area=tuple(player.resolution_area),
            success_live_area=tuple(player.success_live_area),
        )

    # LegalActionGenerator is authoritative for private cards explicitly exposed
    # by a structured choice (for example an inspected or revealed candidate).
    for action in legal_actions:
        visible_ids.update(_card_ids_in_value(action.options, state.cards))

    cards = {
        instance_id: state.cards[instance_id].card.model_copy(deep=True)
        for instance_id in sorted(visible_ids)
        if instance_id in state.cards
    }
    effect_ids = {
        effect_id
        for card in cards.values()
        for effect_id in card.effect_ids
        if effect_id in state.effect_definitions
    }
    for action in legal_actions:
        effect_ids.update(_effect_ids_in_value(action.options, state.effect_definitions))
    effects = {
        effect_id: state.effect_definitions[effect_id].model_copy(deep=True)
        for effect_id in sorted(effect_ids)
    }
    return AIObservation(
        player_id=player_id,
        phase=state.phase,
        turn_number=state.turn_number,
        revision=state.revision,
        active_player_id=state.active_player_id,
        players=MappingProxyType(observed_players),
        cards=MappingProxyType(cards),
        effects=MappingProxyType(effects),
        evaluation=build_rule_evaluation_snapshot(state, player_id),
    )


def estimate_live_combo_missing_hearts(
    snapshot: RuleEvaluationSnapshot,
    live_instance_ids: tuple[str, ...],
) -> float:
    requirements: Counter[str] = Counter()
    for instance_id in live_instance_ids:
        live = snapshot.live(instance_id)
        if live is not None:
            requirements.update(dict(live.required_hearts))

    available: Counter[str] = Counter(dict(snapshot.stage_hearts))
    expected = dict(snapshot.expected_yell_hearts)
    for color, amount in expected.items():
        available[color] += amount
    flexible = float(available.pop("heart0", 0)) + snapshot.expected_yell_all_color
    missing = 0.0
    for color, amount in sorted(
        ((color, amount) for color, amount in requirements.items() if color != "heart0"),
        key=lambda item: -(item[1] - available.get(item[0], 0)),
    ):
        shortage = max(0.0, amount - available.get(color, 0))
        covered = min(flexible, shortage)
        flexible -= covered
        missing += shortage - covered
    generic = requirements.get("heart0", 0)
    if generic:
        remaining = sum(max(0.0, amount) for amount in available.values()) + flexible
        missing += max(0.0, generic - remaining)
    return round(missing, 4)


def _card_ids_in_value(value: Any, cards: Mapping[str, Any]) -> set[str]:
    if isinstance(value, str):
        return {value} if value in cards else set()
    if isinstance(value, dict):
        return {
            item
            for nested in value.values()
            for item in _card_ids_in_value(nested, cards)
        }
    if isinstance(value, (list, tuple, set)):
        return {item for nested in value for item in _card_ids_in_value(nested, cards)}
    return set()


def _effect_ids_in_value(
    value: Any,
    effects: Mapping[str, EffectDefinition],
) -> set[str]:
    if isinstance(value, str):
        return {value} if value in effects else set()
    if isinstance(value, dict):
        return {
            item
            for nested in value.values()
            for item in _effect_ids_in_value(nested, effects)
        }
    if isinstance(value, (list, tuple, set)):
        return {item for nested in value for item in _effect_ids_in_value(nested, effects)}
    return set()
