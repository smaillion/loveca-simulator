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
    private_inspected = private_inspection_card_ids(state, viewer_id)
    visible_ids: set[str] = public_inspection_card_ids(state)
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
    for action in legal_actions:
        if action.player_id in {None, viewer_id}:
            visible_ids.update(_referenced_ids(action.options, state.cards))
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
    hidden_ids = set(state.cards) - visible_ids
    for field in ("pending_effects", "effect_usage"):
        payload[field] = redact_hidden_references(payload[field], hidden_ids)
    for projected in payload["players"].values():
        for field in ("manual_modifiers", "effect_ready_flags_this_turn", "live_result"):
            projected[field] = redact_hidden_references(projected[field], hidden_ids)
    return hidden_ids


def _hidden_slots(player_id: str, zone: str, count: int) -> list[str]:
    return [f"__hidden__/{player_id}/{zone}/{index}" for index in range(count)]


def _referenced_ids(value: Any, cards: dict[str, Any]) -> set[str]:
    if isinstance(value, str):
        return {value} if value in cards else set()
    values = value.values() if isinstance(value, dict) else value if isinstance(value, list) else ()
    return {item for nested in values for item in _referenced_ids(nested, cards)}


def redact_hidden_references(value: Any, hidden_ids: set[str]) -> Any:
    if isinstance(value, str):
        return "__hidden__" if value in hidden_ids else value
    if isinstance(value, list):
        return [redact_hidden_references(item, hidden_ids) for item in value]
    if isinstance(value, dict):
        return {
            f"__hidden__/metadata/{index}" if key in hidden_ids else key: item
            if key == "revealed_cards"
            else redact_hidden_references(item, hidden_ids)
            for index, (key, item) in enumerate(value.items())
        }
    return value
