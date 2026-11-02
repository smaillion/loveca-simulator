from contextlib import closing
from copy import deepcopy
from functools import lru_cache
from pathlib import Path

import pytest
from test_baton_hand_deploy_audit import _state as _base_state, CARD_CODES
from test_all_active_live_requirement_boundary import _exclusive
from test_mirakura_front_position_boundary import _swap_roles

from loveca.db.bootstrap import connect_database
from loveca.simulation.catalog import _load_definition
from loveca.simulation.effect_candidates import discover_effect_candidates
from loveca.simulation.effects import EffectDefinition, load_effect_registry
from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions, _effective_member_play_cost
from loveca.simulation.models import ActionRequest
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository
from loveca.webapp import _match_state_payload

CODE = "PL!S-PR-045"
EFFECT = CODE + ":1"
POLICY = "private_baton_cost7_draw2_discard1"
RULE_REFERENCE_IDS = ("1.3.2", "2.6.1", "4.1.4", "9.6.2.3.2", "9.6.2.4.2", "9.7.7", "9.11.1", "10.2.2.1", "11.4.2")


@lru_cache
def _raw():
    candidate = next((c for c in discover_effect_candidates(Path("data/loveca.sqlite3"), include_registered=True) if c.effect_id == EFFECT), None)
    return candidate.to_registry_entry() if candidate else next(e.model_dump(mode="json") for e in load_effect_registry().effects if e.effect_id == EFFECT)


def _state(cost=7, *, legacy=False, control=False):
    state = _base_state(CARD_CODES[0], cost)
    raw = deepcopy(_raw())
    if legacy:
        raw.update(condition={}, choice=None, actions=[{"action_type": "manual_resolution"}], execution_mode="manual_resolution", simulation_support="manual_resolution")
    effect = EffectDefinition.model_validate(raw)
    state.effect_definitions = {EFFECT: effect}
    with closing(connect_database(Path("data/loveca.sqlite3"))) as db:
        state.cards["source-live"].card = _load_definition(db, CODE, None, state.effect_definitions, {})
    state.effect_order_policy = "ap_nap_player_choice"
    if control:
        for key in ["CONTROL", "TAIL"]:
            audit = {**raw, "effect_id": key, "choice": None, "actions": [{"action_type": "manual_resolution"}], "execution_mode": "manual_resolution", "simulation_support": "manual_resolution"}
            state.effect_definitions[key] = EffectDefinition.model_validate(audit)
            state.cards["source-live"].card.effect_ids.append(key)
    _exclusive(state)
    return state


def _play(state, baton=True):
    owner = state.cards["source-live"].owner_id
    player = state.players[owner]
    cost = _effective_member_play_cost(state, owner, "source-live")
    payment = max(0, cost - state.cards["previous"].card.cost) if baton else cost
    return ActionRequest(action_type="play_member", player_id=owner, expected_revision=state.revision,
        payload={"card_instance_id": "source-live", "slot": "center", "use_baton_touch": baton, "energy_instance_ids": player.energy_area[:payment]})


def _resolve(state, ids=None, **extra):
    inv = next(i for i in state.pending_effects if i.effect_id == EFFECT)
    return ActionRequest(action_type="resolve_effect", player_id=inv.player_id, expected_revision=state.revision,
        payload={"invocation_id": inv.invocation_id, "selected_card_instance_ids": ids or [], **extra})


def _event(result):
    return next(e.data for e in result.events if e.event_type == "effect_baton_cost7_draw_discard_resolved")


def test_native_baton_cost7_draws_two_before_private_discard_red():
    state = _state()
    current = apply_action(state, _play(state)).state
    first = apply_action(current, _resolve(current))
    assert len(first.state.players["player_1"].hand) == 2
    assert first.state.pending_effects[0].resolution_stage == "after_cost"
    result = apply_action(first.state, _resolve(first.state, [first.state.players["player_1"].hand[0]]))
    assert _event(result)["drawn_count"] == 2
    assert _event(result)["discarded_count"] == 1


def test_native_non_cost7_condition_completes_without_manual_red():
    state = _state(6)
    result = apply_action(state, _play(state))
    assert not result.state.pending_effects
    assert _event(result)["condition_met"] is False


def _repo(state, tmp_path):
    repo = MatchRepository(tmp_path / "audit.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    return repo


def _replay(repo, state):
    _exclusive(state)
    replay = repo.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == state.model_dump(mode="json")


def _finish(repo, state):
    first = repo.apply(state.match_id, _resolve(state))
    if any(i.effect_id == EFFECT for i in first.state.pending_effects):
        return repo.apply(state.match_id, _resolve(first.state, [first.state.players[state.cards["source-live"].owner_id].hand[0]]))
    return first


def _manual(state, changes):
    inv = next(i for i in state.pending_effects if i.effect_id == "CONTROL")
    return ActionRequest(action_type="manual_adjustment", player_id=inv.player_id, expected_revision=state.revision,
        payload={"reason": "AUDIT CONTROL only", "source_invocation_id": inv.invocation_id,
            "source_effect_id": inv.effect_id, "source_card_instance_id": inv.source_card_instance_id,
            "adjustments": [{"target_player_id": inv.player_id, **c} for c in changes]})


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("cost", [6, 7, 8])
@pytest.mark.parametrize("baton", [False, True])
def test_native_baton_actual_cost_and_roles_sql(tmp_path, owner, cost, baton):
    state = _state(cost)
    if owner == "player_2":
        state = _swap_roles(state)
        state.phase, state.active_player_id = "second_main", owner
    before = match_state_hash(state)
    repo = _repo(state, tmp_path)
    result = repo.apply(state.match_id, _play(state, baton))
    if baton and cost == 7:
        result = _finish(repo, result.state)
    data = _event(result)
    assert data["condition_met"] is (baton and cost == 7)
    assert data["drawn_count"] == (2 if baton and cost == 7 else 0)
    assert data["discarded_count"] == int(baton and cost == 7)
    assert match_state_hash(state) == before
    _replay(repo, result.state)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("target", ["source-live", "previous"])
@pytest.mark.parametrize("move", ["hand", "deck", "waiting", "return", "position"])
def test_source_and_original_baton_member_interference_sql(tmp_path, owner, target, move):
    state = _state(control=True)
    if owner == "player_2":
        state = _swap_roles(state)
        state.phase, state.active_player_id = "second_main", owner
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _play(state)).state
    if move == "position" and target == "source-live":
        changes = [{"adjustment_type": "position_change", "from_slot": "center", "to_slot": "right"}]
    else:
        zone = {"hand": "hand", "deck": "main_deck", "waiting": "waiting_room", "return": "hand", "position": "hand"}[move]
        changes = [{"adjustment_type": "move_card", "target_card_instance_id": target, "to_zone": zone}]
        if move in {"return", "position"}:
            changes.append({"adjustment_type": "move_card", "target_card_instance_id": target,
                "to_zone": "member_center" if target == "source-live" else "member_left"})
    current = repo.apply(state.match_id, _manual(current, changes)).state
    result = _finish(repo, current)
    assert _event(result)["condition_met"] is True
    assert _event(result)["discarded_count"] == 1
    for viewer in ["player_1", "player_2"]:
        payload = _match_state_payload(result.state, events=result.events, legal_actions=result.legal_actions, player_id=viewer)
        for p in result.state.players.values():
            assert not any(i in payload["state"]["cards"] for i in p.main_deck)
            if p.player_id != viewer:
                assert not any(i in payload["state"]["cards"] for i in p.hand)
    _replay(repo, result.state)


@pytest.mark.parametrize("deck_size,waiting_size,held", [(0, 0, 0), (0, 0, 1), (0, 1, 0), (1, 0, 0), (1, 1, 0), (2, 0, 0), (3, 1, 1)])
def test_draw_two_short_refresh_then_discard_possible_range_sql(tmp_path, deck_size, waiting_size, held):
    state = _state(control=True)
    p = state.players["player_1"]
    pool = [f"draw-{i}" for i in range(deck_size + waiting_size + held)]
    for key in pool:
        state.cards[key] = state.cards["previous"].model_copy(update={"instance_id": key}, deep=True)
        state.cards[key].card.card_code = state.cards[key].card.name_ja = "AUDIT-" + key
    p.main_deck = pool[:deck_size]
    p.waiting_room = pool[deck_size:deck_size + waiting_size]
    p.hand += pool[deck_size + waiting_size:]
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _play(state)).state
    # Move the Baton payment under a Member so the empty-library case is real.
    current = repo.apply(state.match_id, _manual(current, [
        {"adjustment_type": "move_card", "target_card_instance_id": "previous", "to_zone": "hand"},
        {"adjustment_type": "attach_card_under_member", "target_card_instance_id": "previous", "target_slot": "center"}])).state
    result = _finish(repo, current)
    assert _event(result)["drawn_count"] == min(2, deck_size + waiting_size)
    assert _event(result)["discarded_count"] == int(bool(deck_size + waiting_size + held))
    assert len(result.state.players["player_1"].hand) == held + min(2, deck_size + waiting_size) - int(bool(deck_size + waiting_size + held))
    p = result.state.players["player_1"]
    assert p.main_deck or not p.waiting_room
    if 0 < deck_size + waiting_size + held <= 2:
        assert p.refresh_count >= 1
    _replay(repo, result.state)


@pytest.mark.parametrize("cost", [6, 7, 8])
def test_baton_fact_is_not_re_read_from_moved_card_or_payment_discount(cost):
    state = _state(cost, control=True)
    current = apply_action(state, _play(state)).state
    current.cards["previous"].card.cost = 7 if cost != 7 else 99
    result = apply_action(current, _resolve(current))
    if cost == 7:
        result = apply_action(result.state, _resolve(result.state, [result.state.players["player_1"].hand[0]]))
    assert _event(result)["condition_met"] is (cost == 7)


@pytest.mark.parametrize("cost", [6, 7, 8])
@pytest.mark.parametrize("target", ["source-live", "previous"])
def test_reduce_play_cost_is_not_card_cost_for_baton_reference(cost, target):
    state = _state(cost)
    effect = EffectDefinition(effect_id="discount", card_code=CODE, text_revision_id=1, raw_text_hash="d" * 64,
        effect_index=2, label_ja="AUDIT payment reduction", effect_type="static", timing="static_always", trigger="static_always",
        execution_mode="auto_resolve", frequency_limit="none", is_optional=False, actions=[{"action_type": "reduce_play_cost", "amount": 2}],
        simulation_support="test_validated_executable", review_status="test_validated", source_reference="AUDIT")
    state.effect_definitions["discount"] = effect
    state.cards[target].card.effect_ids.append("discount")
    assert _effective_member_play_cost(state, "player_1", target) == state.cards[target].card.cost - 2
    current = apply_action(state, _play(state))
    if cost == 7:
        current = apply_action(current.state, _resolve(current.state))
        current = apply_action(current.state, _resolve(current.state, [current.state.players["player_1"].hand[0]]))
    assert _event(current)["condition_met"] is (cost == 7)


def test_client_cannot_supply_a_replacement_cost_in_play_payload():
    state = _state(6)
    request = _play(state)
    request.payload["baton_replaced_member_cost_v1"] = 7
    result = apply_action(state, request)
    assert _event(result)["condition_met"] is False


@pytest.mark.parametrize("legacy", [False, True])
def test_new_and_old_manual_baton_snapshot_sql(tmp_path, legacy):
    state = _state(legacy=legacy)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _play(state)).state
    if legacy:
        assert "baton_replaced_member_cost_v1" not in current.pending_effects[0].trigger_data
        with pytest.raises(IllegalActionError, match="ManualAdjustmentAction"):
            apply_action(current, _resolve(current))
    else:
        result = _finish(repo, current)
        assert _event(result)["drawn_count"] == 2
        current = result.state
    _replay(repo, current)


@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_four_ai_real_draw_and_discard_hidden_identity_invariance(policy, owner):
    from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
    state = _state()
    if owner == "player_2":
        state = _swap_roles(state)
        state.phase, state.active_player_id = "second_main", owner
    current = apply_action(state, _play(state)).state
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    for step in range(2):
        before = match_state_hash(current)
        changed = current.model_copy(deep=True)
        for p in changed.players.values():
            keys = p.main_deck + (p.hand if p.player_id != owner else [])
            for key in list(keys):
                card = changed.cards.pop(key)
                new = "HIDDEN-" + key
                card.instance_id = new
                card.card.name_ja = card.card.card_code = "HIDDEN-IDENTITY"
                changed.cards[new] = card
                for zone in ["hand", "main_deck"]:
                    setattr(p, zone, [new if i == key else i for i in getattr(p, zone)])
        decision = controller.choose_action(current, generate_legal_actions(current), controlled_player_ids={owner})
        assert isinstance(decision, SimpleAIDecision)
        assert controller.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={owner}).action == decision.action
        assert match_state_hash(current) == before
        result = apply_action(current, decision.action)
        current = result.state
    assert _event(result)["discarded_count"] == 1


@pytest.mark.parametrize("extra", [{"energy_instance_ids": ["energy-0"]}, {"selected_branch": "draw"}, {"selected_color_slot": "heart01"}, {"accepted": False}, {"accepted": "yes"}, {"accepted": 1}, {"selected_card_instance_ids": ["deck-member-1"]}])
def test_initial_invalid_parameters_are_atomic(extra):
    state = _state()
    current = apply_action(state, _play(state)).state
    before = match_state_hash(current)
    with pytest.raises(IllegalActionError):
        apply_action(current, _resolve(current, **extra))
    assert match_state_hash(current) == before


@pytest.mark.parametrize("ids", [[], ["energy-0"], ["deck-member-1", "deck-member-1"], ["deck-member-1", "deck-live-1"]])
def test_follow_up_invalid_or_non_owner_discard_atomic(ids):
    state = _state()
    current = apply_action(state, _play(state)).state
    current = apply_action(current, _resolve(current)).state
    before = match_state_hash(current)
    with pytest.raises(IllegalActionError):
        apply_action(current, _resolve(current, ids))
    wrong = _resolve(current, [current.players["player_1"].hand[0]])
    wrong.player_id = "player_2"
    with pytest.raises(IllegalActionError):
        apply_action(current, wrong)
    assert match_state_hash(current) == before


@pytest.mark.parametrize("field,value", [("baton_replaced_member_cost_v1", True), ("baton_replaced_member_cost_v1", None), ("used_baton_touch", 1), ("baton_play_turn_v1", -1), ("replacement_card_instance_id", None)])
def test_missing_or_bad_original_context_rejected(field, value):
    state = _state()
    current = apply_action(state, _play(state)).state
    current.pending_effects[0].trigger_data[field] = value
    before = match_state_hash(current)
    with pytest.raises(IllegalActionError):
        apply_action(current, _resolve(current))
    assert match_state_hash(current) == before


def test_stale_and_repeat_submission_rejected():
    from loveca.simulation.engine import StaleRevisionError
    state = _state()
    current = apply_action(state, _play(state)).state
    current = apply_action(current, _resolve(current)).state
    request = _resolve(current, [current.players["player_1"].hand[0]])
    final = apply_action(current, request).state
    with pytest.raises(StaleRevisionError):
        apply_action(final, request)
    request.expected_revision = final.revision
    with pytest.raises(IllegalActionError):
        apply_action(final, request)


@pytest.mark.parametrize("field,value", [("condition", {"requires_baton_touch": True}), ("is_optional", True), ("duration", "game"), ("frequency_limit", "once_per_turn"), ("timing", "live_start"), ("cost", [{"action_type": "draw_card", "amount": 1}])])
def test_snapshot_rejects_widening(field, value):
    from pydantic import ValidationError
    raw = deepcopy(_raw())
    raw[field] = value
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate(raw)


def test_exact_full_text_revision_hash():
    from loveca.simulation.effect_candidates import _onplay_baton_cost7_draw_discard
    raw = _raw()
    row = {k: raw[k] for k in ["card_code", "text_revision_id", "raw_text_hash"]}
    row["raw_effect_text_ja"] = raw["label_ja"]
    assert _onplay_baton_cost7_draw_discard(row)
    for key in row:
        bad = dict(row)
        bad[key] = 0 if key == "text_revision_id" else "WRONG"
        assert _onplay_baton_cost7_draw_discard(bad) is None


def test_follow_up_lock_blocks_manual_interference_and_second_draw():
    state = _state(control=True)
    current = apply_action(state, _play(state)).state
    current = apply_action(current, _resolve(current)).state
    before = match_state_hash(current)
    with pytest.raises(IllegalActionError):
        apply_action(current, _manual(current, [{"adjustment_type": "draw_card", "amount": 1}]))
    with pytest.raises(IllegalActionError):
        apply_action(current, _resolve(current))
    assert match_state_hash(current) == before


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_drawn_hand_private_in_complete_both_views(owner):
    state = _state()
    if owner == "player_2":
        state = _swap_roles(state)
        state.phase, state.active_player_id = "second_main", owner
    current = apply_action(state, _play(state)).state
    first = apply_action(current, _resolve(current))
    before = match_state_hash(first.state)
    for viewer in ["player_1", "player_2"]:
        payload = _match_state_payload(first.state, events=first.events, legal_actions=first.legal_actions, player_id=viewer)
        for p in first.state.players.values():
            assert not any(i in payload["state"]["cards"] for i in p.main_deck)
            for key in p.hand:
                assert (key in payload["state"]["cards"]) is (viewer == p.player_id)
    assert match_state_hash(first.state) == before


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_two_distinct_native_batons_have_separate_original_context_sql(tmp_path, owner):
    state = _state()
    state.cards["source-2"] = state.cards["source-live"].model_copy(update={"instance_id": "source-2"}, deep=True)
    state.cards["previous-2"] = state.cards["previous"].model_copy(update={"instance_id": "previous-2"}, deep=True)
    state.players["player_1"].member_area["left"] = "previous-2"
    state.players["player_1"].hand.append("source-2")
    if owner == "player_2":
        state = _swap_roles(state)
        state.phase, state.active_player_id = "second_main", owner
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _play(state)).state
    current = repo.apply(state.match_id, _resolve(current)).state
    # Keep the second source for a separate real Baton entry.
    selected = next(i for i in current.players[owner].hand if i != "source-2")
    first = repo.apply(state.match_id, _resolve(current, [selected]))
    current = first.state
    energy = [i for i in current.players[owner].energy_area if current.cards[i].orientation == "active"]
    payment = max(0, _effective_member_play_cost(current, owner, "source-2") - 7)
    current = repo.apply(state.match_id, ActionRequest(action_type="play_member", player_id=owner, expected_revision=current.revision,
        payload={"card_instance_id": "source-2", "slot": "left", "use_baton_touch": True, "energy_instance_ids": energy[:payment]})).state
    inv = next(i for i in current.pending_effects if i.effect_id == EFFECT)
    assert inv.source_card_instance_id == "source-2" and inv.trigger_data["replacement_card_instance_id"] == "previous-2"
    second = _finish(repo, current)
    assert _event(first)["discarded_count"] == _event(second)["discarded_count"] == 1
    _replay(repo, second.state)


@pytest.mark.parametrize("field,value", [("minimum", 0), ("maximum", 2), ("zone", "waiting_room"), ("reveal_selected_to_opponent", True)])
def test_fixed_private_choice_cannot_be_widened(field, value):
    from pydantic import ValidationError
    raw = deepcopy(_raw())
    raw["choice"][field] = value
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate(raw)
