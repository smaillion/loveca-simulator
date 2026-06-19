from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import pytest

from tools.ai_sandbox.blackbox_playtest import (
    _choose_live_cards_for_progress,
    build_decks,
    run_matches,
    summarize_deck,
    write_outputs,
)
from loveca.simulation.models import CardDefinition, CardInstance, MatchState, PlayerState

PROJECT_ROOT = Path(__file__).parents[1]
CARD_DATABASE = PROJECT_ROOT / "data" / "loveca.sqlite3"


def _live_strategy_state(turn_number: int) -> MatchState:
    member_card = CardDefinition(
        card_code="M-001",
        card_id="M-001-R",
        name_ja="テストメンバー",
        card_type="member",
        basic_hearts={"heart01": 3},
        blade=0,
    )
    live_cards = [
        CardDefinition(
            card_code=f"L-00{index}",
            card_id=f"L-00{index}-R",
            name_ja=f"テストライブ{index}",
            card_type="live",
            required_hearts={"heart01": 1},
            score=index,
        )
        for index in range(1, 4)
    ]
    cards = {
        "member-1": CardInstance(
            instance_id="member-1",
            owner_id="player_1",
            card=member_card,
        ),
        **{
            f"live-{index}": CardInstance(
                instance_id=f"live-{index}",
                owner_id="player_1",
                card=live_card,
            )
            for index, live_card in enumerate(live_cards, start=1)
        },
    }
    return MatchState(
        match_id="live-strategy",
        seed=1,
        phase="live_set_first",
        active_player_id="player_1",
        first_player_id="player_1",
        second_player_id="player_2",
        turn_number=turn_number,
        cards=cards,
        players={
            "player_1": PlayerState(
                player_id="player_1",
                name="P1",
                hand=["live-1", "live-2", "live-3"],
                member_area={"left": None, "center": "member-1", "right": None},
            ),
            "player_2": PlayerState(player_id="player_2", name="P2"),
        },
    )


def test_live_selection_pushes_three_lives_from_midgame():
    early = _choose_live_cards_for_progress(_live_strategy_state(turn_number=1), "player_1")
    midgame = _choose_live_cards_for_progress(_live_strategy_state(turn_number=5), "player_1")

    assert len(early) == 1
    assert len(midgame) == 3


@pytest.mark.sandbox
def test_ai_sandbox_generates_20_decks_and_runs_20_black_box_matches(tmp_path):
    if not CARD_DATABASE.exists():
        pytest.skip("local full card database is required for AI sandbox flow")

    decks = build_decks(CARD_DATABASE, 20)
    assert len(decks) == 20

    deck_summaries = [summarize_deck(CARD_DATABASE, deck) for deck in decks]
    assert all(item.members == 48 for item in deck_summaries)
    assert all(item.lives == 12 for item in deck_summaries)
    assert all(item.energy == 12 for item in deck_summaries)
    assert any(
        item.effect_summary.get("prompt_then_resolve", 0)
        + item.effect_summary.get("auto_resolve", 0)
        > 0
        for item in deck_summaries
    )

    match_summaries = run_matches(
        CARD_DATABASE,
        decks,
        match_count=20,
        max_actions=220,
        manual_policy="block",
    )
    assert len(match_summaries) == 20
    assert all(item.status in {"completed", "blocked"} for item in match_summaries)
    assert all(item.action_count > 0 for item in match_summaries)
    assert all(item.status == "completed" or item.blocker for item in match_summaries)

    output = tmp_path / "ai_sandbox"
    write_outputs(output, decks, deck_summaries, match_summaries)
    assert (output / "sandbox-report.md").exists()
    assert (output / "sandbox-summary.json").exists()
    assert len(list((output / "decks").glob("Sandbox Deck *.json"))) == 20

    # Keep blocker distribution visible in pytest failure output if the harness
    # regresses from "auditable blocker" to an unclassified stop.
    unexpected = [
        asdict(item)
        for item in match_summaries
        if item.status == "blocked" and not item.blocker
    ]
    assert unexpected == []
