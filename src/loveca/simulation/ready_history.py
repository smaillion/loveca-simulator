"""Opt-in member ready provenance; legacy ready operations never produce it."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

OPERATION = "ready_member_with_provenance_v1"
SOURCE_WAIT_OPERATION = "ready_member_after_source_wait_provenance_v1"
PROVENANCE_OPERATIONS = frozenset({OPERATION, SOURCE_WAIT_OPERATION})
SOURCE_KEY = "ready_source_lki_v1"
COST_KEY = "ready_source_wait_cost_v1"


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


def uses_ready_provenance(effect: Any) -> bool:
    return any(op.action_type in PROVENANCE_OPERATIONS for op in getattr(effect, "actions", []))


def uses_source_wait_cost(effect: Any) -> bool:
    return any(op.action_type == SOURCE_WAIT_OPERATION for op in getattr(effect, "actions", []))


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
    if getattr(state, "member_ready_history", None) is None and any(uses_ready_provenance(e) for e in state.effect_definitions.values()):
        state.member_ready_history = MemberReadyHistoryV1(turn_number=state.turn_number,
            coverage_complete=state.revision == 0 and not any(
                any(flag.endswith(":member") for flag in p.effect_ready_flags_this_turn) for p in state.players.values()))


def _source_zone(state: Any, instance_id: str) -> str | None:
    for player in state.players.values():
        if instance_id in player.member_area.values():
            return "stage"
        if instance_id in player.live_area:
            return "live_area"
    return None


def prepare_ready_source(state: Any, invocation: Any) -> None:
    if not uses_ready_provenance(state.effect_definitions.get(invocation.effect_id)):
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


def mark_ready_departure(state: Any, instance_ids: list[str], zone: str) -> None:
    history = getattr(state, "member_ready_history", None)
    if history is None:
        return
    if zone == "stage":
        for instance_id in instance_ids:
            history.object_ids.pop(instance_id, None)
    for invocation in state.pending_effects:
        raw = invocation.trigger_data.get(SOURCE_KEY)
        if not isinstance(raw, dict):
            continue
        source = ReadySourceV1.model_validate(raw)
        if source.instance_id not in instance_ids or source.zone != zone or source.departed:
            continue
        instance = state.cards[source.instance_id]
        source.owner_id = instance.owner_id
        source.unit_keys, source.work_keys = list(instance.card.unit_keys), list(instance.card.work_keys)
        source.departed = True
        invocation.trigger_data[SOURCE_KEY] = source.model_dump(mode="json")


def record_member_ready(state: Any, invocation: Any, target_id: str, previous: str) -> None:
    if uses_source_wait_cost(state.effect_definitions.get(invocation.effect_id)):
        validate_source_wait_cost(state, invocation)
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
