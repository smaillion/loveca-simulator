from __future__ import annotations

from loveca.simulation.ai import SimpleAIController
from loveca.simulation.models import (
    CardDefinition,
    CardInstance,
    LegalAction,
    MatchState,
    PendingChoice,
    PlayerState,
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
