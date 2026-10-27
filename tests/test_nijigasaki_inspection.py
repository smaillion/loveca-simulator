from contextlib import closing
from functools import lru_cache
from pathlib import Path

import pytest
from test_effect_execution import _minimal_effect_state

from loveca.db.bootstrap import connect_database
from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation.catalog import _load_definition
from loveca.simulation.effect_candidates import discover_effect_candidates
from loveca.simulation.effects import EffectDefinition, load_effect_registry
from loveca.simulation.engine import IllegalActionError, apply_action, generate_legal_actions
from loveca.simulation.models import ActionRequest, CardDefinition, CardInstance, SpecialBladeHeart
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository
from loveca.webapp import _match_state_payload

CODES = ("PL!N-sd2-009", "PL!N-sd2-012", "PL!N-sd2-014", "PL!N-bp7-018")
RULE_REFERENCE_IDS = ("5.7.1", "9.4.2", "9.6.3.1.4", "9.7.3.1.1", "10.2.2.2", "10.2.3", "11.4.2")


@lru_cache
def _candidate(code):
    return next(c for c in discover_effect_candidates(Path("data/loveca.sqlite3"), include_registered=True)
                if c.effect_id == code + ":1")


def _state(code, *, legacy=False):
    effect = next(e for e in load_effect_registry().effects if e.effect_id == code + ":1")
    if legacy:
        effect = effect.model_copy(update={"choice": None, "cost": [], "cost_choice": None,
            "execution_mode": "manual_resolution", "simulation_support": "manual_resolution",
            "actions": [effect.actions[0].model_copy(update={"action_type": "manual_resolution"})]})
    with closing(connect_database(Path("data/loveca.sqlite3"))) as connection:
        source = _load_definition(connection, code, None, {effect.effect_id: effect}, {})
    state = _minimal_effect_state(effect)
    state.phase, state.pending_effects = "first_main", []
    state.cards["source-live"].card = source
    player = state.players["player_1"]
    player.live_area = []
    player.hand = ["source-live"]
    for key, work, card_type, special in [
        ("cost", "nijigasaki", "member", []),
        ("good-member", "nijigasaki", "member", []),
        ("good-live", "nijigasaki", "live", []),
        ("wrong-work", "love_live_superstar", "member", []),
        ("blade-heart", "nijigasaki", "member", [{"effect_type": "draw", "source_alt": "ドロー", "value": 1}]),
        ("tail", "nijigasaki", "member", []),
        ("opponent-secret", "nijigasaki", "member", []),
    ]:
        raw = state.cards["deck-member-1"].card.model_dump(mode="json")
        raw.update(card_code="AUDIT-" + key, card_id="AUDIT-" + key, name_ja="AUDIT-" + key,
                   card_type=card_type, work_keys=[work], effect_ids=[], special_blade_hearts=special)
        if key == "good-member":
            raw["image_url"] = "https://example.test/good-member.png"
        state.cards[key] = CardInstance(instance_id=key, owner_id="player_2" if key == "opponent-secret" else "player_1",
                                       card=CardDefinition.model_validate(raw), face_up=False)
    player.hand.append("cost")
    player.main_deck = ["good-member", "good-live", "wrong-work", "blade-heart", "tail", "deck-live-1"]
    state.players["player_2"].hand = ["opponent-secret"]
    for i in range(source.cost):
        key = f"energy-{i}"
        state.cards[key] = CardInstance(instance_id=key, owner_id="player_1",
            card=CardDefinition(card_code="AUDIT-ENERGY", card_id="AUDIT-ENERGY", name_ja="AUDIT", card_type="energy"))
        player.energy_area.append(key)
    return state


def _play(state):
    return ActionRequest(action_type="play_member", player_id="player_1", expected_revision=state.revision,
        payload={"card_instance_id": "source-live", "slot": "center", "energy_instance_ids": state.players["player_1"].energy_area,
                 "use_baton_touch": False})


def _resolve(state, **payload):
    return ActionRequest(action_type="resolve_effect", player_id="player_1", expected_revision=state.revision,
        payload={"invocation_id": state.pending_effects[0].invocation_id, "accepted": True, **payload})


def _inspect(state):
    return apply_action(state, _resolve(state, **({"selected_card_instance_ids": ["cost"]} if state.pending_effects[0].effect_id != CODES[0] + ":1" else {})))


def _select(state, ids):
    return ActionRequest(action_type="resolve_effect_choice", player_id="player_1", expected_revision=state.revision,
                         payload={"selected_card_instance_ids": ids})


@pytest.mark.parametrize("code", CODES)
def test_real_onplay_is_structured_not_manual(code):
    result = apply_action(_state(code), _play(_state(code)))
    assert result.state.pending_effects[0].effect_id == code + ":1"
    assert next(a for a in result.legal_actions if a.action_type == "resolve_effect").options["invocations"][0]["execution_mode"] == "prompt_then_resolve"


@pytest.mark.parametrize("code,revision,hash_value", [
    (CODES[0], 940, "b64351fca23338935d3946e58e848a264e14912b996a77a11b0b031f90468d6d"),
    (CODES[1], 943, "63f2404c02df8f97141c7010c582421c3d67017654b29028d75fb066a71ffd88"),
    (CODES[2], 945, "63f2404c02df8f97141c7010c582421c3d67017654b29028d75fb066a71ffd88"),
    (CODES[3], 881, "f1f681a59c0dbbe12f4d400fefa2b32c7117ee99b89d90be272f34ef8271f0e1")])
def test_exact_identity_candidate_and_registry(code, revision, hash_value):
    effect = _state(code).effect_definitions[code + ":1"]
    assert effect == EffectDefinition.model_validate(_candidate(code).to_registry_entry())
    assert (effect.text_revision_id, effect.raw_text_hash) == (revision, hash_value)
    assert effect.review_status == "test_validated" and effect.simulation_support == "test_validated_executable"
    assert effect.choice.minimum == 0 and effect.choice.maximum == 1
    assert effect.choice.work_key == "nijigasaki" and effect.choice.reveal_selected_to_opponent
    assert effect.choice.exclude_blade_heart == (code == CODES[3])


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("selected", [[], ["good-member"]])
def test_native_inspect_cost_selection_and_remaining_zones(code, selected):
    state = apply_action(_state(code), _play(_state(code))).state
    result = _inspect(state)
    count = 5 if code == CODES[3] else 3
    assert result.state.pending_choice.options["inspected_card_instance_ids"] == state.players["player_1"].main_deck[:count]
    assert ("cost" in result.state.players["player_1"].waiting_room) == (code != CODES[0])
    final = apply_action(result.state, _select(result.state, selected))
    player = final.state.players["player_1"]
    assert set(player.hand) == set(selected + (["cost"] if code == CODES[0] else []))
    assert set(player.waiting_room) == set(state.players["player_1"].main_deck[:count]) - set(selected) | ({"cost"} if code != CODES[0] else set())
    assert player.main_deck == state.players["player_1"].main_deck[count:]
    assert not final.state.pending_effects and final.state.pending_choice is None


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("invalid", [["wrong-work"], ["cost"], ["opponent-secret"], ["good-member", "good-live"], ["good-member", "good-member"]])
def test_inspection_illegal_target_is_atomic(code, invalid):
    state = _inspect(apply_action(_state(code), _play(_state(code))).state).state
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _select(state, invalid))
    assert match_state_hash(state) == before


def test_no_blade_heart_member_filter_rejects_live_and_special_heart():
    state = _inspect(apply_action(_state(CODES[3]), _play(_state(CODES[3]))).state).state
    legal = next(a for a in generate_legal_actions(state) if a.action_type == "resolve_effect_choice")
    assert set(legal.options["candidate_card_instance_ids"]) == {"good-member", "tail"}
    for key in ("good-live", "blade-heart"):
        with pytest.raises(IllegalActionError):
            apply_action(state, _select(state, [key]))


@pytest.mark.parametrize("kind", ["heart01", "heart02", "heart03", "heart04", "heart05", "heart06", "draw", "score", "all_color", "unknown"])
def test_all_color_and_special_blade_hearts_are_excluded(kind):
    state = apply_action(_state(CODES[3]), _play(_state(CODES[3]))).state
    card = state.cards["blade-heart"].card
    card.blade_heart_color_slot = kind if kind.startswith("heart") else None
    card.special_blade_hearts = [] if kind.startswith("heart") else [SpecialBladeHeart(effect_type=kind, source_alt="AUDIT")]
    inspected = _inspect(state)
    assert "blade-heart" not in inspected.state.pending_choice.options["candidate_card_instance_ids"]
    before = match_state_hash(inspected.state)
    with pytest.raises(IllegalActionError):
        apply_action(inspected.state, _select(inspected.state, ["blade-heart"]))
    assert match_state_hash(inspected.state) == before


@pytest.mark.parametrize("code", CODES[1:])
def test_declining_optional_cost_preserves_deck_and_hand(code):
    state = apply_action(_state(code), _play(_state(code))).state
    result = apply_action(state, _resolve(state, accepted=False))
    assert result.state.players["player_1"].hand == ["cost"]
    assert result.state.players["player_1"].main_deck == state.players["player_1"].main_deck
    assert not result.state.pending_effects and result.state.pending_choice is None


@pytest.mark.parametrize("code", CODES)
def test_no_eligible_inspected_card_finishes_without_inventing_a_target(code):
    state = apply_action(_state(code), _play(_state(code))).state
    for key in state.players["player_1"].main_deck:
        state.cards[key].card.work_keys = ["love_live_superstar"]
    inspected = _inspect(state)
    final = apply_action(inspected.state, _select(inspected.state, [])) if inspected.state.pending_choice else inspected
    assert final.state.pending_choice is None and not final.state.pending_effects
    assert final.state.players["player_1"].hand == (["cost"] if code == CODES[0] else [])


@pytest.mark.parametrize("code", CODES[1:])
@pytest.mark.parametrize("ids", [[], ["source-live"], ["opponent-secret"], ["cost", "cost"]])
def test_invalid_discard_cost_never_starts_private_inspection(code, ids):
    state = apply_action(_state(code), _play(_state(code))).state
    before = match_state_hash(state)
    with pytest.raises(IllegalActionError):
        apply_action(state, _resolve(state, selected_card_instance_ids=ids))
    assert match_state_hash(state) == before and state.pending_choice is None


@pytest.mark.parametrize("code", CODES)
def test_candidate_requires_complete_exact_segment(code):
    from loveca.simulation.effect_candidates import _nijigasaki_onplay_inspection
    effect = _state(code).effect_definitions[code + ":1"]
    row = {"card_code": code, "text_revision_id": effect.text_revision_id,
           "raw_text_hash": effect.raw_text_hash, "raw_effect_text_ja": effect.label_ja + "カードを1枚引く。"}
    assert _nijigasaki_onplay_inspection(row) is None


@pytest.mark.parametrize("code", CODES)
def test_short_deck_refreshes_below_remaining_cards_after_optional_cost(code):
    state = apply_action(_state(code), _play(_state(code))).state
    state.players["player_1"].main_deck = ["good-member"]
    state.players["player_1"].waiting_room = ["good-live", "wrong-work", "blade-heart", "tail"]
    result = _inspect(state)
    inspected = result.state.pending_choice.options["inspected_card_instance_ids"]
    assert inspected[0] == "good-member" and len(inspected) == (5 if code == CODES[3] else 3)
    kinds = [e.event_type for e in result.events]
    assert kinds.index("deck_refreshed") < kinds.index("effect_inspection_started")
    if code != CODES[0]:
        assert kinds.index("effect_cost_paid") < kinds.index("deck_refreshed")
    final = apply_action(result.state, _select(result.state, []))
    assert not final.state.pending_effects and final.state.pending_choice is None


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("legacy", [False, True])
def test_sql_replay_old_manual_and_new_inspection(tmp_path, code, legacy):
    state = _state(code, legacy=legacy)
    repository = MatchRepository(tmp_path / "runtime.sqlite3")
    repository.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    result = repository.apply(state.match_id, _play(state))
    if not legacy:
        result = repository.apply(state.match_id, _resolve(result.state, **({"selected_card_instance_ids": ["cost"]} if code != CODES[0] else {})))
        result = repository.apply(state.match_id, _select(result.state, ["good-member"]))
    replay = repository.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["final_state"] == result.state.model_dump(mode="json")


@pytest.mark.parametrize("code", CODES)
def test_private_inspected_cards_and_public_selected_card(code):
    state = _inspect(apply_action(_state(code), _play(_state(code))).state).state
    own = _match_state_payload(state, events=[], legal_actions=generate_legal_actions(state), player_id="player_1")
    other = _match_state_payload(state, events=[], legal_actions=generate_legal_actions(state), player_id="player_2")
    assert "good-member" in own["state"]["cards"] and "good-member" not in other["state"]["cards"]
    assert other["state"]["pending_choice"]["options"].get("inspected_card_instance_ids", []) == []
    result = apply_action(state, _select(state, ["good-member"]))
    other = _match_state_payload(result.state, events=result.events, legal_actions=result.legal_actions, player_id="player_2")
    revealed = next(card for event in other["events"] for card in event["data"].get("revealed_cards", []) if card.get("instance_id") == "good-member")
    assert (revealed["card_code"], revealed["name_ja"], revealed["image_url"]) == (
        "AUDIT-good-member", "AUDIT-good-member", "https://example.test/good-member.png")
    assert "cost" not in other["state"]["players"]["player_1"]["hand"]


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_four_policies_finish_choices_without_opponent_hidden_dependency(code, policy):
    state = apply_action(_state(code), _play(_state(code))).state
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy))
    for _ in range(2):
        if not state.pending_effects and state.pending_choice is None:
            break
        before = match_state_hash(state)
        decision = controller.choose_action(state, generate_legal_actions(state), controlled_player_ids={"player_1"})
        assert isinstance(decision, SimpleAIDecision)
        assert match_state_hash(state) == before
        changed = state.model_copy(deep=True)
        changed.cards["opponent-secret"].card.card_code = "AUDIT-CHANGED-SECRET"
        assert controller.choose_action(changed, generate_legal_actions(changed), controlled_player_ids={"player_1"}).action == decision.action
        state = apply_action(state, decision.action).state
    assert not state.pending_effects and state.pending_choice is None
