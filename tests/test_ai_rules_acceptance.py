from __future__ import annotations

import json
from pathlib import Path

from loveca.simulation.models import (
    ActionRequest,
    CardDefinition,
    CardInstance,
    GameEvent,
    MatchState,
    PlayerState,
)
from tools.ai_sandbox.ai_rules_acceptance import (
    audit_rulebook,
    load_strategy_experiment,
)
from tools.ai_sandbox.rule_conformance import (
    RULE_REFERENCES,
    _action_semantics_check,
    _event_conformance_checks,
    _expected_live_winners,
    _semantic_operation_alignment,
)
from tools.ai_sandbox.semantic_playtest import DEFAULT_RULES_PDF


def _live_judgment_state(
    *,
    first_score: int,
    second_score: int,
    first_success: int,
    second_success: int,
) -> MatchState:
    first = PlayerState(
        player_id="player_1",
        name="First",
        live_area=["first-live"],
        success_live_area=[f"first-success-{index}" for index in range(first_success)],
    )
    first.live_result.total_score = first_score
    second = PlayerState(
        player_id="player_2",
        name="Second",
        live_area=["second-live"],
        success_live_area=[f"second-success-{index}" for index in range(second_success)],
    )
    second.live_result.total_score = second_score
    return MatchState(
        match_id="rule-audit-live-result",
        seed=1,
        first_player_id="player_1",
        second_player_id="player_2",
        players={"player_1": first, "player_2": second},
        cards={},
    )


def test_rulebook_audit_locates_every_referenced_official_section() -> None:
    assert Path(DEFAULT_RULES_PDF).is_file()

    audit = audit_rulebook(DEFAULT_RULES_PDF)

    assert audit.page_count == 17
    assert audit.extracted_characters > 10_000
    assert set(audit.referenced_sections) == set(RULE_REFERENCES)
    assert audit.missing_sections == []


def test_semantic_alignment_covers_inspection_reveal_and_position_change() -> None:
    inspect_label = (
        "【登場】自分のデッキの上からカードを2枚見る。その中からカードを1枚公開して手札に加える。"
    )
    position_label = "【ライブ開始時】このメンバーをポジションチェンジしてもよい。"

    assert _semantic_operation_alignment(
        inspect_label,
        {"inspect_top_cards", "select_to_hand_from_inspected"},
    )
    assert _semantic_operation_alignment(
        position_label,
        {"position_change_source"},
    )
    assert _semantic_operation_alignment(
        "【登場】自分のデッキの上からカードを3枚見る。残りを控え室に置く。",
        {"inspect_top_cards", "move_remaining_cards"},
    )


def test_semantic_alignment_does_not_treat_heart_filter_as_heart_gain() -> None:
    filter_label = (
        "【登場】自分のデッキの上からカードを2枚見る。"
        "その中から赤のハートを持つカードを1枚公開して手札に加える。"
    )

    assert _semantic_operation_alignment(
        filter_label,
        {"inspect_top_cards", "select_to_hand_from_inspected"},
    )


def test_semantic_alignment_distinguishes_energy_attachment_from_deck_placement() -> None:
    attachment_label = (
        "【起動】自分のエネルギー置き場にあるエネルギー1枚をこのメンバーの下に置く："
        "自分の控え室からライブカードを1枚手札に加える。"
        "（このメンバーが離れたとき、エネルギーカードはエネルギーデッキに戻す。）"
    )
    deck_placement_label = (
        "【登場】手札を1枚控え室に置いてもよい："
        "自分のエネルギーデッキから、エネルギーカードを1枚ウェイト状態で置く。"
    )

    assert _semantic_operation_alignment(
        attachment_label,
        {"attach_selected_under_source", "return_from_waiting_room"},
    )
    assert _semantic_operation_alignment(
        deck_placement_label,
        {"discard_from_hand", "place_energy_from_deck"},
    )


def test_semantic_alignment_covers_mill_deck_position_and_heart_replacement() -> None:
    mill_then_position = (
        "【登場】自分のデッキの上からカードを2枚控え室に置く。"
        "その後、自分の控え室からライブカード1枚を"
        "自分のデッキの一番上から4枚目に置いてもよい。"
    )
    replace_heart = (
        "【ライブ開始時】【heart01】か【heart03】のうち1つを選ぶ。"
        "ライブ終了時まで、このメンバーが元々持つハートは選んだハートになる。"
    )

    assert _semantic_operation_alignment(
        mill_then_position,
        {"mill_top_cards", "move_selected_to_deck_position"},
    )
    assert _semantic_operation_alignment(
        replace_heart,
        {"replace_member_base_hearts"},
    )


def test_semantic_alignment_distinguishes_prior_reveal_and_base_blade_replacement() -> None:
    move_from_yell = (
        "【ライブ成功時】エールにより公開された自分のカードの中から、"
        "『Aqours』のライブカードを1枚手札に加える。"
    )
    replace_blade = (
        "【ライブ開始時】ライブ終了時まで、自分のステージのセンターエリアにいる"
        "『Liella!』のメンバーが元々持つ【ブレード】の数は3つになる。"
    )

    assert _semantic_operation_alignment(move_from_yell, {"move_selected_to_hand"})
    assert _semantic_operation_alignment(replace_blade, {"replace_member_base_blade"})


def test_equal_score_winners_are_independent_from_match_point_placement() -> None:
    neither_at_match_point = _live_judgment_state(
        first_score=2,
        second_score=2,
        first_success=1,
        second_success=0,
    )
    only_first_at_match_point = _live_judgment_state(
        first_score=2,
        second_score=2,
        first_success=2,
        second_success=1,
    )
    both_at_match_point = _live_judgment_state(
        first_score=2,
        second_score=2,
        first_success=2,
        second_success=2,
    )

    assert _expected_live_winners(neither_at_match_point) == ["player_1", "player_2"]
    assert _expected_live_winners(only_first_at_match_point) == [
        "player_1",
        "player_2",
    ]
    assert _expected_live_winners(both_at_match_point) == ["player_1", "player_2"]


def test_live_success_audit_uses_requirement_result_from_same_action() -> None:
    before = _live_judgment_state(
        first_score=1,
        second_score=0,
        first_success=0,
        second_success=0,
    )
    after = before.model_copy(deep=True)
    events = [
        GameEvent(
            event_type="live_requirements_resolved",
            player_id="player_2",
            data={"satisfied": False, "allocations": []},
        ),
        GameEvent(
            event_type="live_success_determined",
            data={"successful_player_ids": ["player_1"]},
        ),
    ]

    checks = _event_conformance_checks(before, after, events)

    success_check = next(
        check
        for check in checks
        if check.check_id == "live_success_before_score_comparison"
    )
    assert success_check.verdict == "pass"


def test_live_judgment_audit_uses_live_area_after_success_effects() -> None:
    before = _live_judgment_state(
        first_score=0,
        second_score=1,
        first_success=2,
        second_success=2,
    )
    after = before.model_copy(deep=True)
    events = [
        GameEvent(
            event_type="live_judgment_started",
            data={
                "basis": "only_one_player_has_successful_live",
                "successful_player_ids": ["player_1", "player_2"],
                "winner_ids": ["player_2"],
                "placement_eligible_player_ids": ["player_2"],
                "placement_prevented_player_ids": [],
                "scores": {"player_1": 0, "player_2": 1},
                "players": {
                    "player_1": {
                        "successful_live_instance_ids": [],
                        "base_score": 0,
                        "score_bonus": 0,
                        "total_score": 0,
                        "success_live_count_before": 2,
                    },
                    "player_2": {
                        "successful_live_instance_ids": ["second-live"],
                        "base_score": 1,
                        "score_bonus": 0,
                        "total_score": 1,
                        "success_live_count_before": 2,
                    },
                },
            },
        )
    ]

    checks = _event_conformance_checks(before, after, events)

    judgment = next(
        check for check in checks if check.check_id == "live_judgment_basis_and_winners"
    )
    assert judgment.verdict == "pass"
    assert judgment.evidence["expected_basis"] == "only_one_player_has_successful_live"


def test_member_payment_audit_accepts_energy_readied_by_onplay_effect() -> None:
    member = CardInstance(
        instance_id="member-1",
        owner_id="player_1",
        card=CardDefinition(
            card_code="TEST-MEMBER",
            card_id="TEST-MEMBER",
            name_ja="テストメンバー",
            card_type="member",
            cost=1,
        ),
    )
    energy = CardInstance(
        instance_id="energy-1",
        owner_id="player_1",
        card=CardDefinition(
            card_code="TEST-ENERGY",
            card_id="TEST-ENERGY",
            name_ja="テストエネルギー",
            card_type="energy",
        ),
        orientation="active",
    )
    before = MatchState(
        match_id="payment-audit",
        seed=1,
        first_player_id="player_1",
        second_player_id="player_2",
        active_player_id="player_1",
        phase="first_main",
        players={
            "player_1": PlayerState(
                player_id="player_1",
                name="First",
                hand=["member-1"],
                energy_area=["energy-1"],
            ),
            "player_2": PlayerState(player_id="player_2", name="Second"),
        },
        cards={"member-1": member, "energy-1": energy},
    )
    after = before.model_copy(deep=True)
    after.players["player_1"].hand = []
    after.players["player_1"].member_area["center"] = "member-1"
    # A triggered on-play effect may ready the Energy again before the composite
    # action returns, so final orientation is not proof that payment was skipped.
    after.cards["energy-1"].orientation = "active"
    action = ActionRequest(
        action_type="play_member",
        expected_revision=before.revision,
        player_id="player_1",
        payload={
            "card_instance_id": "member-1",
            "slot": "center",
            "energy_instance_ids": ["energy-1"],
            "use_baton_touch": False,
        },
    )
    events = [
        GameEvent(
            event_type="member_played",
            player_id="player_1",
            data={
                "card_instance_id": "member-1",
                "slot": "center",
                "energy_instance_ids": ["energy-1"],
                "payment_cost": 1,
                "baton_touch": False,
            },
        ),
        GameEvent(
            event_type="effect_auto_resolved",
            player_id="player_1",
            data={"effect_id": "TEST-MEMBER:1"},
        ),
    ]

    check = _action_semantics_check(before, after, action, events)

    assert check.verdict == "pass"
    assert check.evidence["payment_orientations_after"] == {"energy-1": "active"}


def test_strategy_experiment_rejects_clean_but_weaker_candidate(tmp_path: Path) -> None:
    report_path = tmp_path / "live-access" / "simple-ai-policy-summary.json"
    report_path.parent.mkdir()
    report_path.write_text(
        json.dumps(
            {
                "summary": {
                    "baseline_policy": "simple_ai_v1_1",
                    "challenger_policy": "simple_ai_v1_2",
                    "matches": 80,
                    "completed": 80,
                    "v1_points_rate": 0.475,
                    "average_turns": 8.137,
                    "p95_turns": 14,
                    "v0_live_success_rate": 0.5732,
                    "v1_live_success_rate": 0.5301,
                    "illegal_actions": 0,
                    "replay_errors": 0,
                }
            }
        ),
        encoding="utf-8",
    )

    experiment = load_strategy_experiment(report_path)

    assert experiment.name == "live-access"
    assert experiment.recommendation == "不采用"
    assert experiment.challenger_points_rate == 0.475


def test_strategy_experiment_requires_benchmark_contract(tmp_path: Path) -> None:
    report_path = tmp_path / "invalid.json"
    report_path.write_text('{"summary": {"matches": 2}}', encoding="utf-8")

    try:
        load_strategy_experiment(report_path)
    except ValueError as exc:
        assert "missing" in str(exc)
    else:
        raise AssertionError("invalid benchmark contract must be rejected")
