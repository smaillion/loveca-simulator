"""Official-rule boundary matrix for Live judgment.

The matrix intentionally uses the production judgment path while comparing its
observable result with explicit expectations transcribed from comprehensive
rules 8.4.2-8.4.13 and 1.2.1.1-1.2.1.2.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from loveca.simulation.effects import EffectDefinition
from loveca.simulation.engine import _begin_live_judgment
from loveca.simulation.models import (
    CardDefinition,
    CardInstance,
    GameEvent,
    LivePerformanceResult,
    MatchState,
    PlayerState,
)


@dataclass(frozen=True)
class LiveJudgmentBoundaryResult:
    scenario_id: str
    title_zh: str
    rule_refs: tuple[str, ...]
    expected: dict[str, Any]
    actual: dict[str, Any]
    passed: bool


def run_live_judgment_boundary_matrix() -> list[LiveJudgmentBoundaryResult]:
    scenarios = [
        _scenario(
            "neither_successful",
            "双方均没有成功 Live",
            first_live_score=None,
            second_live_score=None,
            expected={
                "successful_player_ids": [],
                "winner_ids": [],
                "eligible_player_ids": [],
                "moved_player_ids": [],
                "next_first_player_id": "player_1",
            },
        ),
        _scenario(
            "only_one_successful",
            "仅一方有成功 Live 时不比较另一方分数",
            first_live_score=0,
            second_live_score=None,
            expected={
                "successful_player_ids": ["player_1"],
                "winner_ids": ["player_1"],
                "eligible_player_ids": ["player_1"],
                "moved_player_ids": ["player_1"],
                "next_first_player_id": "player_1",
            },
        ),
        _scenario(
            "higher_score",
            "双方成功时由较高总分玩家获胜",
            first_live_score=3,
            second_live_score=2,
            expected={
                "successful_player_ids": ["player_1", "player_2"],
                "winner_ids": ["player_1"],
                "eligible_player_ids": ["player_1"],
                "moved_player_ids": ["player_1"],
                "next_first_player_id": "player_1",
            },
        ),
        _scenario(
            "equal_score_no_match_point",
            "普通同分时双方均胜利并各移动一张",
            first_live_score=2,
            second_live_score=2,
            expected={
                "successful_player_ids": ["player_1", "player_2"],
                "winner_ids": ["player_1", "player_2"],
                "eligible_player_ids": ["player_1", "player_2"],
                "prevented_player_ids": [],
                "moved_player_ids": ["player_1", "player_2"],
                "next_first_player_id": "player_1",
            },
        ),
        _scenario(
            "equal_score_one_match_point",
            "单边 Match Point 同分时双方胜利但仅另一方移动",
            first_live_score=2,
            second_live_score=2,
            first_success_count=2,
            expected={
                "winner_ids": ["player_1", "player_2"],
                "eligible_player_ids": ["player_2"],
                "prevented_player_ids": ["player_1"],
                "moved_player_ids": ["player_2"],
                "next_first_player_id": "player_2",
                "game_result": None,
            },
        ),
        _scenario(
            "equal_score_both_match_point",
            "双方 Match Point 同分时双方胜利但均不移动",
            first_live_score=2,
            second_live_score=2,
            first_success_count=2,
            second_success_count=2,
            expected={
                "winner_ids": ["player_1", "player_2"],
                "eligible_player_ids": [],
                "prevented_player_ids": ["player_1", "player_2"],
                "moved_player_ids": [],
                "next_first_player_id": "player_1",
                "game_result": None,
            },
        ),
        _scenario(
            "higher_score_at_match_point",
            "双方 Match Point 但分数不同时高分方移动并获胜",
            first_live_score=3,
            second_live_score=2,
            first_success_count=2,
            second_success_count=2,
            expected={
                "winner_ids": ["player_1"],
                "eligible_player_ids": ["player_1"],
                "prevented_player_ids": [],
                "moved_player_ids": ["player_1"],
                "game_result": {
                    "outcome": "win",
                    "winner_player_ids": ["player_1"],
                },
            },
        ),
        _scenario(
            "live_success_score_before_comparison",
            "Live 成功时加分在胜者比较前结算",
            first_live_score=1,
            second_live_score=2,
            first_effect="score_plus_two",
            expected={
                "winner_ids": ["player_1"],
                "eligible_player_ids": ["player_1"],
                "scores": {"player_1": 3, "player_2": 2},
            },
        ),
        _scenario(
            "card_effect_blocks_equal_placement",
            "卡牌效果可在同分时阻止双方移动成功 Live",
            first_live_score=2,
            second_live_score=2,
            first_effect="block_equal_placement",
            expected={
                "winner_ids": ["player_1", "player_2"],
                "eligible_player_ids": [],
                "prevented_player_ids": ["player_1", "player_2"],
                "moved_player_ids": [],
            },
        ),
    ]
    return scenarios


def serialize_live_judgment_boundary_matrix() -> list[dict[str, Any]]:
    return [asdict(item) for item in run_live_judgment_boundary_matrix()]


def _scenario(
    scenario_id: str,
    title_zh: str,
    *,
    first_live_score: int | None,
    second_live_score: int | None,
    first_success_count: int = 0,
    second_success_count: int = 0,
    first_effect: str | None = None,
    expected: dict[str, Any],
) -> LiveJudgmentBoundaryResult:
    state = _build_state(
        first_live_score=first_live_score,
        second_live_score=second_live_score,
        first_success_count=first_success_count,
        second_success_count=second_success_count,
        first_effect=first_effect,
    )
    events: list[GameEvent] = []
    _begin_live_judgment(state, events)
    summary = state.live_judgment_summary or {}
    actual = {
        "successful_player_ids": list(state.live_success_player_ids),
        "winner_ids": list(state.live_winner_ids),
        "eligible_player_ids": list(state.live_placement_eligible_player_ids),
        "prevented_player_ids": list(state.live_placement_prevented_player_ids),
        "moved_player_ids": list(state.success_live_moved_player_ids),
        "next_first_player_id": state.next_first_player_id,
        "scores": {
            player_id: int(detail.get("total_score", 0))
            for player_id, detail in summary.get("players", {}).items()
        },
        "game_result": (
            {
                "outcome": state.game_result.outcome,
                "winner_player_ids": list(state.game_result.winner_player_ids),
            }
            if state.game_result
            else None
        ),
        "event_types": [event.event_type for event in events],
    }
    passed = all(actual.get(key) == value for key, value in expected.items())
    return LiveJudgmentBoundaryResult(
        scenario_id=scenario_id,
        title_zh=title_zh,
        rule_refs=(
            "8.4.2",
            "8.4.4",
            "8.4.5",
            "8.4.6",
            "8.4.7",
            "8.4.7.1",
            "8.4.8",
            "8.4.13",
            "1.2.1.1",
            "1.2.1.2",
        ),
        expected=expected,
        actual=actual,
        passed=passed,
    )


def _build_state(
    *,
    first_live_score: int | None,
    second_live_score: int | None,
    first_success_count: int,
    second_success_count: int,
    first_effect: str | None,
) -> MatchState:
    effect = _effect_definition(first_effect) if first_effect else None
    cards: dict[str, CardInstance] = {}
    players: dict[str, PlayerState] = {}
    for player_id, live_score, success_count in (
        ("player_1", first_live_score, first_success_count),
        ("player_2", second_live_score, second_success_count),
    ):
        success_ids = []
        for index in range(success_count):
            instance_id = f"{player_id}-success-{index}"
            cards[instance_id] = _live_instance(instance_id, player_id, 1)
            success_ids.append(instance_id)
        live_ids = []
        if live_score is not None:
            instance_id = f"{player_id}-current-live"
            card = _live_instance(instance_id, player_id, live_score)
            if player_id == "player_1" and effect is not None:
                card.card.effect_ids = [effect.effect_id]
                card.card.effect_registry_status = "supported"
            cards[instance_id] = card
            live_ids.append(instance_id)
        players[player_id] = PlayerState(
            player_id=player_id,
            name=player_id,
            live_area=live_ids,
            success_live_area=success_ids,
            live_result=LivePerformanceResult(
                requirements_satisfied=bool(live_ids),
                base_score=live_score or 0,
                total_score=live_score or 0,
            ),
        )
    return MatchState(
        match_id="live-boundary-audit",
        seed=1,
        phase="live_judgment",
        first_player_id="player_1",
        second_player_id="player_2",
        players=players,
        cards=cards,
        effect_definitions={effect.effect_id: effect} if effect else {},
    )


def _live_instance(
    instance_id: str,
    player_id: str,
    score: int,
) -> CardInstance:
    return CardInstance(
        instance_id=instance_id,
        owner_id=player_id,
        card=CardDefinition(
            card_code=instance_id,
            card_id=instance_id,
            name_ja=instance_id,
            card_type="live",
            score=score,
        ),
    )


def _effect_definition(kind: str) -> EffectDefinition:
    action = (
        {"action_type": "modify_score", "amount": 2}
        if kind == "score_plus_two"
        else {"action_type": "prevent_equal_score_success_live_placement"}
    )
    condition = (
        {}
        if kind == "score_plus_two"
        else {"live_score_relation": "equal_to_opponent"}
    )
    return EffectDefinition.model_validate(
        {
            "effect_id": f"audit-{kind}:1",
            "card_code": "AUDIT-LIVE",
            "text_revision_id": 1,
            "raw_text_hash": "a" * 64,
            "effect_index": 1,
            "label_ja": f"【ライブ成功時】{kind}",
            "effect_type": "triggered",
            "timing": "live_success",
            "trigger": "live_succeeded",
            "execution_mode": "auto_resolve",
            "frequency_limit": "once_per_live",
            "is_optional": False,
            "condition": condition,
            "cost": [],
            "choice": None,
            "actions": [action],
            "duration": "live",
            "simulation_support": "test_validated_executable",
            "review_status": "test_validated",
            "source_reference": "Comprehensive rules ver. 1.06 audit fixture",
        }
    )
