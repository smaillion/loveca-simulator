import json
from pathlib import Path

import pytest
from test_disjoint_overlap_source import _options
from test_disjoint_overlap_source import _state as disjoint_state
from test_occupied_effect_deployment import ROOT, _request

from loveca.simulation.effects import EffectDefinition, EffectOperation, load_effect_registry
from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions
from loveca.simulation.models import MatchState
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository
from loveca.simulation.ai import SimpleAIBlocker, SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.webapp import _match_state_payload

POLICY = "require_complete_source_bindings"
RULE_REFERENCE_IDS = ("9.3.4", "9.7.2", "10.1.2", "10.4.1")


def _state(*, strict=False):
    state = disjoint_state()
    # Controlled AUDIT sources carry complete text/identity, not real-card claims.
    for instance in state.cards.values():
        card = instance.card
        effects = [state.effect_definitions[key] for key in card.effect_ids]
        card.effect_registry_errors = []
        if effects:
            card.card_code = effects[0].card_code
            card.text_revision_id = effects[0].text_revision_id
            card.raw_text_hash = effects[0].raw_text_hash
            card.raw_effect_text_ja = "\n".join(e.label_ja for e in effects)
            card.effect_registry_status = "supported"
            card.ability_bucket = "other"
        else:
            card.raw_effect_text_ja = None
            card.ability_bucket = "none"
            card.effect_registry_status = "unregistered"
    if strict:
        raw = state.effect_definitions[ROOT].model_dump(mode="json")
        raw["actions"][0]["overlap_observer_policy"] = POLICY
        state.effect_definitions[ROOT] = EffectDefinition.model_validate(raw)
    return state


def _unknown_source(state, location):
    keys = {"incoming": "target", "attached": "attached-member", "other": "source-live"}
    if location in keys:
        instance = state.cards[keys[location]]
    else:
        key = f"unknown-{location}"
        owner = "player_2" if location.startswith("opponent") else "player_1"
        instance = state.cards["target"].model_copy(
            update={"instance_id": key, "owner_id": owner}, deep=True,
        )
        state.cards[key] = instance
        if location == "opponent":
            state.players[owner].member_area["center"] = key
        elif location == "opponent_attached":
            state.players[owner].member_area_attachments["center"].append(key)
        else:
            instance.card.card_type = "live"
            state.players[owner].live_area.append(key)
            instance.face_up = True
    instance.card.effect_ids = []
    instance.card.raw_effect_text_ja = "【自動】メンバーが登場したとき、カードを1枚引く。"
    instance.card.effect_registry_status = "unregistered"
    instance.card.ability_bucket = "other"
    return instance


@pytest.mark.parametrize("location", ["incoming", "attached", "other", "opponent", "opponent_attached", "live"])
def test_unbound_public_ability_is_not_silently_treated_as_blank(location):
    state = _state(strict=True)
    _unknown_source(state, location)
    assert "right" not in _options(state)["position_change_slots_by_candidate"].get("target", [])
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _request(state))
    assert match_state_hash(state) == before
    assert _options(state)["deployment_requires_manual_resolution"] is True
    with pytest.raises(IllegalActionError, match="require manual resolution"):
        apply_action(state, _request(state, selected_card_instance_ids=[]))
    assert match_state_hash(state) == before


@pytest.mark.parametrize("location", ["incoming", "attached", "other", "opponent", "live"])
def test_prior_snapshot_keeps_historical_behavior_without_new_policy(location):
    state = _state()
    _unknown_source(state, location)
    restored = MatchState.model_validate_json(state.model_dump_json())
    assert match_state_hash(restored) == match_state_hash(state)
    result = apply_action(restored, _request(restored))
    assert result.state.players["player_1"].member_area["right"] == "target"
    assert restored.effect_definitions[ROOT].actions[0].overlap_observer_policy == "ignore_disjoint_source_triggers"


@pytest.mark.parametrize("location", ["incoming", "other", "old"])
@pytest.mark.parametrize("defect", ["card_code", "revision", "hash", "missing_text", "extra_text", "missing_definition", "duplicate_index", "binding_error"])
def test_complete_label_alone_cannot_hide_wrong_identity_or_missing_segments(location, defect):
    state = _state(strict=True)
    key = {"incoming": "target", "other": "source-live", "old": "old"}[location]
    card = state.cards[key].card
    effect = state.effect_definitions[card.effect_ids[0]]
    if defect == "card_code":
        card.card_code = "WRONG"
    elif defect == "revision":
        card.text_revision_id = (card.text_revision_id or 0) + 1
    elif defect == "hash":
        card.raw_text_hash = "0" * 64
    elif defect == "missing_text":
        card.raw_effect_text_ja = None
    elif defect == "extra_text":
        card.raw_effect_text_ja += "\n【常時】監査用の未登録能力。"
    elif defect == "missing_definition":
        state.effect_definitions.pop(effect.effect_id)
    elif defect == "duplicate_index":
        card.effect_ids.append(effect.effect_id)
        card.raw_effect_text_ja += effect.label_ja
    else:
        card.effect_registry_errors = ["identity mismatch"]
    before = match_state_hash(state)
    options = _options(state)
    assert options["deployment_unsupported_slots_by_candidate"]["target"]["right"] == "overlap_source_binding_incomplete"
    with pytest.raises(IllegalActionError):
        apply_action(state, _request(state))
    assert match_state_hash(state) == before


@pytest.mark.parametrize("location", ["attached", "opponent", "live", "other"])
def test_completely_bound_but_unimplemented_public_abilities_remain_explicit(location):
    state = _state(strict=True)
    instance = _unknown_source(state, location)
    effect = state.effect_definitions["audit-observer:1"].model_copy(deep=True)
    if location == "other":
        effect.effect_type, effect.trigger = "static", "static_always"
    state.effect_definitions[effect.effect_id] = effect
    instance.card.card_code = effect.card_code
    instance.card.raw_text_hash = effect.raw_text_hash
    instance.card.text_revision_id = effect.text_revision_id
    instance.card.effect_ids = [effect.effect_id]
    instance.card.raw_effect_text_ja = effect.label_ja
    instance.card.effect_registry_status = "supported"
    options = _options(state)
    reason = options["deployment_unsupported_slots_by_candidate"]["target"]["right"]
    assert reason in {"overlap_attached_ability_requires_review", "overlap_public_ability_requires_timing_review"}


def test_empty_area_needs_no_temporary_overlap_and_keeps_native_entry():
    state = _state(strict=True)
    _unknown_source(state, "incoming")
    player = state.players["player_1"]
    player.waiting_room.append(player.member_area["right"])
    player.member_area["right"] = None
    player.member_area_attachments["right"] = []
    result = apply_action(state, _request(state))
    assert result.state.players["player_1"].member_area["right"] == "target"


def test_private_filtered_none_remains_a_real_choice_not_a_forced_review():
    state = _state(strict=True)
    player = state.players["player_1"]
    player.waiting_room.remove("target")
    player.hand.append("target")
    raw = state.effect_definitions[ROOT].model_dump(mode="json")
    raw["choice"].update(zone="hand", selection_policy="private_filtered_may_choose_none")
    state.effect_definitions[ROOT] = EffectDefinition.model_validate(raw)
    _unknown_source(state, "attached")
    options = _options(state)
    assert not options.get("deployment_requires_manual_resolution")
    action = _request(state, selected_card_instance_ids=[])
    action.payload.pop("to_slot")
    result = apply_action(state, action)
    assert result.state.players["player_1"].member_area["right"] == "old"
    assert "target" in result.state.players["player_1"].hand
    assert len(result.state.players["player_1"].hand) == len(player.hand)
    assert any(e.data.get("reason") == "private_selection_none" for e in result.events)
    assert all(result.state.cards[i].orientation == "wait" for i in ["energy-0", "energy-1"])


def test_no_matching_public_card_is_not_a_fictitious_unknown_source_blocker():
    state = _state(strict=True)
    state.players["player_1"].waiting_room.clear()
    _unknown_source(state, "attached")
    assert not _options(state).get("deployment_requires_manual_resolution")


def test_sql_rejection_preserves_revision_pending_zones_and_cost(tmp_path):
    state = _state(strict=True)
    _unknown_source(state, "attached")
    repository = MatchRepository(tmp_path / "runtime.sqlite3")
    repository.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    before = repository.replay(state.match_id)
    with pytest.raises(IllegalActionError, match="require manual resolution"):
        repository.apply(state.match_id, _request(state, selected_card_instance_ids=[]))
    assert repository.replay(state.match_id) == before


def test_manual_adjustment_can_finish_the_explicit_blocker_without_hidden_mutation(tmp_path):
    from loveca.simulation.models import ActionRequest

    state = _state(strict=True)
    _unknown_source(state, "attached")
    assert any(a.action_type == "manual_adjustment" for a in generate_legal_actions(state))
    repository = MatchRepository(tmp_path / "runtime.sqlite3")
    repository.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    action = ActionRequest(
        action_type="manual_adjustment", player_id="player_1", expected_revision=state.revision,
        payload={"source_invocation_id": "audit-parent", "source_effect_id": ROOT,
                 "source_card_instance_id": "source-live", "adjustments": [{
                     "adjustment_type": "set_flag", "target_player_id": "player_1",
                     "flag": "audit_manual_confirmation", "value": True, "duration": "turn",
                 }]},
    )
    result = repository.apply(state.match_id, action)
    assert not result.state.pending_effects
    assert result.state.players["player_1"].member_area == state.players["player_1"].member_area
    assert any(e.event_type == "manual_adjustment_applied" for e in result.events)
    replay = repository.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == result.state.model_dump(mode="json")
    assert replay["events"] == [e.model_dump(mode="json") for e in result.events]


@pytest.mark.parametrize("defect", ["safe_structured", "wrong_effect", "wrong_card"])
def test_manual_fallback_requires_current_gap_and_the_exact_pending_source(defect):
    from loveca.simulation.models import ActionRequest

    state = _state(strict=True)
    if defect != "safe_structured":
        _unknown_source(state, "attached")
    payload = {"source_invocation_id": "audit-parent", "source_effect_id": ROOT,
               "source_card_instance_id": "source-live", "adjustments": [{
                   "adjustment_type": "set_flag", "target_player_id": "player_1",
                   "flag": "audit_manual_confirmation", "value": True, "duration": "turn",
               }]}
    if defect == "wrong_effect":
        payload["source_effect_id"] = "wrong:1"
    elif defect == "wrong_card":
        payload["source_card_instance_id"] = "target"
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, ActionRequest(action_type="manual_adjustment", player_id="player_1",
                                          expected_revision=state.revision, payload=payload))
    assert match_state_hash(state) == before


@pytest.mark.parametrize("strict", [False, True])
def test_sql_replay_preserves_policy_native_entry_draws_and_hidden_views(tmp_path, strict):
    state = _state(strict=strict)
    repository = MatchRepository(tmp_path / "runtime.sqlite3")
    repository.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    before = match_state_hash(state)
    result = repository.apply(state.match_id, _request(state))
    replay = repository.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == result.state.model_dump(mode="json")
    assert replay["events"] == [e.model_dump(mode="json") for e in result.events]
    assert replay["metadata"]["final_state_hash"] == match_state_hash(result.state)
    assert len(result.state.players["player_1"].hand) == len(state.players["player_1"].hand) + 2
    assert result.state.players["player_1"].member_area["right"] == "target"
    assert state.cards["old"].instance_id in result.state.players["player_1"].waiting_room
    assert not result.state.pending_effects
    assert match_state_hash(state) == before
    for viewer, hidden in [("player_1", "opponent-private"), ("player_2", "live-1")]:
        payload = _match_state_payload(result.state, events=result.events,
                                       legal_actions=result.legal_actions, player_id=viewer)
        assert hidden not in payload["state"]["cards"]
        assert f'"{hidden}"' not in json.dumps(payload["events"])


def test_hidden_card_text_does_not_affect_restrictions_or_player_payload():
    state = _state(strict=True)
    other = state.model_copy(deep=True)
    for key in ["opponent-private", *other.players["player_2"].main_deck]:
        other.cards[key].card.card_code = "HIDDEN-CHANGE"
        other.cards[key].card.raw_effect_text_ja = "【常時】未知の能力。"
        other.cards[key].card.effect_ids = ["missing-hidden:1"]
    hidden_live = _unknown_source(other, "opponent_live")
    hidden_live.face_up = False
    state.cards[hidden_live.instance_id] = hidden_live.model_copy(deep=True)
    state.cards[hidden_live.instance_id].card.raw_effect_text_ja = None
    state.cards[hidden_live.instance_id].card.effect_ids = []
    state.players["player_2"].live_area.append(hidden_live.instance_id)
    assert _options(state) == _options(other)
    view = lambda s: _match_state_payload(s, events=[], legal_actions=generate_legal_actions(s), player_id="player_1")
    assert view(state) == view(other)


@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_four_ai_policies_only_deploy_to_safe_native_slots(policy):
    state = _state(strict=True)
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy))
    legal = generate_legal_actions(state)
    decision = controller.choose_action(state, legal, controlled_player_ids={"player_1"})
    assert isinstance(decision, SimpleAIDecision)
    assert decision.action.action_type == "resolve_effect"
    assert decision.action.payload["to_slot"] == "right"
    assert apply_action(state, decision.action).state.players["player_1"].member_area["right"] == "target"
    changed = state.model_copy(deep=True)
    changed.cards["opponent-private"].card.card_code = "PRIVATE-CHANGED"
    assert controller.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={"player_1"}).action == decision.action
    _unknown_source(state, "attached")
    blocked = controller.choose_action(state, generate_legal_actions(state), controlled_player_ids={"player_1"})
    assert isinstance(blocked, SimpleAIBlocker)
    assert blocked.reason == "overlap_source_requires_manual_review"


@pytest.mark.parametrize("action_type", ["draw_card", "gain_blade", "pay_energy"])
def test_policy_remains_restricted_to_stage_deployment(action_type):
    with pytest.raises(ValueError, match="overlap observer policy"):
        EffectOperation(action_type=action_type, amount=1, overlap_observer_policy=POLICY)


def test_policy_cannot_be_a_cost():
    raw = _state(strict=True).effect_definitions[ROOT].model_dump(mode="json")
    raw["cost"] = [raw["actions"][0]]
    with pytest.raises(ValueError, match="cannot be used as a cost"):
        EffectDefinition.model_validate(raw)


def test_registry_and_old_shape_are_not_promoted_or_rewritten():
    raw = EffectOperation(action_type="draw_card", amount=1).model_dump(mode="json")
    assert "overlap_observer_policy" not in raw
    ids = {"PL!-PR-015:1", "PL!SP-PR-020:1", *(f"PL!N-pb1-{n}:1" for n in ["013", "015", "017", "023"])}
    effects = [e for e in load_effect_registry().effects if e.effect_id in ids]
    assert len(effects) == 6 and all(e.simulation_support == "manual_resolution" for e in effects)
