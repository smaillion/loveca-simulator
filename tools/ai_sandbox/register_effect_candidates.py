"""Review-gated merger for exact-text Effect Registry candidates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from loveca.simulation.effects import (
    DEFAULT_EFFECT_REGISTRY,
    EffectDefinition,
    EffectRegistry,
    load_effect_registry,
)


class CandidateRegistrationError(RuntimeError):
    """Raised when candidate input cannot be merged without changing identity."""


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate and optionally append reviewed exact-text candidates."
    )
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--registry", type=Path, default=DEFAULT_EFFECT_REGISTRY)
    parser.add_argument(
        "--approve",
        action="store_true",
        help="Write the validated merge. Without this flag the command is read-only.",
    )
    parser.add_argument(
        "--replace-matching-manual",
        action="store_true",
        help=(
            "Replace only an identity-matching manual_resolution entry with a "
            "test_validated_executable candidate."
        ),
    )
    args = parser.parse_args()

    try:
        merged, added = merge_candidates(
            args.registry,
            args.candidates,
            replace_matching_manual=args.replace_matching_manual,
        )
    except (OSError, ValueError, CandidateRegistrationError) as exc:
        print(f"error: {exc}")
        return 1

    counts: dict[str, int] = {}
    for effect in added:
        counts[effect.simulation_support] = counts.get(effect.simulation_support, 0) + 1
    print(f"Validated {len(added)} new effect candidate(s): {counts}")
    if not args.approve:
        print("Dry run only. Pass --approve after reviewing the candidate artifact.")
        return 0

    payload = merged.model_dump(mode="json")
    original = json.loads(args.registry.read_text(encoding="utf-8"))
    original_by_id = {effect["effect_id"]: effect for effect in original["effects"]}
    changed_ids = {effect.effect_id for effect in added}
    # Do not materialize newly introduced model defaults in unrelated snapshots.
    payload["effects"] = [
        effect if effect["effect_id"] in changed_ids else original_by_id[effect["effect_id"]]
        for effect in payload["effects"]
    ]
    temporary = args.registry.with_suffix(f"{args.registry.suffix}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(args.registry)
    print(f"Registered {len(added)} effect candidate(s) in {args.registry}.")
    return 0


def merge_candidates(
    registry_path: Path,
    candidates_path: Path,
    *,
    replace_matching_manual: bool = False,
) -> tuple[EffectRegistry, list[EffectDefinition]]:
    registry = load_effect_registry(registry_path)
    payload = json.loads(candidates_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise CandidateRegistrationError("candidate artifact must be a JSON array")

    registered_ids = {effect.effect_id for effect in registry.effects}
    registered_by_id = {effect.effect_id: effect for effect in registry.effects}
    registered_identities = {
        (effect.card_code, effect.raw_text_hash, effect.effect_index)
        for effect in registry.effects
    }
    added: list[EffectDefinition] = []
    candidate_ids: set[str] = set()
    candidate_identities: set[tuple[str, str, int]] = set()
    replacements: dict[str, EffectDefinition] = {}
    allowed_fields = set(EffectDefinition.model_fields)

    for index, raw_candidate in enumerate(payload):
        if not isinstance(raw_candidate, dict):
            raise CandidateRegistrationError(f"candidate {index} must be an object")
        if (
            raw_candidate.get("already_registered") is True
            and not replace_matching_manual
        ):
            raise CandidateRegistrationError(
                f"candidate {index} is already registered and must not be rewritten"
            )
        candidate_payload: dict[str, Any] = {
            key: value for key, value in raw_candidate.items() if key in allowed_fields
        }
        candidate = EffectDefinition.model_validate(candidate_payload)
        identity = (
            candidate.card_code,
            candidate.raw_text_hash,
            candidate.effect_index,
        )
        if candidate.effect_id in registered_ids or identity in registered_identities:
            existing = registered_by_id.get(candidate.effect_id)
            existing_identity = (
                existing.card_code,
                existing.raw_text_hash,
                existing.effect_index,
            ) if existing is not None else None
            can_replace = (
                replace_matching_manual
                and existing is not None
                and existing_identity == identity
                and existing.text_revision_id == candidate.text_revision_id
                and existing.simulation_support == "manual_resolution"
                and candidate.simulation_support == "test_validated_executable"
                and candidate.review_status == "test_validated"
            )
            if not can_replace:
                raise CandidateRegistrationError(
                    f"candidate would overwrite an existing effect: {candidate.effect_id}"
                )
            replacements[candidate.effect_id] = candidate
            added.append(candidate)
            continue
        if candidate.effect_id in candidate_ids or identity in candidate_identities:
            raise CandidateRegistrationError(
                f"candidate artifact contains a duplicate effect: {candidate.effect_id}"
            )
        candidate_ids.add(candidate.effect_id)
        candidate_identities.add(identity)
        added.append(candidate)

    unchanged = [
        replacements.get(effect.effect_id, effect)
        for effect in registry.effects
    ]
    new_effects = [
        effect for effect in added if effect.effect_id not in replacements
    ]
    effects = sorted(
        [*unchanged, *new_effects],
        key=lambda effect: (effect.card_code, effect.effect_index, effect.effect_id),
    )
    return (
        EffectRegistry(
            registry_version=registry.registry_version,
            rule_version=registry.rule_version,
            effects=effects,
        ),
        added,
    )


if __name__ == "__main__":
    raise SystemExit(main())
