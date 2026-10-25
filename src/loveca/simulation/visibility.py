"""Private inspection boundaries shared by player and test-controller views."""

from loveca.simulation.models import MatchState


def private_inspection_card_ids(state: MatchState, viewer_id: str | None) -> set[str]:
    choice = state.pending_choice
    if choice is None or choice.player_id == viewer_id or choice.choice_type not in {
        "effect_inspection_selection", "manual_card_selection",
    }:
        return set()
    return {
        item for item in choice.options.get("inspected_card_instance_ids", [])
        if isinstance(item, str)
    }
