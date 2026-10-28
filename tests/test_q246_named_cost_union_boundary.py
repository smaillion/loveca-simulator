from collections import Counter

import pytest

from loveca.simulation.effects import EffectDefinition
from loveca.simulation.engine import IllegalActionError, generate_legal_actions
from loveca.simulation.online import match_state_hash
from loveca.webapp import _match_state_payload
from test_ll_bp6_named_discard_scope import _actual, EFFECT
from test_printemps_ready_history_boundary import _advance, _repo, _replay, _resolve

PROBE = "UNREGISTERED-Q246-COST-AUDIT:1"
NAMES = ["南 ことり", "黒澤ダイヤ", "徒町小鈴"]


def _probe(owner):
    state = _actual(owner, hand=True)
    raw = state.effect_definitions[EFFECT].model_dump(mode="json")
    raw.update(effect_id=PROBE, card_code="UNREGISTERED-Q246-COST-AUDIT",
        execution_mode="prompt_then_resolve", simulation_support="test_validated_executable",
        review_status="test_validated", cost=[{"action_type": "discard_from_hand", "target": "selected"}],
        cost_choice={"choice_type": "card_from_zone", "zone": "hand", "card_type": "member",
                     "target_player": "self", "name_ja_any": NAMES, "minimum": 0, "maximum": 4},
        actions=[{"action_type": "gain_heart_from_selected_card_colors", "target": "cost_selected",
                  "value": {"target_stage_member_name_ja": state.cards["source-live"].card.name_ja}}])
    state.effect_definitions = {PROBE: EffectDefinition.model_validate(raw)}
    state.cards["source-live"].card.card_code = "UNREGISTERED-Q246-COST-AUDIT"
    state.cards["source-live"].card.effect_ids = [PROBE]
    state.cards["audit-hand-0"].card.basic_hearts = {"heart01": 2, "heart02": 1}
    state.cards["audit-hand-1"].card.basic_hearts = {"heart02": 1, "heart03": 1, "heart04": 1}
    return state


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("count", [0, 1, 2, 3, 4])
def test_synthetic_variable_named_cost_is_paid_and_replayed_sql(tmp_path, owner, count):
    state = _probe(owner)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    chosen = [f"audit-hand-{i}" for i in range(count)]
    result = repo.apply(state.match_id, _resolve(current, PROBE, accepted=True, selected_card_instance_ids=chosen))
    assert all(i in result.state.players[owner].waiting_room for i in chosen)
    assert all(i not in result.state.players[owner].hand for i in chosen)
    paid = [e for e in result.events if e.event_type == "effect_cost_paid"]
    assert len(paid) == 1 and paid[0].data["selected_card_instance_ids"] == chosen
    _replay(repo, result.state)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_old_selected_color_operation_counts_shared_color_twice_not_q246_sql(tmp_path, owner):
    state = _probe(owner)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    result = repo.apply(state.match_id, _resolve(current, PROBE, accepted=True,
        selected_card_instance_ids=["audit-hand-0", "audit-hand-1"]))
    colors = Counter(m.color_slot for m in result.state.players[owner].manual_modifiers
                     if m.modifier_type == "heart" and m.target_card_instance_id == "source-live")
    assert colors == {"heart01": 1, "heart02": 2, "heart03": 1, "heart04": 1}
    assert colors != {"heart01": 1, "heart02": 1, "heart03": 1, "heart04": 1}
    _replay(repo, result.state)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("selection", [["audit-hand-0", "audit-hand-0"], ["wrong-work"]])
def test_illegal_synthetic_cost_is_atomic_sql(tmp_path, owner, selection):
    state = _probe(owner)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    before = match_state_hash(current)
    with pytest.raises(IllegalActionError):
        repo.apply(state.match_id, _resolve(current, PROBE, accepted=True, selected_card_instance_ids=selection))
    assert match_state_hash(repo.get_state(state.match_id)) == before
    _replay(repo, current)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_current_exact_name_filter_does_not_split_composite_names_sql(tmp_path, owner):
    state = _probe(owner)
    state.cards["audit-hand-0"].card.name_ja = "南 ことり&黒澤ダイヤ&徒町小鈴"
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    before = match_state_hash(current)
    with pytest.raises(IllegalActionError):
        repo.apply(state.match_id, _resolve(current, PROBE, accepted=True,
                                            selected_card_instance_ids=["audit-hand-0"]))
    assert match_state_hash(repo.get_state(state.match_id)) == before
    _replay(repo, current)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_synthetic_private_cost_candidates_do_not_grant_opponent_faces(owner):
    from loveca.simulation.engine import apply_action
    state = _probe(owner)
    current = apply_action(state, _advance(state)).state
    opponent = "player_2" if owner == "player_1" else "player_1"
    before = match_state_hash(current)
    payload = _match_state_payload(current, events=[], legal_actions=generate_legal_actions(current), player_id=opponent)
    assert all(i not in payload["state"]["cards"] for i in current.players[owner].hand)
    assert match_state_hash(current) == before
