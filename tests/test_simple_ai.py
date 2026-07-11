from __future__ import annotations

from loveca.simulation.ai import SimpleAIController
from loveca.simulation.models import (
    ActionResult,
    CardDefinition,
    CardInstance,
    LegalAction,
    MatchState,
    PendingChoice,
    PlayerState,
)
from loveca.simulation.runtime import MatchRepository
from loveca.simulation.service import MatchService
from tools.ai_sandbox.simple_ai_acceptance import (
    SimpleAIMatchReport,
    _choose_acceptance_driver_action,
    acceptance_passed,
)


def test_simple_ai_returns_a_legal_deterministic_action_without_mutating_state():
    own_member = "player_1-member"
    own_live = "player_1-live"
    hidden_opponent = "player_2-hidden"
    state = MatchState(
        match_id="simple-ai-test",
        seed=1,
        revision=7,
        phase="setup_mulligan_first",
        active_player_id="player_1",
        players={
            "player_1": PlayerState(
                player_id="player_1",
                name="AI",
                hand=[own_member, own_live],
            ),
            "player_2": PlayerState(
                player_id="player_2",
                name="Opponent",
                hand=[hidden_opponent],
            ),
        },
        cards={
            own_member: CardInstance(
                instance_id=own_member,
                owner_id="player_1",
                card=CardDefinition(
                    card_code="M001",
                    card_id="M001",
                    name_ja="Member",
                    card_type="member",
                    basic_hearts={"heart01": 1},
                ),
            ),
            own_live: CardInstance(
                instance_id=own_live,
                owner_id="player_1",
                card=CardDefinition(
                    card_code="L001",
                    card_id="L001",
                    name_ja="Live",
                    card_type="live",
                    required_hearts={"heart01": 1},
                    score=1,
                ),
            ),
            hidden_opponent: CardInstance(
                instance_id=hidden_opponent,
                owner_id="player_2",
                card=CardDefinition(
                    card_code="M999",
                    card_id="M999",
                    name_ja="Hidden",
                    card_type="member",
                ),
            ),
        },
        controllers={"player_1": "simple_ai", "player_2": "human"},
        pending_choice=PendingChoice(
            choice_type="mulligan",
            player_id="player_1",
            message_ja="引き直し",
            message_zh="调度",
            options={"card_instance_ids": [own_member, own_live]},
        ),
    )
    legal = [
        LegalAction(
            action_type="submit_mulligan",
            player_id="player_1",
            label_zh="提交调度选择",
            label_ja="引き直しを確定",
            options={"card_instance_ids": [own_member, own_live]},
        )
    ]

    first = SimpleAIController().choose_action(
        state,
        legal,
        controlled_player_ids={"player_1"},
    )
    second = SimpleAIController().choose_action(
        state,
        legal,
        controlled_player_ids={"player_1"},
    )

    assert first == second
    assert first is not None
    assert not isinstance(first, type(None))
    assert first.action.action_type in {action.action_type for action in legal}
    assert first.action.expected_revision == 7
    assert hidden_opponent not in str(first.action.payload)
    assert state.revision == 7


def test_simple_ai_acceptance_driver_can_press_player_neutral_system_actions():
    state = MatchState(
        match_id="simple-ai-system-action",
        seed=1,
        revision=12,
        phase="live_judgment",
        active_player_id="player_1",
        players={
            "player_1": PlayerState(player_id="player_1", name="Human"),
            "player_2": PlayerState(player_id="player_2", name="Computer"),
        },
        cards={},
        controllers={"player_1": "human", "player_2": "simple_ai"},
    )
    result = ActionResult(
        state=state,
        events=[],
        legal_actions=[
            LegalAction(
                action_type="advance_phase",
                player_id=None,
                label_zh="执行 Live 胜负判定",
                label_ja="ライブ勝敗判定を実行",
                options={},
            )
        ],
    )

    action = _choose_acceptance_driver_action(result)

    assert action is not None
    assert action.action_type == "advance_phase"
    assert action.player_id is None
    assert action.expected_revision == 12
    assert action.payload["acceptance_driver"]["reason"] == "advance_phase"


def test_simple_ai_only_uses_player_neutral_actions_when_continuing_ai_turn():
    state = MatchState(
        match_id="simple-ai-neutral-action",
        seed=1,
        revision=3,
        phase="live_judgment",
        active_player_id=None,
        players={
            "player_1": PlayerState(player_id="player_1", name="Human"),
            "player_2": PlayerState(player_id="player_2", name="Computer"),
        },
        cards={},
        controllers={"player_1": "human", "player_2": "simple_ai"},
    )
    legal = [
        LegalAction(
            action_type="advance_phase",
            player_id=None,
            label_zh="执行 Live 胜负判定",
            label_ja="ライブ勝敗判定を実行",
            options={},
        )
    ]
    controller = SimpleAIController()

    assert controller.choose_action(
        state,
        legal,
        controlled_player_ids={"player_2"},
    ) is None
    decision = controller.choose_action(
        state,
        legal,
        controlled_player_ids={"player_2"},
        allow_player_neutral_actions=True,
    )

    assert decision is not None
    assert not isinstance(decision, type(None))
    assert decision.action.action_type == "advance_phase"
    assert decision.action.player_id is None


def test_simple_ai_acceptance_gate_requires_replay_serialization_success():
    base = dict(
        match_index=1,
        mode="ai-vs-ai",
        first_deck="A",
        second_deck="B",
        status="completed",
        final_phase="complete",
        turn_number=3,
        revision=20,
        driven_human_actions=0,
        ai_actions=20,
        success_live_counts={"player_1": 3, "player_2": 1},
    )

    assert acceptance_passed(
        [SimpleAIMatchReport(**base, replay_serialization_ok=True)]
    )
    assert not acceptance_passed(
        [
            SimpleAIMatchReport(
                **base,
                replay_serialization_ok=False,
                replay_error="replayed state does not match",
            )
        ]
    )


def test_ai_action_cap_blocker_is_persisted_and_exported_in_replay(tmp_path):
    runtime_path = tmp_path / "matches.sqlite3"
    repository = MatchRepository(runtime_path)
    state = MatchState(
        match_id="simple-ai-action-cap",
        seed=1,
        revision=0,
        phase="second_active",
        active_player_id="player_2",
        players={
            "player_1": PlayerState(player_id="player_1", name="Human"),
            "player_2": PlayerState(player_id="player_2", name="Computer"),
        },
        cards={},
        controllers={"player_1": "human", "player_2": "simple_ai"},
    )
    repository.create_match(state, card_database_path=tmp_path / "cards.sqlite3")
    service = object.__new__(MatchService)
    service.repository = repository
    initial_result = ActionResult(
        state=state,
        events=[],
        legal_actions=[
            LegalAction(
                action_type="advance_phase",
                player_id="player_2",
                label_zh="推进阶段",
                label_ja="フェイズを進める",
                options={},
            )
        ],
    )

    result = service.advance_ai(
        state.match_id,
        initial_result,
        max_ai_actions=0,
    )

    assert result.state == state
    assert result.events[-1].event_type == "ai_blocked"
    assert result.events[-1].data["reason"] == "ai_action_cap_reached"
    assert result.events[-1].data["state_revision"] == 0
    persisted = repository.list_events(state.match_id)
    assert persisted[-1] == result.events[-1]
    replay = repository.replay(state.match_id)
    assert replay["events"][-1]["event_type"] == "ai_blocked"
    assert replay["events"][-1]["data"]["reason"] == "ai_action_cap_reached"
