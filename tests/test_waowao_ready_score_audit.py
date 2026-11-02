import hashlib
import json
from pathlib import Path

import pytest

from loveca.simulation.engine import _card_score, _modifier_total
from loveca.simulation.effects import load_effect_registry
from loveca.simulation.effects import EffectDefinition
from loveca.simulation.engine import IllegalActionError, generate_legal_actions, apply_action
from loveca.simulation.online import match_state_hash
from loveca.simulation.models import ActionRequest
from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.webapp import _match_state_payload
from test_printemps_ready_history_boundary import READY, _advance, _manual, _repo, _replay, _resolve, _state

TEXT = "【ライブ開始時】自分のステージにいる『Printemps』のメンバーをアクティブにする。これによりウェイト状態のメンバーが3人以上アクティブ状態になったとき、このカードのスコアを＋１する。"
HASH = "2079004eee0c3c29da064a8859bd918c283872063c845f240311f8b9120e9ff5"


def _fixture(owner, waits, control=False, legacy=False):
    state = _state(owner=owner, waits=waits, ready=True, control=control)
    if not legacy:
        state.effect_definitions[READY] = next(e for e in load_effect_registry().effects if e.effect_id == READY)
    card = state.cards["live-1"].card
    assert (card.card_code, card.text_revision_id, card.raw_effect_text_ja) == ("PL!-pb1-028", 437, TEXT)
    assert card.raw_text_hash == hashlib.sha256(TEXT.encode()).hexdigest() == HASH
    other = state.cards["live-1"].model_copy(deep=True)
    other.instance_id = "other-live"
    other.card.effect_ids = []
    state.cards["other-live"] = other
    state.players[owner].live_area.append("other-live")
    return state


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("waits", [0, 1, 2, 3])
def test_native_old_snapshot_ready_count_and_global_score_sql(tmp_path, owner, waits):
    state = _fixture(owner, waits, legacy=True)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    result = repo.apply(state.match_id, _resolve(current, READY)).state
    assert all(result.cards[i].orientation == "active" for i in ["source-live", "target", "wrong-work"])
    assert _modifier_total(result.players[owner], "score") == int(waits == 3)
    assert _card_score(result, owner, "live-1") == _card_score(result, owner, "other-live") == 5
    assert result.member_ready_history is None
    _replay(repo, result)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("movement", ["hand", "main_deck", "return"])
def test_native_old_source_departure_global_score_sql(tmp_path, owner, movement):
    state = _fixture(owner, 3, control=True, legacy=True)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    changes = [{"adjustment_type": "move_card", "target_card_instance_id": "live-1",
                "to_zone": "hand" if movement == "return" else movement}]
    if movement == "return":
        changes.append({"adjustment_type": "move_card", "target_card_instance_id": "live-1", "to_zone": "live_area"})
    current = repo.apply(state.match_id, _manual(current, "CONTROL", changes)).state
    result = repo.apply(state.match_id, _resolve(current, READY)).state
    assert _modifier_total(result.players[owner], "score") == 1
    assert not any(m.modifier_type == "live_card_score" for m in result.players[owner].manual_modifiers)
    _replay(repo, result)


def test_live_source_only_score_matches_card(tmp_path):
    state = _fixture("player_1", 3)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    result = repo.apply(state.match_id, _resolve(current, READY)).state
    assert _modifier_total(result.players["player_1"], "score") == 0
    assert _card_score(result, "player_1", "live-1") == 6
    assert _card_score(result, "player_1", "other-live") == 5


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("waits", [0, 1, 2, 3])
def test_new_snapshot_records_actual_ready_and_only_source_score_sql(tmp_path, owner, waits):
    state = _fixture(owner, waits)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    result = repo.apply(state.match_id, _resolve(current, READY)).state
    assert len(result.member_ready_history.events) == waits
    assert _modifier_total(result.players[owner], "score") == 0
    assert _card_score(result, owner, "live-1") == 5 + int(waits == 3)
    assert _card_score(result, owner, "other-live") == 5
    if waits == 3:
        marker = next(m for m in result.players[owner].manual_modifiers if m.modifier_type == "live_card_score")
        assert marker.duration == "game" and marker.target_card_instance_id == "live-1"
    _replay(repo, result)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("movement", ["hand", "main_deck", "return"])
def test_new_snapshot_source_departure_still_readies_but_not_old_live_score_sql(tmp_path, owner, movement):
    state = _fixture(owner, 3, control=True)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    changes = [{"adjustment_type": "move_card", "target_card_instance_id": "live-1",
                "to_zone": "hand" if movement == "return" else movement}]
    if movement == "return":
        changes.append({"adjustment_type": "move_card", "target_card_instance_id": "live-1", "to_zone": "live_area"})
    current = repo.apply(state.match_id, _manual(current, "CONTROL", changes)).state
    result = repo.apply(state.match_id, _resolve(current, READY)).state
    assert len(result.member_ready_history.events) == 3
    assert _modifier_total(result.players[owner], "score") == 0
    assert not any(m.modifier_type == "live_card_score" for m in result.players[owner].manual_modifiers)
    assert _card_score(result, owner, "other-live") == 5
    _replay(repo, result)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_new_snapshot_score_expires_on_real_source_departure_sql(tmp_path, owner):
    state = _fixture(owner, 3, control=True)
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    current = repo.apply(state.match_id, _resolve(current, READY)).state
    assert _card_score(current, owner, "live-1") == 6
    changes = [{"adjustment_type": "move_card", "target_card_instance_id": "live-1", "to_zone": "hand"},
               {"adjustment_type": "move_card", "target_card_instance_id": "live-1", "to_zone": "live_area"}]
    result = repo.apply(state.match_id, _manual(current, "CONTROL", changes)).state
    assert _card_score(result, owner, "live-1") == 5
    assert _card_score(result, owner, "other-live") == 5
    _replay(repo, result)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_two_real_sources_each_resolve_current_ready_count_sql(tmp_path, owner):
    state = _fixture(owner, 3)
    state.cards["other-live"].card.effect_ids = [READY]
    repo = _repo(state, tmp_path)
    current = repo.apply(state.match_id, _advance(state)).state
    ids = [i.invocation_id for i in current.pending_effects if i.effect_id == READY]
    assert len(ids) == 2
    for invocation_id in ids:
        current = repo.apply(state.match_id, ActionRequest(action_type="resolve_effect", player_id=owner,
            expected_revision=current.revision, payload={"invocation_id": invocation_id})).state
    assert len(current.member_ready_history.events) == 3
    assert _modifier_total(current.players[owner], "score") == 0
    assert sorted([_card_score(current, owner, "live-1"), _card_score(current, owner, "other-live")]) == [5, 6]
    _replay(repo, current)


@pytest.mark.parametrize("field,value", [("duration", "live"), ("is_optional", True),
    ("condition", {"flag": "x"}), ("cost", [{"action_type": "draw_card", "amount": 1}])])
def test_new_snapshot_rejects_unbounded_shape(field, value):
    raw = _fixture("player_1", 0).effect_definitions[READY].model_dump(mode="json")
    raw[field] = value
    with pytest.raises(ValueError, match="fixed mandatory Live-start shape"):
        EffectDefinition.model_validate(raw)


@pytest.mark.parametrize("payload", [{"accepted": False}, {"energy_instance_ids": ["fake"]},
    {"selected_card_instance_ids": ["target"]}, {"accepted": 1}, {"selected_color_slot": "heart01"}])
def test_new_snapshot_rejects_extra_input_atomically(payload):
    state = _fixture("player_1", 3)
    current = apply_action(state, _advance(state)).state
    before = match_state_hash(current)
    request = _resolve(current, READY, **payload)
    with pytest.raises(IllegalActionError):
        apply_action(current, request)
    assert match_state_hash(current) == before


def test_exact_candidate_binding_rejects_changed_identity():
    from loveca.simulation.effect_candidates import _simple_ai_v1_1_safe_effects
    row = {"card_code": "PL!-pb1-028", "raw_effect_text_ja": TEXT, "text_revision_id": 437, "raw_text_hash": HASH}
    assert _simple_ai_v1_1_safe_effects(row).pattern_id == "live_start_waowao_ready_three_source_score_v2"
    for field, value in [("raw_effect_text_ja", TEXT + " "), ("text_revision_id", 438), ("raw_text_hash", "0" * 64)]:
        assert _simple_ai_v1_1_safe_effects({**row, field: value}) is None


def test_new_score_ai_value_matches_existing_score_operation():
    from loveca.simulation.ai import _operation_value_without_observation
    from loveca.simulation.effects import EffectOperation
    current = _fixture("player_1", 0).effect_definitions[READY].actions[1]
    assert _operation_value_without_observation(current, is_cost=False) == _operation_value_without_observation(
        EffectOperation(action_type="modify_score", amount=1), is_cost=False) == 11


@pytest.mark.parametrize("field,value", [("raw_text_hash", "OTHER"), ("text_revision_id", 438),
    ("raw_effect_text_ja", " " + TEXT), ("raw_effect_text_ja", TEXT + " ")])
def test_changed_identity_cannot_fall_back_to_other_pattern(field, value):
    from loveca.db.bootstrap import connect_database
    from loveca.simulation.effect_candidates import _effect_text_rows, _PATTERNS
    with connect_database(Path("data/loveca.sqlite3")) as db:
        row = next(dict(r) for r in _effect_text_rows(db) if r["card_code"] == "PL!-pb1-028")
    row[field] = value
    assert not any(pattern(row) is not None for pattern in _PATTERNS)


@pytest.mark.parametrize("mutation", ["missing_source", "wrong_owner", "wrong_turn", "wrong_trigger", "bad_departed", "false_original"])
def test_malformed_original_live_evidence_is_rejected_even_with_empty_stage(mutation):
    state = _fixture("player_1", 0)
    current = apply_action(state, _advance(state)).state
    player = current.players["player_1"]
    for slot, instance_id in player.member_area.items():
        if instance_id:
            player.hand.append(instance_id)
            player.member_area[slot] = None
    inv = next(i for i in current.pending_effects if i.effect_id == READY)
    if mutation == "missing_source": inv.trigger_data.pop("ready_source_lki_v1")
    elif mutation == "wrong_owner": inv.trigger_data["ready_source_lki_v1"]["owner_id"] = "player_2"
    elif mutation == "wrong_turn": inv.trigger_data["ready_source_lki_v1"]["turn_number"] = True
    elif mutation == "wrong_trigger": inv.trigger_event = "member_played"
    elif mutation == "bad_departed": inv.trigger_data["original_source_live_object_departed"] = 1
    else: inv.trigger_data["original_source_live_object"] = False
    before = match_state_hash(current)
    with pytest.raises(IllegalActionError):
        apply_action(current, _resolve(current, READY))
    assert match_state_hash(current) == before


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("waits", [0, 3])
@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_four_ai_two_sources_hidden_identity_invariance(owner, waits, policy):
    state = _fixture(owner, waits, control=True)
    state.cards["source-live"].card.effect_ids = []
    state.cards["other-live"].card.effect_ids = [READY]
    current = apply_action(state, _advance(state)).state
    current = apply_action(current, _manual(current, "CONTROL", [{"adjustment_type": "move_card",
        "target_card_instance_id": "live-1", "to_zone": "main_deck"}])).state
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    before = match_state_hash(current)
    decision = controller.choose_action(current, generate_legal_actions(current), controlled_player_ids={owner})
    assert isinstance(decision, SimpleAIDecision)
    changed = current.model_copy(deep=True)
    for player in changed.players.values():
        for key in list(player.main_deck + (player.hand if player.player_id != owner else [])):
            item = changed.cards.pop(key)
            name = "HIDDEN-" + key
            item.instance_id = name
            item.card.name_ja = item.card.card_code = "HIDDEN"
            item.card.unit_keys, item.card.work_keys, item.card.blade = ["bibi"], ["hasunosora"], 99
            changed.cards[name] = item
            player.main_deck = [name if i == key else i for i in player.main_deck]
            player.hand = [name if i == key else i for i in player.hand]
            for invocation in changed.pending_effects:
                if invocation.source_card_instance_id == key:
                    invocation.source_card_instance_id = name
                    invocation.trigger_data["ready_source_lki_v1"]["instance_id"] = name
    changed_before = match_state_hash(changed)
    changed_decision = controller.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={owner})
    assert isinstance(changed_decision, SimpleAIDecision) and changed_decision.action == decision.action
    assert match_state_hash(current) == before and match_state_hash(changed) == changed_before
    apply_action(current, decision.action)
    apply_action(changed, changed_decision.action)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_views_do_not_reveal_hidden_source_or_ready_provenance(owner):
    from tools.ai_sandbox.semantic_playtest import build_agent_context, build_api_play_context
    state = _fixture(owner, 3, control=True)
    entered = apply_action(state, _advance(state))
    moved = apply_action(entered.state, _manual(entered.state, "CONTROL", [{"adjustment_type": "move_card",
        "target_card_instance_id": "live-1", "to_zone": "main_deck"}]))
    current = moved.state
    before = match_state_hash(current)
    legal = generate_legal_actions(current)
    for viewer in ["player_1", "player_2"]:
        payload = _match_state_payload(current, events=[*entered.events, *moved.events], legal_actions=legal, player_id=viewer)
        assert "ready_source_lki_v1" not in json.dumps(payload)
        assert "member_ready_history" not in payload["state"] and "live-1" not in payload["state"]["cards"]
        for player in current.players.values():
            assert not any(i in payload["state"]["cards"] for i in player.main_deck)
            if player.player_id != viewer:
                assert not any(i in payload["state"]["cards"] for i in player.hand)
    for builder in [build_api_play_context, build_agent_context]:
        text = json.dumps(builder(current, legal))
        assert "ready_source_lki_v1" not in text and "member_ready_history" not in text
    assert match_state_hash(current) == before
