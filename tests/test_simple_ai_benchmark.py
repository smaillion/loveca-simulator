from loveca.simulation.models import GameEvent
from tools.ai_sandbox.simple_ai_benchmark import (
    _percentile,
    _player_policy_metrics,
    benchmark_passed,
)


def test_simple_ai_benchmark_gate_includes_decision_latency():
    summary = {
        "matches": 200,
        "completed": 200,
        "illegal_actions": 0,
        "replay_errors": 0,
        "v1_points_rate": 0.55,
        "average_turns": 10.7,
        "p95_turns": 20,
        "v1_decision_p95_ms": 249.9,
    }

    assert benchmark_passed(summary)
    summary["v1_decision_p95_ms"] = 250.1
    assert not benchmark_passed(summary)
    summary["v1_decision_p95_ms"] = 249.9
    summary["average_turns"] = 10.701
    assert not benchmark_passed(summary)


def test_percentile_uses_nearest_rank():
    assert _percentile([1.0, 2.0, 3.0, 4.0], 0.95) == 4.0
    assert _percentile([], 0.95) == 0.0


def test_policy_metrics_keep_live_energy_and_effect_results_by_player():
    events = [
        GameEvent(
            event_type="member_played",
            player_id="player_1",
            data={"payment_cost": 2},
        ),
        GameEvent(
            event_type="effect_cost_paid",
            player_id="player_1",
            data={"energy_instance_ids": ["energy-1"]},
        ),
        GameEvent(
            event_type="live_requirements_resolved",
            player_id="player_1",
            data={"satisfied": True},
        ),
        GameEvent(event_type="effect_resolved", player_id="player_1"),
        GameEvent(
            event_type="live_requirements_resolved",
            player_id="player_2",
            data={"satisfied": False},
        ),
    ]

    assert _player_policy_metrics(events, "player_1") == {
        "live_checks": 1,
        "live_successes": 1,
        "energy_spent": 3,
        "effect_decisions": 1,
    }
