from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import pytest

from tools.ai_sandbox.blackbox_playtest import (
    build_decks,
    run_matches,
    summarize_deck,
    write_outputs,
)

PROJECT_ROOT = Path(__file__).parents[1]
CARD_DATABASE = PROJECT_ROOT / "data" / "loveca.sqlite3"


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
