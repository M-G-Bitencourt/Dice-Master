"""Forward-only SQLite migrations for the Dice Master database."""

from __future__ import annotations

import sqlite3


SCHEMA_VERSION = 10


_MIGRATION_1 = """
CREATE TABLE IF NOT EXISTS "hit_locations" (
    "hit_location_id" INTEGER PRIMARY KEY,
    "name" TEXT NOT NULL,
    "penalty" INTEGER NOT NULL,
    "armor_body_part" TEXT NOT NULL,
    "notes" TEXT
);
INSERT OR IGNORE INTO "hit_locations" ("hit_location_id", "name", "penalty", "armor_body_part") VALUES
    (0, 'Tronco', 0, 'Tronco'),
    (1, 'Órgãos Vitais', -3, 'Tórax'),
    (2, 'Crânio', -7, 'Crânio'),
    (3, 'Olho', -9, 'Crânio'),
    (4, 'Rosto', -5, 'Rosto'),
    (5, 'Pescoço', -5, 'Pescoço'),
    (6, 'Virilha', -3, 'Virilha'),
    (7, 'Braço', -2, 'Braços'),
    (8, 'Perna', -2, 'Pernas'),
    (9, 'Mão', -4, 'Mãos'),
    (10, 'Pé', -4, 'Pés');
CREATE TABLE IF NOT EXISTS "combat_sessions" (
    "session_id" INTEGER PRIMARY KEY AUTOINCREMENT,
    "guild_id" INTEGER,
    "channel_id" INTEGER NOT NULL,
    "status" TEXT NOT NULL DEFAULT 'active' CHECK ("status" IN ('active', 'closed')),
    "created_at" TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "closed_at" TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS "idx_combat_sessions_active_channel"
    ON "combat_sessions" ("channel_id")
    WHERE "status" = 'active';
CREATE TABLE IF NOT EXISTS "pending_attacks" (
    "attack_id" INTEGER PRIMARY KEY AUTOINCREMENT,
    "session_id" INTEGER,
    "guild_id" INTEGER,
    "channel_id" INTEGER NOT NULL,
    "message_id" INTEGER,
    "attacker_id" INTEGER NOT NULL,
    "attacker_character_id" INTEGER NOT NULL,
    "target_character_id" INTEGER NOT NULL,
    "target_owner_id" INTEGER,
    "weapon_name" TEXT NOT NULL,
    "mode_name" TEXT,
    "skill_name" TEXT,
    "nh_base" INTEGER NOT NULL,
    "nh_effective" INTEGER NOT NULL,
    "attack_roll" INTEGER NOT NULL,
    "attack_margin" INTEGER NOT NULL,
    "raw_damage" INTEGER NOT NULL,
    "critical_damage" INTEGER NOT NULL,
    "rd" INTEGER NOT NULL DEFAULT 0,
    "damage_type" INTEGER NOT NULL,
    "hit_location" INTEGER NOT NULL,
    "feint" INTEGER NOT NULL DEFAULT 0,
    "is_critical" INTEGER NOT NULL DEFAULT 0,
    "modifiers_json" TEXT,
    "status" TEXT NOT NULL DEFAULT 'pending'
        CHECK ("status" IN ('pending', 'resolving', 'resolved', 'superseded', 'expired')),
    "created_at" TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "expires_at" TEXT,
    "resolved_at" TEXT,
    FOREIGN KEY("session_id") REFERENCES "combat_sessions"("session_id") ON DELETE SET NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS "idx_pending_attacks_one_per_channel"
    ON "pending_attacks" ("channel_id")
    WHERE "status" IN ('pending', 'resolving');
CREATE INDEX IF NOT EXISTS "idx_pending_attacks_target"
    ON "pending_attacks" ("target_character_id", "status");
"""


_MIGRATION_2 = """
CREATE TABLE IF NOT EXISTS "character_combat_effects" (
    "effect_id" INTEGER PRIMARY KEY AUTOINCREMENT,
    "character_id" INTEGER NOT NULL,
    "name" TEXT NOT NULL,
    "applies_to" TEXT NOT NULL,
    "target" TEXT,
    "value" INTEGER NOT NULL DEFAULT 0,
    "uses_per_turn" INTEGER NOT NULL DEFAULT 0,
    "resource_type" TEXT NOT NULL DEFAULT 'none'
        CHECK ("resource_type" IN ('none', 'pf', 'er')),
    "resource_cost" INTEGER NOT NULL DEFAULT 0,
    "is_active" INTEGER NOT NULL DEFAULT 1,
    "notes" TEXT,
    "created_at" TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY("character_id") REFERENCES "characters"("character_id") ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS "idx_character_combat_effects_character"
    ON "character_combat_effects" ("character_id", "is_active");
CREATE TABLE IF NOT EXISTS "combat_participants" (
    "session_id" INTEGER NOT NULL,
    "character_id" INTEGER NOT NULL,
    "owner_id" INTEGER,
    "is_npc" INTEGER NOT NULL DEFAULT 0,
    "defense_uses_json" TEXT NOT NULL DEFAULT '{}',
    "effect_uses_json" TEXT NOT NULL DEFAULT '{}',
    "created_at" TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY("session_id", "character_id"),
    FOREIGN KEY("session_id") REFERENCES "combat_sessions"("session_id") ON DELETE CASCADE,
    FOREIGN KEY("character_id") REFERENCES "characters"("character_id") ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS "idx_combat_participants_character"
    ON "combat_participants" ("character_id");
"""


def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    """Return True when the given table exists in the database."""
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _has_column(
    connection: sqlite3.Connection, table_name: str, column_name: str
) -> bool:
    """Return True when the given table already exposes the requested column."""
    if not _table_exists(connection, table_name):
        return False
    rows = connection.execute(f'PRAGMA table_info("{table_name}")').fetchall()
    return any(row[1] == column_name for row in rows)


def _apply_migration_1_columns(connection: sqlite3.Connection) -> None:
    """Apply the column additions that migration 1 needs on legacy tables."""
    if _table_exists(connection, "character_armors") and not _has_column(
        connection, "character_armors", "layer_order"
    ):
        connection.execute(
            'ALTER TABLE "character_armors" '
            'ADD COLUMN "layer_order" INTEGER NOT NULL DEFAULT 0'
        )

    if _table_exists(connection, "next_turn_conditions"):
        if not _has_column(connection, "next_turn_conditions", "no_defense"):
            connection.execute(
                'ALTER TABLE "next_turn_conditions" '
                'ADD COLUMN "no_defense" INTEGER NOT NULL DEFAULT 0'
            )
        if not _has_column(connection, "next_turn_conditions", "defense_bonus"):
            connection.execute(
                'ALTER TABLE "next_turn_conditions" '
                'ADD COLUMN "defense_bonus" INTEGER NOT NULL DEFAULT 0'
            )

    if _table_exists(connection, "character_armors"):
        connection.execute(
            'CREATE INDEX IF NOT EXISTS "idx_character_armors_character" '
            'ON "character_armors" ("character_id", "is_equipped")'
        )


def _apply_migration_2_columns(connection: sqlite3.Connection) -> None:
    """Apply the column additions required by the multiple-defence release."""
    pending_columns = {
        "mode_id": 'INTEGER',
        "maneuver": 'TEXT',
        "custom_modifier": 'INTEGER NOT NULL DEFAULT 0',
        "max_defense_attempts": 'INTEGER NOT NULL DEFAULT 1',
        "defense_attempts": 'INTEGER NOT NULL DEFAULT 0',
    }
    if _table_exists(connection, "pending_attacks"):
        for column_name, column_type in pending_columns.items():
            if not _has_column(connection, "pending_attacks", column_name):
                connection.execute(
                    f'ALTER TABLE "pending_attacks" '
                    f'ADD COLUMN "{column_name}" {column_type}'
                )

    if _table_exists(connection, "combat_sessions") and not _has_column(
        connection, "combat_sessions", "round_number"
    ):
        connection.execute(
            'ALTER TABLE "combat_sessions" '
            'ADD COLUMN "round_number" INTEGER NOT NULL DEFAULT 1'
        )


_MIGRATION_3 = """
CREATE TABLE IF NOT EXISTS "combat_log" (
    "log_id" INTEGER PRIMARY KEY AUTOINCREMENT,
    "session_id" INTEGER,
    "channel_id" INTEGER NOT NULL,
    "event_type" TEXT NOT NULL,
    "actor_character_id" INTEGER,
    "target_character_id" INTEGER,
    "value" INTEGER,
    "hp_before" INTEGER,
    "hp_after" INTEGER,
    "description" TEXT,
    "reverted" INTEGER NOT NULL DEFAULT 0,
    "created_at" TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY("session_id") REFERENCES "combat_sessions"("session_id") ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS "idx_combat_log_session"
    ON "combat_log" ("session_id", "log_id");
"""


def _apply_migration_3_columns(connection: sqlite3.Connection) -> None:
    """Apply the ranged-combat, initiative and log column additions."""
    session_columns = {
        "active_character_id": "INTEGER",
        "panel_message_id": "INTEGER",
    }
    if _table_exists(connection, "combat_sessions"):
        for column_name, column_type in session_columns.items():
            if not _has_column(connection, "combat_sessions", column_name):
                connection.execute(
                    f'ALTER TABLE "combat_sessions" '
                    f'ADD COLUMN "{column_name}" {column_type}'
                )

    participant_columns = {
        "initiative": "INTEGER NOT NULL DEFAULT 0",
    }
    if _table_exists(connection, "combat_participants"):
        for column_name, column_type in participant_columns.items():
            if not _has_column(connection, "combat_participants", column_name):
                connection.execute(
                    f'ALTER TABLE "combat_participants" '
                    f'ADD COLUMN "{column_name}" {column_type}'
                )

    pending_columns = {
        "attack_kind": "TEXT NOT NULL DEFAULT 'melee'",
        "ranged_weapon_id": "INTEGER",
        "damage_expression": "TEXT",
    }
    if _table_exists(connection, "pending_attacks"):
        for column_name, column_type in pending_columns.items():
            if not _has_column(connection, "pending_attacks", column_name):
                connection.execute(
                    f'ALTER TABLE "pending_attacks" '
                    f'ADD COLUMN "{column_name}" {column_type}'
                )


def _apply_migration_4(connection: sqlite3.Connection) -> None:
    """Rebuild combat_participants with REAL initiative while preserving rows."""
    if not _table_exists(connection, "combat_participants"):
        return

    connection.executescript(
        """
        CREATE TABLE "combat_participants_new" (
            "session_id" INTEGER NOT NULL,
            "character_id" INTEGER NOT NULL,
            "owner_id" INTEGER,
            "is_npc" INTEGER NOT NULL DEFAULT 0,
            "initiative" REAL NOT NULL DEFAULT 0,
            "defense_uses_json" TEXT NOT NULL DEFAULT '{}',
            "effect_uses_json" TEXT NOT NULL DEFAULT '{}',
            "created_at" TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY("session_id", "character_id"),
            FOREIGN KEY("session_id") REFERENCES "combat_sessions"("session_id") ON DELETE CASCADE,
            FOREIGN KEY("character_id") REFERENCES "characters"("character_id") ON DELETE CASCADE
        );
        INSERT INTO "combat_participants_new" (
            session_id, character_id, owner_id, is_npc, initiative,
            defense_uses_json, effect_uses_json, created_at
        )
        SELECT
            session_id, character_id, owner_id, is_npc, initiative,
            defense_uses_json, effect_uses_json, created_at
        FROM "combat_participants";
        DROP TABLE "combat_participants";
        ALTER TABLE "combat_participants_new" RENAME TO "combat_participants";
        CREATE INDEX "idx_combat_participants_character"
            ON "combat_participants" ("character_id");
        """
    )


def _apply_migration_5(connection: sqlite3.Connection) -> None:
    """Replace per-character effects with an external catalog and links."""
    connection.executescript(
        """
        DROP TABLE IF EXISTS "character_combat_effects";
        CREATE TABLE IF NOT EXISTS "combat_effects" (
            "effect_id" INTEGER PRIMARY KEY AUTOINCREMENT,
            "name" TEXT NOT NULL,
            "applies_to" TEXT NOT NULL,
            "target" TEXT,
            "value" INTEGER NOT NULL DEFAULT 0,
            "uses_per_turn" INTEGER NOT NULL DEFAULT 0,
            "notes" TEXT,
            "created_at" TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE "character_combat_effects" (
            "character_id" INTEGER NOT NULL,
            "effect_id" INTEGER NOT NULL,
            "created_at" TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY("character_id", "effect_id"),
            FOREIGN KEY("character_id") REFERENCES "characters"("character_id") ON DELETE CASCADE,
            FOREIGN KEY("effect_id") REFERENCES "combat_effects"("effect_id") ON DELETE CASCADE
        );
        CREATE INDEX "idx_character_combat_effects_character"
            ON "character_combat_effects" ("character_id");
        CREATE INDEX "idx_character_combat_effects_effect"
            ON "character_combat_effects" ("effect_id");
        UPDATE "combat_participants" SET "effect_uses_json" = '{}';
        """
    )


_MODE_SKILL_CANONICAL = {
    "Boxe, Briga ou Caratê": "Briga",
    "Briga ou Caratê": "Briga",
    "Espada de Lâmina Larga": "Espadas de Lâmina Larga",
}


def _apply_migration_6(connection: sqlite3.Connection) -> None:
    """Replace melee mode skill names with direct skill references."""
    if not _table_exists(connection, "melee_weapon_modes"):
        return

    mode_names = [
        row[0]
        for row in connection.execute(
            "SELECT DISTINCT skill_name FROM melee_weapon_modes"
        )
        if row[0] is not None
    ]
    mapping: dict[str, int] = {}
    for legacy_name in mode_names:
        canonical_name = _MODE_SKILL_CANONICAL.get(
            legacy_name, legacy_name
        )
        row = connection.execute(
            "SELECT skill_id FROM skills WHERE name = ?",
            (canonical_name,),
        ).fetchone()
        if row is None:
            cursor = connection.execute(
                """
                INSERT INTO skills (name, attribute, difficulty_id, description)
                VALUES (?, 'DX', NULL, ?)
                """,
                (
                    canonical_name,
                    "Perfil criado automaticamente a partir de um modo de arma.",
                ),
            )
            skill_id = int(cursor.lastrowid)
        else:
            skill_id = int(row[0])
        mapping[legacy_name] = skill_id

    connection.execute(
        """
        CREATE TEMP TABLE "_melee_mode_skill_map" (
            legacy_name TEXT PRIMARY KEY,
            skill_id INTEGER NOT NULL
        )
        """
    )
    connection.executemany(
        'INSERT INTO "_melee_mode_skill_map" (legacy_name, skill_id) '
        "VALUES (?, ?)",
        list(mapping.items()),
    )
    connection.executescript(
        """
        CREATE TABLE "melee_weapon_modes_new" (
            "mode_id" INTEGER PRIMARY KEY AUTOINCREMENT,
            "melee_weapon_id" INTEGER NOT NULL,
            "mode_name" TEXT DEFAULT 'Padrão',
            "skill_id" INTEGER NOT NULL,
            "damage_base" TEXT NOT NULL,
            "damage_modifier" INTEGER DEFAULT 0,
            "damage_type" TEXT NOT NULL,
            "reach" TEXT NOT NULL,
            "parry" TEXT NOT NULL,
            "notes" TEXT,
            FOREIGN KEY("melee_weapon_id") REFERENCES "melee_weapons"("melee_weapon_id") ON DELETE CASCADE,
            FOREIGN KEY("skill_id") REFERENCES "skills"("skill_id") ON DELETE RESTRICT
        );
        INSERT INTO "melee_weapon_modes_new" (
            mode_id, melee_weapon_id, mode_name, skill_id,
            damage_base, damage_modifier, damage_type, reach, parry, notes
        )
        SELECT
            m.mode_id, m.melee_weapon_id, m.mode_name, map.skill_id,
            m.damage_base, m.damage_modifier, m.damage_type, m.reach,
            m.parry, m.notes
        FROM "melee_weapon_modes" m
        JOIN "_melee_mode_skill_map" map ON map.legacy_name = m.skill_name;
        DROP TABLE "melee_weapon_modes";
        ALTER TABLE "melee_weapon_modes_new" RENAME TO "melee_weapon_modes";
        CREATE INDEX "idx_melee_weapon_modes_weapon"
            ON "melee_weapon_modes" ("melee_weapon_id");
        DROP TABLE "_melee_mode_skill_map";
        """
    )


def _apply_migration_7(connection: sqlite3.Connection) -> None:
    """Add the required skill reference to ranged weapons."""
    if _table_exists(connection, "ranged_weapons") and not _has_column(
        connection, "ranged_weapons", "skill_id"
    ):
        connection.execute(
            'ALTER TABLE "ranged_weapons" '
            'ADD COLUMN "skill_id" INTEGER '
            'REFERENCES "skills"("skill_id") ON DELETE RESTRICT'
        )


def _apply_migration_8(connection: sqlite3.Connection) -> None:
    """Add internal unarmed weapons and their attack modes."""
    if _table_exists(connection, "melee_weapons"):
        if not _has_column(connection, "melee_weapons", "is_unarmed"):
            connection.execute(
                'ALTER TABLE "melee_weapons" '
                'ADD COLUMN "is_unarmed" INTEGER NOT NULL DEFAULT 0'
            )
        if not _has_column(connection, "melee_weapons", "allow_default"):
            connection.execute(
                'ALTER TABLE "melee_weapons" '
                'ADD COLUMN "allow_default" INTEGER NOT NULL DEFAULT 0'
            )

    if _table_exists(connection, "melee_weapon_modes") and not _has_column(
        connection, "melee_weapon_modes", "attack_modifier"
    ):
        connection.execute(
            'ALTER TABLE "melee_weapon_modes" '
            'ADD COLUMN "attack_modifier" INTEGER NOT NULL DEFAULT 0'
        )

    if not (
        _table_exists(connection, "skills")
        and _table_exists(connection, "melee_weapons")
        and _table_exists(connection, "melee_weapon_modes")
    ):
        return

    required_weapon_columns = {
        "name", "tl", "min_st", "is_two_handed", "weight", "cost",
        "description", "is_unarmed", "allow_default",
    }
    required_mode_columns = {
        "melee_weapon_id", "mode_name", "skill_id", "damage_base",
        "damage_modifier", "damage_type", "reach", "parry", "notes",
        "attack_modifier",
    }
    if not required_weapon_columns.issubset(
        {row[1] for row in connection.execute("PRAGMA table_info(melee_weapons)")}
    ):
        return
    if not required_mode_columns.issubset(
        {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(melee_weapon_modes)"
            )
        }
    ):
        return

    row = connection.execute(
        'SELECT "skill_id" FROM "skills" WHERE "name" = ?',
        ("Briga",),
    ).fetchone()
    if row is None:
        cursor = connection.execute(
            """
            INSERT INTO "skills" ("name", "attribute", "difficulty_id", "description")
            VALUES ('Briga', 'DX', 1, 'Perícia de combate desarmado.')
            """
        )
        skill_id = int(cursor.lastrowid)
    else:
        skill_id = int(row[0])

    row = connection.execute(
        'SELECT "melee_weapon_id" FROM "melee_weapons" '
        'WHERE "is_unarmed" = 1 AND "name" = ?',
        ("Briga",),
    ).fetchone()
    if row is None:
        cursor = connection.execute(
            """
            INSERT INTO "melee_weapons" (
                "name", "tl", "min_st", "is_two_handed", "weight", "cost",
                "description", "is_unarmed", "allow_default"
            )
            VALUES ('Briga', 0, 0, 0, 0.0, 0.0,
                    'Ataques desarmados de Briga.', 1, 1)
            """
        )
        weapon_id = int(cursor.lastrowid)
    else:
        weapon_id = int(row[0])

    modes = (
        (
            "Soco",
            "GdP",
            -1,
            "C",
            "GURPS 4e: thr-1 cr.",
            0,
        ),
        (
            "Chute",
            "GdP",
            0,
            "C,1",
            "GURPS 4e: thr cr; -2 para acertar.",
            -2,
        ),
    )
    for mode_name, damage_base, damage_modifier, reach, notes, attack_modifier in modes:
        exists = connection.execute(
            'SELECT 1 FROM "melee_weapon_modes" '
            'WHERE "melee_weapon_id" = ? AND "mode_name" = ?',
            (weapon_id, mode_name),
        ).fetchone()
        if exists is not None:
            continue
        connection.execute(
            """
            INSERT INTO "melee_weapon_modes" (
                "melee_weapon_id", "mode_name", "skill_id", "damage_base",
                "damage_modifier", "damage_type", "reach", "parry", "notes",
                "attack_modifier"
            )
            VALUES (?, ?, ?, ?, ?, 'contusão', ?, 'Não', ?, ?)
            """,
            (
                weapon_id,
                mode_name,
                skill_id,
                damage_base,
                damage_modifier,
                reach,
                notes,
                attack_modifier,
            ),
        )


def _ensure_skill(
    connection: sqlite3.Connection, name: str, description: str
) -> int:
    """Return an existing skill id or create the skill with DX/Easy defaults."""
    row = connection.execute(
        'SELECT "skill_id" FROM "skills" WHERE "name" = ?',
        (name,),
    ).fetchone()
    if row is not None:
        return int(row[0])
    cursor = connection.execute(
        """
        INSERT INTO "skills" ("name", "attribute", "difficulty_id", "description")
        VALUES (?, 'DX', 1, ?)
        """,
        (name, description),
    )
    return int(cursor.lastrowid)


def _apply_migration_9(connection: sqlite3.Connection) -> None:
    """Add the generic unarmed fallback and make Briga specific."""
    if _table_exists(connection, "melee_weapons") and not _has_column(
        connection, "melee_weapons", "is_fallback"
    ):
        connection.execute(
            'ALTER TABLE "melee_weapons" '
            'ADD COLUMN "is_fallback" INTEGER NOT NULL DEFAULT 0'
        )

    if not (
        _table_exists(connection, "skills")
        and _table_exists(connection, "melee_weapons")
        and _table_exists(connection, "melee_weapon_modes")
    ):
        return

    required_weapon_columns = {
        "name", "tl", "min_st", "is_two_handed", "weight", "cost",
        "description", "is_unarmed", "allow_default", "is_fallback",
    }
    required_mode_columns = {
        "melee_weapon_id", "mode_name", "skill_id", "damage_base",
        "damage_modifier", "damage_type", "reach", "parry", "notes",
        "attack_modifier",
    }
    if not required_weapon_columns.issubset(
        {row[1] for row in connection.execute("PRAGMA table_info(melee_weapons)")}
    ):
        return
    if not required_mode_columns.issubset(
        {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(melee_weapon_modes)"
            )
        }
    ):
        return

    connection.execute(
        """
        UPDATE "melee_weapons"
        SET "allow_default" = 0, "is_fallback" = 0
        WHERE "is_unarmed" = 1 AND "name" = 'Briga'
        """
    )

    generic_skill_id = _ensure_skill(
        connection,
        "Combate Desarmado",
        "Perícia genérica de combate desarmado.",
    )

    row = connection.execute(
        'SELECT "melee_weapon_id" FROM "melee_weapons" '
        'WHERE "is_unarmed" = 1 AND "is_fallback" = 1'
    ).fetchone()
    if row is None:
        cursor = connection.execute(
            """
            INSERT INTO "melee_weapons" (
                "name", "tl", "min_st", "is_two_handed", "weight", "cost",
                "description", "is_unarmed", "allow_default", "is_fallback"
            )
            VALUES (
                'Combate Desarmado', 0, 0, 0, 0.0, 0.0,
                'Modos genéricos para personagens sem perícia desarmada específica.',
                1, 1, 1
            )
            """
        )
        weapon_id = int(cursor.lastrowid)
    else:
        weapon_id = int(row[0])

    modes = (
        ("Soco", -1, "C", "GURPS 4e: thr-1 cr.", 0),
        ("Chute", 0, "C,1", "GURPS 4e: thr cr; -2 para acertar.", -2),
    )
    for mode_name, damage_modifier, reach, notes, attack_modifier in modes:
        exists = connection.execute(
            'SELECT 1 FROM "melee_weapon_modes" '
            'WHERE "melee_weapon_id" = ? AND "mode_name" = ?',
            (weapon_id, mode_name),
        ).fetchone()
        if exists is not None:
            continue
        connection.execute(
            """
            INSERT INTO "melee_weapon_modes" (
                "melee_weapon_id", "mode_name", "skill_id", "damage_base",
                "damage_modifier", "damage_type", "reach", "parry", "notes",
                "attack_modifier"
            )
            VALUES (?, ?, ?, 'GdP', ?, 'contusão', ?, 'Não', ?, ?)
            """,
            (
                weapon_id,
                mode_name,
                generic_skill_id,
                damage_modifier,
                reach,
                notes,
                attack_modifier,
            ),
        )


def _apply_migration_10(connection: sqlite3.Connection) -> None:
    """Make fallback unarmed modes skill-less and remove the generic skill."""
    if _table_exists(connection, "melee_weapons") and not _has_column(
        connection, "melee_weapons", "is_fallback"
    ):
        connection.execute(
            'ALTER TABLE "melee_weapons" '
            'ADD COLUMN "is_fallback" INTEGER NOT NULL DEFAULT 0'
        )

    if _table_exists(connection, "melee_weapon_modes"):
        required_mode_columns = {
            "mode_id", "melee_weapon_id", "mode_name", "skill_id",
            "damage_base", "damage_modifier", "damage_type", "reach",
            "parry", "notes", "attack_modifier",
        }
        if required_mode_columns.issubset(
            {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(melee_weapon_modes)"
                )
            }
        ):
            connection.executescript(
                """
                DROP TABLE IF EXISTS "melee_weapon_modes_new";
                CREATE TABLE "melee_weapon_modes_new" (
                    "mode_id" INTEGER PRIMARY KEY AUTOINCREMENT,
                    "melee_weapon_id" INTEGER NOT NULL,
                    "mode_name" TEXT DEFAULT 'Padrão',
                    "skill_id" INTEGER,
                    "damage_base" TEXT NOT NULL,
                    "damage_modifier" INTEGER DEFAULT 0,
                    "damage_type" TEXT NOT NULL,
                    "reach" TEXT NOT NULL,
                    "parry" TEXT NOT NULL,
                    "notes" TEXT,
                    "attack_modifier" INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY("melee_weapon_id") REFERENCES "melee_weapons"("melee_weapon_id") ON DELETE CASCADE,
                    FOREIGN KEY("skill_id") REFERENCES "skills"("skill_id") ON DELETE RESTRICT
                );
                INSERT INTO "melee_weapon_modes_new" (
                    mode_id, melee_weapon_id, mode_name, skill_id,
                    damage_base, damage_modifier, damage_type, reach, parry,
                    notes, attack_modifier
                )
                SELECT
                    mode_id, melee_weapon_id, mode_name, skill_id,
                    damage_base, damage_modifier, damage_type, reach, parry,
                    notes, attack_modifier
                FROM "melee_weapon_modes";
                DROP TABLE "melee_weapon_modes";
                ALTER TABLE "melee_weapon_modes_new" RENAME TO "melee_weapon_modes";
                CREATE INDEX "idx_melee_weapon_modes_weapon"
                    ON "melee_weapon_modes" ("melee_weapon_id");
                """
            )

    if _table_exists(connection, "melee_weapons") and _has_column(
        connection, "melee_weapons", "is_fallback"
    ):
        connection.execute(
            """
            UPDATE "melee_weapon_modes"
            SET "skill_id" = NULL
            WHERE "melee_weapon_id" IN (
                SELECT "melee_weapon_id" FROM "melee_weapons"
                WHERE "is_unarmed" = 1 AND "is_fallback" = 1
            )
            """
        )

    if _table_exists(connection, "skills"):
        referenced = None
        if _table_exists(connection, "character_skills"):
            referenced = connection.execute(
                """
                SELECT 1
                FROM "character_skills" cs
                JOIN "skills" s ON s."skill_id" = cs."skill_id"
                WHERE s."name" = 'Combate Desarmado'
                LIMIT 1
                """
            ).fetchone()
        if referenced is not None:
            raise ValueError(
                "Migration aborted: 'Combate Desarmado' is assigned to a character."
            )
        connection.execute(
            'DELETE FROM "skills" WHERE "name" = ?',
            ("Combate Desarmado",),
        )

    if _table_exists(connection, "melee_weapons") and _has_column(
        connection, "melee_weapons", "allow_default"
    ):
        connection.execute(
            'ALTER TABLE "melee_weapons" DROP COLUMN "allow_default"'
        )


def apply_migrations(connection: sqlite3.Connection) -> int:
    """Apply every pending migration and return the resulting schema version."""
    current_version = int(connection.execute("PRAGMA user_version").fetchone()[0])

    if current_version < 1:
        connection.executescript(_MIGRATION_1)
        _apply_migration_1_columns(connection)
        connection.execute("PRAGMA user_version = 1")
        connection.commit()
        current_version = 1

    if current_version < 2:
        connection.executescript(_MIGRATION_2)
        _apply_migration_2_columns(connection)
        connection.execute("PRAGMA user_version = 2")
        connection.commit()
        current_version = 2

    if current_version < 3:
        connection.executescript(_MIGRATION_3)
        _apply_migration_3_columns(connection)
        connection.execute("PRAGMA user_version = 3")
        connection.commit()
        current_version = 3

    if current_version < 4:
        _apply_migration_4(connection)
        connection.execute("PRAGMA user_version = 4")
        connection.commit()
        current_version = 4

    if current_version < 5:
        _apply_migration_5(connection)
        connection.execute("PRAGMA user_version = 5")
        connection.commit()
        current_version = 5

    if current_version < 6:
        _apply_migration_6(connection)
        connection.execute("PRAGMA user_version = 6")
        connection.commit()
        current_version = 6

    if current_version < 7:
        _apply_migration_7(connection)
        connection.execute("PRAGMA user_version = 7")
        connection.commit()
        current_version = 7

    if current_version < 8:
        _apply_migration_8(connection)
        connection.execute("PRAGMA user_version = 8")
        connection.commit()
        current_version = 8

    if current_version < 9:
        _apply_migration_9(connection)
        connection.execute("PRAGMA user_version = 9")
        connection.commit()
        current_version = 9

    if current_version < 10:
        _apply_migration_10(connection)
        connection.execute("PRAGMA user_version = 10")
        connection.commit()
        current_version = 10

    return current_version
