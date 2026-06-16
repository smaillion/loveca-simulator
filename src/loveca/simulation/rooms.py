"""Temporary hosted room coordination for low-cost online playtesting."""

from __future__ import annotations

import json
import secrets
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from loveca.decks.analyzer import DeckList, parse_deck
from loveca.simulation.engine import generate_legal_actions
from loveca.simulation.models import ActionRequest, ActionResult
from loveca.simulation.service import MatchService

ROOM_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
ROOM_CODE_LENGTH = 6

ROOM_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS hosted_rooms (
    room_code TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    host_token TEXT NOT NULL,
    guest_token TEXT,
    host_name TEXT NOT NULL,
    guest_name TEXT,
    host_deck_json TEXT NOT NULL,
    guest_deck_json TEXT,
    seed INTEGER,
    match_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    host_last_seen_at TEXT,
    guest_last_seen_at TEXT,
    closed_at TEXT,
    close_reason TEXT,
    CHECK (status IN ('waiting_for_guest', 'active', 'expired'))
);

CREATE INDEX IF NOT EXISTS idx_hosted_rooms_expires
    ON hosted_rooms(expires_at);
"""

ROOM_OPTIONAL_COLUMNS = {
    "host_last_seen_at": "TEXT",
    "guest_last_seen_at": "TEXT",
    "closed_at": "TEXT",
    "close_reason": "TEXT",
}


class RoomError(RuntimeError):
    """Base room coordination error."""


class RoomNotFoundError(RoomError):
    """Raised when a room code does not exist."""


class RoomTokenError(RoomError):
    """Raised when a player token is missing or does not match the room."""


class RoomStateError(RoomError):
    """Raised when the requested room operation is not valid for the state."""


@dataclass(frozen=True)
class RoomRecord:
    room_code: str
    status: str
    host_token: str
    guest_token: str | None
    host_name: str
    guest_name: str | None
    host_deck_json: str
    guest_deck_json: str | None
    seed: int | None
    match_id: str | None
    created_at: str
    updated_at: str
    expires_at: str
    host_last_seen_at: str | None
    guest_last_seen_at: str | None
    closed_at: str | None
    close_reason: str | None

    @property
    def host_deck(self) -> DeckList:
        return parse_deck(json.loads(self.host_deck_json))

    @property
    def guest_deck(self) -> DeckList:
        if self.guest_deck_json is None:
            raise RoomStateError("guest deck is not available")
        return parse_deck(json.loads(self.guest_deck_json))


class RoomRepository:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            connection.executescript(ROOM_SCHEMA_SQL)
            _ensure_optional_room_columns(connection)
            connection.commit()

    def create_room(
        self,
        *,
        host_name: str,
        host_deck: dict[str, Any],
        seed: int | None,
        ttl_hours: int,
    ) -> RoomRecord:
        now = _utc_now()
        expires_at = _utc_after_hours(ttl_hours)
        # Validate before persisting so malformed decks do not become rooms.
        parse_deck(host_deck)
        for _ in range(8):
            room_code = _new_room_code()
            token = secrets.token_urlsafe(24)
            try:
                with closing(self._connect()) as connection:
                    connection.execute(
                        """
                        INSERT INTO hosted_rooms (
                            room_code, status, host_token, host_name, host_deck_json,
                            seed, created_at, updated_at, expires_at, host_last_seen_at
                        )
                        VALUES (?, 'waiting_for_guest', ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            room_code,
                            token,
                            host_name,
                            _json(host_deck),
                            seed,
                            now,
                            now,
                            expires_at,
                            now,
                        ),
                    )
                    connection.commit()
                return self.get_room(room_code)
            except sqlite3.IntegrityError:
                continue
        raise RoomStateError("failed to allocate a unique room code")

    def get_room(self, room_code: str) -> RoomRecord:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM hosted_rooms WHERE room_code = ?",
                (room_code.upper(),),
            ).fetchone()
        if row is None:
            raise RoomNotFoundError(f"room not found: {room_code}")
        record = _record_from_row(row)
        if record.status != "expired" and _is_expired(record.expires_at):
            return self.expire_room(record.room_code)
        return record

    def expire_room(self, room_code: str, *, close_reason: str = "expired") -> RoomRecord:
        now = _utc_now()
        with closing(self._connect()) as connection:
            connection.execute(
                """
                UPDATE hosted_rooms
                SET status = 'expired',
                    updated_at = ?,
                    closed_at = COALESCE(closed_at, ?),
                    close_reason = COALESCE(close_reason, ?)
                WHERE room_code = ?
                """,
                (now, now, close_reason, room_code.upper()),
            )
            connection.commit()
        return self.get_room(room_code)

    def join_room(
        self,
        *,
        room_code: str,
        guest_name: str,
        guest_deck: dict[str, Any],
        match_id: str,
        ttl_hours: int,
    ) -> RoomRecord:
        parse_deck(guest_deck)
        record = self.get_room(room_code)
        if record.status == "expired":
            raise RoomStateError("room has expired")
        if record.status != "waiting_for_guest":
            raise RoomStateError("room is not waiting for a guest")
        now = _utc_now()
        guest_token = secrets.token_urlsafe(24)
        with closing(self._connect()) as connection:
            connection.execute(
                """
                UPDATE hosted_rooms
                SET status = 'active',
                    guest_token = ?,
                    guest_name = ?,
                    guest_deck_json = ?,
                    match_id = ?,
                    updated_at = ?,
                    guest_last_seen_at = ?,
                    expires_at = ?
                WHERE room_code = ? AND status = 'waiting_for_guest'
                """,
                (
                    guest_token,
                    guest_name,
                    _json(guest_deck),
                    match_id,
                    now,
                    now,
                    _utc_after_hours(ttl_hours),
                    record.room_code,
                ),
            )
            connection.commit()
        return self.get_room(room_code)

    def touch_room(
        self,
        room_code: str,
        *,
        player_id: str | None = None,
        ttl_hours: int | None = None,
    ) -> None:
        now = _utc_now()
        expires_at = _utc_after_hours(ttl_hours) if ttl_hours is not None else None
        updates = ["updated_at = ?"]
        values: list[Any] = [now]
        if expires_at is not None:
            updates.append("expires_at = ?")
            values.append(expires_at)
        if player_id == "player_1":
            updates.append("host_last_seen_at = ?")
            values.append(now)
        elif player_id == "player_2":
            updates.append("guest_last_seen_at = ?")
            values.append(now)
        values.append(room_code.upper())
        with closing(self._connect()) as connection:
            connection.execute(
                f"""
                UPDATE hosted_rooms
                SET {", ".join(updates)}
                WHERE room_code = ? AND status != 'expired'
                """,
                tuple(values),
            )
            connection.commit()

    def cleanup_expired(self, *, delete_grace_hours: int) -> CleanupResult:
        now = _utc_now()
        delete_before = _utc_before_hours(delete_grace_hours)
        with closing(self._connect()) as connection:
            expired_cursor = connection.execute(
                """
                UPDATE hosted_rooms
                SET status = 'expired',
                    updated_at = ?,
                    closed_at = COALESCE(closed_at, ?),
                    close_reason = COALESCE(close_reason, 'ttl_expired')
                WHERE status != 'expired' AND expires_at <= ?
                """,
                (now, now, now),
            )
            connection.execute(
                """
                UPDATE hosted_rooms
                SET closed_at = COALESCE(closed_at, updated_at, expires_at),
                    close_reason = COALESCE(close_reason, 'legacy_expired')
                WHERE status = 'expired'
                """
            )
            deleted_cursor = connection.execute(
                """
                DELETE FROM hosted_rooms
                WHERE status = 'expired' AND closed_at <= ?
                """,
                (delete_before,),
            )
            connection.commit()
            return CleanupResult(
                expired_count=int(expired_cursor.rowcount),
                deleted_count=int(deleted_cursor.rowcount),
            )

    def active_match_ids(self) -> set[str]:
        now = _utc_now()
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT match_id
                FROM hosted_rooms
                WHERE match_id IS NOT NULL
                  AND status != 'expired'
                  AND expires_at > ?
                """,
                (now,),
            ).fetchall()
        return {str(row["match_id"]) for row in rows}

    def match_is_active_room_match(self, match_id: str) -> bool:
        now = _utc_now()
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT 1
                FROM hosted_rooms
                WHERE match_id = ?
                  AND status != 'expired'
                  AND expires_at > ?
                LIMIT 1
                """,
                (match_id, now),
            ).fetchone()
        return row is not None

    def validate_token(self, record: RoomRecord, token: str) -> str:
        if secrets.compare_digest(token, record.host_token):
            return "player_1"
        if record.guest_token and secrets.compare_digest(token, record.guest_token):
            return "player_2"
        raise RoomTokenError("invalid room player token")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection


class RoomService:
    def __init__(
        self,
        match_service: MatchService,
        runtime_database_path: Path,
        *,
        ttl_hours: int = 24,
        delete_grace_hours: int = 1,
    ) -> None:
        if ttl_hours < 1:
            raise ValueError("ttl_hours must be at least 1")
        if delete_grace_hours < 1:
            raise ValueError("delete_grace_hours must be at least 1")
        self.match_service = match_service
        self.repository = RoomRepository(runtime_database_path)
        self.ttl_hours = ttl_hours
        self.delete_grace_hours = delete_grace_hours

    def create_room(
        self,
        *,
        host_name: str,
        host_deck: dict[str, Any],
        seed: int | None,
    ) -> RoomRecord:
        self.cleanup_expired()
        return self.repository.create_room(
            host_name=host_name,
            host_deck=host_deck,
            seed=seed,
            ttl_hours=self.ttl_hours,
        )

    def join_room(
        self,
        *,
        room_code: str,
        guest_name: str,
        guest_deck: dict[str, Any],
    ) -> RoomRecord:
        record = self.repository.get_room(room_code)
        result = self.match_service.create_match(
            first_name=record.host_name,
            first_deck=record.host_deck,
            second_name=guest_name,
            second_deck=parse_deck(guest_deck),
            seed=record.seed,
        )
        joined = self.repository.join_room(
            room_code=record.room_code,
            guest_name=guest_name,
            guest_deck=guest_deck,
            match_id=result.state.match_id,
            ttl_hours=self.ttl_hours,
        )
        self.repository.touch_room(joined.room_code, player_id="player_2", ttl_hours=self.ttl_hours)
        return joined

    def get_room_for_player(
        self,
        room_code: str,
        token: str | None,
    ) -> tuple[RoomRecord, str | None]:
        record = self.repository.get_room(room_code)
        if token is None:
            return record, None
        player_id = self.repository.validate_token(record, token)
        if record.status != "expired":
            self.repository.touch_room(record.room_code, player_id=player_id, ttl_hours=self.ttl_hours)
            record = self.repository.get_room(record.room_code)
        return record, player_id

    def leave_room(self, *, room_code: str, token: str) -> RoomRecord:
        record = self.repository.get_room(room_code)
        self.repository.validate_token(record, token)
        return self.repository.expire_room(record.room_code, close_reason="player_left")

    def apply_action(
        self,
        *,
        room_code: str,
        token: str,
        action: ActionRequest,
    ) -> ActionResult:
        record = self.repository.get_room(room_code)
        player_id = self.repository.validate_token(record, token)
        if record.status != "active" or record.match_id is None:
            raise RoomStateError("room does not have an active match")
        if action.player_id is not None and action.player_id != player_id:
            raise RoomTokenError("action player_id does not match the room token")
        state = self.match_service.repository.get_state(record.match_id)
        matching_actions = [
            legal_action
            for legal_action in generate_legal_actions(state)
            if legal_action.action_type == action.action_type
        ]
        if matching_actions:
            allowed_player_ids = {legal_action.player_id for legal_action in matching_actions}
            if None not in allowed_player_ids and player_id not in allowed_player_ids:
                raise RoomTokenError("room token cannot submit this player's action")
            if action.player_id is None and None not in allowed_player_ids:
                raise RoomTokenError("action player_id is required for this room action")
        result = self.match_service.apply(record.match_id, action)
        self.repository.touch_room(record.room_code, player_id=player_id, ttl_hours=self.ttl_hours)
        return result

    def cleanup_expired(self) -> CleanupResult:
        return self.repository.cleanup_expired(delete_grace_hours=self.delete_grace_hours)


@dataclass(frozen=True)
class CleanupResult:
    expired_count: int
    deleted_count: int


def _record_from_row(row: sqlite3.Row) -> RoomRecord:
    return RoomRecord(
        room_code=str(row["room_code"]),
        status=str(row["status"]),
        host_token=str(row["host_token"]),
        guest_token=row["guest_token"],
        host_name=str(row["host_name"]),
        guest_name=row["guest_name"],
        host_deck_json=str(row["host_deck_json"]),
        guest_deck_json=row["guest_deck_json"],
        seed=row["seed"],
        match_id=row["match_id"],
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        expires_at=str(row["expires_at"]),
        host_last_seen_at=row["host_last_seen_at"],
        guest_last_seen_at=row["guest_last_seen_at"],
        closed_at=row["closed_at"],
        close_reason=row["close_reason"],
    )


def _new_room_code() -> str:
    return "".join(secrets.choice(ROOM_CODE_ALPHABET) for _ in range(ROOM_CODE_LENGTH))


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _utc_after_hours(hours: int) -> str:
    return (datetime.now(UTC) + timedelta(hours=hours)).isoformat(timespec="seconds")


def _utc_before_hours(hours: int) -> str:
    return (datetime.now(UTC) - timedelta(hours=hours)).isoformat(timespec="seconds")


def _is_expired(value: str) -> bool:
    return datetime.fromisoformat(value) <= datetime.now(UTC)


def _ensure_optional_room_columns(connection: sqlite3.Connection) -> None:
    columns = {
        str(row["name"])
        for row in connection.execute("PRAGMA table_info(hosted_rooms)").fetchall()
    }
    for name, declaration in ROOM_OPTIONAL_COLUMNS.items():
        if name not in columns:
            connection.execute(
                f"ALTER TABLE hosted_rooms ADD COLUMN {name} {declaration}"
            )
