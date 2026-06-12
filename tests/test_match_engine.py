from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from loveca.cards.importer import import_normalized_cards
from loveca.decks.analyzer import load_deck
from loveca.simulation.engine import IllegalActionError, StaleRevisionError
from loveca.simulation.models import ActionRequest
from loveca.simulation.service import MatchService


# Official comprehensive rules ver. 1.06:
# 6.2.1.5 opening hand 6; 6.2.1.6 mulligan; 6.2.1.7 initial Energy 3;
# 7.1.2 and 7.3.3 phase order; 8.2 set up to 3 cards; 8.3 performance;
# 8.3.10-8.3.15 Blade total, Yell, Live owned Hearts, and requirements;
# 8.4.2-8.4.6 score calculation and first Live judgment.
PROJECT_ROOT = Path(__file__).parents[1]
SAMPLE_CARDS = (
    PROJECT_ROOT
    / "data_samples"
    / "normalized"
    / "cards-cross-product-sample.json"
)
NORMALIZATION = PROJECT_ROOT / "data_sources" / "card-entity-normalization.json"
SAMPLE_DECK = PROJECT_ROOT / "examples" / "decks" / "sample-deck.json"


def test_setup_phase_order_and_first_live_completion(tmp_path):
    service, match_id = _create_match(tmp_path, seed=260428)

    state = service.repository.get_state(match_id)
    assert state.phase == "setup_choose_first"
    assert len(state.players["player_1"].main_deck) == 60

    state = _apply(
        service,
        match_id,
        state,
        "choose_first_player",
        payload={"first_player_id": "player_1"},
    )
    assert len(state.players["player_1"].hand) == 6
    assert len(state.players["player_2"].hand) == 6

    state = _apply(
        service,
        match_id,
        state,
        "submit_mulligan",
        player_id="player_1",
        payload={"card_instance_ids": state.players["player_1"].hand[:2]},
    )
    assert len(state.players["player_1"].hand) == 6
    state = _apply(
        service,
        match_id,
        state,
        "submit_mulligan",
        player_id="player_2",
        payload={"card_instance_ids": []},
    )
    assert state.phase == "first_active"
    assert len(state.players["player_1"].energy_area) == 3
    assert len(state.players["player_2"].energy_area) == 3

    expected_phases = [
        "first_energy",
        "first_draw",
        "first_main",
        "second_active",
        "second_energy",
        "second_draw",
        "second_main",
        "live_set_first",
        "live_set_second",
        "performance_first",
        "yell_first",
        "performance_second",
        "yell_second",
        "live_judgment",
        "complete",
    ]
    for expected in expected_phases:
        if state.phase.endswith(("_active", "_energy", "_draw")):
            action_type = "advance_phase"
        elif state.phase.endswith("_main"):
            action_type = "end_main_phase"
        elif state.phase.startswith("live_set"):
            action_type = "set_live_cards"
        else:
            action_type = "advance_phase"
        state = _apply(
            service,
            match_id,
            state,
            action_type,
            player_id=state.active_player_id,
            payload={"card_instance_ids": []} if action_type == "set_live_cards" else {},
        )
        assert state.phase == expected
    assert state.completed_reason == "live_judgment_completed"
    assert state.live_judgment_summary is not None
    assert state.live_judgment_summary["basis"] == "no_successful_live"


def test_yell_and_live_requirement_details_are_preserved(tmp_path):
    service, match_id = _create_match(tmp_path, seed=106)
    state = _reach_first_main(service, match_id)
    live_id = next(
        instance_id
        for instance_id in state.players["player_1"].main_deck
        if state.cards[instance_id].card.card_type == "live"
        and state.cards[instance_id].card.required_hearts
    )
    state = _apply(
        service,
        match_id,
        state,
        "manual_adjustment",
        player_id="player_1",
        payload={
            "reason": "prepare Live requirement review",
            "requires_confirmation": True,
            "confirmed_by": "tester",
            "adjustments": [
                {
                    "adjustment_type": "move_card",
                    "target_player_id": "player_1",
                    "target_card_instance_id": live_id,
                    "to_zone": "hand",
                }
            ],
        },
    )
    state = _apply(
        service,
        match_id,
        state,
        "end_main_phase",
        player_id="player_1",
    )
    for _ in range(3):
        state = _apply(
            service,
            match_id,
            state,
            "advance_phase",
            player_id="player_2",
        )
    state = _apply(
        service,
        match_id,
        state,
        "end_main_phase",
        player_id="player_2",
    )
    state = _apply(
        service,
        match_id,
        state,
        "set_live_cards",
        player_id="player_1",
        payload={"card_instance_ids": [live_id]},
    )
    state = _apply(
        service,
        match_id,
        state,
        "set_live_cards",
        player_id="player_2",
        payload={"card_instance_ids": []},
    )
    assert state.phase == "performance_first"

    state = _apply(
        service,
        match_id,
        state,
        "advance_phase",
        player_id="player_1",
    )
    assert state.phase == "yell_first"
    assert state.cards[live_id].face_up
    state = _apply(
        service,
        match_id,
        state,
        "manual_adjustment",
        player_id="player_1",
        payload={
            "reason": "exercise Yell output",
            "requires_confirmation": True,
            "confirmed_by": "tester",
            "adjustments": [
                {
                    "adjustment_type": "modify_blade",
                    "target_player_id": "player_1",
                    "amount": 2,
                }
            ],
        },
    )
    state = _apply(
        service,
        match_id,
        state,
        "advance_phase",
        player_id="player_1",
    )
    if state.pending_choice is not None:
        state = _apply(
            service,
            match_id,
            state,
            "resolve_live_requirements",
            player_id="player_1",
            payload={"live_instance_ids": [live_id]},
        )

    result = state.players["player_1"].live_result
    assert state.phase == "performance_second"
    assert result.blade_count == 2
    assert len(result.revealed_instance_ids) == 2
    assert result.live_allocations[0]["live_instance_id"] == live_id
    assert result.live_allocations[0]["required_hearts"]
    assert "consumed_hearts" in result.live_allocations[0]
    assert "missing_hearts" in result.live_allocations[0]


def test_manual_adjustment_and_member_play_are_action_only(tmp_path):
    service, match_id = _create_match(tmp_path, seed=11)
    state = _reach_first_main(service, match_id)
    player = state.players["player_1"]
    member_id = next(
        instance_id
        for instance_id in player.main_deck
        if state.cards[instance_id].card.card_type == "member"
        and state.cards[instance_id].card.cost is not None
        and state.cards[instance_id].card.cost <= len(player.energy_area)
    )
    state = _apply(
        service,
        match_id,
        state,
        "manual_adjustment",
        player_id="player_1",
        payload={
            "reason": "rule test setup",
            "requires_confirmation": True,
            "confirmed_by": "tester",
            "adjustments": [
                {
                    "adjustment_type": "move_card",
                    "target_player_id": "player_1",
                    "target_card_instance_id": member_id,
                    "to_zone": "hand",
                }
            ],
        },
    )
    cost = state.cards[member_id].card.cost or 0
    energy_ids = state.players["player_1"].energy_area[:cost]
    state = _apply(
        service,
        match_id,
        state,
        "play_member",
        player_id="player_1",
        payload={
            "card_instance_id": member_id,
            "slot": "center",
            "energy_instance_ids": energy_ids,
        },
    )
    assert state.players["player_1"].member_area["center"] == member_id
    assert all(state.cards[item].orientation == "wait" for item in energy_ids)


def test_stale_or_illegal_action_does_not_persist(tmp_path):
    service, match_id = _create_match(tmp_path, seed=5)
    before = service.repository.get_state(match_id)
    with pytest.raises(StaleRevisionError):
        service.apply(
            match_id,
            ActionRequest(
                action_type="choose_first_player",
                expected_revision=99,
                payload={"first_player_id": "player_1"},
            ),
        )
    with pytest.raises(IllegalActionError):
        service.apply(
            match_id,
            ActionRequest(
                action_type="advance_phase",
                expected_revision=0,
            ),
        )
    after = service.repository.get_state(match_id)
    assert after == before
    with closing(sqlite3.connect(service.repository.path)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM match_actions").fetchone()[0] == 0


def test_replay_reconstructs_current_state(tmp_path):
    service, match_id = _create_match(tmp_path, seed=77)
    state = service.repository.get_state(match_id)
    state = _apply(
        service,
        match_id,
        state,
        "choose_first_player",
        payload={"first_player_id": "player_2"},
    )
    state = _apply(
        service,
        match_id,
        state,
        "submit_mulligan",
        player_id="player_2",
        payload={"card_instance_ids": []},
    )
    state = _apply(
        service,
        match_id,
        state,
        "submit_mulligan",
        player_id="player_1",
        payload={"card_instance_ids": []},
    )

    replay = service.repository.replay(match_id)

    assert replay["final_state"] == state.model_dump()
    assert len(replay["actions"]) == 3


def _create_match(tmp_path: Path, *, seed: int) -> tuple[MatchService, str]:
    card_database = tmp_path / "cards.sqlite3"
    import_normalized_cards(card_database, SAMPLE_CARDS, NORMALIZATION)
    service = MatchService(card_database, tmp_path / "matches.sqlite3")
    result = service.create_match(
        first_name="先攻候補",
        first_deck=load_deck(SAMPLE_DECK),
        second_name="後攻候補",
        second_deck=load_deck(SAMPLE_DECK),
        seed=seed,
        match_id=f"match-{seed}",
    )
    return service, result.state.match_id


def _reach_first_main(service: MatchService, match_id: str):
    state = service.repository.get_state(match_id)
    state = _apply(
        service,
        match_id,
        state,
        "choose_first_player",
        payload={"first_player_id": "player_1"},
    )
    for player_id in ("player_1", "player_2"):
        state = _apply(
            service,
            match_id,
            state,
            "submit_mulligan",
            player_id=player_id,
            payload={"card_instance_ids": []},
        )
    for _ in range(3):
        state = _apply(
            service,
            match_id,
            state,
            "advance_phase",
            player_id="player_1",
        )
    return state


def _apply(
    service: MatchService,
    match_id: str,
    state,
    action_type: str,
    *,
    player_id: str | None = None,
    payload: dict | None = None,
):
    return service.apply(
        match_id,
        ActionRequest(
            action_type=action_type,
            expected_revision=state.revision,
            player_id=player_id,
            payload=payload or {},
        ),
    ).state
