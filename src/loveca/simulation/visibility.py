"""Private inspection boundaries shared by player and test-controller views."""

from typing import Any

from loveca.simulation.models import LegalAction, MatchState


def public_inspection_card_ids(state: MatchState) -> set[str]:
    choice = state.pending_choice
    if choice is None or choice.choice_type != "effect_inspection_selection":
        return set()
    effect = state.effect_definitions.get(choice.options.get("effect_id"))
    if (effect is None or effect.choice is None
            or effect.choice.selection_policy != "public_four_lily_white_live"
            or choice.options.get("public_reveal_policy") != "public_four_lily_white_live"
            or len(choice.options.get("inspected_card_instance_ids", [])) != 4):
        return set()
    return {
        item for item in choice.options.get("inspected_card_instance_ids", [])
        if isinstance(item, str) and item in state.players[choice.player_id].main_deck
    }


def private_inspection_card_ids(state: MatchState, viewer_id: str | None) -> set[str]:
    choice = state.pending_choice
    if (
        choice is None
        or choice.player_id == viewer_id
        or choice.choice_type
        not in {
            "effect_inspection_selection",
            "manual_card_selection",
        }
    ):
        return set()
    return {
        item
        for item in choice.options.get("inspected_card_instance_ids", [])
        if isinstance(item, str)
    }


def redact_player_state(
    state: MatchState,
    payload: dict[str, Any],
    viewer_id: str,
    legal_actions: list[LegalAction],
) -> set[str]:
    """Project a player response; never serialize hidden pile identities or order."""
    visible_ids = player_visible_card_ids(state, viewer_id)
    for player_id, player in state.players.items():
        own = player_id == viewer_id
        projected = payload["players"][player_id]
        for zone in ("main_deck", "energy_deck"):
            projected[zone] = _hidden_slots(player_id, zone, len(projected[zone]))
        if not own:
            projected["hand"] = _hidden_slots(player_id, "hand", len(player.hand))
            projected.pop("member_card_instance_ids_entered_stage_this_turn", None)
        for zone in ("live_area", "resolution_area"):
            projected[zone] = [
                item if item in visible_ids else f"__hidden__/{player_id}/{zone}/{index}"
                for index, item in enumerate(projected[zone])
            ]
    payload["cards"] = {key: value for key, value in payload["cards"].items() if key in visible_ids}
    effect_ids = {
        effect_id
        for key in visible_ids
        if key in state.cards
        for effect_id in state.cards[key].card.effect_ids
    }
    effect_ids.update(invocation.effect_id for invocation in state.pending_effects)
    payload["effect_definitions"] = {
        key: value for key, value in payload["effect_definitions"].items() if key in effect_ids
    }
    # The actual shuffle seed belongs in the private runtime / post-game Replay.
    payload["seed"] = 0
    if state.pending_choice is not None and state.pending_choice.player_id != viewer_id:
        payload["pending_choice"]["options"] = {}
        choice = state.pending_choice
        effect = state.effect_definitions.get(choice.options.get("effect_id"))
        if (effect is not None and effect.choice is not None
                and effect.choice.choice_type == "multi_player_center_position_change"
                and effect.choice.selection_policy == "public_both_center_position_sequential"
                and choice.options.get("selection_policy") == effect.choice.selection_policy):
            selections = choice.options.get("selections", {})
            payload["pending_choice"]["options"] = {
                "selections": {
                    player_id: {key: value for key, value in selection.items()
                                if (key == "to_slot" and value in ("left", "right"))
                                or (key == "skipped" and value is True)}
                    for player_id, selection in selections.items()
                    if player_id in state.players and isinstance(selection, dict)
                } if isinstance(selections, dict) else {},
            }
    hidden_ids = set(state.cards) - visible_ids
    for field in ("pending_choice", "pending_effects", "effect_usage"):
        payload[field] = redact_hidden_references(payload[field], hidden_ids)
    for projected in payload["players"].values():
        for field in ("manual_modifiers", "effect_ready_flags_this_turn", "live_result"):
            projected[field] = redact_hidden_references(projected[field], hidden_ids)
    return hidden_ids


def _hidden_slots(player_id: str, zone: str, count: int) -> list[str]:
    return [f"__hidden__/{player_id}/{zone}/{index}" for index in range(count)]


def player_visible_card_ids(state: MatchState, viewer_id: str) -> set[str]:
    """Visibility follows zones and actual inspection policy, never action metadata."""
    private_inspected = private_inspection_card_ids(state, viewer_id)
    visible_ids = public_inspection_card_ids(state)
    for player_id, player in state.players.items():
        own = player_id == viewer_id
        visible_ids.update(item for item in player.member_area.values() if item)
        for attached in player.member_area_attachments.values():
            visible_ids.update(attached)
        for zone in (player.energy_area, player.waiting_room, player.success_live_area):
            visible_ids.update(zone)
        visible_ids.update(item for item in player.live_area if own or state.cards[item].face_up)
        visible_ids.update(item for item in player.resolution_area if item not in private_inspected)
        if own:
            visible_ids.update(player.hand)
    return visible_ids


def owner_manual_source_handles(state: MatchState, viewer_id: str) -> dict[str, tuple[str, str]]:
    """Keep required own-manual submission handles, without granting card visibility."""
    return {
        item.invocation_id: (item.effect_id, item.source_card_instance_id)
        for item in state.pending_effects
        if item.player_id == viewer_id
        and item.source_card_instance_id in state.cards
        and state.cards[item.source_card_instance_id].owner_id == viewer_id
        and item.effect_id in state.effect_definitions
        and state.effect_definitions[item.effect_id].simulation_support == "manual_resolution"
    }


def redact_hidden_references(
    value: Any, hidden_ids: set[str], *, source_handles: dict[str, tuple[str, str]] | None = None,
) -> Any:
    if isinstance(value, str):
        return "__hidden__" if value in hidden_ids else value
    if isinstance(value, list):
        return [redact_hidden_references(item, hidden_ids, source_handles=source_handles) for item in value]
    if isinstance(value, dict):
        result = {
            f"__hidden__/metadata/{index}" if key in hidden_ids else key: item
            if key == "revealed_cards"
            else redact_hidden_references(item, hidden_ids, source_handles=source_handles)
            for index, (key, item) in enumerate(value.items())
        }
        invocation_id = value.get("invocation_id")
        handle = (source_handles or {}).get(invocation_id) if isinstance(invocation_id, str) else None
        if handle is not None and (value.get("effect_id"), value.get("source_card_instance_id")) == handle:
            result["source_card_instance_id"] = handle[1]
        return result
    return value
