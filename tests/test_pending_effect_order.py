from pathlib import Path

import pytest
from test_attachment_promotion import _trigger
from test_member_entry_area_history import _play
from test_overlap_entry_observer import ACTUAL
from test_overlap_entry_observer import _state as overlap_state
from test_private_hand_deployment_choice import ROOT, _private_state

from loveca.simulation.effects import EffectDefinition
from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions
from loveca.simulation.models import ActionRequest, EffectInvocation, MatchState

POLICY = "ap_nap_player_choice"
FIELD = "effect_order_policy"
FILL = "audit-fill:1"
RULE_REFERENCE_IDS = ("7.2.1.1", "7.2.1.2", "9.5.3.2", "9.5.3.3", "9.7.3")


def _modern(state, enabled=True):
    raw = state.model_dump(mode="json")
    if enabled:
        raw[FIELD] = POLICY
    else:
        raw.pop(FIELD, None)
    return MatchState.model_validate(raw)


def _two_effect_entry(*, modern=True):
    state = overlap_state()
    fill = _trigger(FILL, "member_played")
    fill.label_ja = "監査用：手札が4枚になるまで引く"
    fill.actions = [
        EffectDefinition.model_validate(
            {
                **fill.model_dump(),
                "actions": [{"action_type": "draw_until_hand_size", "target_hand_size": 4}],
            }
        ).actions[0]
    ]
    state.effect_definitions[FILL] = fill
    state.cards["entrant"].card.effect_ids = [FILL]
    for i in range(8):
        key = f"extra-{i}"
        state.cards[key] = state.cards["deck-member-1"].model_copy(
            update={"instance_id": key}, deep=True
        )
        state.players["player_1"].main_deck.append(key)
    return _modern(state, modern)


def _resolve(state, effect_id, player="player_1", **payload):
    invocation = next(i for i in state.pending_effects if i.effect_id == effect_id)
    return ActionRequest(
        action_type="resolve_effect",
        player_id=player,
        expected_revision=state.revision,
        payload={"invocation_id": invocation.invocation_id, "accepted": True, **payload},
    )


@pytest.mark.parametrize("first,expected", [(ACTUAL, 4), (FILL, 5)])
def test_real_entry_with_two_auto_effects_waits_and_order_changes_hand(first, expected):
    state = _two_effect_entry()
    result = _play(state, slot="center")
    assert len(result.state.pending_effects) == 2
    assert len(result.state.players["player_1"].hand) == 2
    assert not any(e.event_type == "cards_drawn" for e in result.events)
    action = next(a for a in result.legal_actions if a.action_type == "resolve_effect")
    assert action.options["effect_order_choice"] is True
    assert {i["effect_id"] for i in action.options["invocations"]} == {ACTUAL, FILL}
    finished = apply_action(result.state, _resolve(result.state, first))
    assert not finished.state.pending_effects
    assert len(finished.state.players["player_1"].hand) == expected


def test_existing_overlap_policy_without_order_policy_retains_eager_replay_behavior():
    state = _two_effect_entry(modern=False)
    assert FIELD not in state.model_dump(mode="json")
    result = _play(state, slot="center")
    assert not result.state.pending_effects
    assert len(result.state.players["player_1"].hand) == 4


def _opposing():
    state = _private_state()
    state.pending_effects = []
    for name, owner in [("nap", "player_2"), ("ap", "player_1")]:
        effect = _trigger(f"{name}:1", "member_played")
        effect.execution_mode = "prompt_then_resolve"
        effect.is_optional = True
        state.effect_definitions[effect.effect_id] = effect
        state.cards[name] = state.cards["source-live"].model_copy(
            update={"instance_id": name, "owner_id": owner}, deep=True
        )
        state.pending_effects.append(
            EffectInvocation(
                invocation_id=name,
                effect_id=effect.effect_id,
                source_card_instance_id=name,
                player_id=owner,
                trigger_event="member_played",
            )
        )
    return _modern(state)


@pytest.mark.parametrize(
    "phase,expected",
    [
        ("first_main", "player_1"),
        ("second_main", "player_2"),
        ("performance_second", "player_2"),
        ("live_set_second", "player_1"),
        ("live_judgment", "player_1"),
    ],
)
def test_legal_priority_uses_rules_ap_not_insertion_or_live_selection_player(phase, expected):
    state = _opposing()
    state.phase = phase
    state.active_player_id = "player_2"
    before = state.model_dump(mode="json")
    legal = next(a for a in generate_legal_actions(state) if a.action_type == "resolve_effect")
    assert legal.player_id == expected
    assert {i["source_card_instance_id"] for i in legal.options["invocations"]} == (
        {"ap"} if expected == "player_1" else {"nap"}
    )
    assert state.model_dump(mode="json") == before


def test_nap_resolve_and_skip_cannot_bypass_ap_and_are_atomic():
    state = _opposing()
    before = state.model_dump(mode="json")
    for kind in ["resolve_effect", "skip_effect"]:
        action = ActionRequest(
            action_type=kind,
            player_id="player_2",
            expected_revision=state.revision,
            payload={"invocation_id": "nap", "accepted": False},
        )
        with pytest.raises(IllegalActionError):
            apply_action(state, action)
        assert state.model_dump(mode="json") == before


def test_after_cost_continuation_is_locked_before_other_same_owner_effects():
    state = _private_state()
    state.pending_effects[0].resolution_stage = "after_cost"
    for e in ["energy-0", "energy-1"]:
        state.cards[e].orientation = "wait"
    auto = _trigger("other:1", "member_played")
    state.effect_definitions[auto.effect_id] = auto
    state.pending_effects.insert(
        0,
        EffectInvocation(
            invocation_id="other",
            effect_id=auto.effect_id,
            source_card_instance_id="source-live",
            player_id="player_1",
            trigger_event="member_played",
        ),
    )
    state = _modern(state)
    action = next(a for a in generate_legal_actions(state) if a.action_type == "resolve_effect")
    assert [i["effect_id"] for i in action.options["invocations"]] == [ROOT]
    before = state.model_dump(mode="json")
    with pytest.raises(IllegalActionError):
        apply_action(state, _resolve(state, auto.effect_id))
    assert state.model_dump(mode="json") == before
    with pytest.raises(IllegalActionError):
        apply_action(
            state,
            ActionRequest(
                action_type="skip_effect",
                player_id="player_1",
                expected_revision=state.revision,
                payload={"invocation_id": "other"},
            ),
        )
    assert state.model_dump(mode="json") == before
    result = apply_action(state, _resolve(state, ROOT, selected_card_instance_ids=[]))
    assert not result.state.pending_effects
    assert not any(e.event_type == "effect_cost_paid" for e in result.events)


def test_nap_becomes_legal_after_ap_finishes_its_optional_effect():
    state = _opposing()
    result = apply_action(state, _resolve(state, "ap:1", accepted=False))
    assert [i.invocation_id for i in result.state.pending_effects] == ["nap"]
    legal = next(a for a in result.legal_actions if a.action_type == "resolve_effect")
    assert legal.player_id == "player_2"
    assert [i["invocation_id"] for i in legal.options["invocations"]] == ["nap"]


@pytest.mark.parametrize("first", [ACTUAL, FILL])
def test_actual_runtime_replay_preserves_selected_order(tmp_path, first):
    from loveca.simulation.runtime import MatchRepository

    state = _two_effect_entry()
    probe = _play(state, slot="center")
    played = next(e for e in probe.events if e.event_type == "member_played")
    repo = MatchRepository(tmp_path / "runtime.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    pending = repo.apply(
        state.match_id,
        ActionRequest(
            action_type="play_member",
            player_id="player_1",
            expected_revision=state.revision,
            payload={
                "card_instance_id": "entrant",
                "slot": "center",
                "use_baton_touch": False,
                "energy_instance_ids": played.data["energy_instance_ids"],
            },
        ),
    ).state
    result = repo.apply(state.match_id, _resolve(pending, first))
    replay = repo.replay(state.match_id)
    assert replay["final_state"] == result.state.model_dump(mode="json")


def test_manual_bound_nap_cannot_bypass_ap():
    state = _opposing()
    effect = state.effect_definitions["nap:1"]
    effect.execution_mode = effect.simulation_support = "manual_resolution"
    before = state.model_dump(mode="json")
    with pytest.raises(IllegalActionError, match="another effect"):
        apply_action(
            state,
            ActionRequest(
                action_type="manual_adjustment",
                player_id="player_2",
                expected_revision=state.revision,
                payload={
                    "source_invocation_id": "nap",
                    "source_effect_id": "nap:1",
                    "source_card_instance_id": "nap",
                    "reason": "audit",
                    "adjustments": [
                        {
                            "adjustment_type": "set_flag",
                            "target_player_id": "player_2",
                            "flag": "audit",
                            "value": True,
                        }
                    ],
                },
            ),
        )
    assert state.model_dump(mode="json") == before


@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1"])
def test_ai_resolves_order_choice_without_skip_and_is_private_hand_independent(policy):
    from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy

    state = _play(_two_effect_entry(), slot="center").state
    state.cards["private"] = state.cards["entrant"].model_copy(
        update={"instance_id": "private", "owner_id": "player_2"}, deep=True
    )
    state.players["player_2"].hand = ["private"]
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy))
    decision = controller.choose_action(
        state, generate_legal_actions(state), controlled_player_ids={"player_1"}
    )
    assert (
        isinstance(decision, SimpleAIDecision) and decision.action.action_type == "resolve_effect"
    )
    changed = state.model_copy(deep=True)
    changed.cards["private"].card.card_code = "PRIVATE-CHANGED"
    changed.cards["private"].card.name_ja = "非公開カード変更"
    assert (
        controller.choose_action(
            changed, generate_legal_actions(changed), controlled_player_ids={"player_1"}
        ).action
        == decision.action
    )
    result = apply_action(state, decision.action)
    assert not result.state.pending_effects
    assert not any(e.event_type == "effect_skipped_due_to_error" for e in result.events)


@pytest.mark.parametrize(
    "phase,first",
    [("first_main", "player_1"), ("second_main", "player_2"), ("live_judgment", "player_1")],
)
def test_multi_player_choice_locks_parent_until_both_selections_finish(phase, first):
    from test_multi_player_entry import _begin, _choose
    from test_multi_player_entry import _state as multi_state

    state = multi_state(owner="player_2", active="player_2")
    state.phase = phase
    state = _modern(state)
    state = _begin(state)
    assert state.pending_choice.player_id == first
    # Another effect becoming pending cannot interrupt an already resolving multi-player parent.
    auto = _trigger("interrupt:1", "member_played")
    state.effect_definitions[auto.effect_id] = auto
    state.pending_effects.insert(
        0,
        EffectInvocation(
            invocation_id="interrupt",
            effect_id=auto.effect_id,
            source_card_instance_id="source-live",
            player_id="player_1",
            trigger_event="member_played",
        ),
    )
    with pytest.raises(IllegalActionError):
        apply_action(state, _resolve(state, auto.effect_id))

    def choose(s, actor):
        return _choose(
            s, actor, "target" if actor == "player_1" else "opponent-target", "right"
        ).state

    state = choose(state, first)
    second = "player_2" if first == "player_1" else "player_1"
    assert state.pending_choice.player_id == second
    result_state = choose(state, second)
    assert result_state.pending_choice is None
    assert not any(i.invocation_id == "multi-parent" for i in result_state.pending_effects)
    if result_state.pending_effects:
        assert (
            next(
                a for a in generate_legal_actions(result_state) if a.action_type == "resolve_effect"
            ).player_id
            == first
        )


def test_new_api_match_sets_policy_and_old_unknown_values_are_not_accepted(tmp_path):
    import json

    from test_webapp import SAMPLE_DECK, _client

    client = _client(tmp_path)
    deck = json.loads(SAMPLE_DECK.read_text(encoding="utf-8"))
    response = client.post(
        "/api/matches",
        json={
            "player_1": {"name": "A", "deck": deck},
            "player_2": {"name": "B", "deck": deck},
            "seed": 1,
        },
    )
    assert response.status_code == 200 and response.json()["state"][FIELD] == POLICY
    raw = _opposing().model_dump(mode="json")
    raw[FIELD] = "unknown"
    with pytest.raises(ValueError):
        MatchState.model_validate(raw)
