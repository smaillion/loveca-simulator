from __future__ import annotations

from loveca.simulation.ai import (
    SimpleAIController,
    SimpleAIPolicy,
    _invocation_choices_are_currently_satisfiable,
    _select_cards_satisfying_condition,
)
from loveca.simulation.effects import EffectChoice, EffectDefinition, EffectOperation
from loveca.simulation.engine import generate_legal_actions
from loveca.simulation.models import (
    ActionResult,
    CardDefinition,
    CardInstance,
    EffectInvocation,
    LegalAction,
    ManualModifier,
    MatchState,
    PendingChoice,
    PlayerState,
)
from loveca.simulation.rule_evaluation import (
    build_ai_observation,
    build_rule_evaluation_snapshot,
)
from loveca.simulation.runtime import MatchRepository
from loveca.simulation.service import (
    MatchService,
    _controller_policy_version,
    _new_match_controller_policy_versions,
)
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


def test_simple_ai_v1_1_mulligan_preserves_two_lives_with_a_playable_member_base():
    card_ids = ["member-1", "member-2", "live-1", "live-2"]
    cards = {
        instance_id: CardInstance(
            instance_id=instance_id,
            owner_id="player_1",
            card=CardDefinition(
                card_code=instance_id,
                card_id=instance_id,
                name_ja=instance_id,
                card_type="live" if instance_id.startswith("live") else "member",
                cost=1 if instance_id.startswith("member") else None,
                score=1 if instance_id.startswith("live") else None,
                required_hearts={} if instance_id.startswith("live") else {},
            ),
        )
        for instance_id in card_ids
    }
    state = MatchState(
        match_id="v1-1-mulligan-live-balance",
        seed=1,
        phase="setup_mulligan_first",
        active_player_id="player_1",
        players={
            "player_1": PlayerState(player_id="player_1", name="AI", hand=card_ids),
            "player_2": PlayerState(player_id="player_2", name="Opponent"),
        },
        cards=cards,
        pending_choice=PendingChoice(
            choice_type="mulligan",
            player_id="player_1",
            message_ja="引き直し",
            message_zh="调度",
            options={"card_instance_ids": card_ids},
        ),
    )
    legal = [
        LegalAction(
            action_type="submit_mulligan",
            player_id="player_1",
            label_zh="提交调度选择",
            label_ja="引き直しを確定",
            options={"card_instance_ids": card_ids},
        )
    ]

    decision = SimpleAIController(
        SimpleAIPolicy(policy_version="simple_ai_v1_1")
    ).choose_action(state, legal, controlled_player_ids={"player_1"})

    mulligan_ids = set(decision.action.payload["card_instance_ids"])
    assert not (mulligan_ids & {"live-1", "live-2"})
    assert not (mulligan_ids & {"member-1", "member-2"})


def test_controller_policy_version_defaults_old_snapshots_to_v0():
    state = MatchState(
        match_id="policy-version-default",
        seed=1,
        players={
            "player_1": PlayerState(player_id="player_1", name="AI"),
            "player_2": PlayerState(player_id="player_2", name="Opponent"),
        },
        cards={},
        controllers={"player_1": "simple_ai", "player_2": "human"},
    )

    assert _controller_policy_version(state, {"player_1"}) == "simple_ai_v0"
    state.controller_policy_versions["player_1"] = "simple_ai_v1"
    assert _controller_policy_version(state, {"player_1"}) == "simple_ai_v1"
    state.controller_policy_versions["player_1"] = "simple_ai_v1_1"
    assert _controller_policy_version(state, {"player_1"}) == "simple_ai_v1_1"
    assert (
        MatchState.model_validate_json(state.model_dump_json())
        .controller_policy_versions["player_1"]
        == "simple_ai_v1_1"
    )
    assert _new_match_controller_policy_versions(
        {"player_1": "human", "player_2": "simple_ai"}
    ) == {"player_2": "simple_ai_v1_1"}


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


def test_ai_observation_never_contains_opponent_hidden_hand_identity():
    own = "own-member"
    hidden = "opponent-secret-card"
    state = MatchState(
        match_id="observation-redaction",
        seed=1,
        phase="first_main",
        active_player_id="player_1",
        players={
            "player_1": PlayerState(player_id="player_1", name="AI", hand=[own]),
            "player_2": PlayerState(
                player_id="player_2",
                name="Opponent",
                hand=[hidden],
            ),
        },
        cards={
            own: CardInstance(
                instance_id=own,
                owner_id="player_1",
                card=CardDefinition(
                    card_code="OWN",
                    card_id="OWN",
                    name_ja="Own",
                    card_type="member",
                ),
            ),
            hidden: CardInstance(
                instance_id=hidden,
                owner_id="player_2",
                card=CardDefinition(
                    card_code="SECRET",
                    card_id="SECRET",
                    name_ja="Secret",
                    card_type="live",
                ),
            ),
        },
    )
    legal = [
        LegalAction(
            action_type="end_main_phase",
            player_id="player_1",
            label_zh="结束",
            label_ja="終了",
        )
    ]

    observation = build_ai_observation(state, "player_1", legal)

    assert observation.players["player_2"].hand == ()
    assert observation.players["player_2"].hand_count == 1
    assert hidden not in observation.cards
    assert hidden not in repr(observation)

    changed = state.model_copy(deep=True)
    changed.cards[hidden].card = CardDefinition(
        card_code="DIFFERENT-SECRET",
        card_id="DIFFERENT-SECRET",
        name_ja="Different Secret",
        card_type="member",
        cost=99,
        basic_hearts={"heart06": 9},
        blade=9,
    )
    for policy_version in ("simple_ai_v1", "simple_ai_v1_1"):
        controller = SimpleAIController(SimpleAIPolicy(policy_version=policy_version))
        first = controller.choose_action(
            state,
            legal,
            controlled_player_ids={"player_1"},
        )
        second = controller.choose_action(
            changed,
            legal,
            controlled_player_ids={"player_1"},
        )

        assert first == second


def test_ai_observation_hides_opponent_face_down_live_set_identity() -> None:
    own_live = "own-live"
    hidden_live = "opponent-set-live"
    state = MatchState(
        match_id="observation-face-down-live-redaction",
        seed=2,
        phase="live_set_second",
        active_player_id="player_2",
        players={
            "player_1": PlayerState(
                player_id="player_1",
                name="AI",
                hand=[own_live],
            ),
            "player_2": PlayerState(
                player_id="player_2",
                name="Opponent",
                live_area=[hidden_live],
            ),
        },
        cards={
            own_live: CardInstance(
                instance_id=own_live,
                owner_id="player_1",
                card=CardDefinition(
                    card_code="OWN-LIVE",
                    card_id="OWN-LIVE",
                    name_ja="Own Live",
                    card_type="live",
                    score=1,
                ),
            ),
            hidden_live: CardInstance(
                instance_id=hidden_live,
                owner_id="player_2",
                face_up=False,
                card=CardDefinition(
                    card_code="SECRET-LIVE",
                    card_id="SECRET-LIVE",
                    name_ja="Secret Live",
                    card_type="live",
                    score=9,
                ),
            ),
        },
    )
    legal = [
        LegalAction(
            action_type="set_live_cards",
            player_id="player_1",
            label_zh="设置 Live",
            label_ja="ライブセット",
        )
    ]

    observation = build_ai_observation(state, "player_1", legal)

    assert observation.players["player_2"].live_area == ()
    assert observation.players["player_2"].live_area_count == 1
    assert hidden_live not in observation.cards
    assert hidden_live not in repr(observation)

    changed = state.model_copy(deep=True)
    changed.cards[hidden_live].card = CardDefinition(
        card_code="DIFFERENT-SECRET-LIVE",
        card_id="DIFFERENT-SECRET-LIVE",
        name_ja="Different Secret Live",
        card_type="live",
        score=1,
        required_hearts={"heart06": 9},
    )
    controller = SimpleAIController(
        SimpleAIPolicy(policy_version="simple_ai_v1_1")
    )
    first = controller.choose_action(
        state,
        legal,
        controlled_player_ids={"player_1"},
    )
    second = controller.choose_action(
        changed,
        legal,
        controlled_player_ids={"player_1"},
    )

    assert first == second


def test_simple_ai_v1_requires_positive_board_gain_for_baton_replacement():
    old_id = "old-member"
    new_id = "new-member"
    state = MatchState(
        match_id="baton-board-gain",
        seed=1,
        phase="first_main",
        active_player_id="player_1",
        players={
            "player_1": PlayerState(
                player_id="player_1",
                name="AI",
                hand=[new_id],
                member_area={"left": None, "center": old_id, "right": None},
            ),
            "player_2": PlayerState(player_id="player_2", name="Opponent"),
        },
        cards={
            old_id: CardInstance(
                instance_id=old_id,
                owner_id="player_1",
                card=CardDefinition(
                    card_code="OLD",
                    card_id="OLD",
                    name_ja="Old",
                    card_type="member",
                    cost=2,
                    blade=1,
                    basic_hearts={"heart01": 1},
                ),
            ),
            new_id: CardInstance(
                instance_id=new_id,
                owner_id="player_1",
                card=CardDefinition(
                    card_code="NEW",
                    card_id="NEW",
                    name_ja="New",
                    card_type="member",
                    cost=2,
                    blade=1,
                    basic_hearts={"heart01": 1},
                ),
            ),
        },
    )
    legal = [
        LegalAction(
            action_type="play_member",
            player_id="player_1",
            label_zh="登场",
            label_ja="登場",
            options={
                "active_energy_instance_ids": [],
                "placements": [
                    {
                        "card_instance_id": new_id,
                        "slot": "center",
                        "payment_cost": 0,
                        "use_baton_touch": True,
                        "replaced_card_instance_id": old_id,
                    }
                ],
            },
        ),
        LegalAction(
            action_type="end_main_phase",
            player_id="player_1",
            label_zh="结束",
            label_ja="終了",
        ),
    ]
    controller = SimpleAIController(SimpleAIPolicy(policy_version="simple_ai_v1"))

    equal_value = controller.choose_action(
        state,
        legal,
        controlled_player_ids={"player_1"},
    )
    assert equal_value.action.action_type == "end_main_phase"

    improved = state.model_copy(deep=True)
    improved.cards[new_id].card.basic_hearts = {"heart01": 2}
    positive_value = controller.choose_action(
        improved,
        legal,
        controlled_player_ids={"player_1"},
    )
    assert positive_value.action.action_type == "play_member"

    v1_1_positive_value = SimpleAIController(
        SimpleAIPolicy(policy_version="simple_ai_v1_1")
    ).choose_action(
        improved,
        legal,
        controlled_player_ids={"player_1"},
    )
    assert v1_1_positive_value.action.action_type == "play_member"


def test_simple_ai_v1_preserves_the_last_live_when_an_effect_discards_from_hand():
    source_id = "source"
    live_id = "last-live"
    member_id = "spare-member"
    effect = EffectDefinition(
        effect_id="DISCARD:1",
        card_code="DISCARD",
        text_revision_id=1,
        raw_text_hash="discard",
        effect_index=1,
        label_ja="手札を1枚控え室に置く。",
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        execution_mode="prompt_then_resolve",
        frequency_limit="none",
        is_optional=False,
        choice=EffectChoice(
            choice_type="card_from_zone",
            zone="hand",
            minimum=1,
            maximum=1,
        ),
        actions=[EffectOperation(action_type="discard_from_hand")],
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test",
    )
    state = MatchState(
        match_id="preserve-last-live",
        seed=1,
        phase="first_main",
        active_player_id="player_1",
        players={
            "player_1": PlayerState(
                player_id="player_1",
                name="AI",
                hand=[live_id, member_id],
                member_area={"left": source_id, "center": None, "right": None},
            ),
            "player_2": PlayerState(player_id="player_2", name="Opponent"),
        },
        cards={
            source_id: CardInstance(
                instance_id=source_id,
                owner_id="player_1",
                card=CardDefinition(
                    card_code="DISCARD",
                    card_id="DISCARD",
                    name_ja="Source",
                    card_type="member",
                    effect_ids=[effect.effect_id],
                ),
            ),
            live_id: CardInstance(
                instance_id=live_id,
                owner_id="player_1",
                card=CardDefinition(
                    card_code="LAST-LIVE",
                    card_id="LAST-LIVE",
                    name_ja="Last Live",
                    card_type="live",
                    score=1,
                    required_hearts={"heart06": 8},
                ),
            ),
            member_id: CardInstance(
                instance_id=member_id,
                owner_id="player_1",
                card=CardDefinition(
                    card_code="SPARE",
                    card_id="SPARE",
                    name_ja="Spare",
                    card_type="member",
                    cost=1,
                    basic_hearts={"heart01": 1},
                ),
            ),
        },
        effect_definitions={effect.effect_id: effect},
        pending_effects=[
            EffectInvocation(
                invocation_id="discard-invocation",
                effect_id=effect.effect_id,
                source_card_instance_id=source_id,
                player_id="player_1",
                trigger_event="member_played",
            )
        ],
    )
    legal = generate_legal_actions(state)

    decision = SimpleAIController(
        SimpleAIPolicy(policy_version="simple_ai_v1")
    ).choose_action(state, legal, controlled_player_ids={"player_1"})

    assert decision.action.action_type == "resolve_effect"
    assert decision.action.payload["selected_card_instance_ids"] == [member_id]


def test_simple_ai_v1_1_declines_optional_effect_that_discards_only_live():
    source_id = "source"
    live_id = "last-live"
    effect = EffectDefinition(
        effect_id="OPTIONAL-DISCARD:1",
        card_code="OPTIONAL-DISCARD",
        text_revision_id=1,
        raw_text_hash="optional-discard",
        effect_index=1,
        label_ja="手札を1枚控え室に置いてもよい：カードを1枚引く。",
        effect_type="triggered",
        timing="on_play",
        trigger="member_played",
        execution_mode="prompt_then_resolve",
        frequency_limit="none",
        is_optional=True,
        choice=EffectChoice(
            choice_type="card_from_zone",
            zone="hand",
            minimum=1,
            maximum=1,
        ),
        actions=[
            EffectOperation(action_type="discard_from_hand"),
            EffectOperation(action_type="draw_card", amount=1),
        ],
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test",
    )
    state = MatchState(
        match_id="v1-1-preserve-only-live",
        seed=1,
        phase="first_main",
        active_player_id="player_1",
        players={
            "player_1": PlayerState(
                player_id="player_1",
                name="AI",
                hand=[live_id],
                member_area={"left": source_id, "center": None, "right": None},
            ),
            "player_2": PlayerState(player_id="player_2", name="Opponent"),
        },
        cards={
            source_id: CardInstance(
                instance_id=source_id,
                owner_id="player_1",
                card=CardDefinition(
                    card_code="OPTIONAL-DISCARD",
                    card_id="OPTIONAL-DISCARD",
                    name_ja="Source",
                    card_type="member",
                    effect_ids=[effect.effect_id],
                ),
            ),
            live_id: CardInstance(
                instance_id=live_id,
                owner_id="player_1",
                card=CardDefinition(
                    card_code="ONLY-LIVE",
                    card_id="ONLY-LIVE",
                    name_ja="Only Live",
                    card_type="live",
                    score=1,
                    required_hearts={"heart01": 1},
                ),
            ),
        },
        effect_definitions={effect.effect_id: effect},
        pending_effects=[
            EffectInvocation(
                invocation_id="optional-discard",
                effect_id=effect.effect_id,
                source_card_instance_id=source_id,
                player_id="player_1",
                trigger_event="member_played",
            )
        ],
    )
    legal = generate_legal_actions(state)

    decision = SimpleAIController(
        SimpleAIPolicy(policy_version="simple_ai_v1_1")
    ).choose_action(state, legal, controlled_player_ids={"player_1"})

    assert decision.action.action_type == "resolve_effect"
    assert decision.action.payload == {
        "invocation_id": "optional-discard",
        "accepted": False,
        "ai_decision": decision.action.payload["ai_decision"],
    }
    assert decision.reason == "decline_effect_that_discards_last_live"


def test_simple_ai_v1_1_caps_choose_count_to_available_active_energy():
    source_id = "source"
    energy_id = "energy-1"
    effect = EffectDefinition(
        effect_id="PAY-UP-TO-TWO:1",
        card_code="PAY-UP-TO-TWO",
        text_revision_id=1,
        raw_text_hash="pay-up-to-two",
        effect_index=1,
        label_ja="エネルギーを2枚までウェイトにする。",
        effect_type="triggered",
        timing="live_start",
        trigger="live_started",
        execution_mode="prompt_then_resolve",
        frequency_limit="once_per_live",
        is_optional=True,
        cost=[
            EffectOperation(
                action_type="pay_energy",
                amount_source="selected_count",
            )
        ],
        choice=EffectChoice(
            choice_type="choose_count",
            minimum=1,
            maximum=2,
        ),
        actions=[
            EffectOperation(
                action_type="gain_blade",
                amount_source="selected_count",
            )
        ],
        duration="live",
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test",
    )
    state = MatchState(
        match_id="v1-1-energy-count",
        seed=1,
        phase="performance_first",
        active_player_id="player_1",
        players={
            "player_1": PlayerState(
                player_id="player_1",
                name="AI",
                member_area={"left": source_id, "center": None, "right": None},
                energy_area=[energy_id],
            ),
            "player_2": PlayerState(player_id="player_2", name="Opponent"),
        },
        cards={
            source_id: CardInstance(
                instance_id=source_id,
                owner_id="player_1",
                card=CardDefinition(
                    card_code="PAY-UP-TO-TWO",
                    card_id="PAY-UP-TO-TWO",
                    name_ja="Source",
                    card_type="member",
                    effect_ids=[effect.effect_id],
                ),
            ),
            energy_id: CardInstance(
                instance_id=energy_id,
                owner_id="player_1",
                card=CardDefinition(
                    card_code="ENERGY",
                    card_id="ENERGY",
                    name_ja="Energy",
                    card_type="energy",
                ),
                orientation="active",
            ),
        },
        effect_definitions={effect.effect_id: effect},
        pending_effects=[
            EffectInvocation(
                invocation_id="pay-up-to-two",
                effect_id=effect.effect_id,
                source_card_instance_id=source_id,
                player_id="player_1",
                trigger_event="live_started",
            )
        ],
    )

    decision = SimpleAIController(
        SimpleAIPolicy(policy_version="simple_ai_v1_1")
    ).choose_action(
        state,
        generate_legal_actions(state),
        controlled_player_ids={"player_1"},
    )

    assert decision.action.action_type == "resolve_effect"
    assert decision.action.payload["selected_count"] == 1
    assert decision.action.payload["energy_instance_ids"] == [energy_id]


def test_simple_ai_v1_1_sets_only_one_reachable_live_at_match_point():
    live_ids = ["live-1", "live-2"]
    success_ids = ["success-1", "success-2"]
    cards = {
        instance_id: CardInstance(
            instance_id=instance_id,
            owner_id="player_1",
            card=CardDefinition(
                card_code=instance_id,
                card_id=instance_id,
                name_ja=instance_id,
                card_type="live",
                score=1,
                required_hearts={},
            ),
        )
        for instance_id in [*live_ids, *success_ids]
    }
    state = MatchState(
        match_id="v1-1-match-point-live",
        seed=1,
        phase="live_set_first",
        active_player_id="player_1",
        players={
            "player_1": PlayerState(
                player_id="player_1",
                name="AI",
                hand=live_ids,
                success_live_area=success_ids,
            ),
            "player_2": PlayerState(player_id="player_2", name="Opponent"),
        },
        cards=cards,
    )
    legal = [
        LegalAction(
            action_type="set_live_cards",
            player_id="player_1",
            label_zh="设置 Live",
            label_ja="ライブカードをセット",
            options={"maximum": 3, "hand_instance_ids": live_ids},
        )
    ]

    decision = SimpleAIController(
        SimpleAIPolicy(policy_version="simple_ai_v1_1")
    ).choose_action(state, legal, controlled_player_ids={"player_1"})

    assert len(decision.action.payload["card_instance_ids"]) == 1
    assert decision.reason == "set_best_reachable_live_combo"


def test_simple_ai_v1_1_prioritizes_total_score_when_both_players_are_at_match_point():
    own_live_ids = ["live-1", "live-2"]
    own_success_ids = ["own-success-1", "own-success-2"]
    opponent_success_ids = ["opponent-success-1", "opponent-success-2"]
    cards = {
        instance_id: CardInstance(
            instance_id=instance_id,
            owner_id="player_2" if instance_id.startswith("opponent") else "player_1",
            card=CardDefinition(
                card_code=instance_id,
                card_id=instance_id,
                name_ja=instance_id,
                card_type="live",
                score=1,
                required_hearts={},
            ),
        )
        for instance_id in [*own_live_ids, *own_success_ids, *opponent_success_ids]
    }
    state = MatchState(
        match_id="v1-1-both-match-point-live",
        seed=1,
        phase="live_set_first",
        active_player_id="player_1",
        players={
            "player_1": PlayerState(
                player_id="player_1",
                name="AI",
                hand=own_live_ids,
                success_live_area=own_success_ids,
            ),
            "player_2": PlayerState(
                player_id="player_2",
                name="Opponent",
                success_live_area=opponent_success_ids,
            ),
        },
        cards=cards,
    )
    legal = [
        LegalAction(
            action_type="set_live_cards",
            player_id="player_1",
            label_zh="设置 Live",
            label_ja="ライブカードをセット",
            options={"maximum": 3, "hand_instance_ids": own_live_ids},
        )
    ]

    decision = SimpleAIController(
        SimpleAIPolicy(policy_version="simple_ai_v1_1")
    ).choose_action(state, legal, controlled_player_ids={"player_1"})

    assert decision.action.payload["card_instance_ids"] == own_live_ids


def test_simple_ai_v1_respects_same_unit_cost_choice_constraint():
    source_id = "source"
    effect = EffectDefinition(
        effect_id="SAME-UNIT:1",
        card_code="SAME-UNIT",
        text_revision_id=1,
        raw_text_hash="same-unit",
        effect_index=1,
        label_ja="同じユニット名を持つカード2枚を控え室に置いてもよい。",
        effect_type="triggered",
        timing="live_start",
        trigger="live_started",
        execution_mode="prompt_then_resolve",
        frequency_limit="once_per_live",
        is_optional=True,
        cost_choice=EffectChoice(
            choice_type="card_from_zone",
            zone="hand",
            minimum=2,
            maximum=2,
            condition={"selected_share_unit_key": True},
        ),
        cost=[EffectOperation(action_type="discard_from_hand")],
        actions=[
            EffectOperation(
                action_type="gain_heart",
                amount=2,
                color_slot="heart05",
            )
        ],
        duration="live",
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test",
    )
    state = MatchState(
        match_id="same-unit-ai-cost",
        seed=1,
        phase="performance_first",
        active_player_id="player_1",
        players={
            "player_1": PlayerState(
                player_id="player_1",
                name="AI",
                hand=["unit-a1", "unit-a2", "unit-b"],
                member_area={"left": source_id, "center": None, "right": None},
            ),
            "player_2": PlayerState(player_id="player_2", name="Opponent"),
        },
        cards={
            source_id: CardInstance(
                instance_id=source_id,
                owner_id="player_1",
                card=CardDefinition(
                    card_code="SAME-UNIT",
                    card_id="SAME-UNIT",
                    name_ja="Source",
                    card_type="member",
                    effect_ids=[effect.effect_id],
                ),
            ),
            "unit-a1": _test_member_card("unit-a1", ["unit_a"], hearts=1),
            "unit-a2": _test_member_card("unit-a2", ["unit_a"], hearts=1),
            "unit-b": _test_member_card("unit-b", ["unit_b"], hearts=0),
        },
        effect_definitions={effect.effect_id: effect},
        pending_effects=[
            EffectInvocation(
                invocation_id="same-unit-invocation",
                effect_id=effect.effect_id,
                source_card_instance_id=source_id,
                player_id="player_1",
                trigger_event="live_started",
            )
        ],
    )
    legal = generate_legal_actions(state)

    decision = SimpleAIController(
        SimpleAIPolicy(policy_version="simple_ai_v1")
    ).choose_action(state, legal, controlled_player_ids={"player_1"})

    assert decision.action.action_type == "resolve_effect"
    assert set(decision.action.payload["selected_card_instance_ids"]) == {
        "unit-a1",
        "unit-a2",
    }


def test_simple_ai_v1_group_selection_supports_shared_work_and_name():
    state = MatchState(
        match_id="shared-card-properties",
        seed=1,
        phase="first_main",
        active_player_id="player_1",
        players={
            "player_1": PlayerState(
                player_id="player_1",
                name="AI",
                hand=["shared-1", "shared-2", "other"],
            ),
            "player_2": PlayerState(player_id="player_2", name="Opponent"),
        },
        cards={
            "shared-1": _test_member_card(
                "shared-1",
                ["unit_a"],
                hearts=1,
                work_keys=["work_a"],
                name_ja="同名",
            ),
            "shared-2": _test_member_card(
                "shared-2",
                ["unit_b"],
                hearts=1,
                work_keys=["work_a"],
                name_ja="同名",
            ),
            "other": _test_member_card(
                "other",
                ["unit_c"],
                hearts=0,
                work_keys=["work_b"],
                name_ja="別名",
            ),
        },
    )
    observation = build_ai_observation(
        state,
        "player_1",
        [
            LegalAction(
                action_type="end_main_phase",
                player_id="player_1",
                label_zh="结束",
                label_ja="終了",
            )
        ],
    )
    candidates = ["shared-1", "shared-2", "other"]

    assert set(
        _select_cards_satisfying_condition(
            observation,
            candidates,
            count=2,
            descending=False,
            condition={"selected_share_work_key": True},
        )
    ) == {"shared-1", "shared-2"}
    assert set(
        _select_cards_satisfying_condition(
            observation,
            candidates,
            count=2,
            descending=False,
            condition={"selected_same_name_ja": True},
        )
    ) == {"shared-1", "shared-2"}


def test_simple_ai_v1_rechecks_pending_choice_capacity_before_resolution():
    assert not _invocation_choices_are_currently_satisfiable(
        {
            "choice_type": "card_from_zone",
            "card_selection_minimum": 2,
            "candidate_card_instance_ids": ["only-one"],
        }
    )
    assert not _invocation_choices_are_currently_satisfiable(
        {
            "choice_groups": [
                {"minimum": 1, "candidate_card_instance_ids": []},
            ]
        }
    )
    assert not _invocation_choices_are_currently_satisfiable(
        {"energy_required": 2, "energy_instance_ids": ["energy-1"]}
    )
    assert _invocation_choices_are_currently_satisfiable(
        {
            "choice_type": "card_from_zone",
            "card_selection_minimum": 1,
            "candidate_card_instance_ids": ["card-1"],
            "energy_required": 1,
            "energy_instance_ids": ["energy-1"],
        }
    )
    assert _invocation_choices_are_currently_satisfiable(
        {
            "choice_type": "post_action_card_from_zone",
            "card_selection_minimum": 1,
            "candidate_card_instance_ids": [],
            "choice_deferred_until_after_first_step": True,
            "resolution_stage": "initial",
            "cost_choice": None,
        }
    )
    assert _invocation_choices_are_currently_satisfiable(
        {
            "choice_type": "choose_color",
            "card_selection_minimum": 1,
            "candidate_card_instance_ids": [],
        }
    )


def test_rule_evaluation_uses_effective_member_and_live_modifiers():
    member_id = "member"
    live_id = "live"
    state = MatchState(
        match_id="rule-evaluation",
        seed=1,
        phase="live_set_first",
        active_player_id="player_1",
        players={
            "player_1": PlayerState(
                player_id="player_1",
                name="AI",
                hand=[live_id],
                member_area={"left": member_id, "center": None, "right": None},
                manual_modifiers=[
                    ManualModifier(
                        modifier_id="heart",
                        modifier_type="heart",
                        duration="turn",
                        created_turn=1,
                        amount=1,
                        color_slot="heart02",
                        target_card_instance_id=member_id,
                    ),
                    ManualModifier(
                        modifier_id="blade",
                        modifier_type="blade",
                        duration="turn",
                        created_turn=1,
                        amount=1,
                        target_card_instance_id=member_id,
                    ),
                    ManualModifier(
                        modifier_id="requirement",
                        modifier_type="required_heart",
                        duration="live",
                        created_turn=1,
                        amount=-1,
                        color_slot="heart01",
                        target_card_instance_id=live_id,
                    ),
                ],
            ),
            "player_2": PlayerState(player_id="player_2", name="Opponent"),
        },
        cards={
            member_id: CardInstance(
                instance_id=member_id,
                owner_id="player_1",
                card=CardDefinition(
                    card_code="MEMBER",
                    card_id="MEMBER",
                    name_ja="Member",
                    card_type="member",
                    blade=1,
                    basic_hearts={"heart01": 1},
                ),
            ),
            live_id: CardInstance(
                instance_id=live_id,
                owner_id="player_1",
                card=CardDefinition(
                    card_code="LIVE",
                    card_id="LIVE",
                    name_ja="Live",
                    card_type="live",
                    score=2,
                    required_hearts={"heart01": 2, "heart02": 1},
                ),
            ),
        },
    )

    snapshot = build_rule_evaluation_snapshot(state, "player_1")

    assert dict(snapshot.stage_hearts) == {"heart01": 1, "heart02": 1}
    assert snapshot.active_blade_count == 2
    assert dict(snapshot.live(live_id).required_hearts) == {
        "heart01": 1,
        "heart02": 1,
    }


def test_simple_ai_v1_activates_positive_structured_main_phase_effect():
    source_id = "source"
    effect = EffectDefinition(
        effect_id="ACTIVATE:1",
        card_code="ACTIVATE",
        text_revision_id=1,
        raw_text_hash="hash",
        effect_index=1,
        label_ja="【起動】カードを1枚引く。",
        effect_type="activated",
        timing="activated_main",
        trigger="player_activation",
        execution_mode="prompt_then_resolve",
        frequency_limit="once_per_turn",
        is_optional=False,
        actions=[EffectOperation(action_type="draw_card", amount=1)],
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test",
    )
    state = MatchState(
        match_id="activate-positive",
        seed=1,
        phase="first_main",
        active_player_id="player_1",
        players={
            "player_1": PlayerState(
                player_id="player_1",
                name="AI",
                member_area={"left": source_id, "center": None, "right": None},
            ),
            "player_2": PlayerState(player_id="player_2", name="Opponent"),
        },
        cards={
            source_id: CardInstance(
                instance_id=source_id,
                owner_id="player_1",
                card=CardDefinition(
                    card_code="ACTIVATE",
                    card_id="ACTIVATE",
                    name_ja="Source",
                    card_type="member",
                    effect_ids=[effect.effect_id],
                ),
            )
        },
        effect_definitions={effect.effect_id: effect},
    )
    legal = [
        LegalAction(
            action_type="activate_effect",
            player_id="player_1",
            label_zh="发动",
            label_ja="起動",
            options={
                "activations": [
                    {
                        "effect_id": effect.effect_id,
                        "source_card_instance_id": source_id,
                    }
                ]
            },
        ),
        LegalAction(
            action_type="end_main_phase",
            player_id="player_1",
            label_zh="结束",
            label_ja="終了",
        ),
    ]

    decision = SimpleAIController(
        SimpleAIPolicy(policy_version="simple_ai_v1")
    ).choose_action(state, legal, controlled_player_ids={"player_1"})

    assert decision.action.action_type == "activate_effect"
    assert decision.action.payload["effect_id"] == effect.effect_id
    assert decision.action.payload["ai_decision"]["policy_version"] == "simple_ai_v1"


def test_simple_ai_v1_does_not_double_count_hand_source_discard_cost():
    source_id = "hand-source"
    effect = EffectDefinition(
        effect_id="HAND-ACTIVATE:1",
        card_code="HAND-ACTIVATE",
        text_revision_id=1,
        raw_text_hash="hand-activate",
        effect_index=1,
        label_ja="【起動】このカードを手札から控え室に置く：カードを1枚引く。",
        effect_type="activated",
        timing="activated_main",
        trigger="player_activation",
        execution_mode="prompt_then_resolve",
        frequency_limit="once_per_turn",
        is_optional=False,
        cost=[EffectOperation(action_type="source_to_waiting_room")],
        actions=[EffectOperation(action_type="draw_card", amount=1)],
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test",
    )
    state = MatchState(
        match_id="hand-activation-value",
        seed=1,
        phase="first_main",
        active_player_id="player_1",
        players={
            "player_1": PlayerState(
                player_id="player_1",
                name="AI",
                hand=[source_id],
            ),
            "player_2": PlayerState(player_id="player_2", name="Opponent"),
        },
        cards={
            source_id: CardInstance(
                instance_id=source_id,
                owner_id="player_1",
                card=CardDefinition(
                    card_code="HAND-ACTIVATE",
                    card_id="HAND-ACTIVATE",
                    name_ja="Hand Source",
                    card_type="member",
                    cost=4,
                    blade=1,
                    basic_hearts={"heart01": 1},
                    effect_ids=[effect.effect_id],
                ),
            )
        },
        effect_definitions={effect.effect_id: effect},
    )
    legal = [
        LegalAction(
            action_type="activate_effect",
            player_id="player_1",
            label_zh="发动",
            label_ja="起動",
            options={
                "activations": [
                    {
                        "effect_id": effect.effect_id,
                        "source_card_instance_id": source_id,
                    }
                ]
            },
        ),
        LegalAction(
            action_type="end_main_phase",
            player_id="player_1",
            label_zh="结束",
            label_ja="終了",
        ),
    ]

    decision = SimpleAIController(
        SimpleAIPolicy(policy_version="simple_ai_v1")
    ).choose_action(state, legal, controlled_player_ids={"player_1"})

    assert decision.action.action_type == "activate_effect"
    assert decision.action.payload["effect_id"] == effect.effect_id
    assert decision.action.payload["ai_decision"]["score"] > 20


def test_simple_ai_v1_chooses_heart_color_needed_by_live():
    source_id = "source"
    live_id = "live"
    effect = EffectDefinition(
        effect_id="COLOR:1",
        card_code="COLOR",
        text_revision_id=1,
        raw_text_hash="hash",
        effect_index=1,
        label_ja="ハートを1つ選ぶ。",
        effect_type="activated",
        timing="activated_main",
        trigger="player_activation",
        execution_mode="prompt_then_resolve",
        frequency_limit="once_per_turn",
        is_optional=False,
        choice=EffectChoice(
            choice_type="choose_color",
            color_slots=["heart01", "heart02"],
            minimum=1,
            maximum=1,
        ),
        actions=[EffectOperation(action_type="gain_heart", amount=1)],
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test",
    )
    state = MatchState(
        match_id="choose-color",
        seed=1,
        phase="first_main",
        active_player_id="player_1",
        players={
            "player_1": PlayerState(
                player_id="player_1",
                name="AI",
                hand=[live_id],
                member_area={"left": source_id, "center": None, "right": None},
            ),
            "player_2": PlayerState(player_id="player_2", name="Opponent"),
        },
        cards={
            source_id: CardInstance(
                instance_id=source_id,
                owner_id="player_1",
                card=CardDefinition(
                    card_code="COLOR",
                    card_id="COLOR",
                    name_ja="Source",
                    card_type="member",
                    basic_hearts={"heart01": 1},
                    effect_ids=[effect.effect_id],
                ),
            ),
            live_id: CardInstance(
                instance_id=live_id,
                owner_id="player_1",
                card=CardDefinition(
                    card_code="LIVE",
                    card_id="LIVE",
                    name_ja="Live",
                    card_type="live",
                    required_hearts={"heart02": 2},
                ),
            ),
        },
        effect_definitions={effect.effect_id: effect},
        pending_effects=[
            EffectInvocation(
                invocation_id="invocation",
                effect_id=effect.effect_id,
                source_card_instance_id=source_id,
                player_id="player_1",
                trigger_event="player_activation",
                resolution_stage="after_cost",
            )
        ],
    )
    legal = [
        LegalAction(
            action_type="resolve_effect",
            player_id="player_1",
            label_zh="处理",
            label_ja="解決",
            options={
                "invocations": [
                    {
                        "invocation_id": "invocation",
                        "effect_id": effect.effect_id,
                        "source_card_instance_id": source_id,
                        "is_optional": False,
                        "simulation_support": "test_validated_executable",
                        "choice_type": "choose_color",
                        "choice": effect.choice.model_dump(),
                        "color_slots": ["heart01", "heart02"],
                        "resolution_stage": "after_cost",
                    }
                ]
            },
        )
    ]

    decision = SimpleAIController(
        SimpleAIPolicy(policy_version="simple_ai_v1")
    ).choose_action(state, legal, controlled_player_ids={"player_1"})

    assert decision.action.payload["selected_color_slot"] == "heart02"


def test_source_to_waiting_activation_requires_post_cost_live_candidate():
    source_id = "source"
    live_id = "waiting-live"
    effect = EffectDefinition(
        effect_id="RETURN-LIVE:1",
        card_code="RETURN-LIVE",
        text_revision_id=1,
        raw_text_hash="hash",
        effect_index=1,
        label_ja="【起動】自身を控室に置く：控室のライブを手札に加える。",
        effect_type="activated",
        timing="activated_main",
        trigger="player_activation",
        execution_mode="prompt_then_resolve",
        frequency_limit="none",
        is_optional=False,
        condition={"source_zone": "stage"},
        cost=[EffectOperation(action_type="source_to_waiting_room")],
        choice=EffectChoice(
            choice_type="card_from_zone",
            zone="waiting_room",
            card_type="live",
            minimum=1,
            maximum=1,
        ),
        actions=[EffectOperation(action_type="return_from_waiting_room")],
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test",
    )
    state = MatchState(
        match_id="post-cost-availability",
        seed=1,
        phase="first_main",
        active_player_id="player_1",
        players={
            "player_1": PlayerState(
                player_id="player_1",
                name="AI",
                member_area={"left": source_id, "center": None, "right": None},
            ),
            "player_2": PlayerState(player_id="player_2", name="Opponent"),
        },
        cards={
            source_id: CardInstance(
                instance_id=source_id,
                owner_id="player_1",
                card=CardDefinition(
                    card_code="RETURN-LIVE",
                    card_id="RETURN-LIVE",
                    name_ja="Source",
                    card_type="member",
                    effect_ids=[effect.effect_id],
                ),
            ),
            live_id: CardInstance(
                instance_id=live_id,
                owner_id="player_1",
                card=CardDefinition(
                    card_code="LIVE",
                    card_id="LIVE",
                    name_ja="Live",
                    card_type="live",
                ),
            ),
        },
        effect_definitions={effect.effect_id: effect},
    )

    assert all(
        action.action_type != "activate_effect" for action in generate_legal_actions(state)
    )

    state.players["player_1"].waiting_room.append(live_id)
    activation = next(
        action for action in generate_legal_actions(state) if action.action_type == "activate_effect"
    )
    assert activation.options["activations"][0]["effect_id"] == effect.effect_id


def test_simple_ai_v1_defers_post_action_destination_until_follow_up_step():
    source_id = "source"
    hand_id = "hand"
    effect = EffectDefinition(
        effect_id="POST-ACTION:1",
        card_code="POST-ACTION",
        text_revision_id=1,
        raw_text_hash="hash",
        effect_index=1,
        label_ja="カードを1枚引き、手札をデッキの上か下に置く。",
        effect_type="triggered",
        timing="live_start",
        trigger="live_started",
        execution_mode="prompt_then_resolve",
        frequency_limit="none",
        is_optional=False,
        choice=EffectChoice(
            choice_type="post_action_card_from_zone",
            zone="hand",
            minimum=1,
            maximum=1,
            destination_options=["main_deck_top", "main_deck_bottom"],
        ),
        actions=[
            EffectOperation(action_type="draw_card", amount=1),
            EffectOperation(action_type="move_selected_to_deck_top_or_bottom"),
        ],
        simulation_support="test_validated_executable",
        review_status="test_validated",
        source_reference="test",
    )
    state = MatchState(
        match_id="post-action-choice",
        seed=1,
        phase="performance_first",
        active_player_id="player_1",
        players={
            "player_1": PlayerState(
                player_id="player_1",
                name="AI",
                hand=[hand_id],
            ),
            "player_2": PlayerState(player_id="player_2", name="Opponent"),
        },
        cards={
            source_id: CardInstance(
                instance_id=source_id,
                owner_id="player_1",
                card=CardDefinition(
                    card_code="POST-ACTION",
                    card_id="POST-ACTION",
                    name_ja="Source",
                    card_type="live",
                    effect_ids=[effect.effect_id],
                ),
            ),
            hand_id: CardInstance(
                instance_id=hand_id,
                owner_id="player_1",
                card=CardDefinition(
                    card_code="HAND",
                    card_id="HAND",
                    name_ja="Hand",
                    card_type="member",
                ),
            ),
        },
        effect_definitions={effect.effect_id: effect},
        pending_effects=[
            EffectInvocation(
                invocation_id="invocation",
                effect_id=effect.effect_id,
                source_card_instance_id=source_id,
                player_id="player_1",
                trigger_event="live_started",
                resolution_stage="initial",
            )
        ],
    )
    legal = generate_legal_actions(state)
    resolution = next(action for action in legal if action.action_type == "resolve_effect")
    invocation = resolution.options["invocations"][0]

    assert invocation["choice_deferred_until_after_first_step"] is True
    decision = SimpleAIController(
        SimpleAIPolicy(policy_version="simple_ai_v1")
    ).choose_action(state, legal, controlled_player_ids={"player_1"})

    assert decision is not None
    assert decision.action.action_type == "resolve_effect"
    assert "selected_destination" not in decision.action.payload


def _test_member_card(
    instance_id: str,
    unit_keys: list[str],
    *,
    hearts: int,
    work_keys: list[str] | None = None,
    name_ja: str | None = None,
) -> CardInstance:
    return CardInstance(
        instance_id=instance_id,
        owner_id="player_1",
        card=CardDefinition(
            card_code=instance_id,
            card_id=instance_id,
            name_ja=name_ja or instance_id,
            card_type="member",
            cost=1,
            unit_keys=unit_keys,
            work_keys=work_keys or [],
            basic_hearts={"heart01": hearts} if hearts else {},
        ),
    )
