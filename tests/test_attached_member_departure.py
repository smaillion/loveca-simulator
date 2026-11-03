import hashlib
import json

import pytest

from loveca.simulation.ai import SimpleAIController, SimpleAIPolicy
from loveca.simulation.engine import IllegalActionError, StaleRevisionError, _effective_member_blade
from loveca.simulation.models import ActionRequest, ManualModifier, MatchState
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository
from test_mulligan_boundary import _replay
from test_normal_phase_boundary import _constructed, _private
from test_yell_icons_boundary import _choose


POLICY = "clear_target_modifiers_v1"
FIELD = "attached_member_departure_policy"
SLOTS = ("left", "center", "right")


def _fixture(path, owner, slot="left", *, modern=True, extra=True, stage_policy=True):
    _, state = _constructed(path / "base", owner, stage_count=1)
    state.phase = "first_main"
    state.attached_member_departure_policy = POLICY if modern else None
    if not stage_policy:
        state.stage_departure_policy = None
    for card in state.cards.values():
        card.card.effect_ids = []
        card.card.raw_effect_text_ja = None
        card.card.ability_bucket = "none"
    player = state.players[owner]
    player.main_deck.extend(player.hand)
    player.hand = []
    top = player.member_area["left"]
    player.member_area["left"] = None
    player.member_area[slot] = top
    member = next(i for i in player.main_deck if state.cards[i].card.card_type == "member")
    player.main_deck.remove(member)
    energy = player.energy_deck.pop(0)
    player.member_area_attachments[slot] = [member, energy]
    for item in (member, energy):
        state.cards[item].face_up = True
    state.cards[member].card.blade = 1
    state.cards[member].orientation = "active"
    player.manual_modifiers.append(ManualModifier(modifier_id="EXTRACTION-AUDIT",
        modifier_type="blade", duration="turn", amount=2, created_turn=state.turn_number,
        target_card_instance_id=member))
    if extra:
        for holder in state.players:
            for kind in ("blade", "heart", "flag"):
                for target in (member, top, None):
                    state.players[holder].manual_modifiers.append(ManualModifier(
                        modifier_id=f"{holder}-{kind}-{target}", modifier_type=kind, duration="game",
                        amount=2, created_turn=state.turn_number, target_card_instance_id=target,
                        color_slot="heart01" if kind == "heart" else None,
                        flag="audit_mark" if kind == "flag" else None,
                        value=True if kind == "flag" else None))
    state = MatchState.model_validate(state.model_dump())
    repo = MatchRepository(path / "extraction.sqlite3")
    repo.create_match(state, card_database_path=path / "base/setup/cards.sqlite3")
    return repo, state, member, energy


def _command(state, target, destination, attached=True):
    return ActionRequest(action_type="manual_adjustment", expected_revision=state.revision,
        player_id=state.active_player_id, payload={"reason": "AUDIT independent attachment extraction",
        "adjustments": [{"adjustment_type": "move_attached_card" if attached else "move_card",
            "target_player_id": state.active_player_id, "target_card_instance_id": target,
            "to_zone": destination}]})


def _step(repo, state, action):
    digest = match_state_hash(state)
    result = repo.apply(state.match_id, action)
    assert match_state_hash(state) == digest
    assert MatchRepository(repo.path).get_state(state.match_id) == result.state
    _private(result)
    _replay(MatchRepository(repo.path), result.state)
    return result


def _extract(repo, initial, member, slot, destination):
    owner = initial.active_player_id
    target_slot = next(s for s in SLOTS if s != slot)
    cross_zone = destination != "same_stage"
    to_zone = destination if cross_zone else "member_" + target_slot
    result = _step(repo, initial, _command(initial, member, to_zone))
    expected = {p: v.model_copy(deep=True) for p, v in initial.players.items()}
    expected[owner].member_area_attachments[slot].remove(member)
    if cross_zone:
        getattr(expected[owner], destination).append(member)
        for player in expected.values():
            player.manual_modifiers = [m for m in player.manual_modifiers if m.target_card_instance_id != member]
    else:
        expected[owner].member_area[target_slot] = member
    assert result.state.players == expected
    assert result.state.cards == initial.cards
    assert result.state.phase == initial.phase and result.state.turn_number == initial.turn_number
    assert result.state.revision == initial.revision + 1
    cleared = [e for e in result.events if e.event_type == "stage_card_modifiers_cleared"]
    assert len(cleared) == int(cross_zone)
    if cross_zone:
        removed = sum(m.target_card_instance_id == member for p in initial.players.values() for m in p.manual_modifiers)
        assert cleared[0].data == {"reason": "attached_member_move_off_stage", "removed_count": removed}
    assert not any(e.event_type == "stage_attachments_cleaned" for e in result.events)
    if cross_zone:
        returned = _step(repo, result.state, _command(result.state, member, "member_" + target_slot, False))
        assert returned.state.players[owner].member_area[target_slot] == member
        assert returned.state.players[owner].member_area_attachments[target_slot] == []
        assert all(m.target_card_instance_id != member for p in returned.state.players.values() for m in p.manual_modifiers)
        assert all(returned.state.players[p].manual_modifiers == result.state.players[p].manual_modifiers for p in initial.players)
        return returned
    return result


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("slot", SLOTS)
@pytest.mark.parametrize("destination", ["hand", "waiting_room", "same_stage"])
@pytest.mark.parametrize("stage_policy", [False, True])
def test_independent_member_extraction_clears_only_cross_zone_targets_sql(tmp_path, owner, slot, destination, stage_policy):
    repo, state, member, _ = _fixture(tmp_path, owner, slot, stage_policy=stage_policy)
    _extract(repo, state, member, slot, destination)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("destination", ["hand", "waiting_room"])
@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_four_ai_continue_after_extraction_without_old_bonus_or_hidden_influence(tmp_path, owner, destination, policy):
    repo, state, member, _ = _fixture(tmp_path, owner, "center", extra=False)
    result = _extract(repo, state, member, "center", destination)
    assert _effective_member_blade(result.state, owner, member) == 1
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    continued = _step(repo, result.state, _choose(controller, result.state))
    assert all(m.target_card_instance_id != member for p in continued.state.players.values() for m in p.manual_modifiers)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("fault", ["stale", "destination", "occupied", "foreign", "batch"])
def test_invalid_extraction_rolls_back_sql_modifiers_and_groups(tmp_path, owner, fault):
    repo, state, member, _ = _fixture(tmp_path, owner)
    action = _command(state, member, "hand")
    adjustment = action.payload["adjustments"][0]
    if fault == "stale":
        action.expected_revision -= 1
    elif fault == "destination":
        adjustment["to_zone"] = "energy_deck"
    elif fault == "occupied":
        adjustment["to_zone"] = "member_left"
    elif fault == "foreign":
        adjustment["target_player_id"] = "player_2" if owner == "player_1" else "player_1"
    else:
        action.payload["adjustments"].append({**adjustment, "to_zone": "invalid"})
    before = repo.replay(state.match_id)
    with pytest.raises(StaleRevisionError if fault == "stale" else IllegalActionError):
        repo.apply(state.match_id, action)
    assert MatchRepository(repo.path).replay(state.match_id) == before


@pytest.mark.parametrize("value", [True, 1, {}, "unknown"])
def test_unknown_attached_departure_policy_rejected(value):
    with pytest.raises(ValueError):
        MatchState(match_id="invalid", seed=1, players={}, cards={}, **{FIELD: value})


@pytest.mark.parametrize("owner,state_hash,event_hash", [
    ("player_1", "058ac4c69ad5f2bac0052153455698ae555cddbad09290e16079349e6da6e193", "7094a32084ef2393cbf8cc053e5c7fdfcb60bb901dd7e905383382b5d0c94c61"),
    ("player_2", "430969820b30a74ccb32c0be25e72ebde7cac467070c7218926f67cabe6f9c49", "2040b667a909d3d55cb183c5ae543ecb6f34071ecda8e647435c45566105b253"),
])
def test_legacy_extraction_json_state_and_event_hashes_remain_unchanged(tmp_path, owner, state_hash, event_hash):
    repo, state, member, _ = _fixture(tmp_path, owner, modern=False, extra=False)
    assert FIELD not in state.model_dump()
    assert MatchState.model_validate_json(state.model_dump_json()) == state
    events = []
    for destination, attached in (("hand", True), ("member_center", False)):
        result = _step(repo, state, _command(state, member, destination, attached))
        state = result.state
        events.extend(e.model_dump() for e in result.events)
    assert _effective_member_blade(state, owner, member) == 3
    assert FIELD not in state.model_dump()
    assert match_state_hash(state) == state_hash
    assert hashlib.sha256(json.dumps(events, ensure_ascii=False, sort_keys=True).encode()).hexdigest() == event_hash
