from copy import deepcopy
from pathlib import Path

import pytest
from test_nijigasaki_inspection import _state as _base_state, _candidate
from test_all_active_live_requirement_boundary import _exclusive

from loveca.simulation.effects import EffectDefinition
from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions
from loveca.simulation.models import ActionRequest
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository
from loveca.webapp import _match_state_payload

CODE = "PL!N-bp7-005"
EFFECT = CODE + ":1"
POLICY = "public_diverdiva_energy_modes"
RULE_REFERENCE_IDS = ("1.3.2", "2.3.2.1", "4.5.5.2", "9.6.2.4.2", "9.7.7")


def _state(*, condition=True, legacy=False):
    state = _base_state(CODE)
    raw = deepcopy(_candidate(CODE).to_registry_entry())
    if legacy:
        raw.update(choice=None, actions=[{"action_type": "manual_resolution"}],
                   execution_mode="manual_resolution", simulation_support="manual_resolution", review_status="parsed_draft")
    state.effect_definitions = {EFFECT: EffectDefinition.model_validate(raw)}
    p = state.players["player_1"]
    p.energy_area = [f"energy-{i}" for i in range(11)]
    state.cards["karin"] = state.cards["good-member"].model_copy(update={"instance_id": "karin"}, deep=True)
    state.cards["karin"].card.name_ja = "朝香果林"
    state.cards["karin"].card.unit_keys = ["diverdiva"] if condition else ["azuna"]
    p.member_area = {"left": "karin", "center": None, "right": None}
    p.member_area_attachments = {"left": [], "center": [], "right": []}
    state.cards["new-energy"] = state.cards["energy-0"].model_copy(update={"instance_id": "new-energy", "face_up": False}, deep=True)
    p.energy_deck = ["new-energy"]
    state.effect_order_policy = "ap_nap_player_choice"
    _exclusive(state)
    return state


def _play(state):
    return ActionRequest(action_type="play_member", player_id="player_1", expected_revision=state.revision,
        payload={"card_instance_id": "source-live", "slot": "center", "energy_instance_ids": list(state.players["player_1"].energy_area), "use_baton_touch": False})


def _resolve(state, **payload):
    inv = next(i for i in state.pending_effects if i.effect_id == EFFECT)
    return ActionRequest(action_type="resolve_effect", player_id=inv.player_id, expected_revision=state.revision,
                         payload={"invocation_id": inv.invocation_id, **payload})


def test_native_onplay_branches_ready_two_without_manual():
    begun = apply_action(_state(), _play(_state())).state
    assert begun.effect_definitions[EFFECT].choice.selection_policy == POLICY
    selected = apply_action(begun, _resolve(begun, selected_branch="ready_energy")).state
    result = apply_action(selected, _resolve(selected, selected_card_instance_ids=["energy-0", "energy-1"]))
    assert not result.state.pending_effects
    assert [result.state.cards[k].orientation for k in ["energy-0", "energy-1", "energy-2"]] == ["active", "active", "wait"]


def _begun(**kwargs):
    state = _state(**kwargs)
    return apply_action(state, _play(state)).state


def _event(result):
    return next(e.data for e in result.events if e.event_type == "effect_diverdiva_energy_resolved")


def _options(state):
    return next(a for a in generate_legal_actions(state) if a.action_type == "resolve_effect").options["invocations"][0]


@pytest.mark.parametrize("waiting", [0, 1, 2, 3])
def test_ready_exact_possible_count_sql(tmp_path, waiting):
    state = _begun()
    for i, key in enumerate(state.players["player_1"].energy_area):
        state.cards[key].orientation = "wait" if i < waiting else "active"
    repo = MatchRepository(tmp_path / "ready.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    selected = repo.apply(state.match_id, _resolve(state, selected_branch="ready_energy")).state
    assert _options(selected)["card_selection_minimum"] == min(2, waiting)
    result = repo.apply(state.match_id, _resolve(selected, selected_card_instance_ids=[f"energy-{i}" for i in range(min(2, waiting))]))
    assert _event(result)["readied_count"] == min(2, waiting)
    assert not result.state.pending_effects
    assert repo.replay(state.match_id)["metadata"]["deterministic_replay_verified"] is True


@pytest.mark.parametrize("target", ["source-live", "karin", "other-nijigasaki"])
@pytest.mark.parametrize("empty", [False, True])
def test_attachment_from_energy_deck_not_energy_area_sql(tmp_path, target, empty):
    state = _begun()
    p = state.players["player_1"]
    if target == "other-nijigasaki":
        state.cards[target] = state.cards["karin"].model_copy(update={"instance_id": target}, deep=True)
        state.cards[target].card.unit_keys = ["azuna"]
        p.member_area["right"] = target
    if empty:
        p.energy_deck = []
    repo = MatchRepository(tmp_path / "attach.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    selected = repo.apply(state.match_id, _resolve(state, selected_branch="attach_energy_deck")).state
    assert _options(selected)["card_selection_minimum"] == int(not empty)
    result = repo.apply(state.match_id, _resolve(selected, selected_card_instance_ids=[] if empty else [target]))
    assert _event(result)["attached_count"] == int(not empty)
    assert result.state.players["player_1"].energy_area == p.energy_area
    assert not any(e.event_type == "energy_added" for e in result.events)
    if not empty:
        slot = next(k for k, v in p.member_area.items() if v == target)
        assert result.state.players["player_1"].member_area_attachments[slot] == ["new-energy"]
        assert result.state.cards["new-energy"].face_up
    _exclusive(result.state)
    assert repo.replay(state.match_id)["metadata"]["deterministic_replay_verified"] is True


@pytest.mark.parametrize("names,units,expected", [
    (["宮下 愛"], ["diverdiva"], False),
    (["宮下 愛", "宮下愛"], ["diverdiva", "diverdiva"], False),
    (["宮下 愛", "朝香果林"], ["diverdiva", "diverdiva"], True),
    (["宮下 愛", "朝香果林"], ["diverdiva", "azuna"], False),
    (["宮下 愛＆朝香果林"], ["diverdiva"], False),
    (["宮下 愛＆朝香果林", "宮下 愛"], ["diverdiva", "diverdiva"], True),
])
def test_physical_members_distinct_names_not_printings_or_work(names, units, expected):
    from loveca.simulation.engine import _diverdiva_two_names
    from loveca.simulation.models import EffectInvocation
    state = _state()
    p = state.players["player_1"]
    p.member_area = {"left": None, "center": None, "right": None}
    for i, (name, unit) in enumerate(zip(names, units)):
        key = "name-" + str(i)
        state.cards[key] = state.cards["karin"].model_copy(update={"instance_id": key}, deep=True)
        state.cards[key].card.name_ja = name
        state.cards[key].card.unit_keys = [unit]
        p.member_area[["left", "center", "right"][i]] = key
    inv = EffectInvocation(invocation_id="probe", effect_id=EFFECT, source_card_instance_id="source-live", player_id="player_1", trigger_event="member_played")
    assert _diverdiva_two_names(state, inv) == expected


def test_condition_false_native_has_no_branch_or_extra_effect():
    state = _state(condition=False)
    result = apply_action(state, _play(state))
    assert not result.state.pending_effects
    assert _event(result)["condition_met"] is False
    assert result.state.players["player_1"].energy_deck == ["new-energy"]


@pytest.mark.parametrize("bad", [{"selected_branch": "other"}, {"selected_branch": ["ready_energy", "attach_energy_deck"]},
    {"selected_branch": "ready_energy", "selected_card_instance_ids": ["energy-0"]}, {"accepted": False},
    {"selected_branch": "ready_energy", "energy_instance_ids": ["energy-0"]}])
def test_illegal_initial_submission_is_atomic(bad):
    state = _begun()
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _resolve(state, **bad))
    assert match_state_hash(state) == before


@pytest.mark.parametrize("branch,bad", [("ready_energy", ["energy-0"]), ("ready_energy", ["energy-0", "energy-0"]),
    ("ready_energy", ["new-energy", "energy-0"]), ("attach_energy_deck", ["opponent-secret"]),
    ("attach_energy_deck", ["cost"]), ("attach_energy_deck", ["source-live", "karin"])])
def test_illegal_followup_is_atomic(branch, bad):
    state = _begun()
    state = apply_action(state, _resolve(state, selected_branch=branch)).state
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _resolve(state, selected_card_instance_ids=bad))
    assert match_state_hash(state) == before


@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
@pytest.mark.parametrize("branch", [None, "ready_energy", "attach_energy_deck"])
@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_four_ai_branch_followup_hidden_invariance_and_no_input_change(policy, branch, owner):
    from loveca.simulation.ai import SimpleAIController, SimpleAIPolicy, SimpleAIDecision
    state = _begun()
    if branch:
        state = apply_action(state, _resolve(state, selected_branch=branch)).state
    if owner == "player_2":
        from test_mirakura_front_position_boundary import _swap_roles
        state = _swap_roles(state)
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    before = match_state_hash(state)
    decision = controller.choose_action(state, generate_legal_actions(state), controlled_player_ids={owner})
    assert isinstance(decision, SimpleAIDecision)
    changed = state.model_copy(deep=True)
    for key in ["tail", "opponent-secret", "new-energy"]:
        instance = changed.cards.pop(key)
        replacement = "hidden-" + key
        instance.instance_id = replacement
        instance.card.card_code = instance.card.name_ja = "HIDDEN-CHANGED"
        changed.cards[replacement] = instance
        for p in changed.players.values():
            for zone in ["main_deck", "hand", "energy_deck"]:
                setattr(p, zone, [replacement if x == key else x for x in getattr(p, zone)])
    assert controller.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={owner}).action == decision.action
    assert before == match_state_hash(state)
    result = apply_action(state, decision.action)
    if result.state.pending_effects:
        follow = controller.choose_action(result.state, result.legal_actions, controlled_player_ids={owner})
        assert isinstance(follow, SimpleAIDecision)
        result = apply_action(result.state, follow.action)
    assert not result.state.pending_effects
    assert _event(result)["attached_count"] + _event(result)["readied_count"] > 0


def _control_state(*, condition=True):
    state = _state(condition=condition)
    raw = state.effect_definitions[EFFECT].model_dump(mode="json")
    raw.update(effect_id="CONTROL", choice=None, actions=[{"action_type": "manual_resolution"}],
               execution_mode="manual_resolution", simulation_support="manual_resolution", review_status="parsed_draft")
    state.effect_definitions["CONTROL"] = EffectDefinition.model_validate(raw)
    state.cards["source-live"].card.effect_ids.append("CONTROL")
    return state


def _manual(state, inv, changes):
    return ActionRequest(action_type="manual_adjustment", player_id=inv.player_id, expected_revision=state.revision,
        payload={"source_invocation_id": inv.invocation_id, "source_effect_id": inv.effect_id,
            "source_card_instance_id": inv.source_card_instance_id, "reason": "AUDIT CONTROL only",
            "adjustments": [{"target_player_id": inv.player_id, **c} for c in changes]})


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("move", ["hand", "main_deck", "return", "position"])
def test_source_departure_return_position_and_owner_sql(tmp_path, owner, move):
    from test_mirakura_front_position_boundary import _swap_roles
    state = _control_state()
    state.cards["other-ai"] = state.cards["karin"].model_copy(update={"instance_id": "other-ai"}, deep=True)
    state.cards["other-ai"].card.name_ja = "宮下 愛"
    state.players["player_1"].member_area["right"] = "other-ai"
    if owner == "player_2":
        state = _swap_roles(state)
        state.phase, state.active_player_id = "second_main", owner
    play = _play(state).model_copy(update={"player_id": owner}, deep=True)
    play.payload["energy_instance_ids"] = list(state.players[owner].energy_area)
    repo = MatchRepository(tmp_path / "source.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    begun = repo.apply(state.match_id, play).state
    ctrl = next(i for i in begun.pending_effects if i.effect_id == "CONTROL")
    changes = [{"adjustment_type": "position_change", "from_slot": "center", "to_slot": "right"}] if move == "position" else [
        {"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "main_deck" if move == "main_deck" else "hand"}]
    if move == "return":
        changes.append({"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "member_center"})
    moved = repo.apply(state.match_id, _manual(begun, ctrl, changes)).state
    selected = repo.apply(state.match_id, _resolve(moved, selected_branch="attach_energy_deck")).state
    result = repo.apply(state.match_id, _resolve(selected, selected_card_instance_ids=["karin"]))
    assert _event(result)["attached_count"] == 1
    for viewer in ["player_1", "player_2"]:
        payload = _match_state_payload(result.state, events=result.events, legal_actions=result.legal_actions, player_id=viewer)
        if move == "main_deck" or (move == "hand" and viewer != owner):
            assert "source-live" not in payload["state"]["cards"]
        assert "tail" not in payload["state"]["cards"]
    _exclusive(result.state)
    assert repo.replay(state.match_id)["metadata"]["deterministic_replay_verified"] is True


@pytest.mark.parametrize("start,end", [(False, True), (True, False)])
def test_condition_is_checked_at_resolution_not_trigger_sql(tmp_path, start, end):
    state = _control_state(condition=start)
    state.cards["new-karin"] = state.cards["karin"].model_copy(update={"instance_id": "new-karin"}, deep=True)
    state.cards["new-karin"].card.unit_keys = ["diverdiva"]
    state.players["player_1"].hand.append("new-karin")
    repo = MatchRepository(tmp_path / "condition.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    begun = repo.apply(state.match_id, _play(state)).state
    ctrl = next(i for i in begun.pending_effects if i.effect_id == "CONTROL")
    changes = [{"adjustment_type": "move_card", "target_card_instance_id": "new-karin" if end else "karin", "to_zone": "member_right" if end else "hand"}]
    result = repo.apply(state.match_id, _manual(begun, ctrl, changes))
    if end:
        selected = repo.apply(state.match_id, _resolve(result.state, selected_branch="ready_energy")).state
        result = repo.apply(state.match_id, _resolve(selected, selected_card_instance_ids=["energy-0", "energy-1"]))
    assert _event(result)["condition_met"] is end
    assert not result.state.pending_effects
    assert repo.replay(state.match_id)["metadata"]["deterministic_replay_verified"] is True


def test_legacy_manual_and_attachment_cleanup_sql(tmp_path):
    state = _state(legacy=True)
    repo = MatchRepository(tmp_path / "legacy.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    begun = repo.apply(state.match_id, _play(state)).state
    result = repo.apply(state.match_id, _manual(begun, begun.pending_effects[0], [{"adjustment_type": "set_flag", "flag": "legacy", "duration": "turn"}]))
    assert not any(e.event_type == "effect_diverdiva_energy_resolved" for e in result.events)
    assert repo.replay(state.match_id)["metadata"]["deterministic_replay_verified"] is True


@pytest.mark.parametrize("change", [{"amount": 2}, {"target": "source"}, {"branch": "ready_energy"}, {"card_type": "member"}])
def test_bounded_operation_shape(change):
    from pydantic import ValidationError
    raw = _state().effect_definitions[EFFECT].model_dump(mode="json")
    raw["actions"][1].update(change)
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate(raw)


@pytest.mark.parametrize("change", [{"is_optional": True}, {"duration": "game"}, {"timing": "live_start"}, {"condition": {"minimum_energy_deck_cards": 1}}, {"frequency_limit": "once_per_turn"}])
def test_bounded_definition(change):
    from pydantic import ValidationError
    raw = _state().effect_definitions[EFFECT].model_dump(mode="json")
    raw.update(change)
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate(raw)


def test_empty_ui_energy_argument_is_compatible_but_no_cost_is_paid():
    state = _begun()
    selected = apply_action(state, _resolve(state, selected_branch="attach_energy_deck", energy_instance_ids=[])).state
    result = apply_action(selected, _resolve(selected, selected_card_instance_ids=["karin"], energy_instance_ids=[]))
    assert _event(result)["attached_count"] == 1
    assert result.state.players["player_1"].energy_area == state.players["player_1"].energy_area


def test_attachment_cleanup_and_current_hidden_energy_deck_sql(tmp_path):
    state = _begun()
    state.cards["energy-tail"] = state.cards["new-energy"].model_copy(update={"instance_id": "energy-tail"}, deep=True)
    state.players["player_1"].energy_deck.append("energy-tail")
    repo = MatchRepository(tmp_path / "cleanup.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    selected = repo.apply(state.match_id, _resolve(state, selected_branch="attach_energy_deck")).state
    result = repo.apply(state.match_id, _resolve(selected, selected_card_instance_ids=["karin"]))
    for viewer in ["player_1", "player_2"]:
        payload = _match_state_payload(result.state, events=result.events, legal_actions=result.legal_actions, player_id=viewer)
        assert "energy-tail" not in payload["state"]["cards"]
        assert "new-energy" in payload["state"]["cards"]
    final = repo.apply(state.match_id, ActionRequest(action_type="manual_adjustment", player_id="player_1", expected_revision=result.state.revision,
        payload={"reason": "AUDIT target departure", "adjustments": [{"target_player_id": "player_1", "adjustment_type": "move_card", "target_card_instance_id": "karin", "to_zone": "hand"}]}))
    assert final.state.players["player_1"].member_area_attachments["left"] == []
    assert "new-energy" in final.state.players["player_1"].energy_deck
    assert "new-energy" not in final.state.players["player_1"].energy_area
    assert repo.replay(state.match_id)["metadata"]["deterministic_replay_verified"] is True


def test_branch_locks_manual_and_rejects_branch_replacement():
    state = _begun()
    state = apply_action(state, _resolve(state, selected_branch="attach_energy_deck")).state
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _resolve(state, selected_branch="ready_energy", selected_card_instance_ids=["karin"]))
    with pytest.raises(IllegalActionError):
        apply_action(state, _manual(state, state.pending_effects[0], [{"adjustment_type": "set_flag", "flag": "bad", "duration": "game"}]))
    assert match_state_hash(state) == before


@pytest.mark.parametrize("field,value", [("card_code", "OTHER"), ("text_revision_id", 869), ("raw_text_hash", "bad"), ("raw_effect_text_ja", "bad")])
def test_exact_full_generator_binding(field, value):
    from loveca.simulation.effect_candidates import _onplay_diverdiva_energy_modes
    card = _state().cards["source-live"].card
    row = {"card_code": CODE, "text_revision_id": 868, "raw_text_hash": card.raw_text_hash, "raw_effect_text_ja": card.raw_effect_text_ja}
    assert _onplay_diverdiva_energy_modes(row) is not None
    assert _onplay_diverdiva_energy_modes({**row, field: value}) is None


@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_four_ai_failed_condition_in_ordered_sibling_queue(policy):
    from loveca.simulation.ai import SimpleAIController, SimpleAIPolicy, SimpleAIDecision
    state = _control_state(condition=False)
    state = apply_action(state, _play(state)).state
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    decision = controller.choose_action(state, generate_legal_actions(state), controlled_player_ids={"player_1"})
    assert isinstance(decision, SimpleAIDecision)
    assert "selected_branch" not in decision.action.payload
    result = apply_action(state, decision.action)
    assert _event(result)["condition_met"] is False
    assert [i.effect_id for i in result.state.pending_effects] == ["CONTROL"]
