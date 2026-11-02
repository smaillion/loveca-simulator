import json
from contextlib import closing
from pathlib import Path

import pytest
from pydantic import ValidationError
from test_aqours_blade_six_score import _state as _live_state
from test_moved_source_ready import _manual
from test_nijigasaki_inspection import _candidate

from loveca.db.bootstrap import connect_database
from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation.catalog import _load_definition
from loveca.simulation.effects import EffectDefinition
from loveca.simulation.engine import IllegalActionError, _card_score, apply_action, generate_legal_actions
from loveca.simulation.models import ActionRequest, EffectInvocation
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository
from loveca.webapp import _match_state_payload

CODE = "PL!S-bp7-021"
EFFECT = CODE + ":1"
POLICY = "original_live_start_bottom_five_source"
RULE_REFERENCE_IDS = ("4.1.4", "4.8.3", "9.6.2.4.2", "9.7.7", "10.2.1", "10.2.2.1", "10.2.3", "8.4.11")


def _state(*, members=5, stage=3, legacy=False):
    raw = _candidate(CODE).to_registry_entry()
    if legacy:
        raw.update(actions=[{"action_type": "manual_resolution"}], execution_mode="manual_resolution",
                   simulation_support="manual_resolution", review_status="parsed_draft")
    effect = EffectDefinition.model_validate(raw)
    state = _live_state()
    state.effect_definitions = {EFFECT: effect}
    with closing(connect_database(Path("data/loveca.sqlite3"))) as connection:
        state.cards["source-live"].card = _load_definition(connection, CODE, None, {EFFECT: effect}, {})
    p = state.players["player_1"]
    p.member_area = dict(zip(["left", "center", "right"], ["target", "wrong-work", "held"][:stage] + [None] * (3 - stage)))
    p.member_area_attachments = {"left": [], "center": [], "right": []}
    secret = state.cards["secret"].model_copy(update={"instance_id": "own-secret", "owner_id": "player_1"}, deep=True)
    state.cards["own-secret"] = secret
    p.hand = ["own-secret", *["target", "wrong-work", "held"][stage:]]
    for i, key in enumerate(["m0", "m1", "m2", "m3", "m4", "draw-next", "tail"]):
        card = state.cards["target"].model_copy(update={"instance_id": key}, deep=True)
        card.card.card_code = card.card.name_ja = f"AUDIT-{key}"
        card.card.card_type = "member" if i < members or i >= 5 else "live"
        card.card.effect_ids = []
        card.face_up = False
        state.cards[key] = card
    p.main_deck = ["draw-next", "tail", "m0", "m1", "m2", "m3", "m4"]
    p.waiting_room = []
    state.stage_departure_policy = "clear_departed_card_modifiers"
    return state


def _advance(state):
    return ActionRequest(action_type="advance_phase", player_id=state.active_player_id, expected_revision=state.revision)


def _resolve(state, **extra):
    inv = next(i for i in state.pending_effects if i.effect_id == EFFECT)
    return ActionRequest(action_type="resolve_effect", player_id=inv.player_id, expected_revision=state.revision,
                         payload={"invocation_id": inv.invocation_id, "accepted": True, **extra})


def _event(result):
    return next(e for e in result.events if e.event_type == "effect_bottom_five_members_resolved")


def _pending(**kwargs):
    state = _state(**kwargs)
    state.pending_effects = [EffectInvocation(invocation_id="five", effect_id=EFFECT,
        source_card_instance_id="source-live", player_id="player_1", trigger_event="live_started",
        trigger_data={"original_source_live_object": True, "_condition_checked_at_trigger": True})]
    return state


def test_native_live_start_draws_one_and_scores_only_original_live():
    state = _state()
    for p in state.players.values():
        ids=[x for z in [p.main_deck,p.hand,p.energy_deck,p.energy_area,p.live_area,p.waiting_room,
                         p.resolution_area,p.success_live_area,[x for x in p.member_area.values() if x]] for x in z]
        assert len(ids) == len(set(ids))
    before = match_state_hash(state)
    result = apply_action(state, _advance(state))
    assert match_state_hash(state) == before
    assert not result.state.pending_effects
    assert _event(result).data["milled_member_count"] == 5
    assert result.state.players["player_1"].hand == ["own-secret", "draw-next"]
    assert _card_score(result.state, "player_1", "source-live") == 6
    assert _card_score(result.state, "player_1", "live-1") == _card_score(state, "player_1", "live-1")
    assert all(m.modifier_type == "live_card_score" for m in result.state.players["player_1"].manual_modifiers)


def _control(**kwargs):
    state = _state(**kwargs)
    raw = state.effect_definitions[EFFECT].model_dump(mode="json")
    raw.update(effect_id="CONTROL", execution_mode="manual_resolution", simulation_support="manual_resolution",
               actions=[{"action_type": "manual_resolution"}], frequency_limit="none")
    state.effect_definitions["CONTROL"] = EffectDefinition.model_validate(raw)
    state.cards["live-1"].card.effect_ids = ["CONTROL"]
    return state


@pytest.mark.parametrize("members", range(6))
def test_member_move_count_and_original_score_thresholds(members):
    state = _pending(members=members)
    result = apply_action(state, _resolve(state))
    data = _event(result).data
    assert data["milled_member_count"] == members and data["milled_count"] == 5
    assert data["drawn_count"] == int(members >= 3)
    assert data["score_delta"] == int(members == 5)
    assert result.state.players["player_1"].waiting_room == ["m4", "m3", "m2", "m1", "m0"]
    assert result.state.players["player_1"].main_deck == (["tail"] if members >= 3 else ["draw-next", "tail"])
    names = [e.event_type for e in result.events]
    if members >= 3:
        assert max(i for i,n in enumerate(names) if n == "effect_cards_milled") < names.index("cards_drawn") < names.index("effect_bottom_five_members_resolved")


@pytest.mark.parametrize("stage", range(4))
def test_stage_condition_has_no_mill_or_draw_when_not_three(stage):
    state = _state(stage=stage)
    result = apply_action(state, _advance(state))
    assert _event(result).data["stage_condition_met"] == (stage == 3)
    assert _event(result).data["milled_count"] == (5 if stage == 3 else 0)
    assert len(result.state.players["player_1"].hand) == len(state.players["player_1"].hand) + int(stage == 3)
    assert not result.state.pending_effects


@pytest.mark.parametrize("start,end", [(2,3), (3,2), (3,3), (0,3)])
def test_native_stage_condition_is_checked_at_resolution_sql(tmp_path, start, end):
    state = _control(stage=start)
    repo = MatchRepository(tmp_path / "condition.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    begun = repo.apply(state.match_id, _advance(state)).state
    assert any(i.effect_id == EFFECT for i in begun.pending_effects)
    ctrl = next(i for i in begun.pending_effects if i.effect_id == "CONTROL")
    changes = []
    if end < start:
        changes.append({"adjustment_type":"move_card","target_card_instance_id":"held","to_zone":"hand"})
    elif end > start:
        for slot,key in list(zip(["left","center","right"],["target","wrong-work","held"]))[start:end]:
            changes.append({"adjustment_type":"move_card","target_card_instance_id":key,"to_zone":f"member_{slot}"})
    else:
        changes.append({"adjustment_type":"set_flag","flag":"audit-noop","duration":"turn"})
    result = repo.apply(state.match_id, _manual(begun, changes, ctrl))
    if result.state.pending_effects:
        result = repo.apply(state.match_id, _resolve(result.state))
    assert _event(result).data["stage_member_count"] == end
    assert _event(result).data["milled_count"] == (5 if end == 3 else 0)
    assert repo.replay(state.match_id)["metadata"]["deterministic_replay_verified"] is True


@pytest.mark.parametrize("movement", ["hand", "return", "main_deck", "same_area"])
@pytest.mark.parametrize("old_departure_policy", [False,True])
def test_native_original_live_source_interference_sql(tmp_path, movement, old_departure_policy):
    state = _control()
    if old_departure_policy:
        state.stage_departure_policy = None
    repo = MatchRepository(tmp_path / "source.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    begun = repo.apply(state.match_id, _advance(state)).state
    inv = next(i for i in begun.pending_effects if i.effect_id == EFFECT)
    assert inv.trigger_data["original_source_live_object"] is True
    ctrl = next(i for i in begun.pending_effects if i.effect_id == "CONTROL")
    changes=[{"adjustment_type":"move_card","target_card_instance_id":"source-live",
              "to_zone":"live_area" if movement=="same_area" else "main_deck" if movement=="main_deck" else "hand"}]
    if movement == "return":
        changes.append({"adjustment_type":"move_card","target_card_instance_id":"source-live","to_zone":"live_area"})
    result = repo.apply(state.match_id, _manual(begun, changes, ctrl))
    if result.state.pending_effects:
        result = repo.apply(state.match_id, _resolve(result.state))
    assert _event(result).data["milled_count"] == 5
    assert _event(result).data["drawn_count"] == 1
    assert _event(result).data["score_delta"] == int(movement == "same_area")
    if movement == "hand":
        payload = _match_state_payload(result.state, events=result.events, legal_actions=result.legal_actions, player_id="player_2")
        assert "source-live" not in payload["state"]["cards"]
    replay=repo.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == result.state.model_dump(mode="json")


@pytest.mark.parametrize("deck,waiting", [([],[]),(["m0"],[]),([],["m0"]),(["m0","m4"],[]),(["m0","m1","m2","m3","m4"],[])])
def test_short_deck_repeated_moves_and_post_draw_refresh_sql(tmp_path, deck, waiting):
    state = _pending(members=4)
    p=state.players["player_1"];p.main_deck,p.waiting_room=deck,waiting
    repo=MatchRepository(tmp_path / "short.sqlite3");repo.create_match(state,card_database_path=Path("data/loveca.sqlite3"))
    result=repo.apply(state.match_id,_resolve(state))
    moves=[c for e in result.events if e.event_type=="effect_cards_milled" for c in e.data["revealed_cards"]]
    data=_event(result).data
    assert data["milled_count"]==len(moves)==(5 if deck or waiting else 0)
    assert data["milled_member_count"]==sum(c["card_type"]=="member" for c in moves)
    assert data["drawn_count"]==int(data["milled_member_count"]>=3)
    assert data["score_delta"]==int(bool(moves) and all(c["card_type"]=="member" for c in moves))
    if deck==["m0"] or waiting==["m0"]:
        assert [c["instance_id"] for c in moves]==["m0"]*5
        assert result.state.players["player_1"].refresh_count==(6 if waiting else 5)
    assert repo.replay(state.match_id)["metadata"]["deterministic_replay_verified"] is True


def test_condition_uses_movement_history_before_extra_draw_refresh():
    state=_pending()
    p=state.players["player_1"];p.main_deck=["m0","m1","m2","m3","m4"];p.waiting_room=["live-1"]
    p.live_area.remove("live-1")
    result=apply_action(state,_resolve(state))
    assert _event(result).data["all_members"] is True
    assert _event(result).data["score_delta"]==1
    assert not result.state.players["player_1"].waiting_room


@pytest.mark.parametrize("zone", ["hand","waiting_room","main_deck","live_area"])
@pytest.mark.parametrize("old_departure_policy", [False,True])
def test_departure_after_grant_clears_new_score_but_same_area_preserves(zone,old_departure_policy):
    initial=_state()
    if old_departure_policy:initial.stage_departure_policy=None
    state=apply_action(initial,_advance(initial)).state
    result=apply_action(state,_manual(state,[{"adjustment_type":"move_card","target_card_instance_id":"source-live","to_zone":zone}]))
    assert len(result.state.players["player_1"].manual_modifiers)==int(zone=="live_area")


def test_native_live_end_clears_source_score():
    state=apply_action(_state(),_advance(_state())).state
    state.phase="live_judgment"
    result=apply_action(state,_advance(state))
    if result.state.pending_choice is not None:
        result=apply_action(result.state,ActionRequest(action_type="resolve_live_requirements",player_id="player_1",
            expected_revision=result.state.revision,payload={"success_live_instance_id":"source-live"}))
    assert not any(m.modifier_type=="live_card_score" for m in result.state.players["player_1"].manual_modifiers)


@pytest.mark.parametrize("legacy", [False,True])
def test_new_and_old_manual_snapshots_sql(tmp_path,legacy):
    state=_state(legacy=legacy)
    repo=MatchRepository(tmp_path / "snapshot.sqlite3");repo.create_match(state,card_database_path=Path("data/loveca.sqlite3"))
    result=repo.apply(state.match_id,_advance(state))
    if legacy:
        assert result.state.pending_effects[0].effect_id==EFFECT
        result=repo.apply(state.match_id,_manual(result.state,[{"adjustment_type":"set_flag","flag":"old-manual","duration":"game"}],result.state.pending_effects[0]))
        assert not any(e.event_type=="effect_bottom_five_members_resolved" for e in result.events)
    assert repo.replay(state.match_id)["metadata"]["deterministic_replay_verified"] is True


@pytest.mark.parametrize("policy", ["simple_ai_v0","simple_ai_v1","simple_ai_v1_1","simple_ai_v1_2"])
@pytest.mark.parametrize("pending", [False,True])
def test_four_ai_native_and_pending_hidden_identity_invariance(policy,pending):
    state=_pending() if pending else _state()
    controller=SimpleAIController(SimpleAIPolicy(policy_version=policy,manual_effect_policy="block"))
    before=match_state_hash(state)
    decision=controller.choose_action(state,generate_legal_actions(state),controlled_player_ids={"player_1"})
    assert isinstance(decision,SimpleAIDecision) and before==match_state_hash(state)
    changed=state.model_copy(deep=True)
    for key in ["secret",*state.players["player_1"].main_deck]:
        changed.cards[key].card.card_code=changed.cards[key].card.name_ja="HIDDEN-CHANGED"
        changed.cards[key].card.blade=99
    assert controller.choose_action(changed,generate_legal_actions(changed),controlled_player_ids={"player_1"}).action==decision.action
    assert _event(apply_action(state,decision.action)).data["score_delta"]==1


@pytest.mark.parametrize("members", [2,3,5])
def test_dual_view_draw_and_unmoved_tail_private(members):
    state=_pending(members=members);result=apply_action(state,_resolve(state))
    for viewer in ["player_1","player_2"]:
        payload=_match_state_payload(result.state,events=result.events,legal_actions=result.legal_actions,player_id=viewer)
        assert "tail" not in json.dumps(payload)
        if viewer=="player_2":
            assert "draw-next" not in json.dumps(payload) and "own-secret" not in json.dumps(payload)
        else:
            assert "secret" not in payload["state"]["cards"]


def test_repeated_public_history_does_not_authorize_new_hidden_hand():
    state=_pending();state.players["player_1"].main_deck=["m0"]
    result=apply_action(state,_resolve(state))
    payload=_match_state_payload(result.state,events=result.events,legal_actions=result.legal_actions,player_id="player_2")
    assert "m0" not in payload["state"]["cards"]
    history=[c for e in payload["events"] for c in e["data"].get("revealed_cards",[])]
    assert len(history)==5 and all(c["instance_id"]=="m0" for c in history)


@pytest.mark.parametrize("defect", ["missing_snapshot","non_boolean_snapshot","opponent","decline"])
def test_bad_resolution_is_atomic(defect):
    state=_pending()
    if defect=="missing_snapshot":state.pending_effects[0].trigger_data.clear()
    if defect=="non_boolean_snapshot":state.pending_effects[0].trigger_data["original_source_live_object"]=1
    action=_resolve(state,accepted=defect!="decline")
    if defect=="opponent":action.player_id="player_2"
    before=match_state_hash(state)
    with pytest.raises(IllegalActionError):apply_action(state,action)
    assert before==match_state_hash(state)


@pytest.mark.parametrize("changes", [{"amount":4},{"target":"self"},{"source_object_policy":None},{"value":True}])
def test_operation_is_bounded(changes):
    raw=_state().effect_definitions[EFFECT].model_dump(mode="json");raw["actions"][0].update(changes)
    with pytest.raises(ValidationError):EffectDefinition.model_validate(raw)


@pytest.mark.parametrize("changes", [{"is_optional":True},{"duration":"turn"},{"frequency_limit":"none"},
    {"condition":{"stage_member_count_at_least":3}},{"trigger":"member_played"},{"execution_mode":"prompt_then_resolve"}])
def test_definition_is_bounded(changes):
    raw=_state().effect_definitions[EFFECT].model_dump(mode="json");raw.update(changes)
    with pytest.raises(ValidationError):EffectDefinition.model_validate(raw)


def test_new_operation_is_not_a_cost():
    raw=_state().effect_definitions[EFFECT].model_dump(mode="json");raw.update(cost=raw["actions"],actions=[{"action_type":"draw_card","amount":1}])
    with pytest.raises(ValidationError):EffectDefinition.model_validate(raw)


@pytest.mark.parametrize("change", [{"card_code":"OTHER"},{"text_revision_id":914},{"raw_text_hash":"bad"},{"raw_effect_text_ja":"【ライブ開始時】カードを1枚引く。"}])
def test_exact_generator_rejects_variants(change):
    from loveca.simulation.effect_candidates import BOTTOM_FIVE_MEMBER_SCORE_TEXT,_live_start_bottom_five_member_score
    row={"card_code":CODE,"text_revision_id":913,"raw_text_hash":_state().effect_definitions[EFFECT].raw_text_hash,
         "raw_effect_text_ja":BOTTOM_FIVE_MEMBER_SCORE_TEXT}
    assert _live_start_bottom_five_member_score({**row,**change}) is None


def test_attached_member_is_not_a_third_stage_member():
    state=_state(stage=2);p=state.players["player_1"]
    p.hand.remove("held");p.member_area_attachments["left"]=["held"]
    result=apply_action(state,_advance(state))
    assert _event(result).data["stage_member_count"]==2 and _event(result).data["milled_count"]==0


def test_member_work_or_unit_does_not_filter_five_member_condition():
    state=_pending()
    for key in ["m0","m1","m2","m3","m4"]:
        state.cards[key].card.work_keys=["nijigasaki"];state.cards[key].card.unit_keys=[]
    assert _event(apply_action(state,_resolve(state))).data["score_delta"]==1


def test_stage_changes_after_resolution_do_not_revoke_granted_score():
    state=apply_action(_state(),_advance(_state())).state
    result=apply_action(state,_manual(state,[{"adjustment_type":"move_card","target_card_instance_id":"held","to_zone":"hand"}]))
    assert _card_score(result.state,"player_1","source-live")==6


def test_extra_draw_empty_deck_refresh_happens_before_final_score_sql(tmp_path):
    state=_pending();state.players["player_1"].main_deck=["draw-next","m0","m1","m2","m3","m4"]
    repo=MatchRepository(tmp_path / "after-draw.sqlite3");repo.create_match(state,card_database_path=Path("data/loveca.sqlite3"))
    result=repo.apply(state.match_id,_resolve(state));names=[e.event_type for e in result.events]
    assert names.index("cards_drawn") < names.index("deck_refreshed") < names.index("effect_bottom_five_members_resolved")
    assert _event(result).data["score_delta"]==1 and _event(result).data["drawn_count"]==1
    assert set(result.state.players["player_1"].main_deck)=={"m0","m1","m2","m3","m4"}
    assert repo.replay(state.match_id)["metadata"]["deterministic_replay_verified"] is True


@pytest.mark.parametrize("members", [2,5])
def test_second_performer_uses_owner_deck_and_only_owner_source(members):
    state=_state(members=members)
    state.players["player_1"],state.players["player_2"]=state.players["player_2"],state.players["player_1"]
    for key,p in state.players.items():p.player_id=key
    for card in state.cards.values():card.owner_id="player_2" if card.owner_id=="player_1" else "player_1"
    state.phase,state.active_player_id="performance_second","player_2"
    result=apply_action(state,_advance(state))
    assert _event(result).player_id=="player_2" and _event(result).data["score_delta"]==int(members==5)
    assert not result.state.players["player_1"].manual_modifiers


@pytest.mark.parametrize("zone", ["hand","main_deck","waiting_room"])
def test_live_start_does_not_trigger_source_outside_live_area(zone):
    state=_state();p=state.players["player_1"]
    p.live_area.remove("source-live");getattr(p,zone).append("source-live")
    assert not any(e.event_type=="effect_bottom_five_members_resolved" for e in apply_action(state,_advance(state)).events)


def test_no_live_attempt_has_no_trigger():
    state=_state();p=state.players["player_1"];p.hand.extend(p.live_area);p.live_area=[]
    assert not any(e.event_type=="effect_bottom_five_members_resolved" for e in apply_action(state,_advance(state)).events)


def test_legacy_generic_bottom_mill_snapshot_is_not_reinterpreted(tmp_path):
    state=_state();raw=state.effect_definitions[EFFECT].model_dump(mode="json")
    raw.update(actions=[{"action_type":"mill_bottom_cards","amount":5}],duration=None)
    state.effect_definitions[EFFECT]=EffectDefinition.model_validate(raw)
    repo=MatchRepository(tmp_path / "generic.sqlite3");repo.create_match(state,card_database_path=Path("data/loveca.sqlite3"))
    result=repo.apply(state.match_id,_advance(state))
    assert not any(e.event_type=="effect_bottom_five_members_resolved" for e in result.events)
    assert result.state.players["player_1"].hand==["own-secret"]
    assert repo.replay(state.match_id)["metadata"]["deterministic_replay_verified"] is True
