"""Tests for the forward-only database migrations."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from utils.combat import HIT_LOCATIONS
from utils.db_migrations import SCHEMA_VERSION, apply_migrations


def make_legacy_database() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.execute(
        """
        CREATE TABLE next_turn_conditions (
            character_id INTEGER PRIMARY KEY,
            aim INTEGER,
            evaluate INTEGER,
            shock INTEGER,
            feint INTEGER
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE character_armors (
            character_armor_id INTEGER PRIMARY KEY AUTOINCREMENT,
            character_id INTEGER NOT NULL,
            material_id INTEGER NOT NULL,
            body_part_id INTEGER NOT NULL,
            custom_name TEXT,
            quantity INTEGER DEFAULT 1,
            is_equipped INTEGER DEFAULT 0
        )
        """
    )
    connection.commit()
    return connection


def test_migration_creates_combat_tables_and_layer_column():
    connection = make_legacy_database()

    assert apply_migrations(connection) == SCHEMA_VERSION

    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert {
        "combat_sessions",
        "pending_attacks",
        "hit_locations",
        "character_combat_effects",
        "combat_participants",
        "combat_log",
        "guild_settings",
    } <= tables

    guild_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(guild_settings)")
    }
    assert {"guild_id", "locale", "updated_at"} <= guild_columns

    columns = {
        row[1]
        for row in connection.execute("PRAGMA table_info(character_armors)")
    }
    assert "layer_order" in columns

    condition_columns = {
        row[1]
        for row in connection.execute("PRAGMA table_info(next_turn_conditions)")
    }
    assert {"no_defense", "defense_bonus"} <= condition_columns

    pending_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(pending_attacks)")
    }
    assert {
        "mode_id",
        "attack_kind",
        "ranged_weapon_id",
        "damage_expression",
        "maneuver",
        "custom_modifier",
        "max_defense_attempts",
        "defense_attempts",
    } <= pending_columns

    session_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(combat_sessions)")
    }
    assert {
        "round_number",
        "active_character_id",
        "panel_message_id",
    } <= session_columns
    participant_columns = {
        row[1]: row[2]
        for row in connection.execute("PRAGMA table_info(combat_participants)")
    }
    assert participant_columns["initiative"] == "REAL"

    effect_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(character_combat_effects)")
    }
    assert effect_columns == {"character_id", "effect_id", "created_at"}
    catalog_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(combat_effects)")
    }
    assert "resource_type" not in catalog_columns
    assert "resource_cost" not in catalog_columns
    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    connection.close()


def test_hit_location_seed_matches_the_pure_engine():
    connection = make_legacy_database()

    apply_migrations(connection)

    rows = connection.execute(
        "SELECT hit_location_id, name, penalty, armor_body_part FROM hit_locations"
    ).fetchall()
    for hit_location_id, name, penalty, armor_body_part in rows:
        expected = HIT_LOCATIONS[hit_location_id]
        assert name == expected["name"]
        assert penalty == expected["penalty"]
        assert armor_body_part == expected["armor_body_part"]
    connection.close()


def test_migration_is_idempotent():
    connection = make_legacy_database()

    first = apply_migrations(connection)
    second = apply_migrations(connection)

    assert first == second == SCHEMA_VERSION
    connection.close()


def test_migration_preserves_fractional_initiative():
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """
        CREATE TABLE characters (character_id INTEGER PRIMARY KEY);
        INSERT INTO characters (character_id) VALUES (1);
        CREATE TABLE combat_sessions (session_id INTEGER PRIMARY KEY);
        INSERT INTO combat_sessions (session_id) VALUES (10);
        CREATE TABLE combat_participants (
            session_id INTEGER NOT NULL,
            character_id INTEGER NOT NULL,
            owner_id INTEGER,
            is_npc INTEGER NOT NULL DEFAULT 0,
            defense_uses_json TEXT NOT NULL DEFAULT '{}',
            effect_uses_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            initiative INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(session_id, character_id)
        );
        INSERT INTO combat_participants (
            session_id, character_id, owner_id, initiative
        ) VALUES (10, 1, 1, 5.25);
        PRAGMA user_version = 3;
        """
    )
    connection.commit()

    assert apply_migrations(connection) == SCHEMA_VERSION

    row = connection.execute(
        "SELECT initiative FROM combat_participants "
        "WHERE session_id = 10 AND character_id = 1"
    ).fetchone()
    assert row == (5.25,)
    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    connection.close()


def test_migration_discards_old_effects_and_creates_catalog_links():
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """
        CREATE TABLE characters (character_id INTEGER PRIMARY KEY);
        INSERT INTO characters (character_id) VALUES (1);
        CREATE TABLE combat_participants (
            session_id INTEGER NOT NULL,
            character_id INTEGER NOT NULL,
            effect_uses_json TEXT NOT NULL DEFAULT '{}',
            PRIMARY KEY(session_id, character_id)
        );
        INSERT INTO combat_participants (
            session_id, character_id, effect_uses_json
        ) VALUES (10, 1, '{"1": 2}');
        CREATE TABLE character_combat_effects (
            effect_id INTEGER PRIMARY KEY AUTOINCREMENT,
            character_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            applies_to TEXT NOT NULL,
            target TEXT,
            value INTEGER NOT NULL DEFAULT 0,
            uses_per_turn INTEGER NOT NULL DEFAULT 0,
            resource_type TEXT NOT NULL DEFAULT 'none',
            resource_cost INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        INSERT INTO character_combat_effects (
            character_id, name, applies_to, resource_type, resource_cost
        ) VALUES (1, 'Efeito antigo', 'attack', 'pf', 2);
        PRAGMA user_version = 4;
        """
    )
    connection.commit()

    assert apply_migrations(connection) == SCHEMA_VERSION

    assert connection.execute(
        "SELECT COUNT(*) FROM combat_effects"
    ).fetchone()[0] == 0
    assert connection.execute(
        "SELECT COUNT(*) FROM character_combat_effects"
    ).fetchone()[0] == 0
    assert connection.execute(
        "SELECT effect_uses_json FROM combat_participants"
    ).fetchone() == ("{}",)
    connection.close()


def test_migration_resolves_mode_skill_names_to_ids():
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """
        CREATE TABLE skills (
            skill_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            attribute TEXT,
            difficulty_id INTEGER,
            description TEXT
        );
        INSERT INTO skills (skill_id, name, attribute) VALUES
            (6, 'Maça/Machado', 'DX'),
            (7, 'Briga', 'DX'),
            (12, 'Espadas de Lâmina Larga', 'DX'),
            (25, 'Espadas Curtas', 'DX');
        CREATE TABLE melee_weapons (
            melee_weapon_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL
        );
        INSERT INTO melee_weapons (melee_weapon_id, name) VALUES (1, 'Arma');
        CREATE TABLE melee_weapon_modes (
            mode_id INTEGER PRIMARY KEY AUTOINCREMENT,
            melee_weapon_id INTEGER NOT NULL,
            mode_name TEXT,
            skill_name TEXT NOT NULL,
            damage_base TEXT NOT NULL,
            damage_modifier INTEGER DEFAULT 0,
            damage_type TEXT NOT NULL,
            reach TEXT NOT NULL,
            parry TEXT NOT NULL,
            notes TEXT
        );
        INSERT INTO melee_weapon_modes (
            mode_id, melee_weapon_id, mode_name, skill_name,
            damage_base, damage_type, reach, parry
        ) VALUES
            (10, 1, 'Corte', 'Espada de Lâmina Larga', 'GeB', 'corte', '1', '0'),
            (11, 1, 'Alternativo', 'Boxe, Briga ou Caratê', 'GeB', 'corte', '1', '0'),
            (12, 1, 'Nova', 'Maça/Machado de Duas Mãos', 'GeB', 'corte', '1', '0');
        PRAGMA user_version = 5;
        """
    )
    connection.commit()

    assert apply_migrations(connection) == SCHEMA_VERSION

    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(melee_weapon_modes)")
    }
    assert "skill_id" in columns
    assert "skill_name" not in columns

    rows = connection.execute(
        "SELECT mode_id, skill_id FROM melee_weapon_modes ORDER BY mode_id"
    ).fetchall()
    assert rows[0] == (10, 12)
    assert rows[1] == (11, 7)
    two_handed_id = rows[2][1]
    assert rows[2][0] == 12
    assert connection.execute(
        "SELECT name FROM skills WHERE skill_id = ?", (two_handed_id,)
    ).fetchone() == ("Maça/Machado de Duas Mãos",)
    connection.close()


def test_migration_adds_ranged_weapon_skill_id():
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """
        CREATE TABLE skills (
            skill_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            attribute TEXT,
            difficulty_id INTEGER,
            description TEXT
        );
        CREATE TABLE ranged_weapons (
            ranged_weapon_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            damage TEXT
        );
        PRAGMA user_version = 6;
        """
    )
    connection.commit()

    assert apply_migrations(connection) == SCHEMA_VERSION

    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(ranged_weapons)")
    }
    assert "skill_id" in columns
    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    connection.close()


def test_migration_seeds_internal_brawling_modes():
    project_root = Path(__file__).resolve().parent.parent
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        (project_root / "data" / "init.sql").read_text(encoding="utf-8")
    )
    connection.execute(
        "DELETE FROM melee_weapon_modes WHERE melee_weapon_id IN "
        "(SELECT melee_weapon_id FROM melee_weapons WHERE is_unarmed = 1)"
    )
    connection.execute("DELETE FROM melee_weapons WHERE is_unarmed = 1")
    connection.execute("PRAGMA user_version = 7")
    connection.commit()

    assert apply_migrations(connection) == SCHEMA_VERSION

    internal = connection.execute(
        "SELECT melee_weapon_id, is_fallback "
        "FROM melee_weapons WHERE is_unarmed = 1 AND name = 'Briga'"
    ).fetchone()
    assert internal is not None
    assert internal[1] == 0
    modes = connection.execute(
        "SELECT mode_name, attack_modifier FROM melee_weapon_modes "
        "WHERE melee_weapon_id = ? ORDER BY mode_id",
        (internal[0],),
    ).fetchall()
    assert modes == [("Soco", 0), ("Chute", -2)]
    generic = connection.execute(
        "SELECT melee_weapon_id, name, is_fallback FROM melee_weapons "
        "WHERE is_unarmed = 1 AND is_fallback = 1"
    ).fetchone()
    assert generic is not None
    assert generic[1:] == ("Combate Desarmado", 1)
    generic_modes = connection.execute(
        "SELECT skill_id FROM melee_weapon_modes WHERE melee_weapon_id = ?",
        (generic[0],),
    ).fetchall()
    assert generic_modes == [(None,), (None,)]
    assert connection.execute(
        "SELECT COUNT(*) FROM skills WHERE name = 'Combate Desarmado'"
    ).fetchone()[0] == 0
    connection.close()
