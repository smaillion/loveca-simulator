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
from loveca.simulation.online import (
    ONLINE_PROTOCOL_VERSION,
    card_database_fingerprint,
    match_state_hash,
)

DEFAULT_MATCH_HISTORY_LIMIT = 100
DEFAULT_MATCH_HISTORY_PAGE_SIZE = 10
MAX_RETAINED_MATCHES = DEFAULT_MATCH_HISTORY_LIMIT

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
    def __init__(self, path: Path, *, max_retained_matches: int = MAX_RETAINED_MATCHES) -> None:
        if max_retained_matches < 1:
            raise ValueError("max_retained_matches must be at least 1")
        self.path = path
        self.max_retained_matches = max_retained_matches
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

    def list_matches(
        self,
        *,
        page: int = 1,
        per_page: int = DEFAULT_MATCH_HISTORY_PAGE_SIZE,
        max_matches: int = DEFAULT_MATCH_HISTORY_LIMIT,
        exclude_match_ids: set[str] | None = None,
    ) -> dict[str, Any]:
        if page < 1:
            raise ValueError("page must be at least 1")
        if per_page < 1:
            raise ValueError("per_page must be at least 1")
        if max_matches < 1:
            raise ValueError("max_matches must be at least 1")
        offset = (page - 1) * per_page
        limit = min(per_page, max(0, max_matches - offset))
        exclusion_clause = ""
        exclusion_parameters: list[str] = []
        if exclude_match_ids:
            placeholders = ", ".join("?" for _ in exclude_match_ids)
            exclusion_clause = f"WHERE match_id NOT IN ({placeholders})"
            exclusion_parameters = sorted(exclude_match_ids)
        with closing(_connect(self.path)) as connection:
            rows = []
            if limit > 0:
                rows = connection.execute(
                    f"""
                    SELECT match_id, rule_version, seed, status, revision, created_at, updated_at
                    FROM matches
                    {exclusion_clause}
                    ORDER BY updated_at DESC, created_at DESC, match_id DESC
                    LIMIT ? OFFSET ?
                    """,
                    (*exclusion_parameters, limit, offset),
                ).fetchall()
            total = int(
                connection.execute(
                    f"""
                    SELECT COUNT(*)
                    FROM (
                        SELECT match_id
                        FROM matches
                        {exclusion_clause}
                        ORDER BY updated_at DESC, created_at DESC, match_id DESC
                        LIMIT ?
                    )
                    """,
                    (*exclusion_parameters, max_matches),
                ).fetchone()[0]
            )
        return {
            "items": [dict(row) for row in rows],
            "page": page,
            "per_page": per_page,
            "total": total,
            "max_total": max_matches,
        }

    def prune_old_matches(self, max_matches: int | None = None) -> int:
        limit = self.max_retained_matches if max_matches is None else max_matches
        if limit < 1:
            raise ValueError("max_matches must be at least 1")
        with closing(_connect(self.path)) as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                deleted = _prune_old_matches(connection, limit)
                connection.commit()
                return deleted
            except Exception:
                connection.rollback()
                raise

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
                SELECT initial_state_json, current_state_json, card_database_path
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
        card_database_path = Path(str(match["card_database_path"]))
        try:
            card_fingerprint = card_database_fingerprint(card_database_path)
        except Exception:
            card_fingerprint = None
        return {
            "metadata": {
                "protocol_version": ONLINE_PROTOCOL_VERSION,
                "rule_version": replay_state.rule_version,
                "card_database_fingerprint": card_fingerprint,
                "effect_registry_version": replay_state.effect_registry_version,
                "initial_state_hash": match_state_hash(initial),
                "final_state_hash": match_state_hash(replay_state),
            },
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


def _prune_old_matches(connection: sqlite3.Connection, max_matches: int) -> int:
    protected_match_ids: list[str] = []
    if _table_exists(connection, "hosted_rooms"):
        protected_match_ids = [
            str(row["match_id"])
            for row in connection.execute(
                """
                SELECT match_id
                FROM hosted_rooms
                WHERE match_id IS NOT NULL AND status != 'expired'
                """
            ).fetchall()
        ]
    protected_clause = ""
    parameters: list[Any] = []
    if protected_match_ids:
        placeholders = ", ".join("?" for _ in protected_match_ids)
        protected_clause = f"AND match_id NOT IN ({placeholders})"
        parameters.extend(protected_match_ids)
    parameters.append(max_matches)
    rows = connection.execute(
        f"""
        SELECT match_id
        FROM matches
        WHERE status != 'active'
        {protected_clause}
        ORDER BY updated_at DESC, created_at DESC, match_id DESC
        LIMIT -1 OFFSET ?
        """,
        parameters,
    ).fetchall()
    stale_match_ids = [str(row["match_id"]) for row in rows]
    for match_id in stale_match_ids:
        connection.execute("DELETE FROM matches WHERE match_id = ?", (match_id,))
    return len(stale_match_ids)


def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
        is not None
    )


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
