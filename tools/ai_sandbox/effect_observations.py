"""Offline event counts; never copy card identities or decision payloads."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

METRICS = ("triggered", "optional_declined", "error_skipped", "manual_blocked")
EVENT_METRICS = {
    "effect_triggered": "triggered",
    "effect_declined": "optional_declined",
    "effect_skipped_due_to_error": "error_skipped",
}


def observe_effects(
    events: Iterable[dict[str, Any]], blocked: Iterable[dict[str, Any]] = ()
) -> dict[str, dict[str, int]]:
    rows = list(events)
    if any(not isinstance(event, dict) for event in rows):
        raise ValueError("events must be objects")
    invocations = {
        e["data"]["invocation_id"]: e["data"]["effect_id"]
        for e in rows
        if isinstance(e.get("data"), dict)
        and isinstance(e["data"].get("invocation_id"), str)
        and isinstance(e["data"].get("effect_id"), str)
    }
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    seen: set[tuple[str, str, object]] = set()
    for index, event in enumerate(rows):
        metric = EVENT_METRICS.get(event.get("event_type"))
        data = event.get("data", {})
        if metric is None or not isinstance(data, dict):
            continue
        if data.get("invocation_id") is not None and not isinstance(data["invocation_id"], str):
            raise ValueError("invocation IDs must be strings")
        effect_id = data.get("effect_id") or invocations.get(data.get("invocation_id"))
        if not isinstance(effect_id, str):
            raise ValueError("effect event requires an effect ID or a known invocation")
        key = (effect_id, metric, data.get("invocation_id") or ("event", index))
        if key not in seen:
            counts[effect_id][metric] += 1
            seen.add(key)
    for index, invocation in enumerate(blocked):
        effect_id = invocation.get("effect_id")
        if not isinstance(effect_id, str):
            continue
        key = (effect_id, "manual_blocked", invocation.get("invocation_id") or ("blocker", index))
        if key not in seen:
            counts[effect_id]["manual_blocked"] += 1
            seen.add(key)
    return {
        key: {metric: value[metric] for metric in METRICS} for key, value in sorted(counts.items())
    }


def merge_observations(items: Iterable[dict[str, dict[str, int]]]) -> dict[str, dict[str, int]]:
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    for item in items:
        for effect_id, metrics in item.items():
            if not isinstance(effect_id, str) or not isinstance(metrics, dict):
                raise ValueError("effect observations require effect ID objects")
            for metric, count in metrics.items():
                if metric not in METRICS or type(count) is not int or count < 0:
                    raise ValueError("invalid effect observation metric/count")
                counts[effect_id][metric] += count
    return {
        key: {metric: value[metric] for metric in METRICS} for key, value in sorted(counts.items())
    }


def load_observations(paths: list[Path]) -> dict[str, dict[str, int]]:
    items = []
    seen_paths: set[Path] = set()
    for path in paths:
        resolved = path.resolve()
        if resolved in seen_paths:
            raise ValueError("duplicate observation input path")
        seen_paths.add(resolved)
        payloads = (
            [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            if path.suffix == ".jsonl"
            else [json.loads(path.read_text(encoding="utf-8"))]
        )
        for payload in payloads:
            matches = (
                payload if isinstance(payload, list) else payload.get("match_summaries", [payload])
            )
            for match in matches:
                if "effect_observations" in match:
                    items.append(match["effect_observations"])
                elif isinstance(match.get("actions"), list):
                    events = [e for action in match["actions"] for e in action.get("events", [])]
                    items.append(observe_effects(events))
                else:
                    raise ValueError(
                        f"{path}: no event observations; legacy skipped counts are not triggers"
                    )
    return merge_observations(items)


def diagnostic_source_fingerprint(root: Path) -> str:
    paths = [
        *root.glob("src/**/*.py"),
        *root.glob("tools/ai_sandbox/*.py"),
        root / "data/loveca.sqlite3",
        root / "data/loveca-db-manifest.json",
        root / "data_sources/effect-registry.v0.json",
    ]
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()
