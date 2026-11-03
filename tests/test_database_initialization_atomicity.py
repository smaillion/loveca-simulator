"""Schema creation is atomic without changing existing SQL or durability settings."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest

from loveca.db import bootstrap
from loveca.simulation import runtime


@pytest.fixture(params=["catalog", "runtime"])
def schema(request):
    if request.param == "catalog":
        return bootstrap, "SCHEMA_SQL", "initialize_database", "connect_database", "schema_metadata"
    return runtime, "RUNTIME_SCHEMA_SQL", "initialize_runtime_database", "_connect", "runtime_metadata"


def _snapshot(path):
    with closing(sqlite3.connect(path)) as connection:
        return (list(connection.iterdump()), connection.execute("PRAGMA user_version").fetchone()[0])


@pytest.mark.parametrize("existing", [False, True])
def test_failed_initialization_rolls_back_schema_and_version(tmp_path, monkeypatch, schema, existing):
    module, constant, initializer, _, _ = schema
    initialize = getattr(module, initializer)
    path = tmp_path / "failed.sqlite3"
    if existing:
        initialize(path)
        with closing(sqlite3.connect(path)) as connection:
            connection.execute("PRAGMA user_version = 777")
    before = _snapshot(path)
    monkeypatch.setattr(module, constant, getattr(module, constant) + "\nCREATE TABLE probe(value);\nINVALID SQL;")
    with pytest.raises(sqlite3.OperationalError):
        initialize(path)
    assert _snapshot(path) == before
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.rollback()


def test_initialization_matches_standalone_schema_and_preserves_settings(tmp_path, schema):
    module, constant, initializer, connector, _ = schema
    expected, actual = tmp_path / "expected.sqlite3", tmp_path / "actual.sqlite3"
    with closing(getattr(module, connector)(expected)) as connection:
        connection.executescript(getattr(module, constant))
    getattr(module, initializer)(actual)
    assert _snapshot(actual) == _snapshot(expected)
    getattr(module, initializer)(actual)
    assert _snapshot(actual) == _snapshot(expected)
    with closing(getattr(module, connector)(actual)) as connection:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA synchronous").fetchone()[0] == 2
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_exactly_one_transaction_per_initialization(tmp_path, monkeypatch, schema):
    module, _, initializer, connector, _ = schema
    original = getattr(module, connector)
    statements = []

    def connect(path):
        connection = original(path)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(module, connector, connect)
    path = tmp_path / "trace.sqlite3"
    for _ in range(2):
        statements.clear()
        getattr(module, initializer)(path)
        controls = [statement.strip().upper().rstrip(";") for statement in statements
                    if statement.strip().upper().startswith(("BEGIN", "COMMIT", "ROLLBACK"))]
        assert controls == ["BEGIN IMMEDIATE", "COMMIT"]


@pytest.mark.parametrize("version", [None, "1", "999", "invalid"])
def test_rejected_schema_is_unchanged(tmp_path, schema, version):
    module, _, initializer, _, metadata = schema
    path = tmp_path / "unsupported.sqlite3"
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(f"CREATE TABLE {metadata}(key TEXT PRIMARY KEY, value TEXT)")
        if version is not None:
            connection.execute(f"INSERT INTO {metadata} VALUES ('schema_version', ?)", (version,))
        connection.commit()
    before = path.read_bytes()
    with pytest.raises((bootstrap.DatabaseSchemaError, runtime.RuntimeSchemaError, ValueError)):
        getattr(module, initializer)(path)
    assert path.read_bytes() == before


def test_concurrent_initializers_produce_complete_schema(tmp_path, schema):
    module, constant, initializer, connector, _ = schema
    actual, expected = tmp_path / "shared.sqlite3", tmp_path / "expected.sqlite3"
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(getattr(module, initializer), [actual] * 4))
    with closing(getattr(module, connector)(expected)) as connection:
        connection.executescript(getattr(module, constant))
    assert _snapshot(actual) == _snapshot(expected)


def test_supported_schema_still_repairs_missing_index(tmp_path, schema):
    module, _, initializer, _, _ = schema
    path = tmp_path / "repair.sqlite3"
    initialize = getattr(module, initializer)
    initialize(path)
    before = _snapshot(path)
    with closing(sqlite3.connect(path)) as connection:
        name = connection.execute("SELECT name FROM sqlite_master WHERE type='index' AND sql IS NOT NULL ORDER BY name LIMIT 1").fetchone()[0]
        connection.execute('DROP INDEX "' + name.replace('"', '""') + '"')
    initialize(path)
    after = _snapshot(path)
    # Recreated indexes move in sqlite_master's creation order, not in semantics.
    assert (sorted(after[0]), after[1]) == (sorted(before[0]), before[1])


def test_busy_database_preserves_data_and_can_retry(tmp_path, monkeypatch, schema):
    module, _, initializer, connector, _ = schema
    path = tmp_path / "busy.sqlite3"
    initialize = getattr(module, initializer)
    initialize(path)
    before = _snapshot(path)

    def connect(path):
        connection = sqlite3.connect(path, timeout=0.02)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    monkeypatch.setattr(module, connector, connect)
    with closing(sqlite3.connect(path)) as blocker:
        blocker.execute("BEGIN IMMEDIATE")
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            initialize(path)
        blocker.rollback()
    assert _snapshot(path) == before
    initialize(path)
    assert _snapshot(path) == before
