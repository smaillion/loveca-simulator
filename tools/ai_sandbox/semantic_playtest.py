"""Semantic user-agent sandbox for manual-resolution effect playtesting.

This tool is intentionally separate from ``blackbox_playtest``.  It still
drives the game only through LegalAction output, but when an unresolved
mandatory manual effect blocks progress it asks a configured semantic agent to
produce a replay-safe ManualAdjustmentAction payload.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

from loveca.decks.analyzer import DeckList
from loveca.simulation.engine import IllegalActionError, generate_legal_actions
from loveca.simulation.models import ActionRequest, CardInstance, LegalAction, MatchState
from loveca.simulation.service import MatchService
from tools.ai_sandbox.blackbox_playtest import (
    SandboxDeckSummary,
    build_decks,
    choose_action,
    describe_state,
    summarize_deck,
)

SEMANTIC_SCHEMA_VERSION = "semantic_sandbox_v0.1"


@dataclass
class SemanticDecision:
    decision: str
    reason_ja_or_zh: str = ""
    action_type: str | None = None
    player_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    confidence: str = "low"
    schema_gap: str | None = None


@dataclass
class SemanticAttempt:
    match_index: int
    action_index: int
    attempt_index: int
    status: str
    effect_id: str | None
    invocation_id: str | None
    source_card_instance_id: str | None
    source_card_code: str | None
    source_card_name_ja: str | None
    label_ja: str | None
    agent_reason: str
    decision: str
    action_type: str | None
    confidence: str
    schema_gap: str | None = None
    submitted_payload: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass
class ApiPlayAttempt:
    match_index: int
    action_index: int
    status: str
    phase: str
    legal_action_types: list[str]
    agent_reason: str
    decision: str
    action_type: str | None
    player_id: str | None
    confidence: str
    schema_gap: str | None = None
    submitted_payload: dict[str, Any] = field(default_factory=dict)
    fallback_used: bool = False
    error: str | None = None


@dataclass
class SemanticMatchSummary:
    match_index: int
    first_deck: str
    second_deck: str
    status: str
    final_phase: str
    turn_number: int
    action_count: int
    manual_effect_count: int = 0
    agent_success_count: int = 0
    agent_failure_count: int = 0
    agent_skip_count: int = 0
    api_play_count: int = 0
    api_play_failure_count: int = 0
    deterministic_fallback_count: int = 0
    schema_gap_count: int = 0
    blocker: str | None = None
    blocker_detail: dict[str, Any] = field(default_factory=dict)
    success_live_counts: dict[str, int] = field(default_factory=dict)
    events: dict[str, int] = field(default_factory=dict)


class SemanticAgentError(RuntimeError):
    """Raised when the semantic agent response is malformed or unavailable."""


class SemanticAgentProvider(Protocol):
    provider_name: str

    def decide(self, context: dict[str, Any]) -> SemanticDecision:
        """Return the next semantic decision for a manual-resolution context."""


class MockSemanticAgentProvider:
    provider_name = "mock"

    def __init__(self, scripted_decisions: list[dict[str, Any]] | None = None) -> None:
        self._scripted_decisions = list(scripted_decisions or [])

    def decide(self, context: dict[str, Any]) -> SemanticDecision:
        if self._scripted_decisions:
            return parse_agent_decision(self._scripted_decisions.pop(0))
        if context.get("mode") == "api_play":
            return SemanticDecision(
                decision="cannot_resolve",
                reason_ja_or_zh="mock provider does not choose ordinary actions",
                confidence="low",
                schema_gap="mock_provider:api_play",
            )
        invocation = context.get("manual_invocation") or {}
        return SemanticDecision(
            decision="cannot_resolve",
            reason_ja_or_zh="mock provider does not resolve manual effects",
            confidence="low",
            schema_gap=f"mock_provider:{invocation.get('effect_id', 'unknown')}",
        )


class OpenAICompatibleSemanticAgentProvider:
    provider_name = "openai_compatible"

    def __init__(self, *, api_base: str, api_key: str, model: str) -> None:
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.model = model

    def decide(self, context: dict[str, Any]) -> SemanticDecision:
        endpoint = self.api_base
        if not endpoint.endswith("/chat/completions"):
            endpoint = f"{endpoint}/chat/completions"
        payload = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a Love Live Card Game rules debugging user. "
                        "Return only strict JSON matching the requested schema. "
                        "Choose only legal actions from the provided list. "
                        "Never mutate state directly."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(context, ensure_ascii=False),
                },
            ],
        }
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise SemanticAgentError(f"semantic provider request failed: {exc}") from exc
        try:
            content = response_payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise SemanticAgentError("semantic provider response shape is invalid") from exc
        return parse_agent_decision(content)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=Path("data/loveca.sqlite3"))
    parser.add_argument("--output", type=Path, default=Path("logs/semantic_sandbox"))
    parser.add_argument("--decks", type=int, default=30)
    parser.add_argument("--matches", type=int, default=20)
    parser.add_argument("--max-actions", type=int, default=320)
    parser.add_argument(
        "--manual-fallback",
        choices=("block", "skip"),
        default="skip",
        help="What to do when the semantic agent cannot resolve a mandatory manual effect.",
    )
    parser.add_argument(
        "--play-policy",
        choices=("deterministic", "api"),
        default="deterministic",
        help=(
            "deterministic keeps the existing scripted sandbox ordinary-action policy; "
            "api asks the semantic provider to choose ordinary LegalActions too."
        ),
    )
    parser.add_argument(
        "--play-fallback",
        choices=("deterministic", "block"),
        default="deterministic",
        help="What to do when API Play cannot produce a valid ordinary action.",
    )
    parser.add_argument("--agent-provider", choices=("mock", "openai_compatible"), default=None)
    args = parser.parse_args()

    provider = provider_from_environment(args.agent_provider)
    args.output.mkdir(parents=True, exist_ok=True)
    decks = build_decks(args.database, args.decks)
    deck_summaries = [summarize_deck(args.database, deck) for deck in decks]
    match_summaries, attempts, api_play_attempts = run_semantic_matches(
        args.database,
        decks,
        provider=provider,
        match_count=args.matches,
        max_actions=args.max_actions,
        manual_fallback=args.manual_fallback,
        play_policy=args.play_policy,
        play_fallback=args.play_fallback,
    )
    write_semantic_outputs(
        args.output,
        provider=provider,
        deck_summaries=deck_summaries,
        match_summaries=match_summaries,
        attempts=attempts,
        api_play_attempts=api_play_attempts,
    )
    print(f"Wrote semantic sandbox report to {args.output / 'semantic-report.md'}")
    return 0


def provider_from_environment(provider_name: str | None = None) -> SemanticAgentProvider:
    provider_name = provider_name or os.environ.get("LOVECA_SEMANTIC_AGENT_PROVIDER", "mock")
    if provider_name == "mock":
        return MockSemanticAgentProvider()
    if provider_name == "openai_compatible":
        api_base = os.environ.get("LOVECA_SEMANTIC_AGENT_API_BASE")
        api_key = os.environ.get("LOVECA_SEMANTIC_AGENT_API_KEY")
        model = os.environ.get("LOVECA_SEMANTIC_AGENT_MODEL")
        missing = [
            name
            for name, value in {
                "LOVECA_SEMANTIC_AGENT_API_BASE": api_base,
                "LOVECA_SEMANTIC_AGENT_API_KEY": api_key,
                "LOVECA_SEMANTIC_AGENT_MODEL": model,
            }.items()
            if not value
        ]
        if missing:
            raise SemanticAgentError(
                "openai_compatible provider requires " + ", ".join(missing)
            )
        return OpenAICompatibleSemanticAgentProvider(
            api_base=str(api_base),
            api_key=str(api_key),
            model=str(model),
        )
    raise SemanticAgentError(f"unsupported semantic agent provider: {provider_name}")


def run_semantic_matches(
    database: Path,
    decks: list[DeckList],
    *,
    provider: SemanticAgentProvider,
    match_count: int,
    max_actions: int,
    manual_fallback: str,
    play_policy: str = "deterministic",
    play_fallback: str = "deterministic",
) -> tuple[list[SemanticMatchSummary], list[SemanticAttempt], list[ApiPlayAttempt]]:
    results: list[SemanticMatchSummary] = []
    attempts: list[SemanticAttempt] = []
    api_play_attempts: list[ApiPlayAttempt] = []
    with tempfile.TemporaryDirectory(prefix="loveca-semantic-sandbox-") as tmp:
        runtime = Path(tmp) / "matches.sqlite3"
        service = MatchService(database, runtime)
        for index in range(match_count):
            first = decks[index % len(decks)]
            second = decks[(index * 7 + 3) % len(decks)]
            result = service.create_match(
                first_name="Semantic A",
                first_deck=first,
                second_name="Semantic B",
                second_deck=second,
                seed=12000 + index,
                match_id=f"semantic-{index + 1:02d}",
            )
            state = result.state
            event_counts: Counter[str] = Counter(event.event_type for event in result.events)
            blocker = None
            blocker_detail: dict[str, Any] = {}
            action_count = 0
            manual_effect_count = 0
            agent_success_count = 0
            agent_failure_count = 0
            agent_skip_count = 0
            api_play_count = 0
            api_play_failure_count = 0
            deterministic_fallback_count = 0
            schema_gap_count = 0
            while action_count < max_actions and state.phase != "complete":
                legal_actions = generate_legal_actions(state)
                decision = choose_action(state, legal_actions, manual_policy="block")
                if decision is None and has_manual_resolution_action(legal_actions):
                    manual_effect_count += 1
                    semantic_result = try_semantic_manual_resolution(
                        service,
                        state,
                        legal_actions,
                        provider=provider,
                        match_index=index + 1,
                        action_index=action_count + 1,
                        manual_fallback=manual_fallback,
                    )
                    attempts.extend(semantic_result.attempts)
                    if semantic_result.state is None:
                        blocker = semantic_result.blocker
                        blocker_detail = semantic_result.blocker_detail
                        agent_failure_count += 1
                        schema_gap_count += semantic_result.schema_gap_count
                        break
                    state = semantic_result.state
                    event_counts.update(event.event_type for event in semantic_result.events)
                    action_count += semantic_result.applied_action_count
                    agent_success_count += semantic_result.success_count
                    agent_failure_count += semantic_result.failure_count
                    agent_skip_count += semantic_result.skip_count
                    schema_gap_count += semantic_result.schema_gap_count
                    continue
                if decision is None:
                    blocker = classify_semantic_blocker(state, legal_actions)
                    blocker_detail = describe_state(state, legal_actions)
                    break
                if play_policy == "api":
                    api_result = try_api_play_action(
                        state,
                        legal_actions,
                        provider=provider,
                        match_index=index + 1,
                        action_index=action_count + 1,
                    )
                    api_play_attempts.append(api_result.attempt)
                    if api_result.decision is not None:
                        decision = api_result.decision
                        api_play_count += 1
                    else:
                        api_play_failure_count += 1
                        if play_fallback == "deterministic":
                            deterministic_fallback_count += 1
                            api_result.attempt.fallback_used = True
                        else:
                            blocker = "api_play_unresolved"
                            blocker_detail = {
                                **describe_state(state, legal_actions),
                                "api_play_error": api_result.attempt.error,
                                "api_play_schema_gap": api_result.attempt.schema_gap,
                            }
                            break
                action_type, player_id, payload = decision
                try:
                    applied = service.apply(
                        state.match_id,
                        ActionRequest(
                            action_type=action_type,
                            expected_revision=state.revision,
                            player_id=player_id,
                            payload=payload,
                        ),
                    )
                except IllegalActionError as exc:
                    blocker = "engine_illegal_action"
                    blocker_detail = {
                        **describe_state(state, legal_actions),
                        "attempted_action": action_type,
                        "error": str(exc),
                    }
                    break
                state = applied.state
                action_count += 1
                event_counts.update(event.event_type for event in applied.events)
            status = "completed" if state.phase == "complete" else "blocked"
            if action_count >= max_actions and state.phase != "complete":
                blocker = "max_actions"
                blocker_detail = describe_state(state, generate_legal_actions(state))
            results.append(
                SemanticMatchSummary(
                    match_index=index + 1,
                    first_deck=first.name or "(unnamed)",
                    second_deck=second.name or "(unnamed)",
                    status=status,
                    final_phase=state.phase,
                    turn_number=state.turn_number,
                    action_count=action_count,
                    manual_effect_count=manual_effect_count,
                    agent_success_count=agent_success_count,
                    agent_failure_count=agent_failure_count,
                    agent_skip_count=agent_skip_count,
                    api_play_count=api_play_count,
                    api_play_failure_count=api_play_failure_count,
                    deterministic_fallback_count=deterministic_fallback_count,
                    schema_gap_count=schema_gap_count,
                    blocker=blocker,
                    blocker_detail=blocker_detail,
                    success_live_counts={
                        player_id: len(player.success_live_area)
                        for player_id, player in state.players.items()
                    },
                    events=dict(sorted(event_counts.items())),
                )
            )
    return results, attempts, api_play_attempts


@dataclass
class SemanticResolutionResult:
    state: MatchState | None
    events: list[Any] = field(default_factory=list)
    attempts: list[SemanticAttempt] = field(default_factory=list)
    applied_action_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    skip_count: int = 0
    schema_gap_count: int = 0
    blocker: str | None = None
    blocker_detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class ApiPlayResult:
    decision: tuple[str, str | None, dict[str, Any]] | None
    attempt: ApiPlayAttempt


def try_api_play_action(
    state: MatchState,
    legal_actions: list[LegalAction],
    *,
    provider: SemanticAgentProvider,
    match_index: int,
    action_index: int,
) -> ApiPlayResult:
    context = build_api_play_context(state, legal_actions)
    try:
        decision = provider.decide(context)
        validate_api_play_decision(decision, legal_actions)
    except (SemanticAgentError, ValueError) as exc:
        return ApiPlayResult(
            decision=None,
            attempt=api_play_attempt_from_decision(
                match_index,
                action_index,
                state,
                legal_actions,
                SemanticDecision(
                    decision="cannot_resolve",
                    reason_ja_or_zh=str(exc),
                    schema_gap=str(exc),
                ),
                status="api_play_invalid",
                error=str(exc),
            ),
        )
    if decision.decision != "submit_action":
        return ApiPlayResult(
            decision=None,
            attempt=api_play_attempt_from_decision(
                match_index,
                action_index,
                state,
                legal_actions,
                decision,
                status="api_play_unresolved",
                error=decision.schema_gap or decision.reason_ja_or_zh,
            ),
        )
    return ApiPlayResult(
        decision=(str(decision.action_type), decision.player_id, decision.payload),
        attempt=api_play_attempt_from_decision(
            match_index,
            action_index,
            state,
            legal_actions,
            decision,
            status="api_play_selected",
        ),
    )


def try_semantic_manual_resolution(
    service: MatchService,
    state: MatchState,
    legal_actions: list[LegalAction],
    *,
    provider: SemanticAgentProvider,
    match_index: int,
    action_index: int,
    manual_fallback: str,
) -> SemanticResolutionResult:
    attempts: list[SemanticAttempt] = []
    current_state = state
    current_legal = legal_actions
    events: list[Any] = []
    schema_gap_count = 0
    for attempt_index in range(1, 3):
        context = build_agent_context(current_state, current_legal)
        invocation = context.get("manual_invocation") or {}
        try:
            decision = provider.decide(context)
            validate_agent_decision(decision, current_state, current_legal, invocation)
        except (SemanticAgentError, ValueError) as exc:
            schema_gap_count += 1
            attempts.append(
                attempt_from_decision(
                    match_index,
                    action_index,
                    attempt_index,
                    "agent_invalid_adjustment",
                    current_state,
                    invocation,
                    SemanticDecision(
                        decision="cannot_resolve",
                        reason_ja_or_zh=str(exc),
                        schema_gap=str(exc),
                    ),
                    error=str(exc),
                )
            )
            continue
        if decision.schema_gap:
            schema_gap_count += 1
        if decision.decision == "cannot_resolve":
            attempts.append(
                attempt_from_decision(
                    match_index,
                    action_index,
                    attempt_index,
                    "schema_gap" if decision.schema_gap else "manual_resolution_failed",
                    current_state,
                    invocation,
                    decision,
                    error=decision.schema_gap,
                )
            )
            continue
        if decision.decision == "skip_effect":
            skip_decision = coerce_skip_decision(decision, current_legal, invocation)
            if skip_decision is None:
                attempts.append(
                    attempt_from_decision(
                        match_index,
                        action_index,
                        attempt_index,
                        "manual_resolution_failed",
                        current_state,
                        invocation,
                        decision,
                        error="skip_effect is not legal",
                    )
                )
                continue
            decision = skip_decision
        try:
            applied = service.apply(
                current_state.match_id,
                ActionRequest(
                    action_type=str(decision.action_type),
                    expected_revision=current_state.revision,
                    player_id=decision.player_id,
                    payload=decision.payload,
                ),
            )
        except IllegalActionError as exc:
            attempts.append(
                attempt_from_decision(
                    match_index,
                    action_index,
                    attempt_index,
                    "agent_invalid_adjustment",
                    current_state,
                    invocation,
                    decision,
                    error=str(exc),
                )
            )
            continue
        attempts.append(
            attempt_from_decision(
                match_index,
                action_index,
                attempt_index,
                "manual_resolution_skipped"
                if decision.action_type == "skip_effect"
                else "manual_resolved_by_agent",
                current_state,
                invocation,
                decision,
            )
        )
        current_state = applied.state
        events.extend(applied.events)
        applied_count = 1
        if (
            current_state.pending_choice is not None
            and current_state.pending_choice.choice_type == "manual_card_selection"
        ):
            follow_up = try_semantic_manual_inspection(
                service,
                current_state,
                provider=provider,
                match_index=match_index,
                action_index=action_index + applied_count,
            )
            attempts.extend(follow_up.attempts)
            if follow_up.state is None:
                return SemanticResolutionResult(
                    state=None,
                    events=events,
                    attempts=attempts,
                    applied_action_count=applied_count,
                    failure_count=1,
                    schema_gap_count=schema_gap_count + follow_up.schema_gap_count,
                    blocker=follow_up.blocker,
                    blocker_detail=follow_up.blocker_detail,
                )
            current_state = follow_up.state
            events.extend(follow_up.events)
            applied_count += follow_up.applied_action_count
            schema_gap_count += follow_up.schema_gap_count
        return SemanticResolutionResult(
            state=current_state,
            events=events,
            attempts=attempts,
            applied_action_count=applied_count,
            success_count=0 if decision.action_type == "skip_effect" else 1,
            skip_count=1 if decision.action_type == "skip_effect" else 0,
            schema_gap_count=schema_gap_count,
        )
    if manual_fallback == "skip":
        skip = fallback_skip_decision(
            current_legal,
            build_agent_context(current_state, current_legal),
        )
        if skip is not None:
            try:
                applied = service.apply(
                    current_state.match_id,
                    ActionRequest(
                        action_type="skip_effect",
                        expected_revision=current_state.revision,
                        player_id=skip.player_id,
                        payload=skip.payload,
                    ),
                )
            except IllegalActionError as exc:
                return SemanticResolutionResult(
                    state=None,
                    attempts=attempts,
                    failure_count=1,
                    schema_gap_count=schema_gap_count,
                    blocker="manual_resolution_failed",
                    blocker_detail={
                        "error": str(exc),
                        **describe_state(current_state, current_legal),
                    },
                )
            return SemanticResolutionResult(
                state=applied.state,
                events=list(applied.events),
                attempts=attempts,
                applied_action_count=1,
                skip_count=1,
                schema_gap_count=schema_gap_count,
            )
    return SemanticResolutionResult(
        state=None,
        attempts=attempts,
        failure_count=1,
        schema_gap_count=schema_gap_count,
        blocker="manual_resolution_failed",
        blocker_detail=describe_state(current_state, current_legal),
    )


def try_semantic_manual_inspection(
    service: MatchService,
    state: MatchState,
    *,
    provider: SemanticAgentProvider,
    match_index: int,
    action_index: int,
) -> SemanticResolutionResult:
    legal_actions = generate_legal_actions(state)
    context = build_agent_context(state, legal_actions)
    invocation = context.get("manual_invocation") or {}
    attempts: list[SemanticAttempt] = []
    schema_gap_count = 0
    for attempt_index in range(1, 3):
        try:
            decision = provider.decide(context)
            validate_agent_decision(decision, state, legal_actions, invocation)
        except (SemanticAgentError, ValueError) as exc:
            schema_gap_count += 1
            attempts.append(
                attempt_from_decision(
                    match_index,
                    action_index,
                    attempt_index,
                    "agent_invalid_adjustment",
                    state,
                    invocation,
                    SemanticDecision(
                        decision="cannot_resolve",
                        reason_ja_or_zh=str(exc),
                        schema_gap=str(exc),
                    ),
                    error=str(exc),
                )
            )
            continue
        if decision.decision != "submit_action":
            attempts.append(
                attempt_from_decision(
                    match_index,
                    action_index,
                    attempt_index,
                    "manual_resolution_failed",
                    state,
                    invocation,
                    decision,
                    error="manual inspection requires submit_action",
                )
            )
            continue
        if decision.schema_gap:
            schema_gap_count += 1
        try:
            applied = service.apply(
                state.match_id,
                ActionRequest(
                    action_type=str(decision.action_type),
                    expected_revision=state.revision,
                    player_id=decision.player_id,
                    payload=decision.payload,
                ),
            )
        except IllegalActionError as exc:
            attempts.append(
                attempt_from_decision(
                    match_index,
                    action_index,
                    attempt_index,
                    "agent_invalid_adjustment",
                    state,
                    invocation,
                    decision,
                    error=str(exc),
                )
            )
            continue
        attempts.append(
            attempt_from_decision(
                match_index,
                action_index,
                attempt_index,
                "manual_resolved_by_agent",
                state,
                invocation,
                decision,
            )
        )
        return SemanticResolutionResult(
            state=applied.state,
            events=list(applied.events),
            attempts=attempts,
            applied_action_count=1,
            success_count=1,
            schema_gap_count=schema_gap_count,
        )
    return SemanticResolutionResult(
        state=None,
        attempts=attempts,
        failure_count=1,
        schema_gap_count=schema_gap_count,
        blocker="manual_resolution_failed",
        blocker_detail=describe_state(state, legal_actions),
    )


def parse_agent_decision(payload: str | dict[str, Any]) -> SemanticDecision:
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise SemanticAgentError(f"agent response is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise SemanticAgentError("agent response must be a JSON object")
    decision = payload.get("decision")
    if decision not in {"submit_action", "skip_effect", "cannot_resolve"}:
        raise SemanticAgentError("agent decision is invalid")
    confidence = payload.get("confidence", "low")
    if confidence not in {"low", "medium", "high"}:
        raise SemanticAgentError("agent confidence is invalid")
    action_type = payload.get("action_type")
    if action_type is not None and not isinstance(action_type, str):
        raise SemanticAgentError("agent action_type must be a string")
    player_id = payload.get("player_id")
    if player_id is not None and not isinstance(player_id, str):
        raise SemanticAgentError("agent player_id must be a string")
    action_payload = payload.get("payload", {})
    if not isinstance(action_payload, dict):
        raise SemanticAgentError("agent payload must be an object")
    return SemanticDecision(
        decision=decision,
        reason_ja_or_zh=str(payload.get("reason_ja_or_zh", "")),
        action_type=action_type,
        player_id=player_id,
        payload=action_payload,
        confidence=confidence,
        schema_gap=(
            str(payload["schema_gap"])
            if payload.get("schema_gap") not in {None, ""}
            else None
        ),
    )


def validate_agent_decision(
    decision: SemanticDecision,
    state: MatchState,
    legal_actions: list[LegalAction],
    invocation: dict[str, Any],
) -> None:
    legal_by_type = {action.action_type: action for action in legal_actions}
    if decision.decision == "cannot_resolve":
        return
    if decision.decision == "skip_effect":
        if "skip_effect" not in legal_by_type:
            raise ValueError("skip_effect is not currently legal")
        return
    if decision.action_type not in legal_by_type:
        raise ValueError(f"agent action is not legal: {decision.action_type}")
    legal_action = legal_by_type[str(decision.action_type)]
    if decision.player_id != legal_action.player_id:
        raise ValueError("agent player_id does not match the legal action")
    if decision.action_type == "manual_adjustment":
        validate_manual_adjustment_payload(decision.payload, invocation)
    elif decision.action_type == "resolve_manual_inspection":
        pending = state.pending_choice
        if pending is None or pending.choice_type != "manual_card_selection":
            raise ValueError("resolve_manual_inspection is not pending")
        selected = decision.payload.get("selected_card_instance_ids")
        if not isinstance(selected, list) or any(not isinstance(item, str) for item in selected):
            raise ValueError("resolve_manual_inspection requires selected_card_instance_ids")
    elif decision.action_type == "skip_effect":
        return
    else:
        raise ValueError(
            "semantic manual agent may only submit manual_adjustment or "
            "resolve_manual_inspection"
        )


def validate_api_play_decision(
    decision: SemanticDecision,
    legal_actions: list[LegalAction],
) -> None:
    if decision.decision == "cannot_resolve":
        return
    if decision.decision == "skip_effect":
        if not any(action.action_type == "skip_effect" for action in legal_actions):
            raise ValueError("skip_effect is not currently legal")
        return
    if decision.decision != "submit_action":
        raise ValueError("API Play decision must submit or decline")
    if decision.action_type == "manual_adjustment":
        raise ValueError("API Play must not handle manual_adjustment")
    matching = [
        action
        for action in legal_actions
        if action.action_type == decision.action_type and action.player_id == decision.player_id
    ]
    if not matching:
        raise ValueError(f"API Play action is not legal: {decision.action_type}")


def validate_manual_adjustment_payload(payload: dict[str, Any], invocation: dict[str, Any]) -> None:
    required = {
        "source_invocation_id": invocation.get("invocation_id"),
        "source_effect_id": invocation.get("effect_id"),
        "source_card_instance_id": invocation.get("source_card_instance_id"),
    }
    for key, expected in required.items():
        if not expected or payload.get(key) != expected:
            raise ValueError(f"manual_adjustment payload has invalid {key}")
    adjustments = payload.get("adjustments")
    if not isinstance(adjustments, list) or not adjustments:
        raise ValueError("manual_adjustment payload requires adjustments")
    if payload.get("requires_confirmation") and not payload.get("confirmed_by"):
        raise ValueError("confirmed manual_adjustment requires confirmed_by")


def build_api_play_context(state: MatchState, legal_actions: list[LegalAction]) -> dict[str, Any]:
    acting_player_id = next(
        (action.player_id for action in legal_actions if action.player_id),
        state.active_player_id,
    )
    return {
        "schema_version": SEMANTIC_SCHEMA_VERSION,
        "mode": "api_play",
        "rules": [
            "Choose one action from legal_actions, or return cannot_resolve.",
            "Return only strict JSON.",
            "Do not invent card ids or mutate GameState directly.",
            "The engine will validate the submitted payload.",
            "Prefer actions that progress the game toward successful Live resolution.",
            "Do not choose manual_adjustment in API Play; manual effects use the dedicated semantic flow.",
        ],
        "allowed_response_schema": {
            "decision": "submit_action | cannot_resolve",
            "reason_ja_or_zh": "short explanation",
            "action_type": "one action_type from legal_actions",
            "player_id": "matching legal action player_id",
            "payload": "payload matching the selected legal action options",
            "confidence": "low | medium | high",
            "schema_gap": "optional reason when cannot_resolve",
        },
        "state": {
            "match_id": state.match_id,
            "phase": state.phase,
            "turn_number": state.turn_number,
            "active_player_id": state.active_player_id,
            "acting_player_id": acting_player_id,
            "revision": state.revision,
            "pending_choice": state.pending_choice.model_dump() if state.pending_choice else None,
            "pending_effects": [effect.model_dump() for effect in state.pending_effects],
        },
        "players": {
            player_id: player_context(
                state,
                player_id,
                include_private=player_id == acting_player_id,
            )
            for player_id in sorted(state.players)
        },
        "legal_actions": [action.model_dump() for action in legal_actions],
    }


def build_agent_context(state: MatchState, legal_actions: list[LegalAction]) -> dict[str, Any]:
    manual_action = next(
        (action for action in legal_actions if action.action_type == "manual_adjustment"),
        None,
    )
    manual_invocation = None
    if manual_action is not None:
        source_invocations = list(manual_action.options.get("source_invocations", []))
        manual_invocation = source_invocations[0] if source_invocations else None
    if manual_invocation is None and state.pending_choice is not None:
        manual_invocation = {
            "invocation_id": state.pending_choice.options.get("source_invocation_id"),
            "effect_id": state.pending_choice.options.get("source_effect_id"),
            "source_card_instance_id": state.pending_choice.options.get(
                "source_card_instance_id"
            ),
            "label_ja": state.pending_choice.message_ja,
            "simulation_support": "manual_resolution",
        }
    source_card = None
    if manual_invocation and manual_invocation.get("source_card_instance_id") in state.cards:
        source_card = card_context(state.cards[str(manual_invocation["source_card_instance_id"])])
    acting_player_id = (
        manual_action.player_id
        if manual_action is not None
        else state.pending_choice.player_id
        if state.pending_choice is not None
        else state.active_player_id
    )
    return {
        "schema_version": SEMANTIC_SCHEMA_VERSION,
        "rules": [
            "Choose only from legal_actions.",
            "Do not mutate GameState directly.",
            "Manual effects must use replay-safe manual_adjustment or resolve_manual_inspection.",
            (
                "If the current schema cannot express the card text, return "
                "cannot_resolve with schema_gap."
            ),
        ],
        "allowed_response_schema": {
            "decision": "submit_action | skip_effect | cannot_resolve",
            "reason_ja_or_zh": "short explanation",
            "action_type": "legal action type when submitting",
            "player_id": "legal action player_id",
            "payload": "action payload object",
            "confidence": "low | medium | high",
            "schema_gap": "optional gap reason",
        },
        "manual_adjustment_schema_reference": manual_adjustment_schema_reference(),
        "state": {
            "match_id": state.match_id,
            "phase": state.phase,
            "turn_number": state.turn_number,
            "active_player_id": state.active_player_id,
            "revision": state.revision,
            "pending_choice": state.pending_choice.model_dump() if state.pending_choice else None,
        },
        "manual_invocation": manual_invocation,
        "source_card": source_card,
        "players": {
            player_id: player_context(
                state,
                player_id,
                include_private=player_id == acting_player_id,
            )
            for player_id in sorted(state.players)
        },
        "legal_actions": [action.model_dump() for action in legal_actions],
    }


def manual_adjustment_schema_reference() -> dict[str, Any]:
    return {
        "required_root_fields_for_pending_effect": [
            "reason",
            "requires_confirmation",
            "confirmed_by",
            "source_invocation_id",
            "source_effect_id",
            "source_card_instance_id",
            "adjustments",
        ],
        "adjustment_types": {
            "draw_card": {"target_player_id": "player_id", "amount": "positive int"},
            "inspect_top_cards": {
                "target_player_id": "player_id",
                "amount": "positive int",
                "minimum": "int",
                "maximum": "int",
                "reveal_selected_to_opponent": "bool",
            },
            "discard_card": {
                "target_player_id": "player_id",
                "target_card_instance_id": "card in hand",
            },
            "move_card": {
                "target_player_id": "player_id",
                "target_card_instance_id": "owned card",
                "to_zone": (
                    "hand|main_deck|energy_deck|energy_area|live_area|waiting_room|"
                    "resolution_area|success_live_area|member_left|member_center|"
                    "member_right"
                ),
            },
            "ready_energy": {
                "target_player_id": "player_id",
                "target_card_instance_ids": "energy_area card ids",
            },
            "pay_energy": {
                "target_player_id": "player_id",
                "target_card_instance_ids": "energy_area card ids",
            },
            "modify_score": {
                "target_player_id": "player_id",
                "amount": "int",
                "duration": "live|turn|game",
            },
            "modify_blade": {
                "target_player_id": "player_id",
                "amount": "int",
                "duration": "live|turn|game",
            },
            "modify_heart": {
                "target_player_id": "player_id",
                "amount": "int",
                "color_slot": "heart01|heart02|heart03|heart06|heart0",
                "duration": "live|turn|game",
            },
            "set_flag": {
                "target_player_id": "player_id",
                "flag": "string",
                "value": "JSON value",
                "duration": "live|turn|game",
            },
            "clear_flag": {"target_player_id": "player_id", "flag": "string"},
        },
    }


def player_context(state: MatchState, player_id: str, *, include_private: bool) -> dict[str, Any]:
    player = state.players[player_id]
    return {
        "player_id": player.player_id,
        "name": player.name,
        "main_deck_count": len(player.main_deck),
        "energy_deck_count": len(player.energy_deck),
        "hand": zone_cards(state, player.hand) if include_private else {"count": len(player.hand)},
        "member_area": {
            slot: card_context(state.cards[instance_id]) if instance_id else None
            for slot, instance_id in player.member_area.items()
        },
        "member_area_attachments": {
            slot: zone_cards(state, instance_ids)
            for slot, instance_ids in player.member_area_attachments.items()
        },
        "energy_area": zone_cards(state, player.energy_area),
        "live_area": zone_cards(state, player.live_area),
        "waiting_room": zone_cards(state, player.waiting_room),
        "resolution_area": zone_cards(state, player.resolution_area),
        "success_live_area": zone_cards(state, player.success_live_area),
        "manual_modifiers": [modifier.model_dump() for modifier in player.manual_modifiers],
    }


def zone_cards(state: MatchState, instance_ids: list[str]) -> list[dict[str, Any]]:
    return [
        card_context(state.cards[instance_id])
        for instance_id in instance_ids
        if instance_id in state.cards
    ]


def card_context(instance: CardInstance) -> dict[str, Any]:
    card = instance.card
    return {
        "instance_id": instance.instance_id,
        "owner_id": instance.owner_id,
        "orientation": instance.orientation,
        "face_up": instance.face_up,
        "card_code": card.card_code,
        "card_id": card.card_id,
        "name_ja": card.name_ja,
        "card_type": card.card_type,
        "cost": card.cost,
        "blade": card.blade,
        "score": card.score,
        "basic_hearts": card.basic_hearts,
        "required_hearts": card.required_hearts,
        "work_keys": card.work_keys,
        "unit_keys": card.unit_keys,
        "raw_effect_text_ja": card.raw_effect_text_ja,
    }


def has_manual_resolution_action(legal_actions: list[LegalAction]) -> bool:
    for action in legal_actions:
        if action.action_type == "manual_adjustment" and action.options.get("source_invocations"):
            return True
    return False


def coerce_skip_decision(
    decision: SemanticDecision,
    legal_actions: list[LegalAction],
    invocation: dict[str, Any],
) -> SemanticDecision | None:
    if not any(action.action_type == "skip_effect" for action in legal_actions):
        return None
    invocation_id = decision.payload.get("invocation_id") or invocation.get("invocation_id")
    if not invocation_id:
        return None
    skip_action = next(action for action in legal_actions if action.action_type == "skip_effect")
    return SemanticDecision(
        decision="submit_action",
        reason_ja_or_zh=decision.reason_ja_or_zh,
        action_type="skip_effect",
        player_id=skip_action.player_id,
        payload={
            "invocation_id": invocation_id,
            "reason": decision.reason_ja_or_zh or "semantic agent requested skip",
            "error_message": decision.schema_gap or "semantic agent skipped effect",
        },
        confidence=decision.confidence,
        schema_gap=decision.schema_gap,
    )


def fallback_skip_decision(
    legal_actions: list[LegalAction],
    context: dict[str, Any],
) -> SemanticDecision | None:
    invocation = context.get("manual_invocation") or {}
    return coerce_skip_decision(
        SemanticDecision(
            decision="skip_effect",
            reason_ja_or_zh="semantic fallback skipped unresolved manual effect",
            payload={"invocation_id": invocation.get("invocation_id")},
            confidence="low",
            schema_gap="semantic_agent_unresolved",
        ),
        legal_actions,
        invocation,
    )


def attempt_from_decision(
    match_index: int,
    action_index: int,
    attempt_index: int,
    status: str,
    state: MatchState,
    invocation: dict[str, Any],
    decision: SemanticDecision,
    *,
    error: str | None = None,
) -> SemanticAttempt:
    source_instance_id = invocation.get("source_card_instance_id")
    source_card = state.cards.get(str(source_instance_id)) if source_instance_id else None
    return SemanticAttempt(
        match_index=match_index,
        action_index=action_index,
        attempt_index=attempt_index,
        status=status,
        effect_id=invocation.get("effect_id"),
        invocation_id=invocation.get("invocation_id"),
        source_card_instance_id=source_instance_id,
        source_card_code=source_card.card.card_code if source_card else None,
        source_card_name_ja=source_card.card.name_ja if source_card else None,
        label_ja=invocation.get("label_ja"),
        agent_reason=decision.reason_ja_or_zh,
        decision=decision.decision,
        action_type=decision.action_type,
        confidence=decision.confidence,
        schema_gap=decision.schema_gap,
        submitted_payload=decision.payload,
        error=error,
    )


def api_play_attempt_from_decision(
    match_index: int,
    action_index: int,
    state: MatchState,
    legal_actions: list[LegalAction],
    decision: SemanticDecision,
    *,
    status: str,
    error: str | None = None,
) -> ApiPlayAttempt:
    return ApiPlayAttempt(
        match_index=match_index,
        action_index=action_index,
        status=status,
        phase=state.phase,
        legal_action_types=sorted({action.action_type for action in legal_actions}),
        agent_reason=decision.reason_ja_or_zh,
        decision=decision.decision,
        action_type=decision.action_type,
        player_id=decision.player_id,
        confidence=decision.confidence,
        schema_gap=decision.schema_gap,
        submitted_payload=decision.payload,
        error=error,
    )


def classify_semantic_blocker(state: MatchState, legal_actions: list[LegalAction]) -> str:
    if has_manual_resolution_action(legal_actions):
        return "mandatory_manual_resolution"
    if state.pending_effects:
        return "pending_effect_without_policy"
    if state.pending_choice is not None:
        return f"unhandled_pending_choice:{state.pending_choice.choice_type}"
    return "no_legal_action"


def write_semantic_outputs(
    output: Path,
    *,
    provider: SemanticAgentProvider,
    deck_summaries: list[SandboxDeckSummary],
    match_summaries: list[SemanticMatchSummary],
    attempts: list[SemanticAttempt],
    api_play_attempts: list[ApiPlayAttempt] | None = None,
) -> None:
    api_play_attempts = api_play_attempts or []
    output.mkdir(parents=True, exist_ok=True)
    completed = sum(item.status == "completed" for item in match_summaries)
    blockers = Counter(item.blocker or "none" for item in match_summaries)
    attempt_statuses = Counter(item.status for item in attempts)
    api_play_statuses = Counter(item.status for item in api_play_attempts)
    schema_gaps = Counter(item.schema_gap for item in attempts if item.schema_gap)
    api_play_schema_gaps = Counter(item.schema_gap for item in api_play_attempts if item.schema_gap)
    payload = {
        "schema_version": SEMANTIC_SCHEMA_VERSION,
        "provider": provider.provider_name,
        "deck_summaries": [asdict(item) for item in deck_summaries],
        "match_summaries": [asdict(item) for item in match_summaries],
        "semantic_attempts": [asdict(item) for item in attempts],
        "api_play_attempts": [asdict(item) for item in api_play_attempts],
    }
    (output / "semantic-summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# Semantic User-Agent Sandbox Report",
        "",
        "## Scope",
        "",
        "* Default mode drives ordinary actions with the deterministic sandbox policy.",
        "* Optional API Play mode asks the same provider to choose ordinary LegalActions.",
        "* Mandatory manual-resolution effects still use the dedicated semantic flow.",
        "* All submitted changes still go through LegalAction and engine validation.",
        "* Agent success is a manual-playability signal, not effect-registry coverage.",
        "",
        "## Summary",
        "",
        f"* Provider: `{provider.provider_name}`",
        f"* Decks summarized: {len(deck_summaries)}",
        f"* Matches attempted: {len(match_summaries)}",
        f"* Matches completed: {completed}",
        f"* Blockers: {dict(sorted(blockers.items()))}",
        f"* Semantic attempt statuses: {dict(sorted(attempt_statuses.items()))}",
        f"* API Play attempt statuses: {dict(sorted(api_play_statuses.items()))}",
        f"* Schema gaps: {dict(schema_gaps.most_common(20))}",
        f"* API Play schema gaps: {dict(api_play_schema_gaps.most_common(20))}",
        "",
        "## Match Results",
        "",
        (
            "| # | Status | Decks | Phase | Turn | Actions | Manual | Agent OK | "
            "Agent Fail | Skips | API Play | API Fail | Fallback | Gaps | Blocker |"
        ),
        "|---:|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for item in match_summaries:
        lines.append(
            f"| {item.match_index} | {item.status} | {item.first_deck} vs {item.second_deck} | "
            f"{item.final_phase} | {item.turn_number} | {item.action_count} | "
            f"{item.manual_effect_count} | {item.agent_success_count} | "
            f"{item.agent_failure_count} | {item.agent_skip_count} | "
            f"{item.api_play_count} | {item.api_play_failure_count} | "
            f"{item.deterministic_fallback_count} | "
            f"{item.schema_gap_count} | {item.blocker or ''} |"
        )
    if api_play_attempts:
        lines.extend(
            [
                "",
                "## API Play Attempts",
                "",
                "| Match | Action | Status | Phase | Action | Confidence | Fallback | Gap | Reason / Error |",
                "|---:|---:|---|---|---|---|---|---|---|",
            ]
        )
        for item in api_play_attempts:
            reason = item.error or item.agent_reason
            lines.append(
                f"| {item.match_index} | {item.action_index} | {item.status} | "
                f"{item.phase} | {item.action_type or ''} | {item.confidence} | "
                f"{'yes' if item.fallback_used else ''} | "
                f"{_markdown_cell(item.schema_gap or '')} | {_markdown_cell(reason)} |"
            )
    if attempts:
        lines.extend(
            [
                "",
                "## Semantic Attempts",
                "",
                "| Match | Action | Status | Effect | Source | Confidence | Gap | Reason / Error |",
                "|---:|---:|---|---|---|---|---|---|",
            ]
        )
        for item in attempts:
            reason = item.error or item.agent_reason
            lines.append(
                f"| {item.match_index} | {item.action_index} | {item.status} | "
                f"{item.effect_id or ''} | {item.source_card_code or ''} "
                f"{_markdown_cell(item.source_card_name_ja or '')} | "
                f"{item.confidence} | {_markdown_cell(item.schema_gap or '')} | "
                f"{_markdown_cell(reason)} |"
            )
    (output / "semantic-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _markdown_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", "<br>")


if __name__ == "__main__":
    raise SystemExit(main())
