"""Low-level database adapter tests."""

from pathlib import Path

import pytest

import app.config as app_config


def test_sqlite_database_adapter_executes_parameterized_queries(tmp_path, monkeypatch):
    from app.database import get_database

    db_path = tmp_path / "adapter-core.db"
    settings = app_config.settings
    monkeypatch.setattr(settings, "database_engine", "sqlite", raising=False)
    monkeypatch.setattr(settings, "database_path", str(db_path), raising=False)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{db_path}", raising=False)

    db = get_database()
    with db.transaction() as conn:
        conn.execute("CREATE TABLE sample (id TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("INSERT INTO sample (id, value) VALUES (?, ?)", ("one", "alpha"))

    with db.connect() as conn:
        row = conn.fetchone("SELECT * FROM sample WHERE id = ?", ("one",))

    assert row == {"id": "one", "value": "alpha"}


def test_mysql_database_adapter_rewrites_qmark_placeholders(monkeypatch):
    from app.database import DatabaseConfig, MySQLDatabase

    db = MySQLDatabase(
        DatabaseConfig(
            engine="mysql",
            url="mysql+pymysql://user:pass@localhost:3306/fasterclip",
            sqlite_path=Path("unused.db"),
        )
    )

    assert db.prepare_sql("SELECT * FROM tasks WHERE id = ? AND version = ?") == (
        "SELECT * FROM tasks WHERE id = %s AND version = %s"
    )


@pytest.mark.mysql
@pytest.mark.skipif(
    not __import__("os").environ.get("MYSQL_TEST_DATABASE_URL"),
    reason="MYSQL_TEST_DATABASE_URL is not set",
)
def test_mysql_database_adapter_connects_and_runs_transaction(monkeypatch):
    import os

    from app.database import get_database

    settings = app_config.settings
    monkeypatch.setattr(settings, "database_engine", "mysql", raising=False)
    monkeypatch.setattr(settings, "database_url", os.environ["MYSQL_TEST_DATABASE_URL"], raising=False)

    db = get_database()
    try:
        with db.transaction() as conn:
            conn.execute("DROP TABLE IF EXISTS adapter_sample")
            conn.execute(
                "CREATE TABLE adapter_sample (id VARCHAR(36) PRIMARY KEY, value TEXT NOT NULL)"
            )
            conn.execute("INSERT INTO adapter_sample (id, value) VALUES (?, ?)", ("one", "alpha"))

        with db.connect() as conn:
            row = conn.fetchone("SELECT * FROM adapter_sample WHERE id = ?", ("one",))

        assert row == {"id": "one", "value": "alpha"}
    finally:
        with db.transaction() as conn:
            conn.execute("DROP TABLE IF EXISTS adapter_sample")
