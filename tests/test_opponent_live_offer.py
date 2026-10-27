import json
from copy import deepcopy
from pathlib import Path

import pytest
from test_nijigasaki_inspection import _state as _base_state, _candidate
from test_mirakura_front_position_boundary import _swap_roles

from loveca.simulation.effects import EffectDefinition
from loveca.simulation.engine import IllegalActionError, StaleRevisionError, apply_action, generate_legal_actions
from loveca.simulation.models import ActionRequest
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository
from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.webapp import _match_state_payload

CODE = "PL!SP-bp2-011"
EFFECT = CODE + ":1"
CHOICE = "multi_player_opponent_live_offer"
POLICY = "public_two_distinct_live_opponent_one"


def _state(names=("A", "B", "C"), *, owner="player_1"):
    state = _base_state(CODE)
    state.effect_order_policy = "ap_nap_player_choice"
    state.players["player_1"].waiting_room = []
    for i, name in enumerate(names):
        key = f"offered-live-{i}"
        card = state.cards["good-live"].model_copy(deep=True)
        card.instance_id = key
        card.card.name_ja = name
        card.card.card_code = "LIVE-" + name
        card.card.card_id = f"LIVE-{name}-PRINT-{i}"
        card.card.score = i + 1
        state.cards[key] = card
        state.players["player_1"].waiting_room.append(key)
    state.players["player_1"].waiting_room.append("good-member")
    state.players["player_1"].main_deck.remove("good-member")
    state.players["player_2"].waiting_room.append("foreign-live")
    state.cards["foreign-live"] = state.cards["good-live"].model_copy(
        deep=True, update={"instance_id": "foreign-live", "owner_id": "player_2"})
    state = _swap_roles(state) if owner == "player_2" else state
    zones = []
    for player in state.players.values():
        for zone in (player.hand, player.main_deck, player.energy_deck, player.energy_area,
                     player.waiting_room, player.live_area, player.resolution_area, player.success_live_area):
            zones.extend(zone)
        zones.extend(item for item in player.member_area.values() if item)
        zones.extend(item for group in player.member_area_attachments.values() for item in group)
    assert len(zones) == len(set(zones)), "test fixture regions must be mutually exclusive"
    return state


def _play(state, owner="player_1"):
    return ActionRequest(action_type="play_member", player_id=owner, expected_revision=state.revision,
        payload={"card_instance_id": "source-live", "slot": "center", "use_baton_touch": False,
                 "energy_instance_ids": list(state.players[owner].energy_area)})


def _resolve(state, owner="player_1"):
    inv = next(i for i in state.pending_effects if i.effect_id == EFFECT)
    return ActionRequest(action_type="resolve_effect", player_id=owner, expected_revision=state.revision,
        payload={"invocation_id": inv.invocation_id})


def _begin(state=None, *, owner="player_1"):
    state = state or _state(owner=owner)
    played = apply_action(state, _play(state, owner)).state
    return apply_action(played, _resolve(played, owner))


def _choose(state, ids, *, actor=None, **extra):
    return ActionRequest(action_type="resolve_effect_choice", player_id=actor or state.pending_choice.player_id,
        expected_revision=state.revision, payload={"selected_card_instance_ids": ids, **extra})


def test_native_onplay_offers_two_distinct_live_cards_before_opponent_chooses():
    result = _begin()
    assert result.state.pending_choice.options["multi_player_choice_type"] == CHOICE
    assert result.state.pending_choice.player_id == "player_1"
    assert result.state.pending_choice.options["minimum"] == 2


def _legacy_effect():
    raw = _candidate(CODE).to_registry_entry()
    raw.update(choice=None, actions=[{"action_type": "manual_resolution"}], execution_mode="manual_resolution",
        simulation_support="manual_resolution", review_status="parsed_draft",
        source_reference="Official card text; timing-only manual fallback pending structured effect modeling")
    return EffectDefinition.model_validate(raw)


def _first_ids(state):
    from loveca.simulation.ai import opponent_live_offer_selection
    return opponent_live_offer_selection(state.pending_choice.options,
        state.pending_choice.options["candidate_card_instance_ids"])


@pytest.mark.parametrize("names", [(), ("A",), ("A", "A"), ("A", "B"), ("A", "A", "B"), ("A", "B", "C")])
@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_q118_distinct_names_and_opponent_only_selects_when_pair_exists_sql(tmp_path, names, owner):
    initial = _state(names, owner=owner)
    original_hand = list(initial.players[owner].hand)
    original_waiting = list(initial.players[owner].waiting_room)
    repo = MatchRepository(tmp_path / "offers.sqlite3")
    repo.create_match(initial, card_database_path=Path("data/loveca.sqlite3"))
    played = repo.apply(initial.match_id, _play(initial, owner)).state
    current = repo.apply(initial.match_id, _resolve(played, owner))
    offered = []
    if current.state.pending_choice:
        assert current.state.pending_choice.player_id == owner
        offered = _first_ids(current.state)
        current = repo.apply(initial.match_id, _choose(current.state, offered))
    has_pair = len(set(names)) >= 2
    if has_pair:
        assert current.state.pending_choice.player_id != owner
        assert all(item in current.state.players[owner].waiting_room for item in offered)
        assert current.state.pending_choice.options["candidate_card_instance_ids"] == offered
        chosen = offered[-1]
        current = repo.apply(initial.match_id, _choose(current.state, [chosen]))
        assert chosen in current.state.players[owner].hand
        assert [item for item in offered if item != chosen][0] in current.state.players[owner].waiting_room
    else:
        assert current.state.pending_choice is None
        assert current.state.players[owner].hand == [item for item in original_hand if item != "source-live"]
        assert current.state.players[owner].waiting_room == original_waiting
    recovered = next(e for e in current.events if e.event_type == "effect_opponent_live_recovered")
    assert recovered.data["condition_met"] is has_pair
    assert recovered.data["recovered_count"] == int(has_pair)
    assert not current.state.pending_effects
    assert repo.replay(initial.match_id)["final_state"] == current.state.model_dump(mode="json")


@pytest.mark.parametrize("ids", [[], ["offered-live-0"], ["offered-live-0", "offered-live-0"],
    ["offered-live-0", "offered-live-1"], ["offered-live-0", "foreign-live"],
    ["good-member", "offered-live-2"], ["cost", "offered-live-2"], [1, "offered-live-2"],
    ["offered-live-0", "offered-live-1", "offered-live-2"], None])
def test_owner_must_offer_exactly_two_distinct_own_waiting_lives_atomically(ids):
    state = _begin(_state(("A", "A", "B"))).state
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _choose(state, ids))
    assert match_state_hash(state) == before


@pytest.mark.parametrize("ids", [[], ["offered-live-2"], ["foreign-live"], ["good-member"],
    ["offered-live-0", "offered-live-1"], ["offered-live-0", "offered-live-0"], [True], None])
def test_opponent_must_choose_exactly_one_fixed_offered_card_atomically(ids):
    state = _begin().state
    state = apply_action(state, _choose(state, ["offered-live-0", "offered-live-1"])).state
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _choose(state, ids))
    assert match_state_hash(state) == before


@pytest.mark.parametrize("stage", [0, 1])
@pytest.mark.parametrize("field,value", [("selected_card_instance_id", "foreign-live"), ("slot", "left"),
    ("target_player_id", "player_2"), ("ordered_card_instance_ids", []), ("selected_destination", "hand")])
def test_other_operation_fields_are_rejected_without_changing_state(stage, field, value):
    state = _begin().state
    if stage:
        state = apply_action(state, _choose(state, ["offered-live-0", "offered-live-1"])).state
    ids = ["offered-live-0"] if stage else ["offered-live-0", "offered-live-1"]
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _choose(state, ids, **{field: value}))
    assert match_state_hash(state) == before


@pytest.mark.parametrize("stage", [0, 1])
def test_wrong_actor_and_duplicate_revision_cannot_choose_for_other_player(stage):
    state = _begin().state
    first = _choose(state, ["offered-live-0", "offered-live-1"])
    advanced = apply_action(state, first).state
    with pytest.raises(StaleRevisionError):
        apply_action(advanced, first)
    state = advanced if stage else state
    before = match_state_hash(state)
    other = "player_1" if state.pending_choice.player_id == "player_2" else "player_2"
    with pytest.raises(IllegalActionError):
        apply_action(state, _choose(state, ["offered-live-0"], actor=other))
    assert match_state_hash(state) == before


@pytest.mark.parametrize("stage", [0, 1])
@pytest.mark.parametrize("action_type", ["skip_effect", "manual_adjustment"])
def test_pending_public_offer_cannot_be_replaced_or_skipped(stage, action_type):
    state = _begin().state
    if stage:
        state = apply_action(state, _choose(state, ["offered-live-0", "offered-live-1"])).state
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, ActionRequest(action_type=action_type, player_id=state.pending_choice.player_id,
            expected_revision=state.revision, payload={"invocation_id": state.pending_effects[0].invocation_id,
                "adjustments": [{"adjustment_type": "move_card", "target_card_instance_id": "offered-live-0", "to_zone": "hand"}]}))
    assert match_state_hash(state) == before


def test_stale_offered_card_cannot_be_replaced_with_other_waiting_live():
    state = _begin().state
    state = apply_action(state, _choose(state, ["offered-live-0", "offered-live-1"])).state
    state.players["player_1"].waiting_room.remove("offered-live-0")
    state.players["player_1"].hand.append("offered-live-0")
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError, match="original public Live offer"):
        apply_action(state, _choose(state, ["offered-live-1"]))
    assert match_state_hash(state) == before


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("zone", ["hand", "main_deck", "waiting_room", "returned", "member_right"])
def test_native_source_interference_then_public_offer_sql(tmp_path, owner, zone):
    state = _state(owner=owner)
    state.effect_definitions["CONTROL"] = _legacy_effect().model_copy(update={"effect_id": "CONTROL"})
    state.cards["source-live"].card.effect_ids.append("CONTROL")
    repo = MatchRepository(tmp_path / "source.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    played = repo.apply(state.match_id, _play(state, owner)).state
    control = next(i for i in played.pending_effects if i.effect_id == "CONTROL")
    changes = [{"adjustment_type": "move_card", "target_player_id": owner,
                "target_card_instance_id": "source-live", "to_zone": "waiting_room" if zone == "returned" else zone}]
    if zone == "returned":
        changes.append({"adjustment_type": "move_card", "target_player_id": owner,
                        "target_card_instance_id": "source-live", "to_zone": "member_right"})
    moved = repo.apply(state.match_id, ActionRequest(action_type="manual_adjustment", player_id=owner,
        expected_revision=played.revision, payload={"adjustments": changes, "source_invocation_id": control.invocation_id,
            "source_effect_id": "CONTROL", "source_card_instance_id": "source-live", "reason": "TEST CONTROL"})).state
    current = repo.apply(state.match_id, _resolve(moved, owner))
    current = repo.apply(state.match_id, _choose(current.state, ["offered-live-0", "offered-live-1"]))
    opponent = current.state.pending_choice.player_id
    payload = _match_state_payload(current.state, events=current.events, legal_actions=current.legal_actions, player_id=opponent)
    if zone in {"hand", "main_deck"}:
        assert "source-live" not in payload["state"]["cards"]
        assert "source-live" not in json.dumps(payload)
    assert payload["state"]["pending_choice"]["options"]["selections"][owner]["selected_card_instance_ids"] == ["offered-live-0", "offered-live-1"]
    final = repo.apply(state.match_id, _choose(current.state, ["offered-live-1"]))
    assert "offered-live-1" in final.state.players[owner].hand
    assert repo.replay(state.match_id)["final_state"] == final.state.model_dump(mode="json")


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_full_views_keep_hidden_hands_and_deck_private_after_public_recovery(owner):
    first = _begin(_state(owner=owner), owner=owner)
    second = apply_action(first.state, _choose(first.state, ["offered-live-0", "offered-live-1"]))
    final = apply_action(second.state, _choose(second.state, ["offered-live-1"]))
    for viewer in final.state.players:
        payload = _match_state_payload(final.state, events=final.events, legal_actions=final.legal_actions, player_id=viewer)
        assert "tail" not in json.dumps(payload)
        assert "AUDIT-tail" not in json.dumps(payload)
        if viewer != owner:
            assert "offered-live-1" not in payload["state"]["cards"]
        event = next(e for e in payload["events"] if e["event_type"] == "effect_opponent_live_recovered")
        assert event["data"]["revealed_cards"][0]["instance_id"] == "offered-live-1"


@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("names", [("A", "A", "B"), ("A",)])
def test_four_ai_legal_public_choices_invariant_to_hidden_identities(policy, owner, names):
    initial = _state(names, owner=owner)
    result = apply_action(initial, _play(initial, owner))
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    while result.state.pending_choice or result.state.pending_effects:
        state = result.state
        actor = state.pending_choice.player_id if state.pending_choice else owner
        before = match_state_hash(state)
        decision = controller.choose_action(state, result.legal_actions, controlled_player_ids={actor})
        assert isinstance(decision, SimpleAIDecision)
        changed = state.model_copy(deep=True)
        hidden = set(changed.players[actor].main_deck)
        hidden.update(item for p, player in changed.players.items() if p != actor for item in player.hand)
        for key in hidden:
            card = changed.cards.pop(key)
            card.instance_id = "hidden-" + key
            card.card.name_ja = card.card.card_code = "HIDDEN-REPLACED"
            card.card.blade = 100
            changed.cards[card.instance_id] = card
            for player in changed.players.values():
                player.hand = [card.instance_id if item == key else item for item in player.hand]
                player.main_deck = [card.instance_id if item == key else item for item in player.main_deck]
        assert controller.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={actor}) == decision
        assert match_state_hash(state) == before
        result = apply_action(state, decision.action)
    assert not result.state.pending_effects


def test_old_manual_snapshot_sql_still_does_not_gain_opponent_choice(tmp_path):
    state = _state()
    state.effect_definitions[EFFECT] = _legacy_effect()
    repo = MatchRepository(tmp_path / "old.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    played = repo.apply(state.match_id, _play(state)).state
    inv = next(i for i in played.pending_effects if i.effect_id == EFFECT)
    final = repo.apply(state.match_id, ActionRequest(action_type="manual_adjustment", player_id="player_1",
        expected_revision=played.revision, payload={"adjustments": [{"adjustment_type": "move_card",
                "target_player_id": "player_1", "target_card_instance_id": "offered-live-0", "to_zone": "hand"}],
            "source_invocation_id": inv.invocation_id, "source_effect_id": EFFECT, "source_card_instance_id": "source-live"})).state
    assert final.pending_choice is None and not final.pending_effects
    assert repo.replay(state.match_id)["final_state"] == final.model_dump(mode="json")


@pytest.mark.parametrize("changes", [{"is_optional": True}, {"timing": "live_start"}, {"duration": "turn"},
    {"actions": [{"action_type": "draw_card", "amount": 1}]}, {"condition": {"x": True}}])
def test_policy_rejects_unbounded_snapshot(changes):
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate({**_candidate(CODE).to_registry_entry(), **changes})


@pytest.mark.parametrize("field,value", [("card_code", "OTHER"), ("text_revision_id", 566),
    ("raw_text_hash", "changed"), ("raw_effect_text_ja", "changed")])
def test_generator_requires_full_exact_identity(field, value):
    from loveca.simulation.effect_candidates import _onplay_opponent_live_offer
    candidate = _candidate(CODE)
    row = {"card_code": CODE, "text_revision_id": 565, "raw_text_hash": candidate.raw_text_hash,
           "raw_effect_text_ja": candidate.label_ja}
    assert _onplay_opponent_live_offer(row) is not None
    assert _onplay_opponent_live_offer({**row, field: value}) is None


def test_semantic_example_selects_distinct_names_and_then_only_offered_one():
    from tools.ai_sandbox.semantic_playtest import payload_example_for_action
    result = _begin(_state(("A", "A", "B")))
    while result.state.pending_choice:
        action = next(a for a in result.legal_actions if a.action_type == "resolve_effect_choice")
        result = apply_action(result.state, _choose(result.state, **{"ids": payload_example_for_action(action)["selected_card_instance_ids"]}))
    assert not result.state.pending_effects


@pytest.mark.parametrize("field,value", [("maximum", 3), ("minimum", 0), ("zone", "hand"),
    ("card_type", "member"), ("target_player", "opponent"), ("requires_order", True),
    ("selection_policy", None)])
def test_choice_snapshot_rejects_wider_selection(field, value):
    from pydantic import ValidationError
    raw = deepcopy(_candidate(CODE).to_registry_entry())
    raw["choice"][field] = value
    with pytest.raises(ValidationError):
        EffectDefinition.model_validate(raw)


@pytest.mark.parametrize("extra", [{"selected_card_instance_ids": ["offered-live-0"]},
    {"selected_destination": "hand"}, {"target_player_id": "player_2"}])
def test_initial_resolution_cannot_submit_offer_or_opponent_selection_inline(extra):
    initial = _state()
    played = apply_action(initial, _play(initial)).state
    action = _resolve(played)
    action.payload.update(extra)
    before = match_state_hash(played)
    with pytest.raises(IllegalActionError):
        apply_action(played, action)
    assert match_state_hash(played) == before


@pytest.mark.parametrize("names,changes", [
    ((), [{"adjustment_type": "move_card", "target_card_instance_id": "good-live", "to_zone": "waiting_room"}]),
    (("A",), [{"adjustment_type": "move_card", "target_card_instance_id": "good-live", "to_zone": "waiting_room"}]),
    (("A", "B"), [{"adjustment_type": "move_card", "target_card_instance_id": "offered-live-0", "to_zone": "hand"}]),
    (("A", "B"), [{"adjustment_type": "move_card", "target_card_instance_id": key, "to_zone": "hand"}
                  for key in ("offered-live-0", "offered-live-1")]),
])
def test_native_candidate_changes_before_resolution_use_current_waiting_room_sql(tmp_path, names, changes):
    state = _state(names)
    state.effect_definitions["CONTROL"] = _legacy_effect().model_copy(update={"effect_id": "CONTROL"})
    state.cards["source-live"].card.effect_ids.append("CONTROL")
    repo = MatchRepository(tmp_path / "candidate-change.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    played = repo.apply(state.match_id, _play(state)).state
    control = next(i for i in played.pending_effects if i.effect_id == "CONTROL")
    moved = repo.apply(state.match_id, ActionRequest(action_type="manual_adjustment", player_id="player_1",
        expected_revision=played.revision, payload={"adjustments": [{"target_player_id": "player_1", **x} for x in changes],
            "source_invocation_id": control.invocation_id, "source_effect_id": "CONTROL",
            "source_card_instance_id": "source-live", "reason": "TEST CONTROL"})).state
    actual_names = {moved.cards[x].card.name_ja for x in moved.players["player_1"].waiting_room
                    if moved.cards[x].card.card_type == "live"}
    current = repo.apply(state.match_id, _resolve(moved))
    while current.state.pending_choice:
        current = repo.apply(state.match_id, _choose(current.state, _first_ids(current.state)))
    event = next(e for e in current.events if e.event_type == "effect_opponent_live_recovered")
    assert event.data["condition_met"] == (len(actual_names) >= 2)
    assert repo.replay(state.match_id)["final_state"] == current.state.model_dump(mode="json")


def test_forged_offer_marker_cannot_upgrade_legacy_multi_player_snapshot():
    from test_multi_player_entry import _state as old_state, _begin as old_begin
    state = old_begin(old_state())
    state.pending_choice.options.update(multi_player_choice_type=CHOICE, selection_policy=POLICY,
                                        owner_player_id=state.pending_choice.player_id)
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError, match="actual snapshot"):
        apply_action(state, _choose(state, []))
    assert match_state_hash(state) == before


def test_official_registry_exact_full_text_identity_and_bounded_choice():
    state = _state()
    effect = state.effect_definitions[EFFECT]
    assert effect == EffectDefinition.model_validate(_candidate(CODE).to_registry_entry())
    assert (effect.text_revision_id, effect.raw_text_hash) == (565, "9e4fd4e9e0b3b110651c0f1139e851bab7f588d77460a36f422db788ae4ef09c")
    assert effect.label_ja == state.cards["source-live"].card.raw_effect_text_ja
    assert effect.simulation_support == "test_validated_executable" and effect.review_status == "test_validated"
