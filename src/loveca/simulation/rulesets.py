"""Read-only, versioned official-rule sources and conformance evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PROJECT_ROOT = Path(__file__).parents[3]
DEFAULT_RULESET_REGISTRY = PROJECT_ROOT / "data_sources" / "ruleset-profiles.v0.json"
DEFAULT_RULESET_ID = "loveca-ja-1.06"

RuleSourceStatus = Literal[
    "source_confirmed", "source_available_unreviewed", "superseded"
]
RuleReferenceStatus = Literal["source_confirmed", "rules_reviewed", "superseded"]
RuleConformanceStatus = Literal["pass", "fail", "blocked", "not_run"]


class _ReadOnlyDefinition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class RuleSource(_ReadOnlyDefinition):
    source_id: str = Field(min_length=1)
    source_kind: Literal["comprehensive_rules_pdf", "official_qa", "official_ruling"]
    official_url: str = Field(pattern=r"^https://\S+$")
    local_path: str | None = None
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    published_date: str | None = None
    validation_status: RuleSourceStatus

    @model_validator(mode="after")
    def validate_confirmed_source(self) -> RuleSource:
        if self.validation_status == "source_confirmed" and self.sha256 is None:
            raise ValueError("confirmed rule source requires a content sha256")
        return self


class RuleReferenceDefinition(_ReadOnlyDefinition):
    reference_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    clause_id: str = Field(min_length=1)
    summary_ja: str = Field(min_length=1)
    summary_zh: str = Field(min_length=1)
    validation_status: RuleReferenceStatus = "source_confirmed"
    notes: str | None = None


class RulesetProfile(_ReadOnlyDefinition):
    ruleset_id: str = Field(min_length=1)
    rule_version: str = Field(min_length=1)
    ruling_pack_version: str = Field(min_length=1)
    source_ids: tuple[str, ...] = Field(min_length=1)
    rule_references: tuple[RuleReferenceDefinition, ...] = ()

    @model_validator(mode="after")
    def validate_identifiers(self) -> RulesetProfile:
        if len(self.source_ids) != len(set(self.source_ids)):
            raise ValueError(f"duplicate source in {self.ruleset_id}")
        identifiers = [item.reference_id for item in self.rule_references]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError(f"duplicate rule reference in {self.ruleset_id}")
        return self


class RulesetIdentity(_ReadOnlyDefinition):
    ruleset_id: str = Field(min_length=1)
    rule_version: str = Field(min_length=1)
    ruleset_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    ruling_pack_version: str = Field(min_length=1)


class RuleConformanceResult(BaseModel):
    """Evidence, not a claim of complete human rules review."""

    model_config = ConfigDict(extra="forbid")
    scenario_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    category: str = Field(min_length=1)
    status: RuleConformanceStatus
    rule_reference_ids: list[str] = Field(min_length=1)
    evidence: str = Field(min_length=1)
    details: dict[str, object] = Field(default_factory=dict)


class RulesetRegistry(_ReadOnlyDefinition):
    schema_version: Literal["ruleset_profiles_v0.1"] = "ruleset_profiles_v0.1"
    current_ruleset_id: str
    sources: tuple[RuleSource, ...]
    profiles: tuple[RulesetProfile, ...]

    @model_validator(mode="after")
    def validate_registry_links(self) -> RulesetRegistry:
        source_ids = [item.source_id for item in self.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("duplicate rule source id")
        profile_ids = [item.ruleset_id for item in self.profiles]
        if len(profile_ids) != len(set(profile_ids)):
            raise ValueError("duplicate ruleset profile id")
        if self.current_ruleset_id not in profile_ids:
            raise ValueError("current_ruleset_id does not reference a profile")
        sources_by_id = {item.source_id: item for item in self.sources}
        for profile in self.profiles:
            referenced = {item.source_id for item in profile.rule_references}
            missing = (set(profile.source_ids) | referenced) - sources_by_id.keys()
            if missing:
                raise ValueError(
                    f"ruleset {profile.ruleset_id} references unknown sources: {sorted(missing)}"
                )
            outside_profile = referenced - set(profile.source_ids)
            if outside_profile:
                raise ValueError(
                    f"ruleset {profile.ruleset_id} references sources outside profile: "
                    f"{sorted(outside_profile)}"
                )
            unreviewed = [
                source_id for source_id in profile.source_ids
                if sources_by_id[source_id].validation_status == "source_available_unreviewed"
            ]
            if unreviewed:
                raise ValueError(f"unreviewed sources cannot be active: {sorted(unreviewed)}")
        return self


def load_ruleset_registry(path: Path = DEFAULT_RULESET_REGISTRY) -> RulesetRegistry:
    try:
        return RulesetRegistry.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"invalid ruleset registry {path}: {exc}") from exc


def get_ruleset_profile(
    ruleset_id: str | None = None,
    *,
    registry: RulesetRegistry | None = None,
    registry_path: Path = DEFAULT_RULESET_REGISTRY,
) -> RulesetProfile:
    resolved_registry = registry or load_ruleset_registry(registry_path)
    resolved_id = resolved_registry.current_ruleset_id if ruleset_id is None else ruleset_id
    for profile in resolved_registry.profiles:
        if profile.ruleset_id == resolved_id:
            return profile
    raise ValueError(f"unknown ruleset_id: {resolved_id}")


def ruleset_fingerprint(profile: RulesetProfile, *, registry: RulesetRegistry) -> str:
    sources_by_id = {item.source_id: item for item in registry.sources}
    missing = set(profile.source_ids) - sources_by_id.keys()
    if missing:
        raise ValueError(f"unknown sources: {sorted(missing)}")
    # Source paths and collection order are packaging details, not rule identity.
    profile_payload = profile.model_dump(mode="json")
    profile_payload["source_ids"] = sorted(profile.source_ids)
    profile_payload["rule_references"] = [
        item.model_dump(mode="json")
        for item in sorted(profile.rule_references, key=lambda item: item.reference_id)
    ]
    payload = {
        "schema_version": registry.schema_version,
        "profile": profile_payload,
        "sources": [
            sources_by_id[source_id].model_dump(mode="json", exclude={"local_path"})
            for source_id in sorted(profile.source_ids)
        ],
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def current_ruleset_identity(
    registry_path: Path = DEFAULT_RULESET_REGISTRY,
) -> tuple[RulesetProfile, str]:
    registry = load_ruleset_registry(registry_path)
    profile = get_ruleset_profile(registry=registry)
    return profile, ruleset_fingerprint(profile, registry=registry)


def ruleset_execution_report(
    *,
    rule_version: str,
    ruleset_id: str | None,
    fingerprint: str | None,
    ruling_pack_version: str | None,
    supported_rule_version: str,
    registry: RulesetRegistry | None = None,
) -> dict[str, object]:
    """Do not reinterpret a pinned snapshot under another active ruleset."""
    resolved = registry or load_ruleset_registry()
    current = get_ruleset_profile(registry=resolved)
    if current.rule_version != supported_rule_version:
        return {
            "can_execute": False,
            "status": "engine_rule_version_mismatch",
            "mismatches": ["rule_version"],
        }
    identity = (ruleset_id, fingerprint, ruling_pack_version)
    if all(value is None for value in identity):
        compatible = rule_version == current.rule_version
        return {
            "can_execute": compatible,
            "status": "legacy_unpinned" if compatible else "rule_version_mismatch",
            "mismatches": [] if compatible else ["rule_version"],
        }
    expected = {
        "rule_version": current.rule_version,
        "ruleset_id": current.ruleset_id,
        "ruleset_fingerprint": ruleset_fingerprint(current, registry=resolved),
        "ruling_pack_version": current.ruling_pack_version,
    }
    saved = {
        "rule_version": rule_version,
        "ruleset_id": ruleset_id,
        "ruleset_fingerprint": fingerprint,
        "ruling_pack_version": ruling_pack_version,
    }
    mismatches = [field for field in expected if saved[field] != expected[field]]
    return {
        "can_execute": not mismatches,
        "status": "compatible" if not mismatches else "ruleset_mismatch",
        "mismatches": mismatches,
    }
