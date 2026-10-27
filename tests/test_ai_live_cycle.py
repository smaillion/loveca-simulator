from pathlib import Path
from types import SimpleNamespace

import pytest

from loveca.simulation.ai import SimpleAIController, SimpleAIDecision, SimpleAIPolicy
from loveca.simulation.engine import generate_legal_actions
from loveca.simulation.models import (
    ActionRequest,
    ActionResult,
    CardDefinition,
    CardInstance,
    GameEvent,
    MatchState,
    PlayerState,
)
from loveca.simulation.online import match_state_hash
from tools.ai_sandbox.simple_ai_acceptance import (
    SimpleAIMatchReport,
    acceptance_passed,
    continue_ai_vs_ai,
    run_acceptance_matches,
)

RULE_REFERENCE_IDS = ("8.2.2", "8.2.4", "8.3.6", "10.5.1")


def _state(members=5):
    state = MatchState(
        match_id="cycle",
        seed=7,
        phase="live_set_first",
        first_player_id="player_1",
        second_player_id="player_2",
        active_player_id="player_1",
        players={
            "player_1": PlayerState(player_id="player_1", name="AI"),
            "player_2": PlayerState(player_id="player_2", name="Other"),
        },
        cards={},
    )
    for i in range(members):
        key = f"member-{i}"
        state.cards[key] = CardInstance(
            instance_id=key,
            owner_id="player_1",
            card=CardDefinition(
                card_code=key,
                card_id=key,
                card_type="member",
                name_ja=key,
                cost=i + 1,
                blade=i + 1,
                basic_hearts={"heart01": i + 1},
            ),
        )
        state.players["player_1"].hand.append(key)
    for i in range(6):
        key = f"deck-{i}"
        state.cards[key] = CardInstance(
            instance_id=key,
            owner_id="player_1",
            face_up=False,
            card=CardDefinition(
                card_code=key,
                card_id=key,
                card_type="live",
                name_ja=key,
                score=1,
                required_hearts={"heart0": 1},
            ),
        )
        state.players["player_1"].main_deck.append(key)
    state.cards["secret"] = state.cards["member-0"].model_copy(
        update={"instance_id": "secret", "owner_id": "player_2"}, deep=True
    )
    state.players["player_2"].hand = ["secret"]
    return state


def _choose(state, policy="simple_ai_v1_2", legal=None):
    result = SimpleAIController(SimpleAIPolicy(policy_version=policy)).choose_action(
        state,
        generate_legal_actions(state) if legal is None else legal,
        controlled_player_ids={"player_1"},
    )
    assert isinstance(result, SimpleAIDecision)
    return result


@pytest.mark.parametrize("members,expected", [(1, 0), (2, 0), (3, 1), (4, 2), (5, 3), (8, 3)])
def test_only_new_policy_cycles_surplus_members_and_keeps_two(members, expected):
    state = _state(members)
    before = state.model_dump(mode="json")
    decision = _choose(state)
    selected = decision.action.payload["card_instance_ids"]
    assert len(selected) == expected
    assert set(selected) <= set(state.players["player_1"].hand)
    assert not {f"member-{members - 1}", f"member-{members - 2}"} & set(selected)
    assert _choose(state, "simple_ai_v1_1").action.payload["card_instance_ids"] == []
    assert state.model_dump(mode="json") == before


def test_cycles_only_offered_members_and_respects_legal_maximum():
    state = _state(8)
    legal = [a for a in generate_legal_actions(state) if a.action_type == "set_live_cards"]
    legal[0].options.update(
        hand_instance_ids=["member-1", "member-3", "member-6", "secret"], maximum=1
    )
    assert _choose(state, legal=legal).action.payload["card_instance_ids"] == ["member-1"]


def test_live_in_hand_keeps_existing_live_plan_instead_of_member_cycle():
    state = _state()
    live = state.players["player_1"].main_deck.pop(0)
    state.players["player_1"].hand.append(live)
    decision = _choose(state)
    assert decision.action.payload["card_instance_ids"] == [live]
    assert decision.reason == "set_best_reachable_live_combo"


def test_cycle_does_not_depend_on_opponent_private_cards_or_own_deck_order():
    state = _state()
    expected = _choose(state).action
    changed = state.model_copy(deep=True)
    changed.cards["secret"].card.name_ja = "秘密変更"
    changed.cards["secret"].card.cost = 99
    changed.players["player_1"].main_deck.reverse()
    assert _choose(changed).action == expected


def test_cycle_replacement_draw_and_nonlive_reveal_use_native_rules_and_replay(tmp_path):
    from loveca.simulation.runtime import MatchRepository
    from loveca.webapp import _match_state_payload

    state = _state()
    repository = MatchRepository(tmp_path / "cycle.sqlite3")
    repository.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    decision = _choose(state)
    selected = decision.action.payload["card_instance_ids"]
    result = repository.apply(state.match_id, decision.action)
    assert result.state.players["player_1"].live_area == selected
    assert len(result.state.players["player_1"].hand) == 5
    assert all(not result.state.cards[i].face_up for i in selected)
    visible = _match_state_payload(
        result.state, events=result.events, legal_actions=result.legal_actions, player_id="player_2"
    )
    assert not set(selected) & set(visible["state"]["cards"])
    events = list(result.events)
    for action in [
        ActionRequest(
            action_type="set_live_cards",
            player_id="player_2",
            expected_revision=1,
            payload={"card_instance_ids": []},
        ),
        ActionRequest(action_type="advance_phase", player_id="player_1", expected_revision=2),
    ]:
        result = repository.apply(state.match_id, action)
        events.extend(result.events)
    assert set(selected) <= set(result.state.players["player_1"].waiting_room)
    assert not result.state.players["player_1"].live_area
    assert not result.state.players["player_1"].success_live_area
    assert result.state.players["player_1"].live_result.total_score == 0
    assert not any(e.event_type == "yell_completed" for e in events)
    replay = repository.replay(state.match_id)
    assert replay["final_state"] == result.state.model_dump(mode="json")
    assert replay["events"] == [e.model_dump(mode="json") for e in events]
    assert match_state_hash(MatchState.model_validate(replay["final_state"])) == match_state_hash(
        result.state
    )


def test_default_and_old_policy_versions_remain_unchanged():
    from loveca.simulation.service import _new_match_controller_policy_versions

    assert SimpleAIPolicy().policy_version == "simple_ai_v1_1"
    assert _new_match_controller_policy_versions({"player_1": "simple_ai"}) == {
        "player_1": "simple_ai_v1_1"
    }
    state = _state()
    state.controller_policy_versions = {"player_1": "simple_ai_v1_2"}
    assert MatchState.model_validate_json(state.model_dump_json()) == state


def test_experimental_policy_retains_v11_efficient_match_point_live_plan():
    state = _state()
    player = state.players["player_1"]
    player.member_area["left"] = player.hand.pop()
    player.success_live_area = player.main_deck[:2]
    del player.main_deck[:2]
    player.hand.extend(player.main_deck[:2])
    del player.main_deck[:2]
    old = _choose(state, "simple_ai_v1_1").action.payload["card_instance_ids"]
    new = _choose(state).action.payload["card_instance_ids"]
    assert old == new and len(new) == 1


@pytest.mark.parametrize(
    "already,cap,expected", [(250, 300, [50]), (0, 600, [256, 256, 88]), (100, 100, [])]
)
def test_acceptance_cap_counts_all_previous_ai_actions(already, cap, expected):
    state = _state()
    events = [GameEvent(event_type="ai_action_selected") for _ in range(already)]
    calls = []

    def advance(match_id, result, *, max_ai_actions):
        calls.append(max_ai_actions)
        events.extend(GameEvent(event_type="ai_action_selected") for _ in range(max_ai_actions))
        return ActionResult(
            state=result.state.model_copy(update={"revision": result.state.revision + 1}),
            events=[],
            legal_actions=[],
        )

    service = SimpleNamespace(
        repository=SimpleNamespace(list_events=lambda _: events), advance_ai=advance
    )
    continue_ai_vs_ai(
        service, ActionResult(state=state, events=[], legal_actions=[]), max_actions=cap
    )
    assert calls == expected
    assert len(events) <= cap


@pytest.mark.parametrize("cap", [0, 3, 5])
def test_initial_service_auto_advance_is_also_inside_match_cap(tmp_path, cap):
    from tools.ai_sandbox.blackbox_playtest import build_decks

    database = Path("data/loveca.sqlite3")
    decks = build_decks(database, 2)
    reports = run_acceptance_matches(
        database,
        decks,
        mode="ai-vs-ai",
        match_count=1,
        max_actions=cap,
        policy_version="simple_ai_v1_2",
    )
    assert reports[0].ai_actions == cap
    assert reports[0].blocker == "max_actions:ai_action_cap_reached"
    assert reports[0].policy_version == "simple_ai_v1_2"
    assert reports[0].seed == 12000
    assert reports[0].replay_serialization_ok


@pytest.mark.parametrize(
    "blocker", ["engine_illegal_action", "runtime_exception", "stale_revision"]
)
def test_unsafe_failures_never_pass_acceptance_even_if_explained(blocker):
    report = SimpleAIMatchReport(
        match_index=1,
        mode="ai-vs-ai",
        first_deck="A",
        second_deck="B",
        status="blocked",
        final_phase="first_main",
        turn_number=1,
        revision=1,
        driven_human_actions=0,
        ai_actions=1,
        success_live_counts={},
        blocker=blocker,
        blocker_detail={"reason": blocker},
        replay_serialization_ok=True,
    )
    assert not acceptance_passed([report])


def test_explicit_error_skips_never_count_as_clean_acceptance():
    report = SimpleAIMatchReport(
        match_index=1,
        mode="ai-vs-ai",
        first_deck="A",
        second_deck="B",
        status="completed",
        final_phase="complete",
        turn_number=3,
        revision=60,
        driven_human_actions=0,
        ai_actions=59,
        success_live_counts={"player_1": 3, "player_2": 1},
        skipped_effects=[{"effect_id": "unsupported"}],
        replay_serialization_ok=True,
    )
    assert not acceptance_passed([report])


def test_blackbox_default_keeps_historical_action_without_ai_metadata():
    from loveca.simulation.ai import choose_simple_ai_action
    from tools.ai_sandbox.blackbox_playtest import choose_action

    state = _state()
    legal = generate_legal_actions(state)
    old = choose_simple_ai_action(state, legal, manual_policy="block")
    assert old is not None
    assert choose_action(state, legal, manual_policy="block") == old[:3]
    assert "ai_decision" not in old[2]


@pytest.mark.parametrize(
    "policy", ["simple_ai_v0", "simple_ai_v1", "simple_ai_v1_1", "simple_ai_v1_2"]
)
def test_blackbox_product_policy_is_deterministic_private_and_nonmutating(policy):
    from tools.ai_sandbox.blackbox_playtest import choose_action

    state = _state()
    before = state.model_dump(mode="json")
    legal = generate_legal_actions(state)
    first = choose_action(state, legal, manual_policy="block", policy_version=policy)
    assert first is not None
    assert first[0] in {a.action_type for a in legal}
    assert first[1] == "player_1"
    assert first[2]["ai_decision"]["policy_version"] == policy
    assert state.model_dump(mode="json") == before
    changed = state.model_copy(deep=True)
    changed.cards["secret"].card.cost = 99
    changed.players["player_1"].main_deck.reverse()
    assert choose_action(changed, legal, manual_policy="block", policy_version=policy) == first


def test_blackbox_product_policy_isolated_to_one_decision_player():
    from tools.ai_sandbox.blackbox_playtest import choose_action

    state = _state()
    own = generate_legal_actions(state)[0]
    other = own.model_copy(update={"player_id": "player_2"}, deep=True)
    other.options["hand_instance_ids"] = ["secret"]
    decision = choose_action(
        state, [other, own], manual_policy="block", policy_version="simple_ai_v1_2"
    )
    assert decision[1] == "player_1"
    assert "secret" not in str(decision[2])


@pytest.mark.parametrize("manual_policy,expected", [("block", None), ("skip", "skip_effect")])
def test_blackbox_shared_controller_does_not_silently_resolve_manual(manual_policy, expected):
    from loveca.simulation.models import LegalAction
    from tools.ai_sandbox.blackbox_playtest import choose_action

    state = _state()
    invocation = {
        "effect_id": "manual",
        "invocation_id": "manual-1",
        "is_optional": False,
        "simulation_support": "manual_resolution",
    }
    legal = [
        LegalAction(
            action_type="resolve_effect",
            player_id="player_1",
            label_ja="解決",
            label_zh="结算",
            options={"invocations": [invocation]},
        ),
        LegalAction(
            action_type="skip_effect",
            player_id="player_1",
            label_ja="スキップ",
            label_zh="跳过",
            options={},
        ),
    ]
    decision = choose_action(
        state, legal, manual_policy=manual_policy, policy_version="simple_ai_v1_2"
    )
    assert (decision[0] if decision else None) == expected
    if decision:
        assert decision[2]["invocation_id"] == "manual-1"
        assert decision[2]["error_message"]


def test_blackbox_frozen_decks_and_split_run_preserve_seed_pair_and_source(tmp_path):
    import json

    from tools.ai_sandbox.blackbox_playtest import build_decks, load_frozen_decks, run_matches

    database = Path("data/loveca.sqlite3")
    decks = build_decks(database, 3)
    source = tmp_path / "source"
    source.mkdir()
    from dataclasses import asdict

    for i, deck in enumerate(decks):
        (source / f"{i:02d}.json").write_text(json.dumps(asdict(deck)), encoding="utf-8")
    before = {p.name: p.read_bytes() for p in source.iterdir()}
    loaded = load_frozen_decks(source, 3)
    assert loaded == decks
    full = run_matches(
        database,
        loaded,
        match_count=3,
        max_actions=3,
        manual_policy="block",
        policy_version="simple_ai_v1_2",
    )
    split = run_matches(
        database,
        loaded,
        match_count=1,
        match_start=3,
        max_actions=3,
        manual_policy="block",
        policy_version="simple_ai_v1_2",
    )
    assert split == [full[2]]
    assert split[0].seed == 9002
    assert split[0].match_index == 3
    assert split[0].action_count == 3
    assert split[0].policy_version == "simple_ai_v1_2"
    assert split[0].replay_ok
    assert {p.name: p.read_bytes() for p in source.iterdir()} == before
    with pytest.raises(ValueError, match="frozen decks"):
        load_frozen_decks(source, 4)


@pytest.mark.parametrize(
    "options",
    [
        {"policy_version": "unknown"},
        {"manual_policy": "unknown"},
        {"manual_policy": "noop", "policy_version": "simple_ai_v1_2"},
        {"match_start": 0},
    ],
)
def test_blackbox_rejects_invalid_policy_before_running(options):
    from tools.ai_sandbox.blackbox_playtest import run_matches

    kwargs = {"manual_policy": "block", **options}
    with pytest.raises(ValueError):
        run_matches(Path("not-a-database"), [object()], match_count=1, max_actions=1, **kwargs)


@pytest.mark.parametrize("same_directory", [True, False])
def test_blackbox_cli_cannot_overwrite_frozen_source_directory(
    tmp_path, monkeypatch, same_directory
):
    from tools.ai_sandbox.blackbox_playtest import main

    source = tmp_path / "decks"
    source.mkdir()
    original = source / "saved.json"
    original.write_text("{}", encoding="utf-8")
    output = source if same_directory else tmp_path
    monkeypatch.setattr(
        "sys.argv", ["blackbox", "--deck-directory", str(source), "--output", str(output)]
    )
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    assert original.read_text(encoding="utf-8") == "{}"


def test_blackbox_report_records_policy_and_never_uses_imported_names_as_paths(tmp_path):
    import json
    from dataclasses import replace

    from tools.ai_sandbox.blackbox_playtest import (
        SandboxMatchSummary,
        build_decks,
        summarize_deck,
        write_outputs,
    )

    database = Path("data/loveca.sqlite3")
    source = build_decks(database, 1)[0]
    decks = [replace(source, name="../escape"), replace(source, name="../escape")]
    report = SandboxMatchSummary(
        match_index=1,
        first_deck=decks[0].name,
        second_deck=decks[1].name,
        status="blocked",
        final_phase="live_set_first",
        turn_number=1,
        action_count=3,
        seed=9000,
        policy_version="simple_ai_v1_2",
        decision_reason_counts={"cycle_spare_members_to_find_live": 2},
    )
    output = tmp_path / "report"
    write_outputs(output, decks, [summarize_deck(database, d) for d in decks], [report])
    assert sorted(p.name for p in (output / "decks").iterdir()) == [
        "Sandbox Deck 01.json",
        "Sandbox Deck 02.json",
    ]
    assert not (output / "escape.json").exists()
    data = json.loads((output / "sandbox-summary.json").read_text(encoding="utf-8"))
    assert data["summary"]["controller_policies"] == {"simple_ai_v1_2": 1}
    assert data["summary"]["resource_cycle_actions"] == 2
    assert data["match_summaries"][0]["seed"] == 9000


def test_blackbox_effect_accounting_distinguishes_rejection_from_resolution_and_silent_loss():
    from tools.ai_sandbox.blackbox_playtest import _executable_effect_outcomes

    state = _state()
    state.effect_definitions = {
        "executable": SimpleNamespace(simulation_support="test_validated_executable"),
        "manual": SimpleNamespace(simulation_support="manual_resolution"),
    }
    events = []
    for iid, ending in [
        ("resolved", "effect_resolved"),
        ("rejected", "effect_not_activatable"),
        ("skipped", "effect_skipped_due_to_error"),
        ("pending", None),
    ]:
        data = {"invocation_id": iid, "effect_id": "executable"}
        events.append(GameEvent(event_type="effect_triggered", data=data))
        if ending:
            events.extend([GameEvent(event_type=ending, data=data)] * 2)
    events.extend(
        [
            GameEvent(
                event_type="effect_not_activatable",
                data={"invocation_id": "never-triggered", "effect_id": "executable"},
            ),
            GameEvent(
                event_type="effect_triggered",
                data={"invocation_id": "manual", "effect_id": "manual"},
            ),
        ]
    )
    assert _executable_effect_outcomes(state, events) == {
        "triggered": 4,
        "resolved": 1,
        "not_activatable": 1,
        "skipped": 1,
        "unfinished": 1,
    }


def test_actual_dollchestra_recoveries_record_second_target_exhaustion_and_replay(tmp_path):
    import json

    from loveca.simulation.effects import EffectDefinition
    from loveca.simulation.models import EffectInvocation
    from loveca.simulation.runtime import MatchRepository
    from tools.ai_sandbox.blackbox_playtest import _executable_effect_outcomes, choose_action

    raw = json.loads(Path("data_sources/effect-registry.v0.json").read_text(encoding="utf-8"))
    effect = EffectDefinition.model_validate(
        next(e for e in raw["effects"] if e["effect_id"] == "PL!HS-bp6-005:2")
    )
    state = _state()
    state.effect_order_policy = "ap_nap_player_choice"
    player = state.players["player_1"]
    source_ids, target, other = player.hand[:2], player.hand[2], player.hand[3]
    player.hand = player.hand[4:]
    player.member_area.update(left=source_ids[0], center=source_ids[1])
    player.resolution_area = [target, other]
    state.cards[target].card.unit_keys = ["dollchestra"]
    state.cards[other].card.unit_keys = ["miracra_park"]
    state.effect_definitions = {effect.effect_id: effect}
    for i, source in enumerate(source_ids):
        state.cards[source].card.effect_ids = [effect.effect_id]
        state.pending_effects.append(
            EffectInvocation(
                invocation_id=f"recover-{i}",
                effect_id=effect.effect_id,
                source_card_instance_id=source,
                player_id="player_1",
                trigger_event="live_succeeded",
                trigger_data={"_condition_checked_at_trigger": True},
            )
        )
    repository = MatchRepository(tmp_path / "two-recoveries.sqlite3")
    events = [
        GameEvent(
            event_type="effect_triggered",
            data={
                "invocation_id": inv.invocation_id,
                "effect_id": inv.effect_id,
            },
        )
        for inv in state.pending_effects
    ]
    repository.create_match(state, card_database_path=Path("data/loveca.sqlite3"))
    for _ in range(4):
        if not state.pending_effects and state.pending_choice is None:
            break
        decision = choose_action(
            state,
            generate_legal_actions(state),
            manual_policy="block",
            policy_version="simple_ai_v1_2",
        )
        assert decision is not None
        result = repository.apply(
            state.match_id,
            ActionRequest(
                action_type=decision[0],
                player_id=decision[1],
                expected_revision=state.revision,
                payload=decision[2],
            ),
        )
        state = result.state
        events.extend(result.events)
    assert target in state.players["player_1"].hand
    assert other in state.players["player_1"].resolution_area
    assert not state.pending_effects and state.pending_choice is None
    assert _executable_effect_outcomes(state, events) == {
        "triggered": 2,
        "resolved": 1,
        "not_activatable": 1,
        "skipped": 0,
        "unfinished": 0,
    }
    assert repository.replay(state.match_id)["final_state"] == state.model_dump(mode="json")
