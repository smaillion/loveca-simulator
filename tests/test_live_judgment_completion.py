import hashlib
import json
from pathlib import Path

import pytest

from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation import engine
from loveca.simulation.engine import generate_legal_actions
from loveca.simulation.models import ActionRequest
from loveca.simulation.online import match_state_hash
from loveca.simulation.rulesets import current_ruleset_identity
from loveca.simulation.runtime import MatchRepository
from loveca.webapp import _match_state_payload
from test_terminal_victory_timing import _state as terminal_state
from tools.ai_sandbox.live_judgment_audit import _live_instance, judgment_action


# Captured from d6a8f7c before extracting completion helpers; compatibility, not rule approval.
GOLDEN = {
    "player_1-0-0-0": [
        "8615959a41bcd2ecbefbefea2f5d523907f9fb78ffc0109a7e34fcc11134353e",
        "bbbaf00b6e443d1443c4d6f925cc23553013101ebc8a9f1497436e655107241a"
    ],
    "player_1-0-0-1": [
        "ea693058e0615fd6781a4e9d73a969f80f5db8e5a0692ed07a271d26dedfafff",
        "b024ace743972e50eb90db4405340d6b0f7c314720da1dc4c22beb6cacd055db"
    ],
    "player_1-0-1-0": [
        "ba905b09514bc53c152b16d950aa2e348680cd1975035bfb5eb31ace0283b618",
        "5951e23275cf89cb228543e1b8f9a7bf84ba4fd302d8dd755707397047718f80"
    ],
    "player_1-0-1-1": [
        "cc76cc42db3d92e3956cc8567cdf1ed2a3d7efb720837486c417e871d11d0c4c",
        "ab23bc665df109e4944e6ebe2f8a0dd1beaff52cc19807f157ab4e673c035c11"
    ],
    "player_1-1-0-0": [
        "94351bdbc6c26a3bafc6f8939597e91f5aca6f2c368a25d59fd3a618f35183ef",
        "bbbaf00b6e443d1443c4d6f925cc23553013101ebc8a9f1497436e655107241a"
    ],
    "player_1-1-0-1": [
        "952a0d0b2c94315f7f44f31293afcae44f269bc9d85356a78aa42f6981f7a02e",
        "b024ace743972e50eb90db4405340d6b0f7c314720da1dc4c22beb6cacd055db"
    ],
    "player_1-1-1-0": [
        "d3bc0f9660d2f1c518189b329d26808afab63368ba97a41a67918b4e2561f1ac",
        "3dc3943294ed6066b585e487bd263ea5d8a81d98af1412d9ae164589f6318c63"
    ],
    "player_1-1-1-1": [
        "cb3776965b9d3bca421e8a96c1bb5ac9473626502e38aeee44b2dd0046587a86",
        "4602c31e1eaedd4dc21d36c90f79db426fc63c87fe7e10838c0cd9fa1f70d49e"
    ],
    "player_2-0-0-0": [
        "7b00743da62d65f84f753b699166ae6194f8d8ee7d5f8eeaa45681d43cb64920",
        "23f327a6553dfe84ba8bd13a6deb0013562503a382559b7d3113cf0e43a45ff5"
    ],
    "player_2-0-0-1": [
        "9cec95ea6085f4d3453163076e4de672a2731c993e13dbe9a5034ee57f3cb970",
        "03157be08a4c7ce45c82cdb22926cbb52add5d61b686c91309b8f2026dce85f0"
    ],
    "player_2-0-1-0": [
        "43d3f74eaf8ba9b62e953f4a0d0ad89c0080a02e3f3eb743737a323e780de52b",
        "4db08a54da4edd677938130807cfaa092450220f21d0ca412afe8f39a7974e19"
    ],
    "player_2-0-1-1": [
        "20e3c9f0733f6fa14833b59408f067499f7901f8d15c4790f6ad7d535e7bc2df",
        "da55bc8f0d84abc908be943e9fbe59b918e122a5a46f180a19081be675da98d0"
    ],
    "player_2-1-0-0": [
        "9f51c7ba39148af83454a99f58ce29a813d6c4e195585bd79fb7f55816633703",
        "23f327a6553dfe84ba8bd13a6deb0013562503a382559b7d3113cf0e43a45ff5"
    ],
    "player_2-1-0-1": [
        "c7f402dcca22ad4c3f073d99fbf0d278784e5f3e4e930a91f118436c2deec321",
        "03157be08a4c7ce45c82cdb22926cbb52add5d61b686c91309b8f2026dce85f0"
    ],
    "player_2-1-1-0": [
        "a647e3e7cc2949c32402bf5502af8189812f48f6022359525f05cd1ed58bb25f",
        "f30d42c35d73a3fd54f3cf7aca68c355ffa2f160309c251bf600cbf3440a5cf9"
    ],
    "player_2-1-1-1": [
        "8d6a26c0fed8a0ec799607149c5b6d440c21ff141316232e0aca0aed8d1ac2dc",
        "3df5cf3003431a13f17ee72b1ce50247fc87376b4679055d174e184043bff183"
    ]
}


def _state(owner, modern, terminal, choice):
    state = terminal_state(owner, modern=modern, terminal=terminal, choice=choice)
    profile, fingerprint = current_ruleset_identity()
    state.ruleset_id = profile.ruleset_id
    state.ruleset_fingerprint = fingerprint
    state.ruling_pack_version = profile.ruling_pack_version
    for player_id, player in state.players.items():
        item = player_id + "-hidden-deck"
        state.cards[item] = _live_instance(item, player_id, 0)
        player.main_deck.append(item)
    return state


def _signature(state, events):
    digest = hashlib.sha256(json.dumps(events, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return [match_state_hash(state), digest]


def _drive(repo, state):
    events = []
    result = repo.apply(state.match_id, judgment_action(state))
    events.extend(event.model_dump() for event in result.events)
    if result.state.pending_choice:
        pending = result.state.pending_choice
        assert pending.choice_type == "success_live"
        assert not any(event["event_type"] == "live_judgment_completed" for event in events)
        assert any(player.live_area for player in result.state.players.values())
        assert all(a.action_type != "start_next_turn" for a in result.legal_actions)
        result = repo.apply(state.match_id, ActionRequest(
            action_type="resolve_live_requirements", player_id=pending.player_id,
            expected_revision=result.state.revision,
            payload={"success_live_instance_id": pending.options["card_instance_ids"][-1]},
        ))
        events.extend(event.model_dump() for event in result.events)
    assert sum(event["event_type"] == "live_judgment_completed" for event in events) == 1
    return result, events


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("modern", [False, True])
@pytest.mark.parametrize("terminal", [False, True])
@pytest.mark.parametrize("choice", [False, True])
def test_completion_preserves_preextraction_state_events_and_sql(tmp_path, monkeypatch, owner, modern, terminal, choice):
    state = _state(owner, modern, terminal, choice)
    before = match_state_hash(state)
    repo = MatchRepository(tmp_path / "match.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    calls = []
    cleanup, finish = engine._cleanup_live_judgment_zones, engine._finish_live_judgment

    def observed_cleanup(current):
        calls.append("cleanup")
        cleanup(current)

    def observed_finish(current, events):
        assert calls == ["cleanup"]
        calls.append("finish")
        finish(current, events)

    monkeypatch.setattr(engine, "_cleanup_live_judgment_zones", observed_cleanup)
    monkeypatch.setattr(engine, "_finish_live_judgment", observed_finish)
    result, events = _drive(repo, state)
    assert calls == ["cleanup", "finish"]
    key = f"{owner}-{int(modern)}-{int(terminal)}-{int(choice)}"
    assert _signature(result.state, events) == GOLDEN[key]
    assert match_state_hash(state) == before
    calls.clear()
    replay = repo.replay(state.match_id)
    assert calls == ["cleanup", "finish"]
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["metadata"]["ruleset_identity_verified"] is True
    assert replay["final_state"] == result.state.model_dump()
    for viewer in state.players:
        other = next(player for player in state.players if player != viewer)
        hidden = result.state.players[other].hand + result.state.players[other].main_deck + result.state.players[viewer].main_deck
        payload = _match_state_payload(result.state, events=result.events, legal_actions=result.legal_actions,
                                       player_id=viewer)
        assert all(json.dumps(item) not in json.dumps(payload) for item in hidden)


@pytest.mark.parametrize("owner", ["player_1", "player_2"])
@pytest.mark.parametrize("policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"])
def test_four_ai_complete_pending_selection_without_repeating_judgment(tmp_path, owner, policy):
    state = _state(owner, True, True, True)
    repo = MatchRepository(tmp_path / "match.sqlite3")
    repo.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    controller = SimpleAIController(SimpleAIPolicy(policy_version=policy, manual_effect_policy="block"))
    events = []
    for _ in range(2):
        before = match_state_hash(state)
        decision = controller.choose_action(state, generate_legal_actions(state), controlled_player_ids=set(state.players))
        assert isinstance(decision, SimpleAIDecision)
        altered = state.model_copy(deep=True)
        for player in altered.players.values():
            for item in player.hand + player.main_deck:
                altered.cards[item].card = altered.cards[item].card.model_copy(update={"name_ja": "UNSEEN", "score": 999})
        altered_before = match_state_hash(altered)
        alternative = controller.choose_action(altered, generate_legal_actions(altered), controlled_player_ids=set(altered.players))
        assert isinstance(alternative, SimpleAIDecision)
        assert alternative.action.model_dump() == decision.action.model_dump()
        assert match_state_hash(altered) == altered_before
        assert match_state_hash(state) == before
        result = repo.apply(state.match_id, decision.action)
        events.extend(event.model_dump() for event in result.events)
        state = result.state
    assert state.phase == "complete" and state.game_result.winner_player_ids == [owner]
    assert sum(event["event_type"] == "live_judgment_completed" for event in events) == 1
    assert sum(event["event_type"] == "match_completed" for event in events) == 1
    replay = repo.replay(state.match_id)
    assert replay["metadata"]["deterministic_replay_verified"] is True
    assert replay["metadata"]["ruleset_identity_verified"] is True
    assert replay["final_state"] == state.model_dump()
