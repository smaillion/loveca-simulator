from __future__ import annotations

from tools.ai_sandbox.live_judgment_audit import (
    run_live_judgment_boundary_matrix,
)


def test_live_judgment_boundary_matrix_passes_all_official_rule_cases() -> None:
    results = run_live_judgment_boundary_matrix()

    assert len(results) == 9
    assert all(item.passed for item in results)


def test_match_point_tie_keeps_winner_and_placement_semantics_separate() -> None:
    results = {
        item.scenario_id: item
        for item in run_live_judgment_boundary_matrix()
    }

    one_match_point = results["equal_score_one_match_point"].actual
    assert one_match_point["winner_ids"] == ["player_1", "player_2"]
    assert one_match_point["eligible_player_ids"] == ["player_2"]
    assert one_match_point["prevented_player_ids"] == ["player_1"]
    assert one_match_point["game_result"] is None

    both_match_point = results["equal_score_both_match_point"].actual
    assert both_match_point["winner_ids"] == ["player_1", "player_2"]
    assert both_match_point["eligible_player_ids"] == []
    assert both_match_point["moved_player_ids"] == []
    assert both_match_point["game_result"] is None


def test_live_success_effects_resolve_before_score_comparison() -> None:
    result = next(
        item
        for item in run_live_judgment_boundary_matrix()
        if item.scenario_id == "live_success_score_before_comparison"
    )

    assert result.actual["scores"] == {"player_1": 3, "player_2": 2}
    assert result.actual["winner_ids"] == ["player_1"]
    assert result.actual["event_types"].index(
        "effect_auto_resolved"
    ) < result.actual["event_types"].index("live_judgment_started")
