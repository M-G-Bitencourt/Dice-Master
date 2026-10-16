"""Tests for the entrypoint bootstrap in the_dice_master.py."""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent

CONFIG_INI = """
[BOT]
Prefix = !
Token = test-token
DM_ID = 999
"""


def load_entrypoint_module():
    spec = importlib.util.spec_from_file_location(
        "the_dice_master_bootstrap", PROJECT_ROOT / "the_dice_master.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def bootstrap_dir(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "init.sql").write_text(
        (PROJECT_ROOT / "data" / "init.sql").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (tmp_path / "config.ini").write_text(CONFIG_INI, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


class TestEntrypointImport:
    def test_import_does_not_run_the_bot(self, bootstrap_dir):
        module = load_entrypoint_module()

        assert module.bot.config["BOT"]["DM_ID"] == "999"
        assert not (bootstrap_dir / "data" / "database.db").exists()

    def test_bot_instance_receives_the_injected_config(self, bootstrap_dir):
        module = load_entrypoint_module()

        assert module.bot.config is module.config
        assert module.bot.command_prefix == "!"


class TestInitializeSystemDatabase:
    def test_creates_database_from_schema(self, bootstrap_dir):
        module = load_entrypoint_module()

        module.initialize_system_database()

        db_file = bootstrap_dir / "data" / "database.db"
        assert db_file.exists()
        connection = sqlite3.connect(db_file)
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        connection.close()
        assert "characters" in tables
        assert "current_attacks" in tables
        assert "next_turn_conditions" in tables

    def test_existing_database_is_preserved(self, bootstrap_dir):
        module = load_entrypoint_module()
        module.initialize_system_database()

        connection = sqlite3.connect(bootstrap_dir / "data" / "database.db")
        connection.execute(
            "INSERT INTO characters (owner_id, name) VALUES (1, 'Keeper')"
        )
        connection.commit()
        connection.close()

        module.initialize_system_database()

        connection = sqlite3.connect(bootstrap_dir / "data" / "database.db")
        row = connection.execute("SELECT name FROM characters").fetchone()
        connection.close()
        assert row == ("Keeper",)

    def test_missing_schema_raises_file_not_found(self, bootstrap_dir):
        module = load_entrypoint_module()
        (bootstrap_dir / "data" / "init.sql").unlink()

        with pytest.raises(FileNotFoundError, match="Initialization aborted"):
            module.initialize_system_database()
