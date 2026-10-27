from __future__ import annotations

import json
from pathlib import Path

import pytest

from loveca.simulation.models import (
    CardDefinition,
    CardInstance,
    LegalAction,
    MatchState,
    PendingChoice,
    PlayerState,
)
from tools.ai_sandbox import semantic_playtest
from tools.ai_sandbox.blackbox_playtest import build_decks, summarize_deck
from tools.ai_sandbox.semantic_playtest import (
    MockSemanticAgentProvider,
    RuleContext,
    SemanticAgentError,
    SemanticDecision,
    build_api_play_context,
    build_agent_context,
    load_rule_context,
    parse_agent_decision,
    run_semantic_matches,
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


def test_agent_context_contains_source_text_and_manual_schema():
    state = _state()
    state.players["player_1"].member_area["center"] = "p1-card-1"
    context = build_agent_context(state, [_manual_action()])

    assert context["manual_invocation"]["effect_id"] == "TEST-001:1"
    assert context["source_card"]["raw_effect_text_ja"] == "【登場】手動で処理するテスト能力。"
    assert "manual_adjustment_schema_reference" in context
    assert context["players"]["player_1"]["hand"] == []


def test_rule_context_from_text_file_is_loaded(tmp_path):
    rules = tmp_path / "rules.txt"
    rules.write_text("先攻\nメインフェイズ\nライブ判定\n" * 5, encoding="utf-8")

    context = load_rule_context(rules, max_chars=24)

    assert context.loaded is True
    assert context.extractor == "text"
    assert context.char_count <= 24
    assert "先攻" in context.excerpts[0]


def test_api_play_context_contains_rule_context_and_private_view():
    state = _state()
    state.players["player_1"].hand = ["p1-card-1"]
    legal = [
        LegalAction(
            action_type="advance_phase",
            player_id="player_1",
            label_zh="推进",
            label_ja="進行",
            options={},
        )
    ]
    rule_context = RuleContext(
        source_path="rules.txt",
        loaded=True,
        extractor="text",
        char_count=12,
        excerpts=["ルール抜粋"],
    )

    context = build_api_play_context(state, legal, rule_context=rule_context)

    assert context["mode"] == "api_play"
    assert context["you_are_player_id"] == "player_1"
    assert context["rule_context"]["loaded"] is True
    assert context["players"]["player_1"]["hand"][0]["instance_id"] == "p1-card-1"
    assert context["players"]["player_2"]["hand"] == {"count": 0}


def test_validate_api_play_decision_rejects_wrong_player():
    legal = [
        LegalAction(
            action_type="advance_phase",
            player_id="player_1",
            label_zh="推进",
            label_ja="進行",
            options={},
        )
    ]

    with pytest.raises(ValueError, match="player_id"):
        validate_api_play_decision(
            SemanticDecision(
                decision="submit_action",
                action_type="advance_phase",
                player_id="player_2",
                payload={},
            ),
            legal,
        )


def test_semantic_cli_real_provider_guard_runs_before_database_access(monkeypatch, tmp_path):
    monkeypatch.setattr("sys.argv", [
        "semantic_playtest", "--agent-provider", "mock", "--require-real-provider",
        "--database", str(tmp_path / "missing.sqlite3"),
        "--output", str(tmp_path / "not-created"),
    ])
    with pytest.raises(SemanticAgentError, match="requires a real semantic provider"):
        semantic_playtest.main()
    assert not (tmp_path / "not-created").exists()


@pytest.mark.parametrize("sample_limit", [0, 2])
def test_semantic_cli_forwards_bounded_context_capture(monkeypatch, tmp_path, sample_limit):
    monkeypatch.setattr("sys.argv", [
        "semantic_playtest", "--agent-provider", "mock", "--two-agent",
        "--api-context-samples", str(sample_limit), "--output", str(tmp_path),
    ])
    monkeypatch.setattr(semantic_playtest, "load_rule_context", lambda *args, **kwargs: None)
    monkeypatch.setattr(semantic_playtest, "build_decks", lambda *args: [])
    captured = {}

    def run(*args, **kwargs):
        captured.update(kwargs)
        return [], [], []

    monkeypatch.setattr(semantic_playtest, "run_semantic_matches", run)
    monkeypatch.setattr(semantic_playtest, "write_semantic_outputs", lambda *args, **kwargs: None)
    assert semantic_playtest.main() == 0
    assert captured["play_policy"] == "api"
    assert captured["api_context_sample_limit"] == sample_limit


@pytest.mark.parametrize("builder", [build_api_play_context, build_agent_context])
def test_agent_context_hides_opponent_face_down_cards_without_mutating_state(builder):
    state = _state()
    state.cards["hidden-live"] = CardInstance(
        instance_id="hidden-live", owner_id="player_2", face_up=False,
        card=CardDefinition(
            card_code="SECRET-CARD", card_id="SECRET-PRINTING", name_ja="秘密のカード",
            card_type="live", raw_effect_text_ja="秘密の効果", score=8,
        ),
    )
    state.players["player_2"].live_area = ["hidden-live"]
    state.cards["p1-card-1"].face_up = False
    state.players["player_1"].live_area = ["p1-card-1"]
    before = state.model_dump(mode="json")
    context = builder(state, [_manual_action()])
    encoded = json.dumps(context, ensure_ascii=False)
    assert "SECRET-CARD" not in encoded
    assert "SECRET-PRINTING" not in encoded
    assert "秘密" not in encoded
    assert context["players"]["player_1"]["live_area"][0]["card_code"] == "TEST-001"
    assert context["players"]["player_2"]["live_area"][0]["hidden"] is True
    assert state.model_dump(mode="json") == before

    changed = state.model_copy(deep=True)
    changed.cards["hidden-live"].card = CardDefinition(
        card_code="OTHER-SECRET", card_id="OTHER-PRINTING", name_ja="別の秘密",
        card_type="member", cost=20,
    )
    assert builder(changed, [_manual_action()]) == context


@pytest.mark.parametrize("builder", [build_api_play_context, build_agent_context])
def test_agent_context_reveals_only_public_opponent_cards(builder):
    state = _state()
    state.cards["public-card"] = CardInstance(
        instance_id="public-card", owner_id="player_2", face_up=True,
        card=state.cards["p1-card-1"].card.model_copy(deep=True),
    )
    state.players["player_2"].live_area = ["public-card"]
    state.cards["waiting-card"] = state.cards["public-card"].model_copy(
        update={"instance_id": "waiting-card"}, deep=True,
    )
    state.players["player_2"].waiting_room = ["waiting-card"]
    context = builder(state, [_manual_action()])
    assert context["players"]["player_2"]["live_area"][0]["card_code"] == "TEST-001"
    assert context["players"]["player_2"]["waiting_room"][0]["card_code"] == "TEST-001"


def test_api_context_does_not_expose_another_players_private_inspection():
    state = _state()
    state.pending_choice = PendingChoice(
        choice_type="effect_inspection_selection", player_id="player_2",
        message_ja="秘密の公開前カード", message_zh="私有查看",
        options={"inspected_cards": [{"card_code": "SECRET-INSPECTED"}]},
    )
    context = build_api_play_context(state, [_manual_action()])
    assert context["state"]["pending_choice"] == {
        "choice_type": "effect_inspection_selection", "player_id": "player_2",
    }
    assert "SECRET-INSPECTED" not in json.dumps(context)


def test_manual_context_does_not_reuse_another_players_private_inspection():
    state = _state()
    state.pending_choice = PendingChoice(
        choice_type="manual_card_selection", player_id="player_2",
        message_ja="SECRET-INSPECTION", message_zh="私有查看",
        options={"source_effect_id": "SECRET-EFFECT"},
    )
    context = build_agent_context(state, [LegalAction(
        action_type="manual_adjustment", player_id="player_1",
        label_ja="手動", label_zh="手动", options={},
    )])
    assert context["manual_invocation"] is None
    assert "SECRET" not in json.dumps(context)


def test_semantic_cli_rejects_negative_sample_limit(monkeypatch, tmp_path):
    monkeypatch.setattr("sys.argv", [
        "semantic_playtest", "--api-context-samples", "-1", "--output", str(tmp_path / "output"),
    ])
    with pytest.raises(SystemExit) as error:
        semantic_playtest.main()
    assert error.value.code == 2
    assert not (tmp_path / "output").exists()


@pytest.mark.sandbox
def test_api_play_context_capture_limit_is_global_across_matches():
    if not CARD_DATABASE.exists():
        pytest.skip("local full card database is required for semantic sandbox flow")
    decks = build_decks(CARD_DATABASE, 2)
    summaries, _, attempts = run_semantic_matches(
        CARD_DATABASE, decks, provider=MockSemanticAgentProvider(),
        match_count=2, max_actions=3, manual_fallback="block", play_policy="api",
        api_context_sample_limit=2,
    )
    assert len(summaries) == 2
    assert len(attempts) == 6
    assert sum(attempt.context_sample is not None for attempt in attempts) == 2
    assert all(attempt.context_sample is None for attempt in attempts if attempt.match_index == 2)


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
    assert summary["api_play_context_sample_count"] == 0
    assert "未调用真实模型" in (tmp_path / "semantic-report.md").read_text(encoding="utf-8")


@pytest.mark.sandbox
def test_semantic_two_agent_mock_mode_writes_rule_context_report(tmp_path):
    if not CARD_DATABASE.exists():
        pytest.skip("local full card database is required for semantic sandbox flow")

    rules = tmp_path / "rules.txt"
    rules.write_text("先攻 メインフェイズ ライブ判定", encoding="utf-8")
    rule_context = load_rule_context(rules, max_chars=100)
    decks = build_decks(CARD_DATABASE, 2)
    provider = MockSemanticAgentProvider()
    match_summaries, attempts, api_play_attempts = run_semantic_matches(
        CARD_DATABASE,
        decks,
        provider=provider,
        match_count=1,
        max_actions=3,
        manual_fallback="skip",
        play_policy="api",
        play_fallback="deterministic",
        rule_context=rule_context,
    )
    deck_summaries = [summarize_deck(CARD_DATABASE, deck) for deck in decks]
    write_semantic_outputs(
        tmp_path,
        provider=provider,
        play_policy="api",
        rule_context=rule_context,
        deck_summaries=deck_summaries,
        match_summaries=match_summaries,
        attempts=attempts,
        api_play_attempts=api_play_attempts,
    )

    assert len(match_summaries) == 1
    assert api_play_attempts
    summary = json.loads((tmp_path / "semantic-summary.json").read_text(encoding="utf-8"))
    report = (tmp_path / "semantic-report.md").read_text(encoding="utf-8")
    assert summary["play_policy"] == "api"
    assert summary["rule_context"]["loaded"] is True
    assert "Rule context" in report
