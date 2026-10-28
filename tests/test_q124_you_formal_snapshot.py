import hashlib
import json
import pytest

from loveca.simulation.effects import EffectDefinition, load_effect_registry
from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions
from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation.online import match_state_hash
from loveca.webapp import _match_state_payload
from test_multi_keep_inspection_audit import CODE, _state as _legacy_state
from test_mirakura_front_position_boundary import _swap_roles
from test_nijigasaki_inspection import _play, _resolve, _select
from test_printemps_ready_history_boundary import _manual, _repo, _replay

POLICY = "triggered_inspection_up_to_three_v1"


def _state(owner="player_1", *, historical=False, empty=False):
    state = _legacy_state(legacy=True, empty=empty)
    if not historical:
        state.effect_definitions[CODE + ":1"] = next(e for e in load_effect_registry().effects if e.effect_id == CODE + ":1")
    return _swap_roles(state) if owner == "player_2" else state


def _for(request, owner):
    request.player_id = owner
    return request


def _play_for(state, owner):
    action = _for(_play(state), owner)
    action.payload["energy_instance_ids"] = state.players[owner].energy_area
    return action


def test_formal_card_identity_and_exact_registration_red():
    state = _state(); card = state.cards["source-live"].card
    assert card.card_code == CODE and card.cost == 13 and card.text_revision_id == 548
    assert hashlib.sha256(card.raw_effect_text_ja.encode()).hexdigest() == card.raw_text_hash == "1d864314344a8d252f580ccee32897f33b3926a9ee9ff37cc5ca64439197da93"
    registered = next(e for e in load_effect_registry().effects if e.effect_id == CODE + ":1")
    assert registered.choice is not None and registered.choice.cost_payment_policy == POLICY


def test_changed_card_identity_does_not_fall_back_to_structured_pattern():
    from pathlib import Path
    from loveca.db.bootstrap import connect_database
    from loveca.simulation.effect_candidates import _effect_text_rows, _PATTERNS
    with connect_database(Path("data/loveca.sqlite3")) as db:
        row = next(dict(r) for r in _effect_text_rows(db) if r["card_code"] == CODE)
    for key, value in [("raw_effect_text_ja", " " + row["raw_effect_text_ja"]),
                       ("raw_effect_text_ja", row["raw_effect_text_ja"] + " "),
                       ("text_revision_id", 549), ("raw_text_hash", "OTHER")]:
        assert not any(pattern({**row, key: value}) is not None for pattern in _PATTERNS)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("count", [0, 1, 2, 3])
def test_actual_card_proposed_snapshot_selection_sql(tmp_path, owner, count):
    state = _state(owner); repo = _repo(state, tmp_path)
    played = repo.apply(state.match_id, _play_for(state, owner)).state
    result = repo.apply(state.match_id, _for(_resolve(played, selected_card_instance_ids=["cost"]), owner))
    assert sum(e.event_type == "effect_cost_paid" for e in result.events) == 1
    assert set(result.state.pending_choice.options["candidate_card_instance_ids"]) == {"good-member", "wrong-work", "tail"}
    assert "blade-heart" not in result.state.pending_choice.options["candidate_card_instance_ids"]
    other = "player_2" if owner == "player_1" else "player_1"
    view = _match_state_payload(result.state, events=result.events, legal_actions=result.legal_actions, player_id=other)
    assert not any(i in json.dumps(view) for i in result.state.pending_choice.options["inspected_card_instance_ids"])
    picked = ["good-member", "wrong-work", "tail"][:count]
    final = repo.apply(state.match_id, _for(_select(result.state, picked), owner))
    assert set(final.state.players[owner].hand) == set(picked)
    assert set(final.state.players[owner].waiting_room) == {"cost", *state.players[owner].main_deck} - set(picked)
    resolved = next(e for e in final.events if e.event_type == "effect_resolved")
    assert {item["instance_id"] for item in resolved.data["revealed_cards"]} == set(picked)
    _replay(repo, final.state)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("accepted", [False, True])
def test_actual_card_unpayable_or_declined_never_inspects_sql(tmp_path, owner, accepted):
    state = _state(owner, empty=True); repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _play_for(state, owner)).state
    result = repo.apply(state.match_id, _for(_resolve(current, accepted=accepted), owner))
    assert not any(e.event_type in {"effect_cost_paid", "effect_inspection_started"} for e in result.events)
    assert result.state.pending_choice is None and not result.state.pending_effects
    _replay(repo, result.state)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_actual_card_payable_decline_keeps_hand_and_deck_sql(tmp_path, owner):
    state = _state(owner); repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _play_for(state, owner)).state
    before = current.players[owner].model_dump(mode="json")
    result = repo.apply(state.match_id, _for(_resolve(current, accepted=False), owner))
    assert result.state.players[owner].model_dump(mode="json") == before
    assert not any(e.event_type in {"effect_cost_paid", "effect_inspection_started", "effect_skipped"} for e in result.events)
    _replay(repo, result.state)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_synthetic_all_heart_does_not_match_colored_basic_heart_sql(tmp_path, owner):
    state = _state(owner)
    state.cards["extra"].card.basic_hearts = {"heart0": 1}
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _play_for(state, owner)).state
    inspected = repo.apply(state.match_id, _for(_resolve(current, selected_card_instance_ids=["cost"]), owner)).state
    assert "extra" not in inspected.pending_choice.options["candidate_card_instance_ids"]
    _replay(repo, inspected)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("zone", ["hand", "main_deck"])
def test_actual_source_later_hidden_pending_continues_sql(tmp_path, owner, zone):
    state = _state(owner)
    raw = state.effect_definitions[CODE + ":1"].model_dump(mode="json")
    raw.update(effect_id="CONTROL", cost=[], cost_choice=None, choice=None, actions=[{"action_type": "manual_resolution"}],
               execution_mode="manual_resolution", simulation_support="manual_resolution", is_optional=False)
    state.effect_definitions["CONTROL"] = EffectDefinition.model_validate(raw)
    state.cards["source-live"].card.effect_ids.append("CONTROL")
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _play_for(state, owner)).state
    current = repo.apply(state.match_id, _manual(current, "CONTROL", [{"adjustment_type": "move_card",
        "target_card_instance_id": "source-live", "to_zone": zone}])).state
    current = repo.apply(state.match_id, _for(_resolve(current, selected_card_instance_ids=["cost"]), owner)).state
    result = repo.apply(state.match_id, _for(_select(current, []), owner)).state
    _replay(repo, result)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("ids", [["good-member", "good-member"], ["good-member", "wrong-work", "tail", "blade-heart"], ["good-live"], ["opponent-secret"]])
def test_actual_card_invalid_selection_is_atomic_sql(tmp_path, owner, ids):
    state = _state(owner); repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _play_for(state, owner)).state
    current = repo.apply(state.match_id, _for(_resolve(current, selected_card_instance_ids=["cost"]), owner)).state
    before = match_state_hash(current)
    with pytest.raises(IllegalActionError):
        repo.apply(state.match_id, _for(_select(current, ids), owner))
    assert match_state_hash(repo.get_state(state.match_id)) == before
    _replay(repo, current)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_actual_card_short_deck_refresh_after_cost_sql(tmp_path, owner):
    state = _state(owner); player = state.players[owner]
    player.main_deck = ["good-member"]
    player.waiting_room = ["wrong-work", "tail", "blade-heart", "good-live", "deck-live-1", "extra"]
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _play_for(state, owner)).state
    result = repo.apply(state.match_id, _for(_resolve(current, selected_card_instance_ids=["cost"]), owner))
    kinds = [e.event_type for e in result.events]
    assert kinds.index("effect_cost_paid") < kinds.index("deck_refreshed") < kinds.index("effect_inspection_started")
    assert len(result.state.pending_choice.options["inspected_card_instance_ids"]) == 7
    final = repo.apply(state.match_id, _for(_select(result.state, []), owner)).state
    _replay(repo, final)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_actual_card_four_ai_hidden_input_and_provider_privacy(owner, policy):
    initial = _state(owner)
    state = apply_action(initial, _play_for(initial, owner)).state
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    first = controller.choose_action(state, generate_legal_actions(state), controlled_player_ids={owner})
    assert isinstance(first, SimpleAIDecision)
    state = apply_action(state, first.action).state
    before = match_state_hash(state)
    decision = controller.choose_action(state, generate_legal_actions(state), controlled_player_ids={owner})
    changed = state.model_copy(deep=True); opponent = "player_2" if owner == "player_1" else "player_1"
    item = changed.cards.pop("opponent-secret"); item.instance_id = "hidden-replacement"
    item.card.card_code = item.card.name_ja = "HIDDEN"
    item.card.unit_keys, item.card.work_keys, item.card.blade = ["bibi"], ["hasunosora"], 99
    changed.cards[item.instance_id] = item
    changed.players[opponent].hand = [item.instance_id if i == "opponent-secret" else i for i in changed.players[opponent].hand]
    changed_before = match_state_hash(changed)
    other = controller.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={owner})
    assert isinstance(decision, SimpleAIDecision) and isinstance(other, SimpleAIDecision) and decision.action == other.action
    assert match_state_hash(state) == before and match_state_hash(changed) == changed_before
    apply_action(state, decision.action); apply_action(changed, other.action)
    from tools.ai_sandbox.semantic_playtest import build_api_play_context, build_agent_context
    for builder in (build_api_play_context, build_agent_context):
        assert "opponent-secret" not in json.dumps(builder(state, generate_legal_actions(state)))
