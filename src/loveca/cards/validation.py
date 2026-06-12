"""Validation primitives for normalized card records."""

from __future__ import annotations

from dataclasses import dataclass


VALID_CARD_TYPES = frozenset(
    {
        "member",
        "live",
        "energy",
    }
)


@dataclass(frozen=True)
class CardValidationError:
    field: str
    message: str


def validate_card_type(card_type: str) -> list[CardValidationError]:
    normalized = card_type.strip().lower()
    if normalized in VALID_CARD_TYPES:
        return []

    return [
        CardValidationError(
            field="card_type",
            message=f"unknown card type: {card_type}",
        )
    ]
