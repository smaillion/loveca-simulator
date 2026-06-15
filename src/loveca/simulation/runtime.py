"""Versioned SQLite persistence for local match execution and replay."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loveca.simulation.engine import apply_action, generate_legal_actions
from loveca.simulation.models import (
    MATCH_RUNTIME_SCHEMA_VERSION,
    ActionRequest,
    ActionResult,
    GameEvent,
    MatchState,
)

RUNTIME_SCHEMA_SQL = f"""
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS runtime_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

INSERT OR IGNORE INTO runtime_metadata (key, value)
VALUES ('schema_version', '{MATCH_RUNTIME_SCHEMA_VERSION}');

CREATE TABLE IF NOT EXISTS matches (
    match_id TEXT PRIMARY KEY,
    card_database_path TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    seed INTEGER NOT NULL,
    status TEXT NOT NULL,
    revision INTEGER NOT NULL,
    initial_state_json TEXT NOT NULL,
    current_state_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (status IN ('active', 'complete'))
);

CREATE TABLE IF NOT EXISTS match_actions (
    id INTEGER PRIMARY KEY,
    match_id TEXT NOT NULL REFERENCES matches(match_id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL,
    action_id TEXT NOT NULL,
    action_type TEXT NOT NULL,
    player_id TEXT,
    payload_json TEXT NOT NULL,
    expected_revision INTEGER NOT NULL,
    result_revision INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (match_id, sequence),
    UNIQUE (match_id, action_id)
);

CREATE TABLE IF NOT EXISTS match_events (
    id INTEGER PRIMARY KEY,
    match_id TEXT NOT NULL REFERENCES matches(match_id) ON DELETE CASCADE,
    action_sequence INTEGER NOT NULL,
    event_index INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    event_json TEXT NOT NULL,
    UNIQUE (match_id, action_sequence, event_index)
);

CREATE TABLE IF NOT EXISTS match_snapshots (
    match_id TEXT NOT NULL REFERENCES matches(match_id) ON DELETE CASCADE,
    revision INTEGER NOT NULL,
    action_sequence INTEGER NOT NULL,
    state_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (match_id, revision)
);

CREATE INDEX IF NOT EXISTS idx_match_actions_match
    ON match_actions(match_id, sequence);
CREATE INDEX IF NOT EXISTS idx_match_events_match
    ON match_events(match_id, action_sequence, event_index);

PRAGMA user_version = {MATCH_RUNTIME_SCHEMA_VERSION};
"""


class MatchRuntimeError(RuntimeError):
    """Base error for runtime persistence failures."""


class MatchNotFoundError(MatchRuntimeError):
    """Raised when a requested match does not exist."""


class RuntimeSchemaError(MatchRuntimeError):
    """Raised when a runtime database has an unsupported layout."""


def initialize_runtime_database(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(_connect(path)) as connection:
        tables = {
            str(row[0])
            for row in connection.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                """
            )
        }
        if tables and "runtime_metadata" not in tables:
            raise RuntimeSchemaError("unversioned runtime database is not supported")
        if "runtime_metadata" in tables:
            row = connection.execute(
                "SELECT value FROM runtime_metadata WHERE key = 'schema_version'"
            ).fetchone()
            if row is None or int(row[0]) != MATCH_RUNTIME_SCHEMA_VERSION:
                found = "missing" if row is None else str(row[0])
                raise RuntimeSchemaError(
                    "unsupported runtime database schema version "
                    f"{found}; expected {MATCH_RUNTIME_SCHEMA_VERSION}. "
                    "Delete the disposable local runtime database and restart."
                )
        connection.executescript(RUNTIME_SCHEMA_SQL)


class MatchRepository:
    def __init__(self, path: Path) -> None:
        self.path = path
        initialize_runtime_database(path)

    def create_match(
        self,
        state: MatchState,
        *,
        card_database_path: Path,
    ) -> ActionResult:
        now = _utc_now()
        state_json = state.model_dump_json()
        with closing(_connect(self.path)) as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """
                    INSERT INTO matches (
                        match_id,
                        card_database_path,
                        rule_version,
                        seed,
                        status,
                        revision,
                        initial_state_json,
                        current_state_json,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, 'active', ?, ?, ?, ?, ?)
                    """,
                    (
                        state.match_id,
                        str(card_database_path.resolve()),
                        state.rule_version,
                        state.seed,
                        state.revision,
                        state_json,
                        state_json,
                        now,
                        now,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO match_snapshots (
                        match_id,
                        revision,
                        action_sequence,
                        state_json,
                        created_at
                    )
                    VALUES (?, ?, 0, ?, ?)
                    """,
                    (state.match_id, state.revision, state_json, now),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return ActionResult(
            state=state,
            events=[],
            legal_actions=generate_legal_actions(state),
        )

    def list_matches(self) -> list[dict[str, Any]]:
        with closing(_connect(self.path)) as connection:
            rows = connection.execute(
                """
                SELECT match_id, rule_version, seed, status, revision, created_at, updated_at
                FROM matches
                ORDER BY updated_at DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def get_state(self, match_id: str) -> MatchState:
        with closing(_connect(self.path)) as connection:
            row = connection.execute(
                "SELECT current_state_json FROM matches WHERE match_id = ?",
                (match_id,),
            ).fetchone()
        if row is None:
            raise MatchNotFoundError(f"match not found: {match_id}")
        return MatchState.model_validate_json(row["current_state_json"])

    def list_events(self, match_id: str) -> list[GameEvent]:
        with closing(_connect(self.path)) as connection:
            exists = connection.execute(
                "SELECT 1 FROM matches WHERE match_id = ?",
                (match_id,),
            ).fetchone()
            if exists is None:
                raise MatchNotFoundError(f"match not found: {match_id}")
            rows = connection.execute(
                """
                SELECT event_json
                FROM match_events
                WHERE match_id = ?
                ORDER BY action_sequence, event_index
                """,
                (match_id,),
            ).fetchall()
        return [GameEvent.model_validate_json(row["event_json"]) for row in rows]

    def apply(self, match_id: str, action: ActionRequest) -> ActionResult:
        now = _utc_now()
        action_id = action.action_id or str(uuid.uuid4())
        persisted_action = action.model_copy(update={"action_id": action_id})
        with closing(_connect(self.path)) as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT current_state_json FROM matches WHERE match_id = ?",
                    (match_id,),
                ).fetchone()
                if row is None:
                    raise MatchNotFoundError(f"match not found: {match_id}")
                state = MatchState.model_validate_json(row["current_state_json"])
                result = apply_action(state, persisted_action)
                sequence = int(
                    connection.execute(
                        """
                        SELECT COALESCE(MAX(sequence), 0) + 1
                        FROM match_actions
                        WHERE match_id = ?
                        """,
                        (match_id,),
                    ).fetchone()[0]
                )
                connection.execute(
                    """
                    INSERT INTO match_actions (
                        match_id,
                        sequence,
                        action_id,
                        action_type,
                        player_id,
                        payload_json,
                        expected_revision,
                        result_revision,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        match_id,
                        sequence,
                        action_id,
                        persisted_action.action_type,
                        persisted_action.player_id,
                        _json(persisted_action.payload),
                        persisted_action.expected_revision,
                        result.state.revision,
                        now,
                    ),
                )
                for event_index, event in enumerate(result.events):
                    connection.execute(
                        """
                        INSERT INTO match_events (
                            match_id,
                            action_sequence,
                            event_index,
                            event_type,
                            event_json
                        )
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            match_id,
                            sequence,
                            event_index,
                            event.event_type,
                            event.model_dump_json(),
                        ),
                    )
                state_json = result.state.model_dump_json()
                status = "complete" if result.state.phase == "complete" else "active"
                connection.execute(
                    """
                    UPDATE matches
                    SET status = ?,
                        revision = ?,
                        current_state_json = ?,
                        updated_at = ?
                    WHERE match_id = ?
                    """,
                    (status, result.state.revision, state_json, now, match_id),
                )
                connection.execute(
                    """
                    INSERT INTO match_snapshots (
                        match_id,
                        revision,
                        action_sequence,
                        state_json,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (match_id, result.state.revision, sequence, state_json, now),
                )
                connection.commit()
                return result
            except Exception:
                connection.rollback()
                raise

    def replay(self, match_id: str) -> dict[str, Any]:
        with closing(_connect(self.path)) as connection:
            match = connection.execute(
                """
                SELECT initial_state_json, current_state_json
                FROM matches
                WHERE match_id = ?
                """,
                (match_id,),
            ).fetchone()
            if match is None:
                raise MatchNotFoundError(f"match not found: {match_id}")
            action_rows = connection.execute(
                """
                SELECT action_id, action_type, player_id, payload_json,
                       expected_revision, result_revision
                FROM match_actions
                WHERE match_id = ?
                ORDER BY sequence
                """,
                (match_id,),
            ).fetchall()
            event_rows = connection.execute(
                """
                SELECT event_json
                FROM match_events
                WHERE match_id = ?
                ORDER BY action_sequence, event_index
                """,
                (match_id,),
            ).fetchall()

        initial = MatchState.model_validate_json(match["initial_state_json"])
        replay_state = initial
        actions: list[dict[str, Any]] = []
        for row in action_rows:
            action = ActionRequest(
                action_id=row["action_id"],
                action_type=row["action_type"],
                player_id=row["player_id"],
                payload=json.loads(row["payload_json"]),
                expected_revision=int(row["expected_revision"]),
            )
            replay_state = apply_action(replay_state, action).state
            actions.append(
                {
                    **action.model_dump(),
                    "result_revision": int(row["result_revision"]),
                }
            )
        expected = MatchState.model_validate_json(match["current_state_json"])
        if replay_state != expected:
            raise MatchRuntimeError("replayed state does not match persisted state")
        return {
            "initial_state": initial.model_dump(),
            "actions": actions,
            "events": [
                GameEvent.model_validate_json(row["event_json"]).model_dump()
                for row in event_rows
            ],
            "final_state": replay_state.model_dump(),
        }


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
