"""Shared pytest fixtures for the Dice Master test suite."""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

import pytest

os.environ.setdefault("DICE_MASTER_DEFAULT_LOCALE", "pt-BR")

TESTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TESTS_DIR.parent

if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from helpers import FakeBot, FakeInteraction, insert_character  # noqa: E402

INIT_SQL_PATH = PROJECT_ROOT / "data" / "init.sql"


def create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(INIT_SQL_PATH.read_text(encoding="utf-8"))
    connection.commit()


@pytest.fixture
def db():
    """Isolated in-memory database with the production schema applied."""
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON;")
    create_schema(connection)
    yield connection
    connection.close()


@pytest.fixture
def db_path(tmp_path):
    """On-disk temporary database for modules that resolve the path themselves."""
    path = tmp_path / "database.db"
    connection = sqlite3.connect(path)
    create_schema(connection)
    connection.close()
    return path


@pytest.fixture
def patched_sqlite(monkeypatch, db):
    """Route every sqlite3.connect call to the shared in-memory database."""
    monkeypatch.setattr(sqlite3, "connect", lambda *args, **kwargs: db)
    return db


@pytest.fixture
def make_cog(patched_sqlite):
    """Instantiates a cog without touching data/database.db."""
    bot = FakeBot()

    def _make_cog(cog_cls, bot_override=None):
        cog = cog_cls(bot_override if bot_override is not None else bot)
        cog.db_connection = patched_sqlite
        patched_sqlite.execute("PRAGMA foreign_keys = ON;")
        return cog

    return _make_cog


@pytest.fixture
def interaction():
    return FakeInteraction()


@pytest.fixture
def character(db):
    """Registers a fresh character owned by player id 1."""
    return insert_character(db, owner_id=1)
