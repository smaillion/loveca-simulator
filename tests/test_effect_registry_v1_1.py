from __future__ import annotations

from collections import Counter
from pathlib import Path

from loveca.simulation.effect_candidates import discover_effect_candidates
from loveca.simulation.effects import EffectDefinition, load_effect_registry
from loveca.simulation.engine import (
    _effective_member_play_cost,
    _static_heart_bonus,
    _static_numeric_bonus,
    apply_action,
    generate_legal_actions,
)
from loveca.simulation.models import (
    ActionRequest,
    CardDefinition,
    CardInstance,
    EffectInvocation,
    MatchState,
    PlayerState,
)

PROJECT_ROOT = Path(__file__).parents[1]
DATABASE = PROJECT_ROOT / "data" / "loveca.sqlite3"
REGISTRY = PROJECT_ROOT / "data_sources" / "effect-registry.v0.json"

V1_1_EFFECT_IDS = {
    "PL!SP-pb2-029:1",
    "PL!SP-pb2-029:2",
    "PL!-bp4-002:1",
    "PL!-bp5-003:1",
    "PL!-bp5-111:1",
    "PL!HS-bp1-003:1",
    "PL!N-pb1-008:1",
    "PL!HS-pb1-003:1",
    "PL!N-bp1-011:1",
    "PL!N-PR-026:1",
    "PL!S-bp2-008:1",
    "PL!S-bp3-001:1",
    "PL!S-sd1-009:1",
    "PL!SP-bp5-025:1",
    "PL!SP-bp5-009:1",
    "PL!N-bp5-021:1",
    "PL!SP-bp1-003:1",
    "PL!S-bp5-111:1",
    "PL!S-bp5-222:1",
    "PL!N-bp3-011:1",
    "PL!N-bp3-028:1",
    "PL!-pb1-028:1",
    "PL!-pb1-004:1",
    "PL!HS-bp6-031:1",
    "PL!HS-bp5-003:2",
    "PL!HS-bp2-007:2",
}


def test_v1_1_candidates_are_exact_text_executable() -> None:
    candidates = {
        candidate.effect_id: candidate
        for candidate in discover_effect_candidates(DATABASE, include_registered=True)
        if candidate.effect_id in V1_1_EFFECT_IDS
    }

    assert set(candidates) == V1_1_EFFECT_IDS
    assert all(
        candidate.simulation_support == "test_validated_executable"
        for candidate in candidates.values()
    )
    assert all(
        candidate.pattern_id != "manual_timing_fallback"
        for candidate in candidates.values()
    )


def test_v1_1_static_heart_score_and_hand_cost_use_live_state() -> None:
    definitions = _definitions(
        "PL!-bp5-003:1",
        "PL!-bp5-111:1",
        "PL!HS-bp1-003:1",
        "PL!N-pb1-008:1",
    )
    source = _member(
        "source",
        "Source",
        cost=4,
        work_keys=["hasunosora"],
        unit_keys=["a_rise"],
        effect_ids=list(definitions),
    )
    source.card.card_code = "PL!N-pb1-008"
    left = _member(
        "left",
        "Left",
        work_keys=["hasunosora", "nijigasaki"],
        unit_keys=["a_rise"],
        orientation="wait",
    )
    right = _member(
        "right",
        "Right",
        work_keys=["hasunosora"],
        unit_keys=["a_rise"],
    )
    state = _state(
        definitions,
        cards=[source, left, right],
        member_area={"left": "left", "center": None, "right": "right"},
        hand=["source"],
    )

    assert _effective_member_play_cost(state, "player_1", "source") == 2

    state.players["player_1"].hand = []
    state.players["player_1"].member_area["center"] = "source"
    assert _static_heart_bonus(state, "player_1", "source") == Counter(
        {"heart03": 1, "heart05": 2}
    )
    assert _static_numeric_bonus(
        state,
        "player_1",
        "source",
        "modify_score",
    ) == 1


def test_reveal_until_live_pays_discard_and_preserves_public_result() -> None:
    effect = _definition("PL!N-bp1-011:1")
    source = _member("source", "Source", effect_ids=[effect.effect_id])
    discard = _member("discard", "Discard")
    top_1 = _member("top-1", "Top 1")
    top_2 = _member("top-2", "Top 2")
    matched = _live("matched", "Matched Live")
    state = _pending_state(
        effect,
        cards=[source, discard, top_1, top_2, matched],
        hand=["discard"],
        main_deck=["top-1", "top-2", "matched"],
    )

    result = _resolve(
        state,
        selected_card_instance_ids=["discard"],
    )
    player = result.state.players["player_1"]

    assert player.hand == ["matched"]
    assert player.waiting_room == ["discard", "top-1", "top-2"]
    assert any(
        event.event_type == "effect_top_cards_revealed_until_match"
        and event.data["matched_card_instance_ids"] == ["matched"]
        for event in result.events
    )


def test_variable_discard_draws_selected_count_plus_one() -> None:
    effect = _definition("PL!HS-pb1-003:1")
    source = _member("source", "Source", effect_ids=[effect.effect_id])
    cost_1 = _member("cost-1", "Cost 1", unit_keys=["miracra_park"])
    cost_2 = _member("cost-2", "Cost 2", unit_keys=["miracra_park"])
    draws = [_member(f"draw-{index}", f"Draw {index}") for index in range(3)]
    state = _pending_state(
        effect,
        cards=[source, cost_1, cost_2, *draws],
        hand=["cost-1", "cost-2"],
        main_deck=["draw-0", "draw-1", "draw-2"],
    )

    result = _resolve(
        state,
        selected_card_instance_ids=["cost-1", "cost-2"],
    )
    player = result.state.players["player_1"]

    assert player.waiting_room == ["cost-1", "cost-2"]
    assert player.hand == ["draw-0", "draw-1", "draw-2"]


def test_waiting_live_moves_to_deck_bottom() -> None:
    effect = _definition("PL!S-bp2-008:1")
    source = _member("source", "Source", effect_ids=[effect.effect_id])
    waiting_live = _live("waiting-live", "Waiting Live")
    deck_card = _member("deck-card", "Deck Card")
    state = _pending_state(
        effect,
        cards=[source, waiting_live, deck_card],
        waiting_room=["waiting-live"],
        main_deck=["deck-card"],
    )

    result = _resolve(
        state,
        selected_card_instance_ids=["waiting-live"],
    )

    assert result.state.players["player_1"].waiting_room == []
    assert result.state.players["player_1"].main_deck == [
        "deck-card",
        "waiting-live",
    ]


def test_waiting_member_attaches_under_source() -> None:
    effect = _definition("PL!N-PR-026:1")
    source = _member("source", "Source", effect_ids=[effect.effect_id])
    target = _member(
        "target",
        "Target",
        cost=9,
        work_keys=["nijigasaki"],
    )
    state = _pending_state(
        effect,
        cards=[source, target],
        waiting_room=["target"],
    )

    result = _resolve(state, selected_card_instance_ids=["target"])

    assert result.state.players["player_1"].waiting_room == []
    assert result.state.players["player_1"].member_area_attachments["center"] == [
        "target"
    ]


def test_live_success_energy_payment_scores_per_four() -> None:
    effect = _definition("PL!SP-bp5-025:1")
    source = _live("source", "Source Live", effect_ids=[effect.effect_id])
    energy = [_energy(f"energy-{index}") for index in range(4)]
    state = _pending_state(
        effect,
        cards=[source, *energy],
        source_zone="live_area",
        energy_area=[card.instance_id for card in energy],
    )

    result = _resolve(
        state,
        selected_count=4,
        energy_instance_ids=[card.instance_id for card in energy],
    )

    assert all(
        result.state.cards[card.instance_id].orientation == "wait"
        for card in energy
    )
    assert [
        modifier.amount
        for modifier in result.state.players["player_1"].manual_modifiers
        if modifier.modifier_type == "score"
    ] == [1]


def test_repeat_mill_grants_blade_and_waits_source_when_live_is_milled() -> None:
    effect = _definition("PL!SP-bp5-009:1")
    source = _member("source", "Source", effect_ids=[effect.effect_id])
    top_1 = _member("top-1", "Top 1")
    top_live = _live("top-live", "Top Live")
    top_3 = _member("top-3", "Top 3")
    state = _pending_state(
        effect,
        cards=[source, top_1, top_live, top_3],
        main_deck=["top-1", "top-live", "top-3"],
    )

    result = _resolve(state, selected_count=3)

    assert result.state.players["player_1"].waiting_room == [
        "top-1",
        "top-live",
        "top-3",
    ]
    assert result.state.cards["source"].orientation == "wait"
    assert [
        modifier.amount
        for modifier in result.state.players["player_1"].manual_modifiers
        if modifier.modifier_type == "blade"
    ] == [3]


def test_post_mill_live_can_be_placed_fourth_from_deck_top() -> None:
    effect = _definition("PL!N-bp5-021:1")
    source = _member("source", "Source", effect_ids=[effect.effect_id])
    milled_member = _member("milled-member", "Milled Member")
    selected_live = _live("selected-live", "Selected Live")
    deck_cards = [_member(f"deck-{index}", f"Deck {index}") for index in range(5)]
    state = _pending_state(
        effect,
        cards=[source, milled_member, selected_live, *deck_cards],
        main_deck=[
            "milled-member",
            "selected-live",
            "deck-0",
            "deck-1",
            "deck-2",
            "deck-3",
            "deck-4",
        ],
    )

    first = _resolve(state)
    assert first.state.players["player_1"].waiting_room == [
        "milled-member",
        "selected-live",
    ]
    second = _resolve(
        first.state,
        selected_card_instance_ids=["selected-live"],
    )

    assert second.state.players["player_1"].main_deck == [
        "deck-0",
        "deck-1",
        "deck-2",
        "selected-live",
        "deck-3",
        "deck-4",
    ]


def test_activated_reveal_cost_is_scored_then_hidden_again() -> None:
    effect = _definition("PL!SP-bp1-003:1")
    source = _member("source", "Source", effect_ids=[effect.effect_id])
    cost_4 = _member("cost-4", "Cost 4", cost=4)
    cost_6 = _member("cost-6", "Cost 6", cost=6)
    state = _state(
        {effect.effect_id: effect},
        cards=[source, cost_4, cost_6],
        member_area={"left": None, "center": "source", "right": None},
        hand=["cost-4", "cost-6"],
    )

    result = apply_action(
        state,
        ActionRequest(
            action_type="activate_effect",
            expected_revision=state.revision,
            player_id="player_1",
            payload={
                "effect_id": effect.effect_id,
                "source_card_instance_id": "source",
                "selected_card_instance_ids": ["cost-4", "cost-6"],
            },
        ),
    )

    assert result.state.cards["cost-4"].face_up is False
    assert result.state.cards["cost-6"].face_up is False
    assert [
        modifier.amount
        for modifier in result.state.players["player_1"].manual_modifiers
        if modifier.modifier_type == "score"
    ] == [1]


def test_member_comparison_counts_heart_cost_and_original_blade_matches() -> None:
    effect = _definition("PL!N-bp3-011:1")
    source = _member(
        "source",
        "Source",
        cost=4,
        effect_ids=[effect.effect_id],
    )
    source.card.basic_hearts = {"heart04": 1}
    source.card.blade = 2
    opponent = _member("opponent", "Opponent", cost=4)
    opponent.owner_id = "player_2"
    opponent.card.basic_hearts = {"heart04": 2}
    opponent.card.blade = 2
    state = _pending_state(effect, cards=[source, opponent])
    state.players["player_2"].member_area["left"] = "opponent"

    result = _resolve(
        state,
        selected_card_instance_ids=["opponent"],
    )

    assert [
        modifier.amount
        for modifier in result.state.players["player_1"].manual_modifiers
        if modifier.modifier_type == "blade"
    ] == [3]


def test_printemps_ready_count_controls_live_score_bonus() -> None:
    effect = _definition("PL!-pb1-028:1")
    source = _live("source", "Source Live", effect_ids=[effect.effect_id])
    members = [
        _member(
            f"member-{index}",
            f"Member {index}",
            unit_keys=["printemps"],
            orientation="wait",
        )
        for index in range(3)
    ]
    state = _pending_state(
        effect,
        cards=[source, *members],
        source_zone="live_area",
    )
    state.players["player_1"].member_area = {
        "left": "member-0",
        "center": "member-1",
        "right": "member-2",
    }

    result = _resolve(state)

    assert all(
        result.state.cards[f"member-{index}"].orientation == "active"
        for index in range(3)
    )
    assert [
        modifier.amount
        for modifier in result.state.players["player_1"].manual_modifiers
        if modifier.modifier_type == "score"
    ] == [1]


def test_discarded_member_can_only_target_same_name_stage_member() -> None:
    effect = _definition("PL!HS-bp2-007:2")
    source = _member("source", "Source", effect_ids=[effect.effect_id])
    target = _member("target", "Shared Name")
    discarded = _member("discarded", "Shared Name")
    state = _pending_state(
        effect,
        cards=[source, target, discarded],
        hand=["discarded"],
    )
    state.players["player_1"].member_area["left"] = "target"

    first = _resolve(
        state,
        selected_card_instance_ids=["discarded"],
    )
    second = _resolve(
        first.state,
        selected_card_instance_ids=["target"],
    )

    modifiers = second.state.players["player_1"].manual_modifiers
    assert any(
        item.modifier_type == "heart"
        and item.color_slot == "heart04"
        and item.target_card_instance_id == "target"
        for item in modifiers
    )
    assert any(
        item.modifier_type == "blade"
        and item.amount == 1
        and item.target_card_instance_id == "target"
        for item in modifiers
    )


def test_position_change_only_allows_area_with_required_unit() -> None:
    effect = _definition("PL!S-bp5-111:1")
    source = _member("source", "Source", effect_ids=[effect.effect_id])
    aqours = _member("aqours", "Aqours", unit_keys=["aqours"])
    other = _member("other", "Other", unit_keys=["other"])
    energy = _energy("energy")
    state = _state(
        {effect.effect_id: effect},
        cards=[source, aqours, other, energy],
        member_area={"left": "aqours", "center": "source", "right": "other"},
    )
    state.players["player_1"].energy_area = ["energy"]

    activated = apply_action(
        state,
        ActionRequest(
            action_type="activate_effect",
            expected_revision=state.revision,
            player_id="player_1",
            payload={
                "effect_id": effect.effect_id,
                "source_card_instance_id": "source",
                "energy_instance_ids": ["energy"],
            },
        ),
    )
    invocation_id = activated.state.pending_effects[0].invocation_id
    resolved = apply_action(
        activated.state,
        ActionRequest(
            action_type="resolve_effect",
            expected_revision=activated.state.revision,
            player_id="player_1",
            payload={
                "invocation_id": invocation_id,
                "accepted": True,
                "selected_position_slot": "left",
            },
        ),
    )

    assert resolved.state.players["player_1"].member_area == {
        "left": "source",
        "center": "aqours",
        "right": "other",
    }
    assert resolved.state.cards["energy"].orientation == "wait"


def test_nijigasaki_inspection_reveals_retained_top_live_and_scores() -> None:
    effect = _definition("PL!N-bp3-028:1")
    source = _live("source", "Source", effect_ids=[effect.effect_id])
    first = _live("first", "First")
    second = _member("second", "Second")
    stage_1 = _member("stage-1", "Stage 1", work_keys=["nijigasaki"])
    stage_2 = _member("stage-2", "Stage 2", work_keys=["nijigasaki"])
    state = _pending_state(
        effect,
        cards=[source, first, second, stage_1, stage_2],
        source_zone="live_area",
        main_deck=["first", "second"],
    )
    state.players["player_1"].member_area = {
        "left": "stage-1",
        "center": "stage-2",
        "right": None,
    }

    inspected = _resolve(state)
    assert inspected.state.pending_choice is not None
    resolved = apply_action(
        inspected.state,
        ActionRequest(
            action_type="resolve_effect_choice",
            expected_revision=inspected.state.revision,
            player_id="player_1",
            payload={
                "invocation_id": "invocation",
                "selected_card_instance_ids": ["first"],
                "ordered_card_instance_ids": ["first"],
            },
        ),
    )

    assert resolved.state.players["player_1"].main_deck[0] == "first"
    assert resolved.state.players["player_1"].waiting_room == ["second"]
    assert [
        modifier.amount
        for modifier in resolved.state.players["player_1"].manual_modifiers
        if modifier.modifier_type == "score"
    ] == [1]
    assert any(
        event.event_type == "effect_top_card_revealed_in_place"
        for event in resolved.events
    )


def test_bulk_waiting_members_unlock_hime_blade_choice() -> None:
    effect = _definition("PL!HS-bp6-031:1")
    source = _live("source", "Source", effect_ids=[effect.effect_id])
    hime = _member("hime", "安養寺姫芽")
    waiting = [
        _member(
            f"waiting-{index}",
            f"Waiting {index}",
            unit_keys=["miracra_park"],
        )
        for index in range(15)
    ]
    state = _pending_state(
        effect,
        cards=[source, hime, *waiting],
        source_zone="live_area",
        waiting_room=[card.instance_id for card in waiting],
    )
    state.players["player_1"].member_area["center"] = "hime"

    moved = _resolve(state)
    assert moved.state.players["player_1"].waiting_room == []
    assert len(moved.state.players["player_1"].main_deck) == 15
    resolved = _resolve(
        moved.state,
        selected_card_instance_ids=["hime"],
    )

    assert any(
        item.modifier_type == "blade"
        and item.amount == 3
        and item.target_card_instance_id == "hime"
        for item in resolved.state.players["player_1"].manual_modifiers
    )


def test_post_cost_required_choice_with_no_candidates_resolves_as_much_as_possible() -> None:
    effect = _definition("PL!-bp5-009:1")
    source = _member("source", "Source", effect_ids=[effect.effect_id])
    cost_1 = _member("cost-1", "Cost 1")
    cost_2 = _member("cost-2", "Cost 2")
    state = _state(
        {effect.effect_id: effect},
        cards=[source, cost_1, cost_2],
        member_area={"left": None, "center": "source", "right": None},
        hand=["cost-1", "cost-2"],
    )

    activated = apply_action(
        state,
        ActionRequest(
            action_type="activate_effect",
            expected_revision=state.revision,
            player_id="player_1",
            payload={
                "effect_id": effect.effect_id,
                "source_card_instance_id": "source",
                "selected_card_instance_ids": ["cost-1", "cost-2"],
            },
        ),
    )
    legal = generate_legal_actions(activated.state)
    resolve = next(action for action in legal if action.action_type == "resolve_effect")
    [invocation] = resolve.options["invocations"]

    assert invocation["card_selection_minimum"] == 0
    assert invocation["candidate_card_instance_ids"] == []

    resolved = apply_action(
        activated.state,
        ActionRequest(
            action_type="resolve_effect",
            expected_revision=activated.state.revision,
            player_id="player_1",
            payload={
                "invocation_id": invocation["invocation_id"],
                "accepted": True,
                "selected_card_instance_ids": [],
            },
        ),
    )

    assert resolved.state.pending_effects == []
    assert resolved.state.players["player_1"].waiting_room == ["cost-1", "cost-2"]


def test_energy_attachment_cost_is_not_reused_as_ready_energy_target() -> None:
    effect = _definition("PL!N-bp5-008:1")
    source = _member("source", "Source", effect_ids=[effect.effect_id])
    cost_energy = _energy("cost-energy")
    wait_energy_1 = _energy("wait-energy-1")
    wait_energy_2 = _energy("wait-energy-2")
    wait_energy_1.orientation = "wait"
    wait_energy_2.orientation = "wait"
    state = _state(
        {effect.effect_id: effect},
        cards=[source, cost_energy, wait_energy_1, wait_energy_2],
        member_area={"left": None, "center": "source", "right": None},
    )
    state.players["player_1"].energy_area = [
        "cost-energy",
        "wait-energy-1",
        "wait-energy-2",
    ]

    activated = apply_action(
        state,
        ActionRequest(
            action_type="activate_effect",
            expected_revision=state.revision,
            player_id="player_1",
            payload={
                "effect_id": effect.effect_id,
                "source_card_instance_id": "source",
            },
        ),
    )
    resolved = apply_action(
        activated.state,
        ActionRequest(
            action_type="resolve_effect",
            expected_revision=activated.state.revision,
            player_id="player_1",
            payload={
                "invocation_id": activated.state.pending_effects[0].invocation_id,
                "accepted": True,
                "selected_card_instance_ids": ["cost-energy"],
            },
        ),
    )

    player = resolved.state.players["player_1"]
    assert player.energy_area == ["wait-energy-1", "wait-energy-2"]
    assert player.member_area_attachments["center"] == ["cost-energy"]
    assert resolved.state.cards["wait-energy-1"].orientation == "active"
    assert resolved.state.cards["wait-energy-2"].orientation == "active"
    assert resolved.state.pending_effects == []


def _definitions(*effect_ids: str) -> dict[str, EffectDefinition]:
    registry = load_effect_registry(REGISTRY)
    requested = set(effect_ids)
    return {
        effect.effect_id: effect
        for effect in registry.effects
        if effect.effect_id in requested
    }


def _definition(effect_id: str) -> EffectDefinition:
    return _definitions(effect_id)[effect_id]


def _state(
    definitions: dict[str, EffectDefinition],
    *,
    cards: list[CardInstance],
    member_area: dict[str, str | None] | None = None,
    hand: list[str] | None = None,
) -> MatchState:
    return MatchState(
        match_id="v1-1-effect-test",
        seed=11,
        phase="first_main",
        first_player_id="player_1",
        second_player_id="player_2",
        active_player_id="player_1",
        players={
            "player_1": PlayerState(
                player_id="player_1",
                name="Player 1",
                member_area=member_area
                or {"left": None, "center": None, "right": None},
                hand=list(hand or []),
            ),
            "player_2": PlayerState(player_id="player_2", name="Player 2"),
        },
        cards={card.instance_id: card for card in cards},
        effect_definitions=definitions,
    )


def _pending_state(
    effect: EffectDefinition,
    *,
    cards: list[CardInstance],
    hand: list[str] | None = None,
    main_deck: list[str] | None = None,
    waiting_room: list[str] | None = None,
    energy_area: list[str] | None = None,
    source_zone: str = "stage",
) -> MatchState:
    source_id = "source"
    member_area = {"left": None, "center": None, "right": None}
    live_area: list[str] = []
    if source_zone == "stage":
        member_area["center"] = source_id
    elif source_zone == "live_area":
        live_area = [source_id]
    state = MatchState(
        match_id=f"v1-1-{effect.effect_id}",
        seed=17,
        phase="first_main",
        first_player_id="player_1",
        second_player_id="player_2",
        active_player_id="player_1",
        players={
            "player_1": PlayerState(
                player_id="player_1",
                name="Player 1",
                member_area=member_area,
                hand=list(hand or []),
                main_deck=list(main_deck or []),
                waiting_room=list(waiting_room or []),
                energy_area=list(energy_area or []),
                live_area=live_area,
            ),
            "player_2": PlayerState(player_id="player_2", name="Player 2"),
        },
        cards={card.instance_id: card for card in cards},
        effect_definitions={effect.effect_id: effect},
        pending_effects=[
            EffectInvocation(
                invocation_id="invocation",
                effect_id=effect.effect_id,
                source_card_instance_id=source_id,
                player_id="player_1",
                trigger_event=effect.trigger,
            )
        ],
    )
    return state


def _resolve(state: MatchState, **payload: object):
    return apply_action(
        state,
        ActionRequest(
            action_type="resolve_effect",
            expected_revision=state.revision,
            player_id="player_1",
            payload={
                "invocation_id": "invocation",
                "accepted": True,
                **payload,
            },
        ),
    )


def _member(
    instance_id: str,
    name: str,
    *,
    cost: int = 1,
    work_keys: list[str] | None = None,
    unit_keys: list[str] | None = None,
    effect_ids: list[str] | None = None,
    orientation: str = "active",
) -> CardInstance:
    return CardInstance(
        instance_id=instance_id,
        owner_id="player_1",
        orientation=orientation,
        card=CardDefinition(
            card_code=instance_id,
            card_id=instance_id,
            name_ja=name,
            card_type="member",
            cost=cost,
            work_keys=list(work_keys or []),
            unit_keys=list(unit_keys or []),
            effect_ids=list(effect_ids or []),
        ),
    )


def _live(
    instance_id: str,
    name: str,
    *,
    effect_ids: list[str] | None = None,
) -> CardInstance:
    return CardInstance(
        instance_id=instance_id,
        owner_id="player_1",
        card=CardDefinition(
            card_code=instance_id,
            card_id=instance_id,
            name_ja=name,
            card_type="live",
            score=1,
            effect_ids=list(effect_ids or []),
        ),
    )


def _energy(instance_id: str) -> CardInstance:
    return CardInstance(
        instance_id=instance_id,
        owner_id="player_1",
        orientation="active",
        card=CardDefinition(
            card_code=instance_id,
            card_id=instance_id,
            name_ja="Energy",
            card_type="energy",
        ),
    )
