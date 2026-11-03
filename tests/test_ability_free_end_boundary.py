import hashlib
import json
from pathlib import Path

import pytest

from loveca.simulation.ai import SimpleAIController, SimpleAIPolicy
from loveca.simulation.engine import IllegalActionError
from loveca.simulation.models import ActionRequest, EffectInvocation, EffectUsage, ManualModifier, MatchState
from loveca.simulation.ready_history import MemberReadyHistoryV1, MemberReadyQualifiedCoverageV1
from loveca.simulation.rulesets import current_ruleset_identity
from loveca.simulation.online import match_state_hash
from loveca.simulation.runtime import MatchRepository
from test_mulligan_boundary import _replay
from test_performance_yell_boundary import _privacy
from test_terminal_victory_timing import _state as _terminal_state, _durations
from test_yell_icons_boundary import _choose
from tools.ai_sandbox.live_judgment_audit import _live_instance, _effect_definition, judgment_action


FIELD = "end_phase_policy"
POLICY = "ability_free_expiry_v1"
LEGACY = {
    ("player_1", False): ("1331dd5eb81e8a0d6badd5813af9de3e013c073f0bb90907ed44b80c202242c3", "bbbaf00b6e443d1443c4d6f925cc23553013101ebc8a9f1497436e655107241a"),
    ("player_1", True): ("992b9d13296b95f2de8d371a75409b7f3c21d3baba8289bdc42869e0fb2711e3", "3dc3943294ed6066b585e487bd263ea5d8a81d98af1412d9ae164589f6318c63"),
    ("player_2", False): ("8fdb4edc58926ae19b958adf2147ac80e97de2e3fcad51db5a3b74b0ccd71966", "23f327a6553dfe84ba8bd13a6deb0013562503a382559b7d3113cf0e43a45ff5"),
    ("player_2", True): ("14245c2d8d7c13fa3651b7221ee78f231f4f7943bebdfae92c8e40c8b8ffd92e", "f30d42c35d73a3fd54f3cf7aca68c355ffa2f160309c251bf600cbf3440a5cf9"),
}


def _state(owner, terminal=False, choice=False, modern=True, modifier_type="blade"):
    state = _terminal_state(owner, terminal=terminal, choice=choice)
    for player_id, player in state.players.items():
        player.manual_modifiers = [ManualModifier(
            modifier_id=player_id + duration, modifier_type=modifier_type, duration=duration,
            created_turn=state.turn_number, amount=1,
            color_slot="red" if modifier_type in {"heart", "required_heart"} else None,
        ) for duration in ("live", "turn", "game")]
        for index in range(3):
            item = f"{player_id}-deck-{index}"
            state.cards[item] = _live_instance(item, player_id, 0)
            state.cards[item].face_up = False
            player.main_deck.append(item)
    raw = state.model_dump()
    if modern:
        raw[FIELD] = POLICY
        profile, fingerprint = current_ruleset_identity()
        raw.update(ruleset_id=profile.ruleset_id, ruleset_fingerprint=fingerprint,
                   ruling_pack_version=profile.ruling_pack_version)
    return MatchState.model_validate(raw)


def _repo(tmp_path, state):
    repo = MatchRepository(tmp_path / "end.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    return repo


def _walk(repo, initial, owner, terminal, choice, controller=None):
    state = initial
    all_events = []
    for step in range(2 if choice else 1):
        before = match_state_hash(state)
        if controller:
            action = _choose(controller, state)
        elif step == 0:
            action = judgment_action(state)
        else:
            action = ActionRequest(action_type="resolve_live_requirements", player_id=owner,
                expected_revision=state.revision, payload={"success_live_instance_id": "extra-live"})
        result = repo.apply(state.match_id, action)
        assert match_state_hash(state) == before
        state = result.state
        events = result.events[1:] if controller else result.events
        if controller:
            assert result.events[0].event_type == "ai_action_selected"
        all_events.extend(events)
        if choice and step == 0:
            assert state.pending_choice.choice_type == "success_live"
            assert _durations(state) == _durations(initial)
            assert state.phase == "live_judgment"
            assert not any(e.event_type == "manual_modifiers_expired" for e in events)
        else:
            assert state.pending_choice is None
            assert state.phase == ("complete" if terminal else "turn_complete")
            assert all(value == (["live", "turn", "game"] if terminal else ["game"])
                       for value in _durations(state).values())
            assert not state.pending_effects and state.turn_number == initial.turn_number
            for player_id, player in state.players.items():
                old = initial.players[player_id]
                assert player.main_deck == old.main_deck and player.hand == old.hand
                assert player.energy_deck == old.energy_deck and player.energy_area == old.energy_area
                assert player.member_area == old.member_area
                assert not player.live_area and not player.resolution_area
                moved = state.success_live_moved_instance_ids.get(player_id, [])
                assert player.success_live_area == old.success_live_area + moved
                assert player.waiting_room == old.waiting_room + [item for item in old.live_area if item not in moved] + old.resolution_area
            assert state.cards == initial.cards
        _privacy(result)
        repo = MatchRepository(repo.path)
        assert repo.get_state(state.match_id) == state
        _replay(repo, state)
    expired = [(e.player_id, e.data["duration"]) for e in all_events if e.event_type == "manual_modifiers_expired"]
    assert expired == ([] if terminal else [(p, d) for d in ("live", "turn") for p in initial.players])
    if not terminal:
        event_types = [e.event_type for e in all_events]
        assert max(i for i, name in enumerate(event_types) if name == "manual_modifiers_expired") < event_types.index("turn_completed")
        result = repo.apply(state.match_id, ActionRequest(action_type="start_next_turn", expected_revision=state.revision))
        assert not any(e.event_type == "manual_modifiers_expired" for e in result.events)
        assert all(value == ["game"] for value in _durations(result.state).values())
        assert result.state.turn_number == initial.turn_number + 1
        _privacy(result)
        _replay(repo, result.state)
    return state


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("terminal", [False, True])
@pytest.mark.parametrize("choice", [False, True])
@pytest.mark.parametrize("modifier_type", ["score", "blade", "heart", "required_heart"])
def test_opt_in_no_ability_end_expires_before_turn_complete_not_before_choice(tmp_path, owner, terminal, choice, modifier_type):
    state = _state(owner, terminal, choice, modifier_type=modifier_type)
    _walk(_repo(tmp_path, state), state, owner, terminal, choice)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("fault", ["definition", "card_effect", "raw_text", "bucket", "attachment", "flag", "empty_deck", "victory_policy", "pending", "usage", "ready", "qualified"])
def test_opt_in_rejects_unsupported_state_before_sql_changes(tmp_path, owner, fault):
    state = _state(owner)
    player = state.players[owner]
    card = state.cards[player.hand[0]].card
    if fault == "definition":
        effect = _effect_definition("score_plus_two")
        state.effect_definitions[effect.effect_id] = effect
    elif fault == "card_effect":
        card.effect_ids = ["AUDIT-UNREGISTERED"]
    elif fault == "raw_text":
        card.raw_effect_text_ja = "AUDIT-UNREGISTERED"
    elif fault == "bucket":
        card.ability_bucket = "static_only"
    elif fault == "attachment":
        player.member_area_attachments["left"] = [player.hand.pop()]
    elif fault == "flag":
        player.manual_modifiers[0].modifier_type = "flag"
        player.manual_modifiers[0].flag = "AUDIT-UNSUPPORTED"
    elif fault == "empty_deck":
        player.waiting_room.extend(player.main_deck)
        player.main_deck = []
    elif fault == "pending":
        effect = _effect_definition("score_plus_two")
        state.effect_definitions[effect.effect_id] = effect
        state.pending_effects = [EffectInvocation(invocation_id="audit", effect_id=effect.effect_id, source_card_instance_id=player.hand[0],
                                                  player_id=owner, trigger_event="audit")]
    elif fault == "usage":
        state.effect_usage = [EffectUsage(effect_id="audit", source_card_instance_id=player.hand[0], turn_number=1)]
    elif fault == "ready":
        state.member_ready_history = MemberReadyHistoryV1(turn_number=1)
    elif fault == "qualified":
        state.member_ready_qualified_coverage = MemberReadyQualifiedCoverageV1(turn_number=1)
    else:
        state.victory_check_policy = None
    state = MatchState.model_validate(state.model_dump())
    repo = _repo(tmp_path, state)
    before = repo.replay(state.match_id)
    with pytest.raises(IllegalActionError, match="ability-free end"):
        repo.apply(state.match_id, ActionRequest(action_type="advance_phase", expected_revision=state.revision))
    assert MatchRepository(repo.path).replay(state.match_id) == before


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_four_ai_no_ability_end_pending_selection_privacy_and_sql(tmp_path, owner, policy):
    state = _state(owner, choice=True)
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    _walk(_repo(tmp_path, state), state, owner, False, True, controller)


@pytest.mark.parametrize("value", [True, 1, {}, "unknown"])
def test_end_policy_rejects_unknown_values(value):
    raw = _state("player_1", modern=False).model_dump()
    raw[FIELD] = value
    with pytest.raises(ValueError):
        MatchState.model_validate(raw)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("terminal", [False, True])
def test_default_end_policy_is_omitted_and_keeps_legacy_timing(tmp_path, owner, terminal):
    state = _state(owner, terminal=terminal, modern=False)
    assert FIELD not in state.model_dump()
    repo = _repo(tmp_path, state)
    result = repo.apply(state.match_id, judgment_action(state))
    event_hash = hashlib.sha256(json.dumps([e.model_dump() for e in result.events], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    assert (match_state_hash(result.state), event_hash) == LEGACY[(owner, terminal)]
    assert all(value == (["live", "turn", "game"] if terminal else ["turn", "game"])
               for value in _durations(result.state).values())
    replay = repo.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    # These prechange goldens intentionally lack the optional ruleset identity.
    assert replay["metadata"]["ruleset_identity_verified"] is False
    assert replay["final_state"] == result.state.model_dump()


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
def test_manual_change_cannot_escape_restricted_end_scope(tmp_path, owner):
    state = _state(owner)
    repo = _repo(tmp_path, state)
    before = repo.replay(state.match_id)
    action = ActionRequest(action_type="manual_adjustment", player_id=owner, expected_revision=state.revision,
        payload={"reason": "AUDIT unsupported flag", "adjustments": [{"adjustment_type": "set_flag",
                 "target_player_id": owner, "flag": "AUDIT-UNSUPPORTED", "duration": "turn"}]})
    with pytest.raises(IllegalActionError, match="ability-free end"):
        repo.apply(state.match_id, action)
    assert MatchRepository(repo.path).replay(state.match_id) == before


@pytest.mark.parametrize("hosted", [False, True])
def test_new_matches_do_not_enable_restricted_end_policy(tmp_path, hosted):
    from test_webapp import SAMPLE_DECK, _client

    client = _client(tmp_path)
    deck = json.loads(SAMPLE_DECK.read_text(encoding="utf-8"))
    if hosted:
        room = client.post("/api/rooms", json={"player_name": "A", "deck": deck, "seed": 1})
        assert room.status_code == 200
        response = client.post(f"/api/rooms/{room.json()['room_code']}/join", json={"player_name": "B", "deck": deck})
        assert response.status_code == 200
        raw = response.json()["match"]["state"]
    else:
        response = client.post("/api/matches", json={"player_1": {"name": "A", "deck": deck},
                                                    "player_2": {"name": "B", "deck": deck}, "seed": 1})
        assert response.status_code == 200
        raw = response.json()["state"]
    assert FIELD not in raw
