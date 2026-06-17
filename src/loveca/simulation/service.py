"""Application service coordinating deck validation, match setup, and persistence."""

from __future__ import annotations

import random
import secrets
import uuid
from pathlib import Path

from loveca.decks.analyzer import DeckList, analyze_deck, load_deck
from loveca.simulation.catalog import MatchPlayerInput, build_match_cards
from loveca.simulation.effects import DEFAULT_EFFECT_REGISTRY
from loveca.simulation.models import ActionRequest, ActionResult, MatchState
from loveca.simulation.runtime import MatchRepository


class MatchSetupError(RuntimeError):
    """Raised when a match cannot be created from the supplied decks."""


class MatchService:
    def __init__(
        self,
        card_database_path: Path,
        runtime_database_path: Path,
        effect_registry_path: Path = DEFAULT_EFFECT_REGISTRY,
    ) -> None:
        self.card_database_path = card_database_path
        self.effect_registry_path = effect_registry_path
        self.repository = MatchRepository(runtime_database_path)

    def create_match(
        self,
        *,
        first_name: str,
        first_deck: DeckList,
        second_name: str,
        second_deck: DeckList,
        seed: int | None = None,
        match_id: str | None = None,
        first_player_id: str | None = None,
    ) -> ActionResult:
        for label, deck in (("player_1", first_deck), ("player_2", second_deck)):
            analysis = analyze_deck(self.card_database_path, deck)
            if not analysis.is_legal:
                messages = "; ".join(issue.message for issue in analysis.issues)
                raise MatchSetupError(f"{label} deck is illegal: {messages}")
        resolved_id = match_id or str(uuid.uuid4())
        resolved_seed = seed if seed is not None else secrets.randbits(63)
        players = (
            MatchPlayerInput("player_1", first_name, first_deck),
            MatchPlayerInput("player_2", second_name, second_deck),
        )
        cards, player_states, registry_version, effects = build_match_cards(
            self.card_database_path,
            players,
            self.effect_registry_path,
        )
        state = MatchState(
            match_id=resolved_id,
            seed=resolved_seed,
            players=player_states,
            cards=cards,
            effect_registry_version=registry_version,
            effect_definitions=effects,
        )
        resolved_first_player_id = first_player_id or _random_first_player_id(resolved_seed)
        if resolved_first_player_id not in state.players:
            raise MatchSetupError("first_player_id must be player_1 or player_2")
        created = self.repository.create_match(
            state,
            card_database_path=self.card_database_path,
        )
        return self.repository.apply(
            created.state.match_id,
            ActionRequest(
                action_type="choose_first_player",
                expected_revision=created.state.revision,
                payload={
                    "first_player_id": resolved_first_player_id,
                    "automatic": first_player_id is None,
                    "selection_method": "random_seeded"
                    if first_player_id is None
                    else "explicit",
                },
            ),
        )

    def create_match_from_paths(
        self,
        *,
        first_name: str,
        first_deck_path: Path,
        second_name: str,
        second_deck_path: Path,
        seed: int | None = None,
    ) -> ActionResult:
        return self.create_match(
            first_name=first_name,
            first_deck=load_deck(first_deck_path),
            second_name=second_name,
            second_deck=load_deck(second_deck_path),
            seed=seed,
        )

    def apply(self, match_id: str, action: ActionRequest) -> ActionResult:
        return self.repository.apply(match_id, action)


def _random_first_player_id(seed: int) -> str:
    return ("player_1", "player_2")[random.Random(f"{seed}:first_player").randrange(2)]
