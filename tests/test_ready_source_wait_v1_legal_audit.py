import pytest

from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions
from loveca.simulation.online import match_state_hash
from loveca.simulation.effects import load_effect_registry
from test_ready_source_wait_cost_probe import PROBE, _activate, _state
from test_printemps_ready_history_boundary import _repo, _replay


def test_no_formal_v1_cost_producers():
    assert not [effect.effect_id for effect in load_effect_registry().effects
                if any(action.action_type == "ready_member_after_source_wait_provenance_v1"
                       for action in effect.actions)]


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("invalid", ["wait", "wrong_owner"])
def test_v1_unpayable_source_is_not_offered(owner, invalid):
    state = _state(owner)
    if invalid == "wait":
        state.cards["source-live"].orientation = "wait"
    else:
        state.cards["source-live"].owner_id = "player_2" if owner == "player_1" else "player_1"
    before = match_state_hash(state)
    actions = [entry for action in generate_legal_actions(state) if action.action_type == "activate_effect"
               for entry in action.options["activations"]]
    assert not any(entry["effect_id"] == PROBE for entry in actions)
    with pytest.raises(IllegalActionError):
        apply_action(state, _activate(state))
    assert match_state_hash(state) == before


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("scenario", ["valid", "wait", "wrong_owner", "attached", "active_target", "no_target"])
def test_v1_legal_source_and_wait_target_sql(tmp_path, owner, scenario):
    state = _state(owner)
    player = state.players[owner]
    if scenario == "wait":
        state.cards["source-live"].orientation = "wait"
    elif scenario == "wrong_owner":
        state.cards["source-live"].owner_id = "player_2" if owner == "player_1" else "player_1"
    elif scenario == "attached":
        player.member_area["left"] = None
        player.member_area_attachments["center"].append("source-live")
    elif scenario == "active_target":
        for instance_id in player.member_area.values():
            if instance_id and instance_id != "source-live":
                state.cards[instance_id].orientation = "active"
    elif scenario == "no_target":
        for slot, instance_id in player.member_area.items():
            if instance_id and instance_id != "source-live":
                player.member_area[slot] = None
                player.hand.append(instance_id)
    repo = _repo(state, tmp_path)
    before = match_state_hash(state)
    actions = [entry for action in generate_legal_actions(state) if action.action_type == "activate_effect"
               for entry in action.options["activations"]]
    assert any(entry["effect_id"] == PROBE for entry in actions) is (scenario == "valid")
    if scenario == "valid":
        paid = repo.apply(state.match_id, _activate(state)).state
        assert paid.cards["source-live"].orientation == "wait"
        _replay(repo, paid)
    else:
        with pytest.raises(IllegalActionError):
            repo.apply(state.match_id, _activate(state))
        assert match_state_hash(repo.get_state(state.match_id)) == before
        _replay(repo, state)
