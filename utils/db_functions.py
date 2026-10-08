import discord
import sqlite3
from pathlib import Path

# SQL FUNCTIONS (next_turn_conditions)
VALID_COLUMNS = {
    "aim",
    "evaluate",
    "shock",
    "feint",
}  # Valid structural columns to prevent unauthorized SQL string injection


def _resolve_character_id(connection: sqlite3.Connection, player_id: int) -> int:
    """
    Internal helper to map the Discord player_id (owner_id) to the internal character_id.
    Raises a ValueError if the structural integrity is broken and no character is assigned.
    """
    cursor = connection.cursor()
    cursor.execute(
        "SELECT character_id FROM characters WHERE owner_id = ?", (player_id,)
    )
    row = cursor.fetchone()

    if row is None:
        raise ValueError(
            f"Database Anomaly: No character found assigned to owner_id {player_id}."
        )
    return int(row[0])


def clear_player_conditions(connection: sqlite3.Connection, player_id: int) -> None:
    """
    Resolves the character identity and purges all transient modifiers by resetting columns to zero.
    """
    character_id = _resolve_character_id(connection, player_id)
    cursor = connection.cursor()
    cursor.execute(
        """
        UPDATE next_turn_conditions
        SET aim = 0, evaluate = 0, shock = 0, feint = 0
        WHERE character_id = ?
    """,
        (character_id,),
    )
    connection.commit()


def set_player_condition(
    connection: sqlite3.Connection, player_id: int, column_name: str, value: int
) -> None:
    """
    Resolves the character identity and executes an atomic upsert on the targeted validated column.
    """
    if column_name.lower() not in VALID_COLUMNS:
        raise ValueError(
            f"Abnormal operation detected: '{column_name}' is not a valid condition column."
        )

    character_id = _resolve_character_id(connection, player_id)
    cursor = connection.cursor()

    query = f"""
        INSERT INTO next_turn_conditions (character_id, {column_name})
        VALUES (?, ?)
        ON CONFLICT(character_id) DO UPDATE SET
            {column_name} = excluded.{column_name}
    """
    cursor.execute(query, (character_id, value))
    connection.commit()


def get_player_condition(
    connection: sqlite3.Connection, player_id: int, column_name: str
) -> int:
    """
    Queries a condition column. Returns 0 if the character lacks an entry or doesn't exist.
    """
    if column_name.lower() not in VALID_COLUMNS:
        raise ValueError(
            f"Abnormal operation detected: '{column_name}' is not a valid condition column."
        )

    try:
        character_id = _resolve_character_id(connection, player_id)
    except ValueError:
        # Defensive fallback: if the player has no character registered, return the neutral modifier 0
        return 0

    cursor = connection.cursor()
    query = f"SELECT {column_name} FROM next_turn_conditions WHERE character_id = ?"
    cursor.execute(query, (character_id,))
    row = cursor.fetchone()

    if row is not None and row[0] is not None:
        return int(row[0])
    return 0


# SQL FUNCTIONS (current_attacks)
def clear_current_attack(connection: sqlite3.Connection) -> None:
    """
    Truncates the current_attacks table, ensuring no transient attack state persists.
    """
    cursor = connection.cursor()
    cursor.execute("DELETE FROM current_attacks")
    connection.commit()


def save_current_attack(
    connection: sqlite3.Connection,
    raw_damage: int,
    dmg_type: int,
    hit_location: int,
    feint: int,
    critical_damage: int,
) -> None:
    """
    Enforces a single-state invariant by clearing the table before injecting
    the new monolithic attack parameters.
    """
    cursor = connection.cursor()

    # First, purge the volatile state to ensure only one row ever exists
    cursor.execute("DELETE FROM current_attacks")

    # Inject the new state vector
    cursor.execute(
        """
        INSERT INTO current_attacks (raw_damage, dmg_type, hit_location, feint, critical_damage)
        VALUES (?, ?, ?, ?, ?)
    """,
        (raw_damage, dmg_type, hit_location, feint, critical_damage),
    )

    connection.commit()


def get_current_attack(connection: sqlite3.Connection) -> dict:
    """
    Queries the solitary attack state record.
    Returns an empty dictionary if the combat pipeline is currently vacant.
    """
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT raw_damage, dmg_type, hit_location, feint, critical_damage 
        FROM current_attacks 
        LIMIT 1
    """
    )
    row = cursor.fetchone()

    if row is None:
        return {}

    return {
        "raw_damage": row[0],
        "dmg_type": row[1],
        "hit_location": row[2],
        "feint": row[3],
        "critical_damage": row[4],
    }


# SQL FUNCTIONS (characters)
def get_character_strength(connection: sqlite3.Connection, owner_id: int) -> int:
    """
    Retrieves the raw Strength (ST) attribute for a character owned by the given owner_id.
    Raises a ValueError if no character entity is bound to the provided identifier.
    """
    cursor = connection.cursor()

    # Selecting the exact scalar attribute filtered by the owner's unique token
    cursor.execute("SELECT st FROM characters WHERE owner_id = ?", (owner_id,))
    row = cursor.fetchone()

    if row is None:
        raise ValueError(
            f"Database Anomaly: Access denied or character non-existent for owner_id {owner_id}."
        )

    return int(row[0])


def get_character_profile(connection: sqlite3.Connection, owner_id: int) -> dict:
    """
    Retrieves the exact attribute matrix for a specific character based exclusively
    on the denormalized 22-column schema, omitting any extraneous statistical queries.
    """
    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT 
            character_id, owner_id, is_npc, name, st, dx, iq, ht, 
            additional_max_pv, additional_vont, additional_per, 
            additional_max_pf, additional_basic_speed, additional_basic_move, 
            energy_reserve, normal_diffuse_homogeneous_unded, money,
            current_pv, current_pf, current_er, current_points, total_points
        FROM characters 
        WHERE owner_id = ?
        """,
        (owner_id,),
    )

    row = cursor.fetchone()

    if row is None:
        raise ValueError(
            f"Database Anomaly: No character sheet linked to owner_id {owner_id}."
        )

    return {
        "character_id": row[0],
        "owner_id": row[1],
        "is_npc": bool(row[2]),
        "name": row[3],
        "st": row[4],
        "dx": row[5],
        "iq": row[6],
        "ht": row[7],
        "additional_max_pv": row[8],
        "additional_vont": row[9],
        "additional_per": row[10],
        "additional_max_pf": row[11],
        "additional_basic_speed": row[12],
        "additional_basic_move": row[13],
        "energy_reserve": row[14],
        "normal_diffuse_homogeneous_unded": row[15],
        "money": row[16],
        "current_pv": row[17],
        "current_pf": row[18],
        "current_er": row[19],
        "current_points": row[20],
        "total_points": row[21],
    }


def get_character_profile_by_id(
    connection: sqlite3.Connection, character_id: int
) -> dict:
    """
    Retrieves the comprehensive attribute matrix for a specific character based
    exclusively on the denormalized 22-column schema using the primary character_id.
    """
    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT 
            character_id, owner_id, is_npc, name, st, dx, iq, ht, 
            additional_max_pv, additional_vont, additional_per, 
            additional_max_pf, additional_basic_speed, additional_basic_move, 
            energy_reserve, normal_diffuse_homogeneous_unded, money,
            current_pv, current_pf, current_er, current_points, total_points
        FROM characters 
        WHERE character_id = ?
        """,
        (character_id,),
    )

    row = cursor.fetchone()

    if row is None:
        raise ValueError(
            f"Database Anomaly: No character sheet linked to character_id {character_id}."
        )

    return {
        "character_id": row[0],
        "owner_id": row[1],
        "is_npc": bool(row[2]),
        "name": row[3],
        "st": row[4],
        "dx": row[5],
        "iq": row[6],
        "ht": row[7],
        "additional_max_pv": row[8],
        "additional_vont": row[9],
        "additional_per": row[10],
        "additional_max_pf": row[11],
        "additional_basic_speed": row[12],
        "additional_basic_move": row[13],
        "energy_reserve": row[14],
        "normal_diffuse_homogeneous_unded": row[15],
        "money": row[16],
        "current_pv": row[17],
        "current_pf": row[18],
        "current_er": row[19],
        "current_points": row[20],
        "total_points": row[21],
    }


def set_character_resource(
    connection: sqlite3.Connection, player_id: int, resource_name: str, new_value: int
) -> None:
    """
    Mutates the absolute value of a specific volatile resource directly
    within the foundational character matrix.
    """
    character_id = _resolve_character_id(connection, player_id)

    # Strict lexical mapping to prevent SQL Injection and ensure schema compliance.
    # This guarantees that regardless of what the Discord interface sends (hp, pv, current_pv),
    # the exact foundational column is targeted.
    column_mapping = {
        "hp": "current_pv",
        "pv": "current_pv",
        "current_pv": "current_pv",
        "fp": "current_pf",
        "pf": "current_pf",
        "current_pf": "current_pf",
        "er": "current_er",
        "re": "current_er",
        "current_er": "current_er",
    }

    sanitized_resource = resource_name.lower()

    if sanitized_resource not in column_mapping:
        raise ValueError(
            f"Lexical Anomaly: The resource '{resource_name}' does not map to any known volatile column."
        )

    target_column = column_mapping[sanitized_resource]
    cursor = connection.cursor()

    # String interpolation is strictly necessary as SQLite prohibits parameterizing column names.
    # It is mathematically safe here due to the hermetic validation of the column_mapping dictionary.
    cursor.execute(
        f"""
        UPDATE characters 
        SET {target_column} = ? 
        WHERE character_id = ?
        """,
        (new_value, character_id),
    )

    # Structural fallback: Since the denormalized paradigm dictates resources are inherent
    # to the character row, a failure to mutate implies the character entity has been purged.
    if cursor.rowcount == 0:
        raise ValueError(
            f"Relational Anomaly: Character entity {character_id} is absent from the foundational matrix."
        )

    connection.commit()


def get_character_thumbnail_by_id(
    connection: sqlite3.Connection, character_id: int
) -> tuple[discord.File | None, str | None]:
    """
    Core asset pipeline. Resolves character image path using the primary key
    and builds the binary stream and attachment URL for the Discord API.
    """
    project_root = Path(__file__).resolve().parent.parent
    image_directory = project_root / "data" / "images" / "characters"

    image_path = image_directory / f"{character_id}.png"
    default_fallback_path = image_directory / "default_character.png"

    # Validation pipeline to shield against FileNotFoundError
    if not image_path.exists():
        if default_fallback_path.exists():
            image_path = default_fallback_path
        else:
            return None, None

    # Using the verified character_id to map the network attachment name
    sealed_filename = f"char_{character_id}.png"

    discord_file = discord.File(image_path, filename=sealed_filename)
    attachment_url = f"attachment://{sealed_filename}"

    return discord_file, attachment_url


def get_character_thumbnail_payload(
    connection: sqlite3.Connection, player_id: int
) -> tuple[discord.File | None, str | None]:
    """
    Convenience wrapper for player-facing commands. Resolves the player_id
    to a character_id before invoking the core asset pipeline.
    """
    try:
        character_id = _resolve_character_id(connection, player_id)
    except ValueError:
        return None, None

    return get_character_thumbnail_by_id(connection, character_id)
<<<<<<< HEAD
=======

def get_character_inventory_data(
    connection: sqlite3.Connection, owner_id: int
) -> dict | None:
    """Fetches all equipped and stored melee weapons with attack modes, ranged weapons,
    modular armors, and items for the active character assigned to the owner."""
    cursor = connection.cursor()

    # 1. Resolve character identity
    cursor.execute(
        "SELECT character_id, name, money FROM characters WHERE owner_id = ?",
        (owner_id,),
    )
    char_row = cursor.fetchone()
    if not char_row:
        return None

    char_id, char_name, money = char_row

    # 2. Query Melee Weapons & Modes
    cursor.execute(
        """
        SELECT 
            cmw.character_melee_id,
            COALESCE(cmw.custom_name, w.name) AS weapon_name,
            w.melee_weapon_id,
            w.min_st,
            w.weight,
            w.cost,
            cmw.quantity,
            cmw.is_equipped
        FROM character_melee_weapons cmw
        JOIN melee_weapons w ON cmw.melee_weapon_id = w.melee_weapon_id
        WHERE cmw.character_id = ?
        ORDER BY cmw.is_equipped DESC, weapon_name ASC
        """,
        (char_id,),
    )
    melee_rows = cursor.fetchall()

    melee_weapons = []
    for row in melee_rows:
        inst_id, name, w_id, min_st, weight, cost, qty, is_eq = row

        # Query all attack modes for this specific physical weapon
        cursor.execute(
            """
            SELECT mode_name, skill_name, damage_base, damage_modifier, damage_type, reach, parry, notes
            FROM melee_weapon_modes
            WHERE melee_weapon_id = ?
            ORDER BY mode_id ASC
            """,
            (w_id,),
        )
        mode_rows = cursor.fetchall()
        modes = [
            {
                "mode_name": m[0],
                "skill_name": m[1],
                "damage_base": m[2],
                "damage_modifier": m[3],
                "damage_type": m[4],
                "reach": m[5],
                "parry": m[6],
                "notes": m[7],
            }
            for m in mode_rows
        ]

        melee_weapons.append(
            {
                "character_melee_id": inst_id,
                "name": name,
                "min_st": min_st,
                "weight": weight,
                "cost": cost,
                "quantity": qty,
                "is_equipped": is_eq,
                "modes": modes,
            }
        )

    # 3. Query Ranged Weapons
    cursor.execute(
        """
        SELECT 
            w.name,
            w.damage,
            w.acc,
            w.range_half,
            w.range_max,
            w.shots,
            w.weight,
            crw.quantity,
            crw.is_equipped
        FROM character_ranged_weapons crw
        JOIN ranged_weapons w ON crw.ranged_weapon_id = w.ranged_weapon_id
        WHERE crw.character_id = ?
        ORDER BY crw.is_equipped DESC, w.name ASC
        """,
        (char_id,),
    )
    ranged_weapons = [
        {
            "name": r[0],
            "damage": r[1],
            "acc": r[2],
            "range_half": r[3],
            "range_max": r[4],
            "shots": r[5],
            "weight": r[6],
            "quantity": r[7],
            "is_equipped": r[8],
        }
        for r in cursor.fetchall()
    ]

    # 4. Query Modular Armors
    cursor.execute(
        """
        SELECT 
            COALESCE(ca.custom_name, m.name || ' (' || bp.name || ')') AS piece_name,
            m.dr,
            m.is_flexible,
            bp.name AS location,
            (m.weight_torso * bp.cost_weight_factor) AS calc_weight,
            (m.cost_torso * bp.cost_weight_factor) AS calc_cost,
            ca.quantity,
            ca.is_equipped
        FROM character_armors ca
        JOIN armor_materials m ON ca.material_id = m.material_id
        JOIN body_parts bp ON ca.body_part_id = bp.body_part_id
        WHERE ca.character_id = ?
        ORDER BY ca.is_equipped DESC, bp.body_part_id ASC
        """,
        (char_id,),
    )
    armors = [
        {
            "name": a[0],
            "dr": a[1],
            "is_flexible": a[2],
            "location": a[3],
            "weight": a[4],
            "cost": a[5],
            "quantity": a[6],
            "is_equipped": a[7],
        }
        for a in cursor.fetchall()
    ]

    # 5. Query General Items
    cursor.execute(
        """
        SELECT i.name, i.weight, i.description, ci.quantity
        FROM character_items ci
        JOIN items i ON ci.item_id = i.item_id
        WHERE ci.character_id = ?
        ORDER BY i.name ASC
        """,
        (char_id,),
    )
    items = [
        {
            "name": it[0],
            "weight": it[1],
            "description": it[2],
            "quantity": it[3],
        }
        for it in cursor.fetchall()
    ]

    return {
        "character_id": char_id,
        "character_name": char_name,
        "money": money,
        "melee_weapons": melee_weapons,
        "ranged_weapons": ranged_weapons,
        "armors": armors,
        "items": items,
    }
>>>>>>> b1db456 (feat(inventory): add inventory system and slash command)
