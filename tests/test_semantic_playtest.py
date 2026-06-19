from __future__ import annotations

import json
from pathlib import Path

import pytest

from loveca.simulation.models import (
    CardDefinition,
    CardInstance,
    LegalAction,
    MatchState,
    PlayerState,
)
from tools.ai_sandbox.blackbox_playtest import build_decks, summarize_deck
from tools.ai_sandbox.semantic_playtest import (
    MockSemanticAgentProvider,
    SemanticAgentError,
    SemanticDecision,
    build_agent_context,
    build_api_play_context,
    parse_agent_decision,
    run_semantic_matches,
    try_api_play_action,
    validate_api_play_decision,
    validate_agent_decision,
    validate_manual_adjustment_payload,
    write_semantic_outputs,
)

PROJECT_ROOT = Path(__file__).parents[1]
CARD_DATABASE = PROJECT_ROOT / "data" / "loveca.sqlite3"


def _state() -> MatchState:
    card = CardDefinition(
        card_code="TEST-001",
        card_id="TEST-001-R",
        name_ja="テストメンバー",
        card_type="member",
        raw_effect_text_ja="【登場】手動で処理するテスト能力。",
    )
    instance = CardInstance(
        instance_id="p1-card-1",
        owner_id="player_1",
        card=card,
    )
    return MatchState(
        match_id="semantic-test",
        seed=1,
        phase="first_main",
        active_player_id="player_1",
        players={
            "player_1": PlayerState(
                player_id="player_1",
                name="P1",
                hand=[],
            ),
            "player_2": PlayerState(
                player_id="player_2",
                name="P2",
                hand=[],
            ),
        },
        cards={"p1-card-1": instance},
    )


def _manual_action() -> LegalAction:
    return LegalAction(
        action_type="manual_adjustment",
        player_id="player_1",
        label_zh="人工处理技能",
        label_ja="能力を手動解決",
        options={
            "source_invocations": [
                {
                    "invocation_id": "inv-1",
                    "effect_id": "TEST-001:1",
                    "source_card_instance_id": "p1-card-1",
                    "label_ja": "【登場】手動で処理するテスト能力。",
                    "trigger": "member_played",
                    "timing": "on_play",
                    "simulation_support": "manual_resolution",
                }
            ]
        },
    )


def test_mock_provider_round_trip_with_scripted_decision():
    provider = MockSemanticAgentProvider(
        [
            {
                "decision": "cannot_resolve",
                "reason_ja_or_zh": "現行スキーマでは表現できない",
                "confidence": "medium",
                "schema_gap": "needs custom choice",
            }
        ]
    )

    decision = provider.decide({"manual_invocation": {"effect_id": "TEST-001:1"}})

    assert decision.decision == "cannot_resolve"
    assert decision.confidence == "medium"
    assert decision.schema_gap == "needs custom choice"


def test_parse_agent_decision_rejects_invalid_json():
    with pytest.raises(SemanticAgentError):
        parse_agent_decision("{not json")


def test_validate_manual_adjustment_requires_source_identity():
    invocation = {
        "invocation_id": "inv-1",
        "effect_id": "TEST-001:1",
        "source_card_instance_id": "p1-card-1",
    }

    with pytest.raises(ValueError, match="source_effect_id"):
        validate_manual_adjustment_payload(
            {
                "source_invocation_id": "inv-1",
                "source_effect_id": "wrong",
                "source_card_instance_id": "p1-card-1",
                "adjustments": [
                    {
                        "adjustment_type": "set_flag",
                        "target_player_id": "player_1",
                        "flag": "test",
                        "duration": "turn",
                    }
                ],
            },
            invocation,
        )


def test_agent_cannot_submit_unknown_action():
    state = _state()
    invocation = _manual_action().options["source_invocations"][0]

    with pytest.raises(ValueError, match="not legal"):
        validate_agent_decision(
            SemanticDecision(
                decision="submit_action",
                action_type="move_card",
                player_id="player_1",
                payload={},
            ),
            state,
            [_manual_action()],
            invocation,
        )


def test_api_play_rejects_manual_adjustment_actions():
    with pytest.raises(ValueError, match="manual_adjustment"):
        validate_api_play_decision(
            SemanticDecision(
                decision="submit_action",
                action_type="manual_adjustment",
                player_id="player_1",
                payload={},
            ),
            [_manual_action()],
        )


def test_api_play_context_contains_ordinary_legal_actions():
    state = _state()
    action = LegalAction(
        action_type="advance_phase",
        player_id="player_1",
        label_zh="推进",
        label_ja="進行",
        options={"phase": "first_energy"},
    )

    context = build_api_play_context(state, [action])

    assert context["mode"] == "api_play"
    assert context["state"]["phase"] == "first_main"
    assert context["players"]["player_1"]["hand"] == []
    assert context["legal_actions"][0]["action_type"] == "advance_phase"
    assert context["legal_action_summary"]["action_type_counts"] == {"advance_phase": 1}
    assert context["strategy"]["recommended_action_order"] == ["advance_phase"]
    assert context["strategy"]["progress"]["acting_player_hand_count"] == 0


def test_api_play_scripted_provider_selects_ordinary_action():
    state = _state()
    action = LegalAction(
        action_type="advance_phase",
        player_id="player_1",
        label_zh="推进",
        label_ja="進行",
        options={"phase": "first_energy"},
    )
    provider = MockSemanticAgentProvider(
        [
            {
                "decision": "submit_action",
                "reason_ja_or_zh": "メインを終了して進行する",
                "action_type": "advance_phase",
                "player_id": "player_1",
                "payload": {},
                "confidence": "high",
            }
        ]
    )

    result = try_api_play_action(
        state,
        [action],
        provider=provider,
        match_index=1,
        action_index=1,
    )

    assert result.decision == ("advance_phase", "player_1", {})
    assert result.attempt.status == "api_play_selected"
    assert result.attempt.confidence == "high"


def test_agent_context_contains_source_text_and_manual_schema():
    state = _state()
    context = build_agent_context(state, [_manual_action()])

    assert context["manual_invocation"]["effect_id"] == "TEST-001:1"
    assert context["source_card"]["raw_effect_text_ja"] == "【登場】手動で処理するテスト能力。"
    assert "manual_adjustment_schema_reference" in context
    assert context["players"]["player_1"]["hand"] == []


@pytest.mark.sandbox
def test_semantic_sandbox_mock_mode_writes_reports(tmp_path):
    if not CARD_DATABASE.exists():
        pytest.skip("local full card database is required for semantic sandbox flow")

    decks = build_decks(CARD_DATABASE, 2)
    provider = MockSemanticAgentProvider()
    match_summaries, attempts, api_play_attempts = run_semantic_matches(
        CARD_DATABASE,
        decks,
        provider=provider,
        match_count=1,
        max_actions=5,
        manual_fallback="skip",
    )
    deck_summaries = [summarize_deck(CARD_DATABASE, deck) for deck in decks]
    write_semantic_outputs(
        tmp_path,
        provider=provider,
        deck_summaries=deck_summaries,
        match_summaries=match_summaries,
        attempts=attempts,
        api_play_attempts=api_play_attempts,
    )

    assert len(match_summaries) == 1
    assert (tmp_path / "semantic-report.md").exists()
    summary = json.loads((tmp_path / "semantic-summary.json").read_text(encoding="utf-8"))
    assert summary["schema_version"] == "semantic_sandbox_v0.1"
    assert summary["provider"] == "mock"
    assert "api_play_attempts" in summary
