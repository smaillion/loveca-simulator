import json

import pytest
from pydantic import ValidationError

from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation.effects import EffectDefinition
from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions
from loveca.simulation.online import match_state_hash
from loveca.webapp import _match_state_payload
from test_ll_bp2_composite_name_cost_audit import _actual, EFFECT
from test_printemps_ready_history_boundary import _advance, _manual, _repo, _replay, _resolve, _state

PROBE = "UNREGISTERED-NAMED-DISCARD:1"
NAMES = ["渡辺 曜", "鬼塚夏美", "大沢瑠璃乃"]


def _probe(owner, control=False):
    state = _actual(owner)
    raw = state.effect_definitions[EFFECT].model_dump(mode="json")
    raw.update(effect_id=PROBE, card_code="UNREGISTERED-NAMED-DISCARD", duration=None,
        actions=[{"action_type": "draw_card", "amount": 1}],
        cost_choice={"choice_type": "card_from_zone", "zone": "hand", "target_player": "self",
                     "name_ja_any": NAMES, "minimum": 0, "maximum": 0,
                     "selection_policy": "private_partial_names_unlimited_discard_v1"})
    state.effect_definitions = {PROBE: EffectDefinition.model_validate(raw)}
    if control:
        state.effect_definitions["CONTROL"] = _state(owner=owner, control=True).effect_definitions["CONTROL"]
        state.cards["live-1"].card.effect_ids.append("CONTROL")
    state.cards["source-live"].card.card_code = "UNREGISTERED-NAMED-DISCARD"
    state.cards["source-live"].card.effect_ids = [PROBE]
    state.cards["unrelated-hand"] = state.cards["single-hand"].model_copy(deep=True)
    state.cards["unrelated-hand"].instance_id = "unrelated-hand"
    state.cards["unrelated-hand"].card.name_ja = "UNRELATED"
    state.players[owner].hand.append("unrelated-hand")
    for index in range(4):
        key = f"single-extra-{index}"
        state.cards[key] = state.cards["single-hand"].model_copy(deep=True)
        state.cards[key].instance_id = key
        state.players[owner].hand.append(key)
    return state


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_composite_and_all_names_are_candidates_and_payable_sql(tmp_path, owner):
    state = _probe(owner)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    legal = next(a for a in generate_legal_actions(current) if a.action_type == "resolve_effect")
    invocation = next(i for i in legal.options["invocations"] if i["effect_id"] == PROBE)
    chosen = ["composite-hand", "single-hand", *(f"single-extra-{i}" for i in range(4))]
    assert set(invocation["candidate_card_instance_ids"]) == set(chosen)
    assert invocation["card_selection_maximum"] == len(chosen)
    result = repo.apply(state.match_id, _resolve(current, PROBE, accepted=True, selected_card_instance_ids=chosen))
    assert all(i in result.state.players[owner].waiting_room for i in chosen)
    _replay(repo, result.state)


@pytest.mark.parametrize("field,value", [("card_code", "FORMAL"), ("is_optional", False),
    ("trigger", "member_played"), ("condition", {"unknown": True}),
    ("actions", [{"action_type": "draw_card", "amount": 2}]),
    ("cost", [{"action_type": "discard_from_hand", "amount": 1}])])
def test_policy_rejects_other_parent_shapes(field, value):
    raw = _probe("player_1").effect_definitions[PROBE].model_dump(mode="json")
    raw[field] = value
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate(raw)


@pytest.mark.parametrize("field,value", [("maximum", 4), ("minimum", 1), ("zone", "waiting_room"),
    ("target_player", "opponent"), ("name_ja_any", ["渡辺 曜"]), ("card_type", "member")])
def test_policy_rejects_other_private_cost_shapes(field, value):
    raw = _probe("player_1").effect_definitions[PROBE].model_dump(mode="json")
    raw["cost_choice"][field] = value
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate(raw)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_empty_candidates_still_allow_zero_cost_sql(tmp_path, owner):
    state = _probe(owner)
    for key in state.players[owner].hand:
        state.cards[key].card.name_ja = "UNRELATED"
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    legal = next(a for a in generate_legal_actions(current) if a.action_type == "resolve_effect")
    invocation = next(i for i in legal.options["invocations"] if i["effect_id"] == PROBE)
    assert invocation["candidate_card_instance_ids"] == []
    assert invocation["card_selection_maximum"] == 0
    result = repo.apply(state.match_id, _resolve(current, PROBE, accepted=True, selected_card_instance_ids=[]))
    _replay(repo, result.state)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("count", [0, 1, 4, 6])
def test_dynamic_zero_to_all_cost_sql(tmp_path, owner, count):
    state = _probe(owner)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    all_ids = ["composite-hand", "single-hand", *(f"single-extra-{i}" for i in range(4))]
    chosen = all_ids[:count]
    result = repo.apply(state.match_id, _resolve(current, PROBE, accepted=True, selected_card_instance_ids=chosen))
    assert all(i in result.state.players[owner].waiting_room for i in chosen)
    assert all(i in result.state.players[owner].hand for i in all_ids[count:])
    assert next(e for e in result.events if e.event_type == "effect_cost_paid").data["selected_card_instance_ids"] == chosen
    _replay(repo, result.state)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("selection", [["single-hand", "single-hand"], ["unrelated-hand"], ["unknown-id"]])
def test_illegal_cost_atomic_sql(tmp_path, owner, selection):
    state = _probe(owner)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    before = match_state_hash(current)
    with pytest.raises(IllegalActionError):
        repo.apply(state.match_id, _resolve(current, PROBE, accepted=True, selected_card_instance_ids=selection))
    assert match_state_hash(repo.get_state(state.match_id)) == before
    _replay(repo, current)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_decline_preserves_hand_sql(tmp_path, owner):
    state = _probe(owner)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    result = repo.apply(state.match_id, _resolve(current, PROBE, accepted=False)).state
    assert result.players[owner].hand == current.players[owner].hand
    _replay(repo, result)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("payload", [{"selected_branch": "fake"}, {"energy_instance_ids": ["fake"]},
    {"accepted": False, "selected_card_instance_ids": ["single-hand"]}])
def test_extra_client_parameters_are_rejected_atomically_sql(tmp_path, owner, payload):
    state = _probe(owner)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    before = match_state_hash(current)
    with pytest.raises(IllegalActionError):
        repo.apply(state.match_id, _resolve(current, PROBE, **payload))
    assert match_state_hash(repo.get_state(state.match_id)) == before
    _replay(repo, current)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_wrong_actor_is_rejected_atomically_sql(tmp_path, owner):
    state = _probe(owner)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    before = match_state_hash(current)
    other = "player_2" if owner == "player_1" else "player_1"
    action = _resolve(current, PROBE, accepted=True, selected_card_instance_ids=["single-hand"])
    with pytest.raises(IllegalActionError):
        repo.apply(state.match_id, action.model_copy(update={"player_id": other}))
    assert match_state_hash(repo.get_state(state.match_id)) == before
    _replay(repo, current)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_hidden_departed_source_and_recent_events_sql(tmp_path, owner):
    state = _probe(owner, control=True)
    repo = _repo(state, tmp_path)
    triggered = repo.apply(state.match_id, _advance(state))
    moved = repo.apply(state.match_id, _manual(triggered.state, "CONTROL", [
        {"adjustment_type": "move_card", "target_card_instance_id": "source-live", "to_zone": "main_deck"},
    ]))
    result = repo.apply(state.match_id, _resolve(moved.state, PROBE, accepted=True,
        selected_card_instance_ids=["composite-hand"]))
    opponent = "player_2" if owner == "player_1" else "player_1"
    for viewer in (owner, opponent):
        payload = _match_state_payload(result.state, events=triggered.events + moved.events + result.events,
            legal_actions=generate_legal_actions(result.state), player_id=viewer)
        text = json.dumps(payload)
        assert "source-live" not in text
        assert "composite-hand" in payload["state"]["cards"]
        if viewer == opponent:
            assert all(i not in text for i in result.state.players[owner].hand)
    _replay(repo, result.state)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_ai_actual_choice_and_hidden_identity(owner, policy):
    state = _probe(owner)
    current = apply_action(state, _advance(state)).state
    before = match_state_hash(current)
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    decision = controller.choose_action(current, generate_legal_actions(current), controlled_player_ids={owner})
    assert isinstance(decision, SimpleAIDecision)
    changed = current.model_copy(deep=True)
    opponent = "player_2" if owner == "player_1" else "player_1"
    player = changed.players[opponent]
    for key in list(player.main_deck + player.hand):
        card = changed.cards.pop(key)
        replacement = "hidden-" + key
        card.instance_id = replacement
        card.card.name_ja = card.card.card_code = "HIDDEN"
        card.card.blade = 99
        changed.cards[replacement] = card
        player.main_deck = [replacement if i == key else i for i in player.main_deck]
        player.hand = [replacement if i == key else i for i in player.hand]
    changed_before = match_state_hash(changed)
    assert controller.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={owner}) == decision
    assert match_state_hash(current) == before and match_state_hash(changed) == changed_before
    apply_action(current, decision.action)
    from tools.ai_sandbox.semantic_playtest import build_api_play_context, build_agent_context
    for builder in (build_api_play_context, build_agent_context):
        context = json.dumps(builder(current, generate_legal_actions(current)))
        assert all(i not in context for i in current.players[opponent].main_deck + current.players[opponent].hand)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_recent_trigger_and_payment_events_keep_unselected_hand_private(owner):
    state = _probe(owner)
    triggered = apply_action(state, _advance(state))
    current = triggered.state
    resolved = apply_action(current, _resolve(current, PROBE, accepted=True, selected_card_instance_ids=["composite-hand"]))
    opponent = "player_2" if owner == "player_1" else "player_1"
    payload = _match_state_payload(resolved.state, events=triggered.events + resolved.events,
        legal_actions=generate_legal_actions(resolved.state), player_id=opponent)
    serialized = json.dumps(payload)
    assert "composite-hand" in payload["state"]["cards"]
    assert all(i not in serialized for i in resolved.state.players[owner].hand)
