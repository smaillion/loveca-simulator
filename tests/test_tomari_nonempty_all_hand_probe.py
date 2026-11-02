import json

import pytest
from pydantic import ValidationError

from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation.effects import EffectDefinition
from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions
from loveca.simulation.online import match_state_hash
from loveca.webapp import _match_state_payload
from test_printemps_ready_history_boundary import _manual, _repo, _replay, _resolve
from test_tomari_all_hand_discard_scope import EFFECT, _actual, _play_for

POLICY = "private_all_hand_nonempty_v1"
PROBE = "UNREGISTERED-TOMARI-ALL-HAND:1"


def _probe(owner, count=3, short=False):
    state = _actual(owner, count, short)
    raw = state.effect_definitions[EFFECT].model_dump(mode="json")
    raw.update(effect_id=PROBE, card_code="UNREGISTERED-TOMARI-ALL-HAND",
               execution_mode="prompt_then_resolve", simulation_support="test_validated_executable",
               review_status="test_validated", cost=[{"action_type": "discard_from_hand"}],
               cost_choice={"choice_type": "card_from_zone", "zone": "hand", "target_player": "self",
                            "minimum": 1, "maximum": 0, "selection_policy": POLICY},
               actions=[{"action_type": "draw_card", "amount": 6}])
    state.effect_definitions = {PROBE: EffectDefinition.model_validate(raw)}
    state.cards["source-live"].card.card_code = "UNREGISTERED-TOMARI-ALL-HAND"
    state.cards["source-live"].card.effect_ids = [PROBE]
    return state


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("count", [1, 2, 3, 4, 6])
def test_exact_all_hand_cost_and_draw_sql(tmp_path, owner, count):
    state = _probe(owner, count)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _play_for(state, owner)).state
    selected = list(current.players[owner].hand)
    options = next(a for a in generate_legal_actions(current) if a.action_type == "resolve_effect").options["invocations"][0]
    assert options["card_selection_minimum"] == options["card_selection_maximum"] == count
    result = repo.apply(state.match_id, _resolve(current, PROBE, accepted=True, selected_card_instance_ids=selected))
    assert all(i in result.state.players[owner].waiting_room for i in selected)
    paid = [e for e in result.events if e.event_type == "effect_cost_paid"]
    draws = [e for e in result.events if e.event_type == "cards_drawn"]
    assert len(paid) == 1 and paid[0].data["selected_card_instance_ids"] == selected
    assert len(draws) == 1 and len(draws[0].data["instance_ids"]) == 6
    _replay(repo, result.state)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("mode", ["partial", "duplicate", "unknown", "opponent", "empty", "extra", "wrong_owner"])
def test_illegal_cost_is_atomic_sql(tmp_path, owner, mode):
    state = _probe(owner, 3)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _play_for(state, owner)).state
    hand = list(current.players[owner].hand)
    other = "player_2" if owner == "player_1" else "player_1"
    selected = {"partial": hand[:1], "duplicate": [hand[0], hand[0], hand[1]],
                "unknown": hand + ["unknown"], "opponent": hand + [current.players[other].hand[0]],
                "empty": [], "extra": hand, "wrong_owner": hand}[mode]
    action = _resolve(current, PROBE, accepted=True, selected_card_instance_ids=selected)
    if mode == "extra":
        action.payload["selected_branch"] = "forged"
    if mode == "wrong_owner":
        action.player_id = other
    before = match_state_hash(current)
    with pytest.raises(IllegalActionError):
        repo.apply(state.match_id, action)
    assert match_state_hash(repo.get_state(state.match_id)) == before
    _replay(repo, current)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_empty_hand_does_not_enter_probe_and_decline_preserves_nonempty_sql(tmp_path, owner):
    state = _probe(owner, 0)
    repo = _repo(state, tmp_path)
    result = repo.apply(state.match_id, _play_for(state, owner))
    assert not result.state.pending_effects
    assert any(e.event_type == "effect_not_activatable" and e.data["effect_id"] == PROBE for e in result.events)
    assert not any(e.event_type in {"effect_cost_paid", "cards_drawn"} for e in result.events)
    _replay(repo, result.state)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_decline_keeps_hand_and_forged_decline_selection_is_rejected_sql(tmp_path, owner):
    state = _probe(owner, 3)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _play_for(state, owner)).state
    before = match_state_hash(current)
    with pytest.raises(IllegalActionError):
        repo.apply(state.match_id, _resolve(current, PROBE, accepted=False,
                   selected_card_instance_ids=list(current.players[owner].hand)))
    assert match_state_hash(repo.get_state(state.match_id)) == before
    player_before = current.players[owner].model_dump(mode="json")
    result = repo.apply(state.match_id, _resolve(current, PROBE, accepted=False))
    assert result.state.players[owner].model_dump(mode="json") == player_before
    assert not any(e.event_type in {"effect_cost_paid", "cards_drawn"} for e in result.events)
    _replay(repo, result.state)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_selection_tracks_current_hand_not_previous_candidate_list(owner):
    state = _probe(owner, 3)
    current = apply_action(state, _play_for(state, owner)).state
    old_hand = list(current.players[owner].hand)
    moved = current.players[owner].main_deck.pop(0)
    current.players[owner].hand.append(moved)
    before = match_state_hash(current)
    with pytest.raises(IllegalActionError):
        apply_action(current, _resolve(current, PROBE, accepted=True, selected_card_instance_ids=old_hand))
    assert match_state_hash(current) == before
    result = apply_action(current, _resolve(current, PROBE, accepted=True,
                                            selected_card_instance_ids=current.players[owner].hand))
    paid = next(e for e in result.events if e.event_type == "effect_cost_paid")
    assert paid.data["selected_card_instance_ids"] == old_hand + [moved]


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_short_deck_refresh_and_draw_is_recorded_sql(tmp_path, owner):
    state = _probe(owner, 3, short=True)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _play_for(state, owner)).state
    selected = list(current.players[owner].hand)
    result = repo.apply(state.match_id, _resolve(current, PROBE, accepted=True, selected_card_instance_ids=selected))
    assert any(e.event_type == "deck_refreshed" for e in result.events)
    assert len(next(e for e in result.events if e.event_type == "cards_drawn").data["instance_ids"]) == 4
    _replay(repo, result.state)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("zone", ["hand", "main_deck"])
def test_departed_source_does_not_change_current_hand_obligation_sql(tmp_path, owner, zone):
    state = _probe(owner, 3)
    raw = state.effect_definitions[PROBE].model_dump(mode="json")
    raw.update(effect_id="CONTROL", cost=[], cost_choice=None, choice=None,
               actions=[{"action_type": "manual_resolution"}], execution_mode="manual_resolution",
               simulation_support="manual_resolution", is_optional=False)
    state.effect_definitions["CONTROL"] = EffectDefinition.model_validate(raw)
    state.cards["source-live"].card.effect_ids.append("CONTROL")
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _play_for(state, owner)).state
    current = repo.apply(state.match_id, _manual(current, "CONTROL", [{"adjustment_type": "move_card",
        "target_card_instance_id": "source-live", "to_zone": zone}])).state
    selected = list(current.players[owner].hand)
    assert ("source-live" in selected) == (zone == "hand")
    result = repo.apply(state.match_id, _resolve(current, PROBE, accepted=True, selected_card_instance_ids=selected))
    paid = next(e for e in result.events if e.event_type == "effect_cost_paid")
    assert paid.data["selected_card_instance_ids"] == selected
    _replay(repo, result.state)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_hidden_source_recent_events_do_not_authorize_hidden_identity(owner):
    state = _probe(owner, 3)
    raw = state.effect_definitions[PROBE].model_dump(mode="json")
    raw.update(effect_id="CONTROL", cost=[], cost_choice=None, choice=None,
               actions=[{"action_type": "manual_resolution"}], execution_mode="manual_resolution",
               simulation_support="manual_resolution", is_optional=False)
    state.effect_definitions["CONTROL"] = EffectDefinition.model_validate(raw)
    state.cards["source-live"].card.effect_ids.append("CONTROL")
    played = apply_action(state, _play_for(state, owner))
    moved = apply_action(played.state, _manual(played.state, "CONTROL", [{"adjustment_type": "move_card",
        "target_card_instance_id": "source-live", "to_zone": "main_deck"}]))
    current = moved.state
    events = played.events + moved.events
    for viewer in ("player_1", "player_2"):
        payload = _match_state_payload(current, events=events, legal_actions=generate_legal_actions(current), player_id=viewer)
        assert "source-live" not in json.dumps(payload)
    from tools.ai_sandbox.semantic_playtest import build_api_play_context, build_agent_context
    for builder in (build_api_play_context, build_agent_context):
        assert "source-live" not in json.dumps(builder(current, generate_legal_actions(current)))
    selected = list(current.players[owner].hand)
    resolved = apply_action(current, _resolve(current, PROBE, accepted=True, selected_card_instance_ids=selected))
    events += resolved.events
    opponent = "player_2" if owner == "player_1" else "player_1"
    payload = _match_state_payload(resolved.state, events=events, legal_actions=generate_legal_actions(resolved.state), player_id=opponent)
    assert all(i not in json.dumps(payload) for i in resolved.state.players[owner].hand)
    if "source-live" in resolved.state.players[owner].main_deck + resolved.state.players[owner].hand:
        assert "source-live" not in json.dumps(payload)


@pytest.mark.parametrize("field,value", [("card_code", "PL!SP-bp7-011"), ("is_optional", False),
                                        ("trigger", "live_started"), ("duration", "game")])
def test_rejects_non_probe_parent_shape(field, value):
    raw = _probe("player_1").effect_definitions[PROBE].model_dump(mode="json")
    raw[field] = value
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate(raw)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_ai_choice_and_hidden_identity_invariance(owner, policy):
    state = _probe(owner, 4)
    current = apply_action(state, _play_for(state, owner)).state
    before = match_state_hash(current)
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    decision = controller.choose_action(current, generate_legal_actions(current), controlled_player_ids={owner})
    assert isinstance(decision, SimpleAIDecision)
    assert set(decision.action.payload["selected_card_instance_ids"]) == set(current.players[owner].hand)
    changed = current.model_copy(deep=True)
    opponent = "player_2" if owner == "player_1" else "player_1"
    player = changed.players[opponent]
    for key in list(player.main_deck + player.hand):
        item = changed.cards.pop(key)
        replacement = "hidden-" + key
        item.instance_id = replacement
        item.card.name_ja = item.card.card_code = "HIDDEN"
        item.card.blade = 99
        changed.cards[replacement] = item
        player.main_deck = [replacement if i == key else i for i in player.main_deck]
        player.hand = [replacement if i == key else i for i in player.hand]
    changed_before = match_state_hash(changed)
    assert controller.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={owner}) == decision
    assert match_state_hash(changed) == changed_before and match_state_hash(current) == before
    apply_action(current, decision.action)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("short", [False, True])
def test_recent_cost_draw_events_and_constructed_provider_privacy(owner, short):
    state = _probe(owner, 3, short=short)
    played = apply_action(state, _play_for(state, owner))
    selected = list(played.state.players[owner].hand)
    resolved = apply_action(played.state, _resolve(played.state, PROBE, accepted=True, selected_card_instance_ids=selected))
    current, events = resolved.state, played.events + resolved.events
    opponent = "player_2" if owner == "player_1" else "player_1"
    for viewer in ("player_1", "player_2"):
        payload = _match_state_payload(current, events=events, legal_actions=generate_legal_actions(current), player_id=viewer)
        for player in current.players.values():
            assert all(i not in payload["state"]["cards"] for i in player.main_deck)
            if player.player_id != viewer:
                assert all(i not in payload["state"]["cards"] for i in player.hand)
    serialized = json.dumps(_match_state_payload(current, events=events, legal_actions=generate_legal_actions(current), player_id=opponent))
    assert all(i not in serialized for i in current.players[owner].hand)
    from tools.ai_sandbox.semantic_playtest import build_api_play_context, build_agent_context
    for builder in (build_api_play_context, build_agent_context):
        serialized = json.dumps(builder(current, generate_legal_actions(current)))
        assert all(i not in serialized for i in current.players[opponent].hand + current.players[opponent].main_deck)
