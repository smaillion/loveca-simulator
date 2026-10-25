from contextlib import closing
from pathlib import Path

import pytest
from pydantic import ValidationError

from loveca.db.bootstrap import connect_database
from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation.catalog import _load_definition
from loveca.simulation.effect_candidates import discover_effect_candidates
from loveca.simulation.effects import EffectDefinition, EffectOperation
from loveca.simulation.engine import (
    IllegalActionError,
    StaleRevisionError,
    _card_score,
    _remove_from_player_zones,
    apply_action,
    generate_legal_actions,
)
from loveca.simulation.models import (
    ActionRequest,
    CardDefinition,
    CardInstance,
    EffectInvocation,
    LivePerformanceResult,
    ManualModifier,
    MatchState,
    PlayerState,
)
from loveca.simulation.runtime import MatchRepository
from loveca.webapp import _match_state_payload

DATABASE = Path("data/loveca.sqlite3")
EFFECT_ID = "PL!N-bp7-027:1"
RULE_REFERENCE_IDS = (
    "4.1.4",
    "8.4.4",
    "8.4.5",
    "8.4.6",
    "9.6.3.1",
    "9.6.3.1.3",
    "9.9.1.4",
    "9.9.1.5",
)


@pytest.fixture(scope="module")
def definition():
    candidates = discover_effect_candidates(DATABASE, include_registered=True)
    effect = EffectDefinition.model_validate(
        next(c for c in candidates if c.effect_id == EFFECT_ID).to_registry_entry()
    )
    with closing(connect_database(DATABASE)) as connection:
        card = _load_definition(connection, effect.card_code, None, {effect.effect_id: effect}, {})
    return effect, card


def _state(definition, *, queued=True):
    effect, source = definition
    state = MatchState(
        match_id="selected-blade",
        seed=1,
        phase="first_main",
        turn_number=1,
        active_player_id="player_1",
        first_player_id="player_1",
        second_player_id="player_2",
        effect_order_policy="ap_nap_player_choice",
        players={p: PlayerState(player_id=p, name=p) for p in ("player_1", "player_2")},
        cards={},
        effect_definitions={effect.effect_id: effect},
    )
    for player, key, blade, work in [
        ("player_1", "best", 4, "nijigasaki"),
        ("player_1", "weak", 1, "nijigasaki"),
        ("player_1", "other", 2, "hasunosora"),
        ("player_2", "opponent", 3, "nijigasaki"),
    ]:
        state.cards[key] = CardInstance(
            instance_id=key,
            owner_id=player,
            card=CardDefinition(
                card_code=key,
                card_id=key,
                name_ja=key,
                card_type="member",
                blade=blade,
                work_keys=[work],
            ),
        )
    state.players["player_1"].member_area.update(left="weak", center="best", right="other")
    state.players["player_2"].member_area["left"] = "opponent"
    state.cards["source"] = CardInstance(
        instance_id="source", owner_id="player_1", card=source.model_copy(deep=True)
    )
    for owner, key, score in [
        ("player_1", "second-live", 2),
        ("player_2", "enemy-live", (source.score or 0) + 2),
    ]:
        state.cards[key] = CardInstance(
            instance_id=key,
            owner_id=owner,
            card=CardDefinition(
                card_code=key,
                card_id=key,
                name_ja=key,
                card_type="live",
                score=score,
            ),
        )
    state.players["player_1"].live_area = ["source", "second-live"]
    state.players["player_2"].live_area = ["enemy-live"]
    for player in state.players.values():
        player.live_result = LivePerformanceResult(requirements_satisfied=True)
    if queued:
        state.pending_effects = [
            EffectInvocation(
                invocation_id="score-1",
                effect_id=effect.effect_id,
                source_card_instance_id="source",
                player_id="player_1",
                trigger_event="live_succeeded",
                trigger_data={"_condition_checked_at_trigger": True},
            )
        ]
    return state


def _resolve(state, selected=None, *, revision=None):
    return apply_action(
        state,
        ActionRequest(
            action_type="resolve_effect",
            player_id="player_1",
            expected_revision=state.revision if revision is None else revision,
            payload={
                "invocation_id": state.pending_effects[0].invocation_id,
                "selected_card_instance_ids": ["best"] if selected is None else selected,
            },
        ),
    )


def test_exact_candidate_identity_and_mandatory_work_choice(definition):
    effect, card = definition
    assert effect.text_revision_id == 921
    assert (
        effect.raw_text_hash == "4c9f50c82ec56c823425e62731d8e0c65cbf30cbf31d3a07e6813a2c3cfe0df0"
    )
    assert effect.execution_mode == "prompt_then_resolve" and not effect.is_optional
    assert (
        effect.choice.work_key == "nijigasaki"
        and effect.choice.minimum == effect.choice.maximum == 1
    )
    assert card.card_code == "PL!N-bp7-027" and effect.effect_id in card.effect_ids
    invocation = generate_legal_actions(_state(definition))[0].options["invocations"][0]
    assert set(invocation["candidate_card_instance_ids"]) == {"best", "weak"}
    assert invocation["candidate_blade_counts"] == {"best": 4, "weak": 1} or invocation[
        "candidate_blade_counts"
    ] == {"weak": 1, "best": 4}


@pytest.mark.parametrize(
    "target,enemy,own_other,expected",
    [
        ("best", 3, 2, 1),
        ("best", 4, 2, 0),
        ("best", 5, 2, 0),
        ("weak", 3, 2, 0),
        ("best", 0, 4, 0),
        ("best", 0, 5, 0),
    ],
)
def test_strict_comparison_checks_both_stages_and_only_source_live(
    definition, target, enemy, own_other, expected
):
    state = _state(definition)
    state.cards["opponent"].card.blade = enemy
    state.cards["other"].card.blade = own_other
    base = _card_score(state, "player_1", "source")
    before = state.model_dump(mode="json")
    result = _resolve(state, [target])
    assert state.model_dump(mode="json") == before
    assert _card_score(result.state, "player_1", "source") == base + expected
    assert _card_score(result.state, "player_1", "second-live") == 2
    assert not result.state.pending_effects
    event = next(e for e in result.events if e.event_type == "effect_blade_comparison_resolved")
    assert event.data["score_delta"] == expected
    assert event.data["condition_met"] == bool(expected)


@pytest.mark.parametrize(
    "kind,amount,expected", [("blade", 2, 1), ("base_blade_replacement", 6, 1), ("blade", -5, 0)]
)
def test_wait_member_uses_effective_not_yell_contribution_blade(definition, kind, amount, expected):
    state = _state(definition)
    state.cards["best"].orientation = "wait"
    state.cards["best"].card.blade = 3
    state.cards["opponent"].card.blade = 4
    state.players["player_1"].manual_modifiers = [
        ManualModifier(
            modifier_id="boost",
            modifier_type=kind,
            duration="live",
            created_turn=1,
            amount=amount,
            target_card_instance_id="best",
        )
    ]
    event = next(
        e for e in _resolve(state).events if e.event_type == "effect_blade_comparison_resolved"
    )
    assert event.data["score_delta"] == expected


@pytest.mark.parametrize("selected", [["opponent"], ["other"], ["best", "best"], [], ["absent"]])
def test_invalid_selection_is_atomic(definition, selected):
    state = _state(definition)
    before = state.model_dump(mode="json")
    with pytest.raises(IllegalActionError):
        _resolve(state, selected)
    assert state.model_dump(mode="json") == before


@pytest.mark.parametrize(
    "policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"]
)
def test_all_ai_policies_submit_legal_choice_and_newer_choose_highest(definition, policy):
    state = _state(definition)
    decision = SimpleAIController(SimpleAIPolicy(policy_version=policy)).choose_action(
        state,
        generate_legal_actions(state),
        controlled_player_ids={"player_1"},
    )
    assert isinstance(decision, SimpleAIDecision)
    result = apply_action(state, decision.action)
    assert not result.state.pending_effects
    if policy != "simple_ai_v0":
        assert decision.action.payload["selected_card_instance_ids"] == ["best"]


def test_judgment_uses_bonus_before_winner_comparison_and_sql_replay(definition, tmp_path):
    state = _state(definition, queued=False)
    state.phase = "live_judgment"
    state.active_player_id = None
    repository = MatchRepository(tmp_path / "blade-score.sqlite3")
    repository.create_match(state, card_database_path=DATABASE)
    result = repository.apply(
        state.match_id, ActionRequest(action_type="advance_phase", expected_revision=0)
    )
    assert result.state.pending_effects[0].effect_id == EFFECT_ID
    before = repository.get_state(state.match_id).model_dump(mode="json")
    with pytest.raises(StaleRevisionError):
        repository.apply(
            state.match_id,
            ActionRequest(
                action_type="resolve_effect", player_id="player_1", expected_revision=0, payload={}
            ),
        )
    assert repository.get_state(state.match_id).model_dump(mode="json") == before
    result = repository.apply(
        state.match_id,
        ActionRequest(
            action_type="resolve_effect",
            player_id="player_1",
            expected_revision=1,
            payload={
                "invocation_id": result.state.pending_effects[0].invocation_id,
                "selected_card_instance_ids": ["best"],
            },
        ),
    )
    assert result.state.live_winner_ids == ["player_1"]
    assert result.state.pending_choice.choice_type == "success_live"
    replay = repository.replay(state.match_id)
    assert replay["final_state"] == result.state.model_dump(mode="json")
    source_score = _card_score(result.state, "player_1", "source")
    result = repository.apply(
        state.match_id,
        ActionRequest(
            action_type="resolve_live_requirements",
            player_id="player_1",
            expected_revision=2,
            payload={"success_live_instance_id": "source"},
        ),
    )
    assert _card_score(result.state, "player_1", "source") == source_score - 1
    assert not any(
        m.modifier_type == "live_card_score"
        for m in result.state.players["player_1"].manual_modifiers
    )
    assert repository.replay(state.match_id)["final_state"] == result.state.model_dump(mode="json")


def test_no_target_and_failed_live_never_offer_manual_fallback(definition):
    state = _state(definition, queued=False)
    state.phase = "live_judgment"
    state.players["player_1"].member_area = {"left": None, "center": None, "right": None}
    result = apply_action(state, ActionRequest(action_type="advance_phase", expected_revision=0))
    assert not result.state.pending_effects
    assert any(
        e.event_type == "effect_not_activatable" and e.data.get("effect_id") == EFFECT_ID
        for e in result.events
    )
    failed = _state(definition, queued=False)
    failed.phase = "live_judgment"
    failed.players["player_1"].waiting_room = failed.players["player_1"].live_area
    failed.players["player_1"].live_area = []
    result = apply_action(failed, ActionRequest(action_type="advance_phase", expected_revision=0))
    assert not any(
        e.event_type == "effect_triggered" and e.data.get("effect_id") == EFFECT_ID
        for e in result.events
    )


def test_zone_change_clears_only_new_card_score_and_private_hands_stay_hidden(definition):
    state = _resolve(_state(definition)).state
    player = state.players["player_1"]
    player.manual_modifiers.append(
        ManualModifier(
            modifier_id="old-global",
            modifier_type="score",
            duration="live",
            created_turn=1,
            amount=2,
        )
    )
    _remove_from_player_zones(player, "source")
    player.hand.append("source")
    assert [m.modifier_id for m in player.manual_modifiers] == ["old-global"]
    view = _match_state_payload(
        state, events=[], legal_actions=generate_legal_actions(state), player_id="player_2"
    )
    assert "source" not in view["state"]["cards"]


@pytest.mark.parametrize(
    "kwargs", [{"amount": 2}, {"target": "opponent"}, {"amount_source": "selected_count"}]
)
def test_operation_shape_is_bounded(kwargs):
    with pytest.raises(ValidationError):
        EffectOperation.model_validate(
            {"action_type": "modify_source_score_if_selected_blade_highest", "amount": 1, **kwargs}
        )


def test_static_blade_and_opponent_temporary_wait_blade_are_compared(definition):
    effect, _ = definition
    state = _state(definition)
    static = EffectDefinition.model_validate(
        {
            **effect.model_dump(mode="json"),
            "effect_id": "static",
            "card_code": "best",
            "effect_type": "static",
            "timing": "static_always",
            "trigger": "static_always",
            "execution_mode": "auto_resolve",
            "frequency_limit": "none",
            "choice": None,
            "actions": [{"action_type": "gain_blade", "amount": 2}],
        }
    )
    state.effect_definitions["static"] = static
    state.cards["best"].card.effect_ids = ["static"]
    state.cards["best"].orientation = "wait"
    state.cards["opponent"].orientation = "wait"
    state.players["player_2"].manual_modifiers = [
        ManualModifier(
            modifier_id="enemy-boost",
            modifier_type="blade",
            duration="live",
            created_turn=1,
            amount=3,
            target_card_instance_id="opponent",
        )
    ]
    event = next(
        e for e in _resolve(state).events if e.event_type == "effect_blade_comparison_resolved"
    )
    assert event.data["selected_blade"] == event.data["other_max_blade"] == 6
    assert event.data["score_delta"] == 0


def test_hidden_and_attached_members_do_not_enter_stage_comparison(definition):
    state = _state(definition)
    for key in ["hidden", "attached"]:
        state.cards[key] = state.cards["opponent"].model_copy(
            update={"instance_id": key}, deep=True
        )
        state.cards[key].card.blade = 99
    state.players["player_2"].hand = ["hidden"]
    state.players["player_2"].member_area_attachments["left"] = ["attached"]
    event = next(
        e for e in _resolve(state).events if e.event_type == "effect_blade_comparison_resolved"
    )
    assert event.data["score_delta"] == 1
    assert "hidden" not in str(event.data) and "attached" not in str(event.data)


def test_departed_source_never_bonuses_another_live(definition):
    state = _state(definition)
    state.players["player_1"].live_area.remove("source")
    state.players["player_1"].waiting_room.append("source")
    result = _resolve(state)
    event = next(e for e in result.events if e.event_type == "effect_blade_comparison_resolved")
    assert event.data["condition_met"] and not event.data["source_available"]
    assert event.data["score_delta"] == 0
    assert _card_score(result.state, "player_1", "second-live") == 2


def test_historical_manual_snapshot_keeps_its_manual_contract(definition):
    state = _state(definition)
    effect, _ = definition
    state.effect_definitions[effect.effect_id] = EffectDefinition.model_validate(
        {
            **effect.model_dump(mode="json"),
            "execution_mode": "manual_resolution",
            "choice": None,
            "actions": [{"action_type": "manual_resolution"}],
            "simulation_support": "manual_resolution",
            "review_status": "parsed_draft",
        }
    )
    assert any(a.action_type == "manual_adjustment" for a in generate_legal_actions(state))
    with pytest.raises(IllegalActionError, match="ManualAdjustmentAction"):
        _resolve(state)


@pytest.mark.parametrize("replacement_first", [True, False])
def test_card_score_replacement_layer_precedes_addition(definition, replacement_first):
    state = _resolve(_state(definition)).state
    replacement = ManualModifier(
        modifier_id="set-score",
        modifier_type="score_replacement",
        duration="live",
        created_turn=1,
        amount=7,
        target_card_instance_id="source",
    )
    if replacement_first:
        state.players["player_1"].manual_modifiers.insert(0, replacement)
    else:
        state.players["player_1"].manual_modifiers.append(replacement)
    assert _card_score(state, "player_1", "source") == 8


@pytest.mark.parametrize(
    "change", [{"choice": None}, {"duration": "game"}, {"trigger": "member_played"}]
)
def test_definition_rejects_unbounded_choice_or_wrong_timing(definition, change):
    effect, _ = definition
    with pytest.raises(ValidationError, match="source score comparison"):
        EffectDefinition.model_validate({**effect.model_dump(mode="json"), **change})


@pytest.mark.parametrize("changed", [False, True])
def test_semantic_audit_accepts_only_the_exact_registered_comparison_text(definition, changed):
    from tools.ai_sandbox.rule_conformance import _semantic_operation_alignment

    effect, _ = definition
    text = effect.label_ja.replace("より多くの", "以上の") if changed else effect.label_ja
    assert _semantic_operation_alignment(text, {effect.actions[0].action_type}) is (not changed)


def test_native_return_to_hand_resets_bonus_and_replays(definition, tmp_path):
    state = _resolve(_state(definition)).state
    effect, _ = definition
    returning = EffectDefinition.model_validate(
        {
            **effect.model_dump(mode="json"),
            "effect_id": "return-source",
            "choice": None,
            "actions": [{"action_type": "return_source_live_to_hand"}],
        }
    )
    state.effect_definitions[returning.effect_id] = returning
    state.pending_effects = [
        EffectInvocation(
            invocation_id="return-1",
            effect_id=returning.effect_id,
            source_card_instance_id="source",
            player_id="player_1",
            trigger_event="live_succeeded",
        )
    ]
    repository = MatchRepository(tmp_path / "return-source.sqlite3")
    repository.create_match(state, card_database_path=DATABASE)
    result = repository.apply(
        state.match_id,
        ActionRequest(
            action_type="resolve_effect",
            player_id="player_1",
            expected_revision=state.revision,
            payload={"invocation_id": "return-1"},
        ),
    )
    assert "source" in result.state.players["player_1"].hand
    assert not any(
        m.modifier_type == "live_card_score"
        for m in result.state.players["player_1"].manual_modifiers
    )
    assert repository.replay(state.match_id)["final_state"] == result.state.model_dump(mode="json")
