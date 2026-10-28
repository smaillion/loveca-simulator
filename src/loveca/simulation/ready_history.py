"""Opt-in member ready provenance; legacy ready operations never produce it."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

OPERATION = "ready_member_with_provenance_v1"
SOURCE_WAIT_OPERATION = "ready_member_after_source_wait_provenance_v1"
SOURCE_WAIT_V2_OPERATION = "ready_member_after_source_wait_provenance_v2"
SOURCE_WAIT_OPERATIONS = frozenset({SOURCE_WAIT_OPERATION, SOURCE_WAIT_V2_OPERATION})
DEPARTED_OPERATION = "ready_member_from_departed_source_provenance_v1"
DEPARTED_BOTH_OPERATION = "ready_member_from_departed_both_provenance_v2"
PROVENANCE_OPERATIONS = frozenset({OPERATION, *SOURCE_WAIT_OPERATIONS, DEPARTED_OPERATION, DEPARTED_BOTH_OPERATION})
SOURCE_KEY = "ready_source_lki_v1"
COST_KEY = "ready_source_wait_cost_v1"
DEPARTED_KEY = "ready_departed_source_v1"
QUALIFIED_SOURCE_KEY = "qualified_ready_source_v1"
QUALIFIED_POLICY = "qualified_source_v1"


class StageReadyDepartureV1(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instance_id: str
    owner_id: str
    turn_number: StrictInt = Field(ge=1)
    from_slot: Literal["left", "center", "right"]
    unit_keys: list[str]
    work_keys: list[str]
    effect_ids: list[str]


class ReadyDepartedSourceV1(BaseModel):
    model_config = ConfigDict(extra="forbid")
    policy: Literal["stage_to_waiting_ready_v1"] = "stage_to_waiting_ready_v1"
    invocation_id: str
    effect_id: str
    instance_id: str
    owner_id: str
    turn_number: StrictInt = Field(ge=1)
    from_slot: Literal["left", "center", "right"]
    unit_keys: list[str]
    work_keys: list[str]


class ReadySourceWaitCostV1(BaseModel):
    model_config = ConfigDict(extra="forbid")
    policy: Literal["source_wait_cost_v1"] = "source_wait_cost_v1"
    invocation_id: str
    effect_id: str
    source_instance_id: str
    player_id: str
    turn_number: StrictInt = Field(ge=1)
    paid: StrictBool = False


class ReadySourceV1(BaseModel):
    model_config = ConfigDict(extra="forbid")
    invocation_id: str
    effect_id: str
    instance_id: str
    effect_player_id: str
    owner_id: str
    turn_number: StrictInt = Field(ge=1)
    zone: Literal["stage", "live_area"]
    unit_keys: list[str]
    work_keys: list[str]
    departed: StrictBool = False


class MemberReadyEventV1(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: ReadySourceV1
    target_instance_id: str
    target_owner_id: str
    target_object_id: str


class MemberReadyHistoryV1(BaseModel):
    model_config = ConfigDict(extra="forbid")
    policy: Literal["effect_member_object_v1"] = "effect_member_object_v1"
    turn_number: StrictInt = Field(ge=1)
    next_object_id: StrictInt = Field(default=0, ge=0)
    coverage_complete: StrictBool = True
    object_ids: dict[str, str] = Field(default_factory=dict)
    events: list[MemberReadyEventV1] = Field(default_factory=list)


class UnprovenMemberReadyV1(BaseModel):
    model_config = ConfigDict(extra="forbid")
    invocation_id: str
    effect_player_id: str
    target_owner_id: str
    source: ReadySourceV1 | None = None


class MemberReadyQualifiedCoverageV1(BaseModel):
    model_config = ConfigDict(extra="forbid")
    policy: Literal["qualified_source_v1"] = "qualified_source_v1"
    turn_number: StrictInt = Field(ge=1)
    baseline_complete: StrictBool = False
    unknown_changes: list[UnprovenMemberReadyV1] = Field(default_factory=list)


def uses_ready_provenance(effect: Any) -> bool:
    return any(op.action_type in PROVENANCE_OPERATIONS for op in getattr(effect, "actions", []))


def uses_source_wait_cost(effect: Any) -> bool:
    return any(op.action_type in SOURCE_WAIT_OPERATIONS for op in getattr(effect, "actions", []))


def uses_departed_source(effect: Any) -> bool:
    return any(op.action_type in {DEPARTED_OPERATION, DEPARTED_BOTH_OPERATION} for op in getattr(effect, "actions", []))


def capture_ready_departure(state: Any, player_id: str, instance_id: str) -> dict[str, Any] | None:
    card = state.cards[instance_id]
    effect_ids = [key for key in card.card.effect_ids if uses_departed_source(state.effect_definitions.get(key))]
    if not effect_ids:
        return None
    slot = next((k for k, value in state.players[player_id].member_area.items() if value == instance_id), None)
    if card.owner_id != player_id or card.card.card_type != "member" or slot is None:
        raise ValueError("departed ready source must be its own original top-level Stage Member")
    return StageReadyDepartureV1(instance_id=instance_id, owner_id=player_id, turn_number=state.turn_number,
        from_slot=slot, unit_keys=list(card.card.unit_keys), work_keys=list(card.card.work_keys), effect_ids=effect_ids).model_dump(mode="json")


def bind_departed_ready_source(state: Any, invocation: Any, captured: Any) -> None:
    data = StageReadyDepartureV1.model_validate(captured)
    if (type(state.turn_number) is not int or data.turn_number != state.turn_number
            or data.instance_id != invocation.source_card_instance_id or data.owner_id != invocation.player_id
            or invocation.effect_id not in data.effect_ids or invocation.trigger_event != "member_left_stage_to_waiting_room"
            or invocation.trigger_data.get("to_zone") != "waiting_room"
            or invocation.trigger_data.get("from_slot") != data.from_slot
            or type(invocation.trigger_data.get("turn_number")) is not int
            or invocation.trigger_data["turn_number"] != data.turn_number
            or data.instance_id not in state.players[data.owner_id].waiting_room):
        raise ValueError("departed ready source requires its actual captured Stage-to-waiting transition")
    begin_ready_tracking(state)
    proof = ReadyDepartedSourceV1(invocation_id=invocation.invocation_id, effect_id=invocation.effect_id,
        **data.model_dump(exclude={"effect_ids"}))
    invocation.trigger_data[DEPARTED_KEY] = proof.model_dump(mode="json")
    invocation.trigger_data[SOURCE_KEY] = ReadySourceV1(invocation_id=proof.invocation_id, effect_id=proof.effect_id,
        instance_id=proof.instance_id, effect_player_id=proof.owner_id, owner_id=proof.owner_id,
        turn_number=proof.turn_number, zone="stage", unit_keys=proof.unit_keys, work_keys=proof.work_keys,
        departed=True).model_dump(mode="json")


def validate_departed_ready_source(state: Any, invocation: Any) -> None:
    proof = ReadyDepartedSourceV1.model_validate(invocation.trigger_data.get(DEPARTED_KEY))
    source = ReadySourceV1.model_validate(invocation.trigger_data.get(SOURCE_KEY))
    if (type(state.turn_number) is not int or proof.turn_number != state.turn_number
            or invocation.resolution_stage not in {"initial", "after_cost"} or invocation.trigger_event != "member_left_stage_to_waiting_room"
            or (proof.invocation_id, proof.effect_id, proof.instance_id, proof.owner_id)
            != (invocation.invocation_id, invocation.effect_id, invocation.source_card_instance_id, invocation.player_id)
            or invocation.trigger_data.get("from_slot") != proof.from_slot
            or invocation.trigger_data.get("to_zone") != "waiting_room"
            or type(invocation.trigger_data.get("turn_number")) is not int
            or invocation.trigger_data["turn_number"] != proof.turn_number
            or source != ReadySourceV1(invocation_id=proof.invocation_id, effect_id=proof.effect_id,
                instance_id=proof.instance_id, effect_player_id=proof.owner_id, owner_id=proof.owner_id,
                turn_number=proof.turn_number, zone="stage", unit_keys=proof.unit_keys, work_keys=proof.work_keys, departed=True)):
        raise ValueError("departed ready source requires its exact original invocation and last information")


def prepare_source_wait_cost(state: Any, invocation: Any) -> None:
    if not uses_source_wait_cost(state.effect_definitions.get(invocation.effect_id)):
        return
    source = state.cards[invocation.source_card_instance_id]
    if (source.owner_id != invocation.player_id or source.card.card_type != "member"
            or source.instance_id not in state.players[invocation.player_id].member_area.values()
            or source.orientation != "active" or invocation.trigger_event != "player_activation"):
        raise ValueError("source Wait cost requires its own original active Stage Member")
    invocation.trigger_data[COST_KEY] = ReadySourceWaitCostV1(invocation_id=invocation.invocation_id,
        effect_id=invocation.effect_id, source_instance_id=source.instance_id,
        player_id=invocation.player_id, turn_number=state.turn_number).model_dump(mode="json")


def validate_source_wait_cost(state: Any, invocation: Any, *, paid: bool = True) -> ReadySourceWaitCostV1:
    cost = ReadySourceWaitCostV1.model_validate(invocation.trigger_data.get(COST_KEY))
    if (type(state.turn_number) is not int or cost.paid is not paid or invocation.resolution_stage != "after_cost"
            or invocation.trigger_event != "player_activation"
            or (cost.invocation_id, cost.effect_id, cost.source_instance_id, cost.player_id, cost.turn_number)
            != (invocation.invocation_id, invocation.effect_id, invocation.source_card_instance_id,
                invocation.player_id, state.turn_number)):
        raise ValueError("ready operation requires its exact actually paid source Wait cost")
    return cost


def finish_source_wait_cost(state: Any, invocation: Any) -> None:
    if not uses_source_wait_cost(state.effect_definitions.get(invocation.effect_id)):
        return
    cost = validate_source_wait_cost(state, invocation, paid=False)
    source = state.cards[cost.source_instance_id]
    if source.orientation != "wait" or source.instance_id not in state.players[cost.player_id].member_area.values():
        raise ValueError("source Wait payment did not actually occur")
    cost.paid = True
    invocation.trigger_data[COST_KEY] = cost.model_dump(mode="json")


def begin_ready_tracking(state: Any) -> None:
    history_was_missing = getattr(state, "member_ready_history", None) is None
    if getattr(state, "member_ready_history", None) is None and any(uses_ready_provenance(e) for e in state.effect_definitions.values()):
        state.member_ready_history = MemberReadyHistoryV1(turn_number=state.turn_number,
            coverage_complete=state.revision == 0 and not any(
                any(flag.endswith(":member") for flag in p.effect_ready_flags_this_turn) for p in state.players.values()))
    if (getattr(state, "member_ready_coverage_policy", None) == QUALIFIED_POLICY
            and getattr(state, "member_ready_qualified_coverage", None) is None):
        history = getattr(state, "member_ready_history", None)
        state.member_ready_qualified_coverage = MemberReadyQualifiedCoverageV1(turn_number=state.turn_number,
            baseline_complete=state.revision == 0 and history is not None and history.coverage_complete)
    if (getattr(state, "member_ready_coverage_policy", None) == QUALIFIED_POLICY and history_was_missing
            and getattr(state, "member_ready_history", None) is not None and state.revision != 0):
        state.member_ready_qualified_coverage.baseline_complete = False


def prepare_qualified_ready_source(state: Any, invocation: Any) -> None:
    effect = state.effect_definitions.get(invocation.effect_id)
    if (getattr(state, "member_ready_coverage_policy", None) != QUALIFIED_POLICY
            or getattr(effect, "cost", None) or getattr(effect, "cost_choice", None)
            or not any(op.action_type == "ready_member" for op in
                       getattr(effect, "actions", []))):
        return
    zone = _source_zone(state, invocation.source_card_instance_id)
    if zone is None:
        return
    instance = state.cards[invocation.source_card_instance_id]
    invocation.trigger_data[QUALIFIED_SOURCE_KEY] = ReadySourceV1(
        invocation_id=invocation.invocation_id, effect_id=invocation.effect_id,
        instance_id=instance.instance_id, effect_player_id=invocation.player_id, owner_id=instance.owner_id,
        turn_number=state.turn_number, zone=zone, unit_keys=list(instance.card.unit_keys),
        work_keys=list(instance.card.work_keys)).model_dump(mode="json")


def record_unproven_member_ready(state: Any, invocation: Any, target_owner_id: str) -> None:
    if getattr(state, "member_ready_coverage_policy", None) != QUALIFIED_POLICY:
        return
    ledger = getattr(state, "member_ready_qualified_coverage", None)
    if ledger is None or type(state.turn_number) is not int or ledger.turn_number != state.turn_number:
        raise ValueError("qualified ready coverage requires its current explicit ledger")
    raw = invocation.trigger_data.get(QUALIFIED_SOURCE_KEY)
    source = ReadySourceV1.model_validate(raw) if raw is not None else None
    if source is not None:
        if (source.turn_number != state.turn_number
                or (source.invocation_id, source.effect_id, source.instance_id, source.effect_player_id)
                != (invocation.invocation_id, invocation.effect_id, invocation.source_card_instance_id, invocation.player_id)):
            raise ValueError("qualified ready source requires its original invocation")
        if not source.departed:
            if _source_zone(state, source.instance_id) != source.zone:
                raise ValueError("qualified ready source departure evidence is missing")
            instance = state.cards[source.instance_id]
            source.owner_id = instance.owner_id
            source.unit_keys, source.work_keys = list(instance.card.unit_keys), list(instance.card.work_keys)
    change = UnprovenMemberReadyV1(invocation_id=invocation.invocation_id, effect_player_id=invocation.player_id,
        target_owner_id=target_owner_id, source=source)
    if change not in ledger.unknown_changes:
        ledger.unknown_changes.append(change)


def _source_zone(state: Any, instance_id: str) -> str | None:
    for player in state.players.values():
        if instance_id in player.member_area.values():
            return "stage"
        if instance_id in player.live_area:
            return "live_area"
    return None


def prepare_ready_source(state: Any, invocation: Any, departure: Any = None) -> None:
    prepare_qualified_ready_source(state, invocation)
    if not uses_ready_provenance(state.effect_definitions.get(invocation.effect_id)):
        return
    if uses_departed_source(state.effect_definitions.get(invocation.effect_id)):
        bind_departed_ready_source(state, invocation, departure)
        return
    zone = _source_zone(state, invocation.source_card_instance_id)
    if zone is None:
        raise ValueError("ready provenance v1 requires an original Stage or Live source")
    begin_ready_tracking(state)
    if state.member_ready_history.turn_number != state.turn_number:
        raise ValueError("ready provenance belongs to a different game turn")
    instance = state.cards[invocation.source_card_instance_id]
    source = ReadySourceV1(invocation_id=invocation.invocation_id, effect_id=invocation.effect_id,
        instance_id=instance.instance_id, effect_player_id=invocation.player_id, owner_id=instance.owner_id,
        turn_number=state.turn_number, zone=zone, unit_keys=list(instance.card.unit_keys), work_keys=list(instance.card.work_keys))
    invocation.trigger_data[SOURCE_KEY] = source.model_dump(mode="json")


def validate_live_start_ready_source(state: Any, invocation: Any) -> None:
    source = ReadySourceV1.model_validate(invocation.trigger_data.get(SOURCE_KEY))
    departed = invocation.trigger_data.get("original_source_live_object_departed", False)
    if (type(state.turn_number) is not int or invocation.trigger_event != "live_started"
            or invocation.trigger_data.get("original_source_live_object") is not True
            or type(departed) is not bool or source.departed is not departed
            or source.turn_number != state.turn_number or source.zone != "live_area"
            or (source.invocation_id, source.effect_id, source.instance_id, source.effect_player_id, source.owner_id)
            != (invocation.invocation_id, invocation.effect_id, invocation.source_card_instance_id,
                invocation.player_id, invocation.player_id)):
        raise ValueError("three ready source score requires its original Live-start source")
    if not departed and source.instance_id not in state.players[invocation.player_id].live_area:
        raise ValueError("three ready source score requires current original Live or departure evidence")


def mark_ready_departure(state: Any, instance_ids: list[str], zone: str) -> None:
    history = getattr(state, "member_ready_history", None)
    if history is None and getattr(state, "member_ready_coverage_policy", None) != QUALIFIED_POLICY:
        return
    if zone == "stage" and history is not None:
        for instance_id in instance_ids:
            history.object_ids.pop(instance_id, None)
    for invocation in state.pending_effects:
        for key in (SOURCE_KEY, QUALIFIED_SOURCE_KEY):
            raw = invocation.trigger_data.get(key)
            if not isinstance(raw, dict):
                continue
            source = ReadySourceV1.model_validate(raw)
            if source.instance_id not in instance_ids or source.zone != zone or source.departed:
                continue
            instance = state.cards[source.instance_id]
            source.owner_id = instance.owner_id
            source.unit_keys, source.work_keys = list(instance.card.unit_keys), list(instance.card.work_keys)
            source.departed = True
            invocation.trigger_data[key] = source.model_dump(mode="json")


def record_member_ready(state: Any, invocation: Any, target_id: str, previous: str) -> None:
    if uses_source_wait_cost(state.effect_definitions.get(invocation.effect_id)):
        validate_source_wait_cost(state, invocation)
    if uses_departed_source(state.effect_definitions.get(invocation.effect_id)):
        validate_departed_ready_source(state, invocation)
    history = getattr(state, "member_ready_history", None)
    source = ReadySourceV1.model_validate(invocation.trigger_data.get(SOURCE_KEY))
    if (history is None or history.turn_number != state.turn_number
            or source.turn_number != state.turn_number
            or (source.invocation_id, source.effect_id, source.instance_id, source.effect_player_id)
            != (invocation.invocation_id, invocation.effect_id, invocation.source_card_instance_id, invocation.player_id)):
        raise ValueError("ready provenance requires its exact current invocation")
    if not source.departed:
        if _source_zone(state, source.instance_id) != source.zone:
            raise ValueError("ready source departure provenance is missing")
        instance = state.cards[source.instance_id]
        source.owner_id = instance.owner_id
        source.unit_keys, source.work_keys = list(instance.card.unit_keys), list(instance.card.work_keys)
    invocation.trigger_data[SOURCE_KEY] = source.model_dump(mode="json")
    target = state.cards[target_id]
    if (target.card.card_type != "member"
            or target_id not in state.players[target.owner_id].member_area.values()):
        raise ValueError("ready provenance target must be a top-level Member")
    if previous != "wait":
        return
    if target_id not in history.object_ids:
        history.next_object_id += 1
        history.object_ids[target_id] = f"member-ready-v1/{history.next_object_id}"
    token = history.object_ids[target_id]
    if not any(e.source.invocation_id == invocation.invocation_id and e.target_object_id == token for e in history.events):
        history.events.append(MemberReadyEventV1(source=source, target_instance_id=target_id,
            target_owner_id=target.owner_id, target_object_id=token))


def current_effect_readied_members(state: Any, player_id: str, *, unit_key: str | None = None,
                                  work_key: str | None = None) -> list[str] | None:
    """None means no versioned evidence, not a proven count of zero."""
    history = getattr(state, "member_ready_history", None)
    if history is None:
        return None
    if history.turn_number != state.turn_number:
        raise ValueError("ready provenance belongs to a different game turn")
    if not history.coverage_complete:
        return None
    eligible = {e.target_instance_id for e in history.events
        if e.source.turn_number == state.turn_number and e.source.effect_player_id == player_id
        and e.source.owner_id == player_id and e.target_owner_id == player_id
        and (unit_key is None or unit_key in e.source.unit_keys)
        and (work_key is None or work_key in e.source.work_keys)
        and history.object_ids.get(e.target_instance_id) == e.target_object_id}
    return [i for i in state.players[player_id].member_area.values()
            if i in eligible and state.cards[i].card.card_type == "member"]


def current_qualified_effect_readied_members(state: Any, player_id: str, *, source_owner_id: str,
        effect_player_id: str, unit_key: str | None = None, work_key: str | None = None) -> list[str] | None:
    """A separate opt-in query; legacy ready facts can disprove completeness, never prove a count."""
    if getattr(state, "member_ready_coverage_policy", None) != QUALIFIED_POLICY:
        return None
    if (any(p not in state.players for p in (player_id, source_owner_id, effect_player_id))
            or any(k is not None and (type(k) is not str or not k) for k in (unit_key, work_key))):
        raise ValueError("qualified ready query requires explicit valid players and qualifiers")
    ledger = getattr(state, "member_ready_qualified_coverage", None)
    history = getattr(state, "member_ready_history", None)
    if ledger is None or history is None:
        return None
    if type(state.turn_number) is not int or ledger.turn_number != state.turn_number or history.turn_number != state.turn_number:
        raise ValueError("qualified ready query belongs to a different game turn")
    if not ledger.baseline_complete:
        return None
    def matches(source: ReadySourceV1) -> bool:
        return (source.owner_id == source_owner_id and source.effect_player_id == effect_player_id
                and (unit_key is None or unit_key in source.unit_keys)
                and (work_key is None or work_key in source.work_keys))
    for change in ledger.unknown_changes:
        if (change.effect_player_id not in state.players or change.target_owner_id not in state.players
                or (change.source is not None and (change.source.turn_number != state.turn_number
                    or change.source.invocation_id != change.invocation_id
                    or change.source.effect_player_id != change.effect_player_id or change.source.owner_id not in state.players))):
            raise ValueError("qualified ready unknown evidence is malformed or stale")
        if change.target_owner_id == player_id and change.effect_player_id == effect_player_id:
            if change.source is None or matches(change.source):
                return None
    eligible = {e.target_instance_id for e in history.events
        if e.source.turn_number == state.turn_number and e.target_owner_id == player_id and matches(e.source)
        and history.object_ids.get(e.target_instance_id) == e.target_object_id}
    return [i for i in state.players[player_id].member_area.values()
            if i in eligible and state.cards[i].card.card_type == "member"]
