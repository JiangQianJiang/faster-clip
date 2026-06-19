"""Database adapter layer for SQLite local tests and MySQL production."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from app import config as app_config


@dataclass(frozen=True)
class DatabaseConfig:
    engine: str
    url: str
    sqlite_path: Path


class DatabaseConnection:
    def __init__(self, database: "BaseDatabase", raw_conn: Any):
        self._database = database
        self.raw_conn = raw_conn

    def execute(self, sql: str, params: tuple | list = ()):
        cursor = self.raw_conn.cursor()
        cursor.execute(self._database.prepare_sql(sql), params)
        return cursor

    def executemany(self, sql: str, params: list[tuple] | tuple[tuple, ...]):
        cursor = self.raw_conn.cursor()
        cursor.executemany(self._database.prepare_sql(sql), params)
        return cursor

    def fetchone(self, sql: str, params: tuple | list = ()) -> dict | None:
        cursor = self.execute(sql, params)
        row = cursor.fetchone()
        return self._database.row_to_dict(row)

    def fetchall(self, sql: str, params: tuple | list = ()) -> list[dict]:
        cursor = self.execute(sql, params)
        return [self._database.row_to_dict(row) for row in cursor.fetchall()]


class BaseDatabase:
    def __init__(self, config: DatabaseConfig):
        self.config = config

    def open_raw_connection(self):
        raise NotImplementedError

    def prepare_sql(self, sql: str) -> str:
        return sql

    def row_to_dict(self, row: Any) -> dict | None:
        raise NotImplementedError

    @contextmanager
    def connect(self):
        raw_conn = self.open_raw_connection()
        try:
            yield DatabaseConnection(self, raw_conn)
        finally:
            raw_conn.close()

    @contextmanager
    def transaction(self):
        raw_conn = self.open_raw_connection()
        try:
            yield DatabaseConnection(self, raw_conn)
            raw_conn.commit()
        except Exception:
            raw_conn.rollback()
            raise
        finally:
            raw_conn.close()


class SQLiteDatabase(BaseDatabase):
    def open_raw_connection(self):
        self.config.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.config.sqlite_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def row_to_dict(self, row: Any) -> dict | None:
        if row is None:
            return None
        return dict(row)


class MySQLDatabase(BaseDatabase):
    def open_raw_connection(self):
        try:
            import pymysql
            from pymysql.cursors import DictCursor
        except ImportError as exc:
            raise RuntimeError(
                "MySQL database engine requires pymysql. Install backend requirements."
            ) from exc

        parsed = urlparse(self.config.url)
        return pymysql.connect(
            host=parsed.hostname or "localhost",
            port=parsed.port or 3306,
            user=unquote(parsed.username or ""),
            password=unquote(parsed.password or ""),
            database=(parsed.path or "/").lstrip("/"),
            charset="utf8mb4",
            autocommit=False,
            cursorclass=DictCursor,
        )

    def prepare_sql(self, sql: str) -> str:
        return sql.replace("?", "%s")

    def row_to_dict(self, row: Any) -> dict | None:
        if row is None:
            return None
        return dict(row)


def get_database_config(sqlite_path: Path | None = None) -> DatabaseConfig:
    settings = app_config.settings
    engine = settings.database_engine.lower()
    return DatabaseConfig(
        engine=engine,
        url=settings.database_url,
        sqlite_path=sqlite_path or Path(settings.database_path),
    )


def get_database(sqlite_path: Path | None = None) -> BaseDatabase:
    config = get_database_config(sqlite_path)
    if config.engine == "sqlite":
        return SQLiteDatabase(config)
    if config.engine == "mysql":
        return MySQLDatabase(config)
    raise ValueError(f"Unsupported database engine: {config.engine}")
