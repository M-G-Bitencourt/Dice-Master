import discord
import json
import sqlite3
from pathlib import Path

from utils.combat import compute_encumbrance_penalty

# SQL FUNCTIONS (next_turn_conditions)
VALID_COLUMNS = {
    "aim",
    "evaluate",
    "shock",
    "feint",
}  # Valid structural columns to prevent unauthorized SQL string injection


def get_guild_locale(
    connection: sqlite3.Connection, guild_id: int
) -> str | None:
    """Return the stored language for one guild, if any."""
    row = connection.execute(
        "SELECT locale FROM guild_settings WHERE guild_id = ?",
        (int(guild_id),),
    ).fetchone()
    return str(row[0]) if row is not None and row[0] else None


def set_guild_locale(
    connection: sqlite3.Connection, guild_id: int, locale: str
) -> None:
    """Persist the language used by one guild."""
    connection.execute(
        """
        INSERT INTO guild_settings (guild_id, locale)
        VALUES (?, ?)
        ON CONFLICT(guild_id) DO UPDATE SET
            locale = excluded.locale,
            updated_at = CURRENT_TIMESTAMP
        """,
        (int(guild_id), str(locale)),
    )
    connection.commit()


def clear_guild_locale(
    connection: sqlite3.Connection, guild_id: int
) -> None:
    """Remove the guild language override."""
    connection.execute(
        "DELETE FROM guild_settings WHERE guild_id = ?",
        (int(guild_id),),
    )
    connection.commit()


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
        SET aim = 0, evaluate = 0, shock = 0, feint = 0,
            no_defense = 0, defense_bonus = 0
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
    on the denormalized 21-column schema, omitting any extraneous statistical queries.
    """
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT 
            character_id, owner_id, is_npc, name, st, dx, iq, ht, 
            additional_max_pv, additional_vont, additional_per, 
            additional_max_pf, additional_basic_speed, additional_basic_move, 
            energy_reserve, normal_diffuse_homogeneous_unded, money,
            current_pv, current_pf, current_er, current_points
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
    }


def get_character_profile_by_id(
    connection: sqlite3.Connection, character_id: int
) -> dict:
    """
    Retrieves the comprehensive attribute matrix for a specific character based exclusively
    on the denormalized 21-column schema using the primary character_id.
    """
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT 
            character_id, owner_id, is_npc, name, st, dx, iq, ht, 
            additional_max_pv, additional_vont, additional_per, 
            additional_max_pf, additional_basic_speed, additional_basic_move, 
            energy_reserve, normal_diffuse_homogeneous_unded, money,
            current_pv, current_pf, current_er, current_points
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


def get_character_inventory_data_by_id(
    connection: sqlite3.Connection, character_id: int
) -> dict | None:
    """Fetches all equipped and stored melee weapons with attack modes, ranged weapons,
    modular armors, and items for the character identified by its primary key."""
    cursor = connection.cursor()

    # 1. Resolve character identity
    cursor.execute(
        "SELECT character_id, name, money FROM characters WHERE character_id = ?",
        (character_id,),
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
            SELECT m.mode_name, m.skill_id, s.name AS skill_name,
                   m.damage_base, m.damage_modifier, m.damage_type,
                   m.reach, m.parry, m.notes
            FROM melee_weapon_modes m
            JOIN skills s ON m.skill_id = s.skill_id
            WHERE m.melee_weapon_id = ?
            ORDER BY m.mode_id ASC
            """,
            (w_id,),
        )
        mode_rows = cursor.fetchall()
        modes = [
            {
                "mode_name": m[0],
                "skill_id": m[1],
                "skill_name": m[2],
                "damage_base": m[3],
                "damage_modifier": m[4],
                "damage_type": m[5],
                "reach": m[6],
                "parry": m[7],
                "notes": m[8],
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


def get_character_inventory_data(
    connection: sqlite3.Connection, owner_id: int
) -> dict | None:
    """Resolves the active character assigned to the owner and delegates the inventory
    assembly to get_character_inventory_data_by_id."""
    cursor = connection.cursor()
    cursor.execute(
        "SELECT character_id FROM characters WHERE owner_id = ?",
        (owner_id,),
    )
    char_row = cursor.fetchone()
    if not char_row:
        return None

    return get_character_inventory_data_by_id(connection, char_row[0])


def modify_character_points(
    connection: sqlite3.Connection, character_id: int, delta_points: int
) -> tuple[str, int, int]:
    """
    Atomically increments or decrements a character's current_points (XP).
    Returns a tuple containing: (character_name, previous_points, updated_points).
    Raises ValueError if the character_id is not found in the database.
    """
    cursor = connection.cursor()
    cursor.execute(
        "SELECT name, current_points FROM characters WHERE character_id = ?",
        (character_id,),
    )
    row = cursor.fetchone()

    if row is None:
        raise ValueError(
            f"Database Anomaly: No character entity found with character_id {character_id}."
        )

    character_name = row[0]
    previous_points = row[1] if row[1] is not None else 0
    updated_points = previous_points + delta_points

    cursor.execute(
        "UPDATE characters SET current_points = ? WHERE character_id = ?",
        (updated_points, character_id),
    )
    connection.commit()

    return character_name, previous_points, updated_points


def _get_character_additional_stats_dict(
    connection: sqlite3.Connection, character_id: int
) -> dict[str, int]:
    """
    Queries the character_additional_stats table and returns a dictionary 
    mapping the stat name (uppercase) to its current value for the given character.
    """
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT ads.stat, cas.value
        FROM character_additional_stats cas
        JOIN additional_stats ads ON cas.additional_stat_id = ads.id_additional_stat
        WHERE cas.character_id = ?
        """,
        (character_id,),
    )
    return {str(row[0]).strip().upper(): int(row[1]) for row in cursor.fetchall()}


def get_character_skills_data(
    connection: sqlite3.Connection, character_id: int
) -> dict | None:
    """
    Retrieves the complete list of registered skills for a character,
    calculating effective skill levels (NH) based on foundational attributes,
    secondary characteristics (Per/Will), and relative skill levels.
    """
    cursor = connection.cursor()

    # 1. Fetch character foundational attributes and name
    cursor.execute(
        """
        SELECT 
            name, st, dx, iq, ht, additional_per, additional_vont
        FROM characters 
        WHERE character_id = ?
        """,
        (character_id,),
    )
    char_row = cursor.fetchone()
    if not char_row:
        return None

    char_name, st, dx, iq, ht, add_per, add_vont = char_row
    per = iq + (add_per or 0)
    vont = iq + (add_vont or 0)

    # 2. Fetch additional stats dictionary
    additional_stats = _get_character_additional_stats_dict(connection, character_id)

    # 3. Fetch associated skills joined with the global skills catalogue
    cursor.execute(
        """
        SELECT 
            s.skill_id,
            s.name,
            s.attribute,
            d.difficulty,
            s.description,
            cs.relative_level
        FROM character_skills cs
        JOIN skills s ON cs.skill_id = s.skill_id
        LEFT JOIN difficulties d ON s.difficulty_id = d.difficulty_id
        WHERE cs.character_id = ?
        ORDER BY s.name COLLATE NOCASE ASC
        """,
        (character_id,),
    )
    skill_rows = cursor.fetchall()

    skills_list = []
    for row in skill_rows:
        s_id, s_name, attr_raw, diff, desc, rel_level = row
        rel = rel_level if rel_level is not None else 0
        attr_norm = (attr_raw or "DX").strip().upper()

        # Map foundational attribute base
        if attr_norm in ("DX",):
            base_val = dx
            attr_label = "DX"
        elif attr_norm in ("IQ",):
            base_val = iq
            attr_label = "IQ"
        elif attr_norm in ("HT",):
            base_val = ht
            attr_label = "HT"
        elif attr_norm in ("ST",):
            base_val = st
            attr_label = "ST"
        elif attr_norm in ("PER", "PERCEPÇÃO", "PERCEPCAO"):
            base_val = per
            attr_label = "Per"
        elif attr_norm in ("VONT", "VONTADE", "WILL"):
            base_val = vont
            attr_label = "Vont"
        elif attr_norm in additional_stats:
            base_val = additional_stats[attr_norm]
            attr_label = attr_raw or attr_norm
        else:
            base_val = dx
            attr_label = attr_raw or "DX"

        # Calculate effective NH
        nh = base_val + rel
        rel_str = f"{attr_label}{rel:+d}"

        skills_list.append(
            {
                "skill_id": s_id,
                "name": s_name,
                "attribute": attr_label,
                "difficulty": diff or "M",
                "description": desc or "Nenhuma descrição detalhada disponível.",
                "relative_level": rel,
                "relative_display": rel_str,
                "nh": nh,
            }
        )

    return {
        "character_id": character_id,
        "character_name": char_name,
        "skills": skills_list,
    }


def get_character_spells_data(
    connection: sqlite3.Connection, character_id: int
) -> dict | None:
    """
    Retrieves the complete list of registered spells for a character,
    calculating effective NH based on foundational attributes and relative levels.
    Maps resources to normalized uppercase abbreviations (PV, PF, ER).
    Groups spells by their school (spell_class).
    """
    cursor = connection.cursor()

    # 1. Fetch character foundational attributes and name
    cursor.execute(
        """
        SELECT 
            name, st, dx, iq, ht, additional_per, additional_vont
        FROM characters 
        WHERE character_id = ?
        """,
        (character_id,),
    )
    char_row = cursor.fetchone()
    if not char_row:
        return None

    char_name, st, dx, iq, ht, add_per, add_vont = char_row
    per = iq + (add_per or 0)
    vont = iq + (add_vont or 0)

    # 2. Fetch additional stats dictionary
    additional_stats = _get_character_additional_stats_dict(connection, character_id)

    # 3. Fetch associated spells joined with the global spells catalogue and schools
    cursor.execute(
        """
        SELECT 
            m.spell_id,
            m.name,
            m.attribute,
            d.difficulty,
            m.cost,
            m.resource,
            m.description,
            cm.relative_level,
            mc.class
        FROM character_spells cm
        JOIN spells m ON cm.spell_id = m.spell_id
        LEFT JOIN spell_classes mc ON m.class = mc.spell_class_id
        LEFT JOIN difficulties d ON m.difficulty_id = d.difficulty_id
        WHERE cm.character_id = ?
        ORDER BY mc.class COLLATE NOCASE ASC, m.name COLLATE NOCASE ASC
        """,
        (character_id,),
    )
    spell_rows = cursor.fetchall()

    spells_list = []
    for row in spell_rows:
        m_id, m_name, attr_raw, diff, cost, res_raw, desc, rel_level, school = row
        rel = rel_level if rel_level is not None else 0
        attr_norm = (attr_raw or "IQ").strip().upper()

        # Map foundational attribute base
        if attr_norm in ("IQ",):
            base_val = iq
            attr_label = "IQ"
        elif attr_norm in ("DX",):
            base_val = dx
            attr_label = "DX"
        elif attr_norm in ("HT",):
            base_val = ht
            attr_label = "HT"
        elif attr_norm in ("ST",):
            base_val = st
            attr_label = "ST"
        elif attr_norm in ("PER", "PERCEPÇÃO", "PERCEPCAO"):
            base_val = per
            attr_label = "Per"
        elif attr_norm in ("VONT", "VONTADE", "WILL"):
            base_val = vont
            attr_label = "Vont"
        elif attr_norm in additional_stats:
            base_val = additional_stats[attr_norm]
            attr_label = attr_raw or attr_norm
        else:
            base_val = iq
            attr_label = attr_raw or "IQ"

        # Calculate effective NH
        nh = base_val + rel
        rel_str = f"{attr_label}{rel:+d}"

        # Resource mapping normalization
        res_label = (res_raw or "PF").strip().upper()

        spells_list.append(
            {
                "spell_id": m_id,
                "name": m_name,
                "school": school or "Sem Escola",
                "attribute": attr_label,
                "difficulty": diff or "M",
                "cost": cost or 0,
                "resource": res_label,
                "description": desc or "Nenhuma descrição detalhada disponível.",
                "relative_level": rel,
                "relative_display": rel_str,
                "nh": nh,
            }
        )

    return {
        "character_id": character_id,
        "character_name": char_name,
        "spells": spells_list,
    }


def get_character_traits_data(
    connection: sqlite3.Connection, character_id: int
) -> dict | None:
    """
    Retrieves the complete list of registered advantages and disadvantages
    for a character, along with the cost in character points and the
    player-specific notes stored for each trait instance.
    """
    cursor = connection.cursor()

    # 1. Fetch character name
    cursor.execute(
        "SELECT name FROM characters WHERE character_id = ?",
        (character_id,),
    )
    char_row = cursor.fetchone()
    if not char_row:
        return None

    char_name = char_row[0]

    # 2. Fetch associated advantages joined with the global advantages catalogue
    cursor.execute(
        """
        SELECT 
            a.advantage_id,
            a.name,
            a.cost,
            a.description,
            ca.notes
        FROM character_advantages ca
        JOIN advantages a ON ca.advantage_id = a.advantage_id
        WHERE ca.character_id = ?
        ORDER BY a.name COLLATE NOCASE ASC
        """,
        (character_id,),
    )
    advantages_list = [
        {
            "trait_key": f"adv_{row[0]}",
            "trait_id": row[0],
            "category": "Vantagem",
            "name": row[1],
            "cost": row[2] if row[2] is not None else 0,
            "description": row[3] or "Nenhuma descrição detalhada disponível.",
            "notes": row[4] or "",
        }
        for row in cursor.fetchall()
    ]

    # 3. Fetch associated disadvantages joined with the global disadvantages catalogue
    cursor.execute(
        """
        SELECT 
            d.disadvantage_id,
            d.name,
            d.cost,
            d.description,
            cd.notes
        FROM character_disadvantages cd
        JOIN disadvantages d ON cd.disadvantage_id = d.disadvantage_id
        WHERE cd.character_id = ?
        ORDER BY d.name COLLATE NOCASE ASC
        """,
        (character_id,),
    )
    disadvantages_list = [
        {
            "trait_key": f"dis_{row[0]}",
            "trait_id": row[0],
            "category": "Desvantagem",
            "name": row[1],
            "cost": row[2] if row[2] is not None else 0,
            "description": row[3] or "Nenhuma descrição detalhada disponível.",
            "notes": row[4] or "",
        }
        for row in cursor.fetchall()
    ]

    return {
        "character_id": character_id,
        "character_name": char_name,
        "advantages": advantages_list,
        "disadvantages": disadvantages_list,
    }


# SQL FUNCTIONS (combat)

_PENDING_ATTACK_COLUMNS = (
    "attack_id",
    "session_id",
    "guild_id",
    "channel_id",
    "message_id",
    "attacker_id",
    "attacker_character_id",
    "target_character_id",
    "target_owner_id",
    "weapon_name",
    "mode_name",
    "skill_name",
    "mode_id",
    "attack_kind",
    "ranged_weapon_id",
    "damage_expression",
    "maneuver",
    "custom_modifier",
    "nh_base",
    "nh_effective",
    "attack_roll",
    "attack_margin",
    "raw_damage",
    "critical_damage",
    "max_defense_attempts",
    "defense_attempts",
    "rd",
    "damage_type",
    "hit_location",
    "feint",
    "is_critical",
    "modifiers_json",
    "status",
    "created_at",
    "expires_at",
    "resolved_at",
)

_PENDING_ATTACK_SELECT = ", ".join(_PENDING_ATTACK_COLUMNS)


def _pending_attack_dict(row) -> dict | None:
    """Convert a pending-attack row into a named dictionary."""
    if row is None:
        return None
    return dict(zip(_PENDING_ATTACK_COLUMNS, row))


def get_character_conditions_by_id(
    connection: sqlite3.Connection, character_id: int
) -> dict:
    """Return the transient combat conditions for one character primary key."""
    row = connection.execute(
        """
        SELECT aim, evaluate, shock, feint, no_defense, defense_bonus
        FROM next_turn_conditions
        WHERE character_id = ?
        """,
        (character_id,),
    ).fetchone()

    if row is None:
        return {
            "aim": 0,
            "evaluate": 0,
            "shock": 0,
            "feint": 0,
            "no_defense": 0,
            "defense_bonus": 0,
        }

    return {
        "aim": int(row[0] or 0),
        "evaluate": int(row[1] or 0),
        "shock": int(row[2] or 0),
        "feint": int(row[3] or 0),
        "no_defense": int(row[4] or 0),
        "defense_bonus": int(row[5] or 0),
    }


def clear_character_conditions(
    connection: sqlite3.Connection, character_id: int
) -> None:
    """Reset every transient condition for a character without committing."""
    connection.execute(
        """
        UPDATE next_turn_conditions
        SET aim = 0, evaluate = 0, shock = 0, feint = 0,
            no_defense = 0, defense_bonus = 0
        WHERE character_id = ?
        """,
        (character_id,),
    )


def set_character_feint(
    connection: sqlite3.Connection, character_id: int, value: int
) -> None:
    """Store the feint penalty produced by the character's last feint."""
    connection.execute(
        """
        INSERT INTO next_turn_conditions (character_id, feint)
        VALUES (?, ?)
        ON CONFLICT(character_id) DO UPDATE SET
            feint = excluded.feint
        """,
        (character_id, max(0, int(value))),
    )


def set_character_shock(
    connection: sqlite3.Connection, character_id: int, value: int
) -> None:
    """Store the pending shock penalty for one character without committing."""
    connection.execute(
        """
        INSERT INTO next_turn_conditions (character_id, shock)
        VALUES (?, ?)
        ON CONFLICT(character_id) DO UPDATE SET
            shock = excluded.shock
        """,
        (character_id, min(4, max(0, int(value)))),
    )


def clear_character_shock(
    connection: sqlite3.Connection, character_id: int
) -> None:
    """Clear the pending shock penalty for one character without committing."""
    set_character_shock(connection, character_id, 0)


def set_character_combat_stance(
    connection: sqlite3.Connection,
    character_id: int,
    *,
    no_defense: int,
    defense_bonus: int,
) -> None:
    """Store the defensive consequences of the character's last maneuver."""
    connection.execute(
        """
        INSERT INTO next_turn_conditions (
            character_id, aim, evaluate, shock, feint, no_defense, defense_bonus
        )
        VALUES (?, 0, 0, 0, 0, ?, ?)
        ON CONFLICT(character_id) DO UPDATE SET
            no_defense = excluded.no_defense,
            defense_bonus = excluded.defense_bonus
        """,
        (character_id, int(no_defense), int(defense_bonus)),
    )


def get_equipped_melee_modes(
    connection: sqlite3.Connection, character_id: int
) -> list[dict]:
    """Return equipped modes plus available internal unarmed modes."""
    rows = connection.execute(
        """
        SELECT * FROM (
            SELECT
                cmw.character_melee_id,
                w.melee_weapon_id,
                COALESCE(cmw.custom_name, w.name) AS weapon_name,
                w.min_st,
                w.weight,
                cmw.quantity,
                m.mode_id,
                m.mode_name,
                m.skill_id,
                s.name AS skill_name,
                m.damage_base,
                m.damage_modifier,
                m.damage_type,
                m.reach,
                m.parry,
                m.notes,
                w.is_unarmed,
                w.is_fallback,
                m.attack_modifier
            FROM character_melee_weapons cmw
            JOIN melee_weapons w ON cmw.melee_weapon_id = w.melee_weapon_id
            JOIN melee_weapon_modes m ON w.melee_weapon_id = m.melee_weapon_id
            JOIN skills s ON m.skill_id = s.skill_id
            WHERE cmw.character_id = ?
              AND cmw.is_equipped = 1
              AND w.is_unarmed = 0

            UNION ALL

            SELECT
                NULL,
                w.melee_weapon_id,
                w.name,
                w.min_st,
                w.weight,
                1,
                m.mode_id,
                m.mode_name,
                m.skill_id,
                s.name,
                m.damage_base,
                m.damage_modifier,
                m.damage_type,
                m.reach,
                m.parry,
                m.notes,
                w.is_unarmed,
                w.is_fallback,
                m.attack_modifier
            FROM melee_weapons w
            JOIN melee_weapon_modes m ON w.melee_weapon_id = m.melee_weapon_id
            JOIN skills s ON m.skill_id = s.skill_id
            WHERE w.is_unarmed = 1
              AND w.is_fallback = 0
              AND EXISTS (
                  SELECT 1
                  FROM character_skills cs
                  WHERE cs.character_id = ?
                    AND cs.skill_id = m.skill_id
              )

            UNION ALL

            SELECT
                NULL,
                w.melee_weapon_id,
                w.name,
                w.min_st,
                w.weight,
                1,
                m.mode_id,
                m.mode_name,
                m.skill_id,
                s.name,
                m.damage_base,
                m.damage_modifier,
                m.damage_type,
                m.reach,
                m.parry,
                m.notes,
                w.is_unarmed,
                w.is_fallback,
                m.attack_modifier
            FROM melee_weapons w
            JOIN melee_weapon_modes m ON w.melee_weapon_id = m.melee_weapon_id
            LEFT JOIN skills s ON m.skill_id = s.skill_id
            WHERE w.is_unarmed = 1
              AND w.is_fallback = 1
              AND NOT EXISTS (
                  SELECT 1
                  FROM character_skills cs
                  JOIN melee_weapon_modes sm ON sm.skill_id = cs.skill_id
                  JOIN melee_weapons sw ON sw.melee_weapon_id = sm.melee_weapon_id
                  WHERE cs.character_id = ?
                    AND sw.is_unarmed = 1
                    AND sw.is_fallback = 0
              )
        )
        ORDER BY is_unarmed ASC, weapon_name COLLATE NOCASE ASC, mode_id ASC
        """,
        (character_id, character_id, character_id),
    ).fetchall()

    return [
        {
            "character_melee_id": row[0],
            "melee_weapon_id": row[1],
            "weapon_name": row[2],
            "min_st": row[3],
            "weight": row[4],
            "quantity": row[5],
            "mode_id": row[6],
            "mode_name": row[7],
            "skill_id": row[8],
            "skill_name": row[9],
            "damage_base": row[10],
            "damage_modifier": row[11],
            "damage_type": row[12],
            "reach": row[13],
            "parry": row[14],
            "notes": row[15],
            "is_unarmed": bool(row[16]),
            "is_fallback": bool(row[17]),
            "attack_modifier": int(row[18] or 0),
        }
        for row in rows
    ]


def get_equipped_armor_layers(
    connection: sqlite3.Connection, character_id: int
) -> list[dict]:
    """Return every equipped armour layer with its body part and layer order."""
    rows = connection.execute(
        """
        SELECT
            ca.character_armor_id,
            COALESCE(ca.custom_name, m.name || ' (' || bp.name || ')') AS piece_name,
            bp.name AS body_part,
            m.dr,
            m.is_flexible,
            ca.layer_order,
            ca.quantity
        FROM character_armors ca
        JOIN armor_materials m ON ca.material_id = m.material_id
        JOIN body_parts bp ON ca.body_part_id = bp.body_part_id
        WHERE ca.character_id = ? AND ca.is_equipped = 1
        ORDER BY ca.layer_order ASC, ca.character_armor_id ASC
        """,
        (character_id,),
    ).fetchall()

    return [
        {
            "character_armor_id": row[0],
            "name": row[1],
            "body_part": row[2],
            "dr": row[3],
            "is_flexible": bool(row[4]),
            "layer_order": int(row[5] or 0),
            "quantity": int(row[6] or 1),
        }
        for row in rows
    ]


def get_character_carried_weight(
    connection: sqlite3.Connection, character_id: int
) -> float:
    """Return the total carried weight used by the encumbrance calculation."""
    row = connection.execute(
        """
        SELECT COALESCE(SUM(weight), 0.0)
        FROM (
            SELECT w.weight * COALESCE(cmw.quantity, 1) AS weight
            FROM character_melee_weapons cmw
            JOIN melee_weapons w ON cmw.melee_weapon_id = w.melee_weapon_id
            WHERE cmw.character_id = ?
            UNION ALL
            SELECT w.weight * COALESCE(crw.quantity, 1) AS weight
            FROM character_ranged_weapons crw
            JOIN ranged_weapons w ON crw.ranged_weapon_id = w.ranged_weapon_id
            WHERE crw.character_id = ?
            UNION ALL
            SELECT
                m.weight_torso * bp.cost_weight_factor * COALESCE(ca.quantity, 1)
            FROM character_armors ca
            JOIN armor_materials m ON ca.material_id = m.material_id
            JOIN body_parts bp ON ca.body_part_id = bp.body_part_id
            WHERE ca.character_id = ?
            UNION ALL
            SELECT i.weight * COALESCE(ci.quantity, 1) AS weight
            FROM character_items ci
            JOIN items i ON ci.item_id = i.item_id
            WHERE ci.character_id = ?
        )
        """,
        (character_id, character_id, character_id, character_id),
    ).fetchone()

    return float(row[0] if row and row[0] is not None else 0.0)


def get_character_combat_data(
    connection: sqlite3.Connection, character_id: int
) -> dict | None:
    """Assemble the profile, skills, conditions, weapons, armour and weight."""
    profile = get_character_profile_by_id(connection, character_id)
    skills_data = get_character_skills_data(connection, character_id)
    if not skills_data:
        return None

    skills = skills_data["skills"]
    skill_by_id = {
        int(skill["skill_id"]): skill
        for skill in skills
    }
    carried_weight = get_character_carried_weight(connection, character_id)
    encumbrance_penalty = compute_encumbrance_penalty(
        carried_weight, int(profile["st"])
    )

    return {
        "profile": profile,
        "skills": skills,
        "skill_by_id": skill_by_id,
        "conditions": get_character_conditions_by_id(connection, character_id),
        "melee_modes": get_equipped_melee_modes(connection, character_id),
        "armor_layers": get_equipped_armor_layers(connection, character_id),
        "carried_weight": carried_weight,
        "encumbrance_penalty": encumbrance_penalty,
    }


def get_active_combat_session(
    connection: sqlite3.Connection, channel_id: int
) -> dict | None:
    """Return the active combat session for one channel, if any."""
    row = connection.execute(
        """
        SELECT session_id, guild_id, channel_id, status, round_number,
               active_character_id, panel_message_id, created_at, closed_at
        FROM combat_sessions
        WHERE channel_id = ? AND status = 'active'
        """,
        (channel_id,),
    ).fetchone()

    if row is None:
        return None

    return {
        "session_id": row[0],
        "guild_id": row[1],
        "channel_id": row[2],
        "status": row[3],
        "round_number": int(row[4] or 1),
        "active_character_id": row[5],
        "panel_message_id": row[6],
        "created_at": row[7],
        "closed_at": row[8],
    }


def get_or_create_combat_session(
    connection: sqlite3.Connection, guild_id: int | None, channel_id: int
) -> dict:
    """Return the active session for a channel, creating one when needed."""
    session = get_active_combat_session(connection, channel_id)
    if session is not None:
        return session

    cursor = connection.execute(
        """
        INSERT INTO combat_sessions (guild_id, channel_id, status)
        VALUES (?, ?, 'active')
        """,
        (guild_id, channel_id),
    )

    return {
        "session_id": int(cursor.lastrowid),
        "guild_id": guild_id,
        "channel_id": channel_id,
        "status": "active",
        "round_number": 1,
        "active_character_id": None,
        "panel_message_id": None,
        "created_at": None,
        "closed_at": None,
    }


def close_combat_session(
    connection: sqlite3.Connection, channel_id: int
) -> None:
    """Close the active session for a channel without committing."""
    connection.execute(
        """
        UPDATE combat_sessions
        SET status = 'closed', closed_at = CURRENT_TIMESTAMP
        WHERE channel_id = ? AND status = 'active'
        """,
        (channel_id,),
    )


def supersede_pending_attacks(
    connection: sqlite3.Connection, channel_id: int
) -> list[int]:
    """Discard every pending attack in a channel and return their message ids."""
    rows = connection.execute(
        """
        SELECT attack_id, message_id
        FROM pending_attacks
        WHERE channel_id = ? AND status IN ('pending', 'resolving')
        """,
        (channel_id,),
    ).fetchall()

    connection.execute(
        """
        UPDATE pending_attacks
        SET status = 'superseded', resolved_at = CURRENT_TIMESTAMP
        WHERE channel_id = ? AND status IN ('pending', 'resolving')
        """,
        (channel_id,),
    )

    return [int(row[1]) for row in rows if row[1] is not None]


def create_pending_attack(
    connection: sqlite3.Connection,
    *,
    session_id: int | None,
    guild_id: int | None,
    channel_id: int,
    attacker_id: int,
    attacker_character_id: int,
    target_character_id: int,
    target_owner_id: int | None,
    weapon_name: str,
    mode_name: str | None,
    skill_name: str | None,
    mode_id: int | None,
    attack_kind: str,
    ranged_weapon_id: int | None,
    damage_expression: str | None,
    maneuver: str | None,
    custom_modifier: int,
    nh_base: int,
    nh_effective: int,
    attack_roll: int,
    attack_margin: int,
    raw_damage: int,
    critical_damage: int,
    max_defense_attempts: int,
    defense_attempts: int,
    rd: int,
    damage_type: int,
    hit_location: int,
    feint: int,
    is_critical: int,
    modifiers_json: str | None,
) -> int:
    """Insert one pending attack and return its primary key."""
    cursor = connection.execute(
        """
        INSERT INTO pending_attacks (
            session_id, guild_id, channel_id,
            attacker_id, attacker_character_id, target_character_id, target_owner_id,
            weapon_name, mode_name, skill_name, mode_id,
            attack_kind, ranged_weapon_id, damage_expression,
            maneuver, custom_modifier,
            nh_base, nh_effective, attack_roll, attack_margin,
            raw_damage, critical_damage, max_defense_attempts, defense_attempts,
            rd, damage_type, hit_location,
            feint, is_critical, modifiers_json, expires_at
        )
        VALUES (
            ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?,
            ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?,
            ?, ?, ?,
            datetime('now', '+15 minutes')
        )
        """,
        (
            session_id,
            guild_id,
            channel_id,
            attacker_id,
            attacker_character_id,
            target_character_id,
            target_owner_id,
            weapon_name,
            mode_name,
            skill_name,
            mode_id,
            attack_kind,
            ranged_weapon_id,
            damage_expression,
            maneuver,
            custom_modifier,
            nh_base,
            nh_effective,
            attack_roll,
            attack_margin,
            raw_damage,
            critical_damage,
            max_defense_attempts,
            defense_attempts,
            rd,
            damage_type,
            hit_location,
            feint,
            is_critical,
            modifiers_json,
        ),
    )
    return int(cursor.lastrowid)


def get_pending_attack(
    connection: sqlite3.Connection, attack_id: int
) -> dict | None:
    """Return one pending attack by primary key."""
    row = connection.execute(
        f"SELECT {_PENDING_ATTACK_SELECT} FROM pending_attacks WHERE attack_id = ?",
        (attack_id,),
    ).fetchone()
    return _pending_attack_dict(row)


def get_pending_attack_for_channel(
    connection: sqlite3.Connection, channel_id: int
) -> dict | None:
    """Return the current pending attack in a channel, if any."""
    row = connection.execute(
        f"""
        SELECT {_PENDING_ATTACK_SELECT}
        FROM pending_attacks
        WHERE channel_id = ? AND status IN ('pending', 'resolving')
        ORDER BY attack_id DESC
        LIMIT 1
        """,
        (channel_id,),
    ).fetchone()
    return _pending_attack_dict(row)


def claim_pending_attack(
    connection: sqlite3.Connection, attack_id: int
) -> dict | None:
    """Atomically move a pending attack to resolving and return its snapshot."""
    row = connection.execute(
        f"""
        UPDATE pending_attacks
        SET status = 'resolving'
        WHERE attack_id = ?
          AND status = 'pending'
          AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)
        RETURNING {_PENDING_ATTACK_SELECT}
        """,
        (attack_id,),
    ).fetchone()
    return _pending_attack_dict(row)


def finish_pending_attack(
    connection: sqlite3.Connection, attack_id: int, status: str = "resolved"
) -> None:
    """Finish a claimed pending attack without committing."""
    connection.execute(
        """
        UPDATE pending_attacks
        SET status = ?, resolved_at = CURRENT_TIMESTAMP
        WHERE attack_id = ?
        """,
        (status, attack_id),
    )


def expire_pending_attack(
    connection: sqlite3.Connection, attack_id: int
) -> None:
    """Mark one pending attack as expired without committing."""
    connection.execute(
        """
        UPDATE pending_attacks
        SET status = 'expired', resolved_at = CURRENT_TIMESTAMP
        WHERE attack_id = ? AND status IN ('pending', 'resolving')
        """,
        (attack_id,),
    )


def apply_character_injury(
    connection: sqlite3.Connection, character_id: int, injury: int
) -> tuple[int, int]:
    """Apply injury to a character's current PV and return old and new values."""
    row = connection.execute(
        "SELECT current_pv FROM characters WHERE character_id = ?",
        (character_id,),
    ).fetchone()
    if row is None:
        raise ValueError(
            f"Database Anomaly: No character sheet linked to character_id {character_id}."
        )

    current_pv = int(row[0] or 0)
    new_pv = current_pv - int(injury)
    connection.execute(
        "UPDATE characters SET current_pv = ? WHERE character_id = ?",
        (new_pv, character_id),
    )
    return current_pv, new_pv


def update_pending_attack_message(
    connection: sqlite3.Connection, attack_id: int, message_id: int
) -> None:
    """Attach the Discord message id to a pending attack without committing."""
    connection.execute(
        "UPDATE pending_attacks SET message_id = ? WHERE attack_id = ?",
        (message_id, attack_id),
    )


def get_all_equipped_melee_modes(
    connection: sqlite3.Connection, search: str = "", limit: int = 25
) -> list[dict]:
    """Return equipped melee modes across characters for GM autocomplete."""
    pattern = f"%{search.strip()}%"
    rows = connection.execute(
        """
        SELECT
            c.character_id,
            c.name AS character_name,
            c.is_npc,
            COALESCE(cmw.custom_name, w.name) AS weapon_name,
            m.mode_id,
            m.mode_name,
            m.skill_id,
            s.name AS skill_name
        FROM character_melee_weapons cmw
        JOIN characters c ON cmw.character_id = c.character_id
        JOIN melee_weapons w ON cmw.melee_weapon_id = w.melee_weapon_id
        JOIN melee_weapon_modes m ON w.melee_weapon_id = m.melee_weapon_id
        JOIN skills s ON m.skill_id = s.skill_id
        WHERE cmw.is_equipped = 1
          AND (
              c.name LIKE ?
              OR COALESCE(cmw.custom_name, w.name) LIKE ?
              OR m.mode_name LIKE ?
          )
        ORDER BY c.name COLLATE NOCASE ASC, weapon_name COLLATE NOCASE ASC, m.mode_id ASC
        LIMIT ?
        """,
        (pattern, pattern, pattern, int(limit)),
    ).fetchall()

    return [
        {
            "character_id": row[0],
            "character_name": row[1],
            "is_npc": bool(row[2]),
            "weapon_name": row[3],
            "mode_id": row[4],
            "mode_name": row[5],
            "skill_id": row[6],
            "skill_name": row[7],
        }
        for row in rows
    ]


def get_active_combat_sessions(connection: sqlite3.Connection) -> list[dict]:
    """Return every active combat session for persistent panel registration."""
    rows = connection.execute(
        """
        SELECT session_id, guild_id, channel_id, status, round_number,
               active_character_id, panel_message_id, created_at, closed_at
        FROM combat_sessions
        WHERE status = 'active'
        ORDER BY channel_id ASC
        """
    ).fetchall()

    return [
        {
            "session_id": row[0],
            "guild_id": row[1],
            "channel_id": row[2],
            "status": row[3],
            "round_number": int(row[4] or 1),
            "active_character_id": row[5],
            "panel_message_id": row[6],
            "created_at": row[7],
            "closed_at": row[8],
        }
        for row in rows
    ]


def get_character_combat_effects(
    connection: sqlite3.Connection,
    character_id: int,
) -> list[dict]:
    """Return the catalog effects linked to one character."""
    rows = connection.execute(
        """
        SELECT e.effect_id, ce.character_id, e.name, e.applies_to, e.target,
               e.value, e.uses_per_turn, e.notes
        FROM character_combat_effects ce
        JOIN combat_effects e ON ce.effect_id = e.effect_id
        WHERE ce.character_id = ?
        ORDER BY e.effect_id ASC
        """,
        (character_id,),
    ).fetchall()

    return [
        {
            "effect_id": row[0],
            "character_id": row[1],
            "name": row[2],
            "applies_to": row[3],
            "target": row[4],
            "value": int(row[5] or 0),
            "uses_per_turn": int(row[6] or 0),
            "notes": row[7],
        }
        for row in rows
    ]


def get_combat_effect(
    connection: sqlite3.Connection, effect_id: int
) -> dict | None:
    """Return one effect from the external catalog by primary key."""
    row = connection.execute(
        """
        SELECT effect_id, name, applies_to, target, value, uses_per_turn, notes
        FROM combat_effects
        WHERE effect_id = ?
        """,
        (effect_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "effect_id": row[0],
        "name": row[1],
        "applies_to": row[2],
        "target": row[3],
        "value": int(row[4] or 0),
        "uses_per_turn": int(row[5] or 0),
        "notes": row[6],
    }


def get_character_effect_link(
    connection: sqlite3.Connection, character_id: int, effect_id: int
) -> bool:
    """Return True when the catalog effect is linked to the character."""
    row = connection.execute(
        """
        SELECT 1
        FROM character_combat_effects
        WHERE character_id = ? AND effect_id = ?
        """,
        (character_id, effect_id),
    ).fetchone()
    return row is not None


def link_character_effect(
    connection: sqlite3.Connection, character_id: int, effect_id: int
) -> bool:
    """Link a catalog effect to a character; return False when already linked."""
    cursor = connection.execute(
        """
        INSERT INTO character_combat_effects (character_id, effect_id)
        VALUES (?, ?)
        ON CONFLICT(character_id, effect_id) DO NOTHING
        """,
        (character_id, effect_id),
    )
    return cursor.rowcount > 0


def unlink_character_effect(
    connection: sqlite3.Connection, character_id: int, effect_id: int
) -> bool:
    """Remove one effect link; return False when it was not linked."""
    cursor = connection.execute(
        """
        DELETE FROM character_combat_effects
        WHERE character_id = ? AND effect_id = ?
        """,
        (character_id, effect_id),
    )
    return cursor.rowcount > 0


def ensure_combat_participant(
    connection: sqlite3.Connection,
    *,
    session_id: int,
    character_id: int,
    owner_id: int | None,
    is_npc: int,
    initiative: float | None = None,
) -> dict:
    """Create or refresh the participant row and return its parsed state."""
    connection.execute(
        """
        INSERT INTO combat_participants (
            session_id, character_id, owner_id, is_npc, initiative
        )
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(session_id, character_id) DO UPDATE SET
            owner_id = excluded.owner_id,
            is_npc = excluded.is_npc
        """,
        (
            session_id,
            character_id,
            owner_id,
            1 if is_npc else 0,
            0.0 if initiative is None else float(initiative),
        ),
    )
    if initiative is not None:
        connection.execute(
            """
            UPDATE combat_participants
            SET initiative = ?
            WHERE session_id = ? AND character_id = ?
            """,
            (float(initiative), session_id, character_id),
        )
    participant = get_combat_participant(connection, session_id, character_id)
    if participant is None:
        raise ValueError("Combat participant could not be created.")
    return participant


def get_combat_participant(
    connection: sqlite3.Connection, session_id: int, character_id: int
) -> dict | None:
    """Return one participant with decoded use counters."""
    row = connection.execute(
        """
        SELECT session_id, character_id, owner_id, is_npc, initiative,
               defense_uses_json, effect_uses_json, created_at
        FROM combat_participants
        WHERE session_id = ? AND character_id = ?
        """,
        (session_id, character_id),
    ).fetchone()
    if row is None:
        return None

    try:
        defense_uses = json.loads(row[5] or "{}")
    except json.JSONDecodeError:
        defense_uses = {}
    try:
        effect_uses = json.loads(row[6] or "{}")
    except json.JSONDecodeError:
        effect_uses = {}

    return {
        "session_id": row[0],
        "character_id": row[1],
        "owner_id": row[2],
        "is_npc": bool(row[3]),
        "initiative": float(row[4] or 0),
        "defense_uses": defense_uses,
        "effect_uses": effect_uses,
        "created_at": row[7],
    }


def record_participant_use(
    connection: sqlite3.Connection,
    *,
    session_id: int,
    character_id: int,
    field: str,
    key: str,
) -> dict:
    """Increment one defense or effect use counter for a participant."""
    if field not in {"defense_uses", "effect_uses"}:
        raise ValueError(f"Invalid participant use field: {field}")

    participant = get_combat_participant(connection, session_id, character_id)
    if participant is None:
        raise ValueError("Combat participant not found.")

    counters = dict(participant[field])
    counters[str(key)] = int(counters.get(str(key), 0)) + 1

    column = "defense_uses_json" if field == "defense_uses" else "effect_uses_json"
    connection.execute(
        f"UPDATE combat_participants SET {column} = ? "
        "WHERE session_id = ? AND character_id = ?",
        (json.dumps(counters), session_id, character_id),
    )
    participant[field] = counters
    return participant


def reset_combat_participant_turn(
    connection: sqlite3.Connection, session_id: int, character_id: int
) -> None:
    """Reset per-turn defense and effect uses for one participant."""
    connection.execute(
        """
        UPDATE combat_participants
        SET defense_uses_json = '{}', effect_uses_json = '{}'
        WHERE session_id = ? AND character_id = ?
        """,
        (session_id, character_id),
    )


def get_combat_participants(
    connection: sqlite3.Connection, session_id: int
) -> list[dict]:
    """Return every participant in a combat session."""
    rows = connection.execute(
        """
        SELECT cp.session_id, cp.character_id, cp.owner_id, cp.is_npc,
               cp.initiative, cp.defense_uses_json, cp.effect_uses_json,
               cp.created_at, c.name
        FROM combat_participants cp
        JOIN characters c ON cp.character_id = c.character_id
        WHERE cp.session_id = ?
        ORDER BY cp.initiative DESC, cp.character_id ASC
        """,
        (session_id,),
    ).fetchall()

    participants = []
    for row in rows:
        try:
            defense_uses = json.loads(row[5] or "{}")
        except json.JSONDecodeError:
            defense_uses = {}
        try:
            effect_uses = json.loads(row[6] or "{}")
        except json.JSONDecodeError:
            effect_uses = {}
        participants.append(
            {
                "session_id": row[0],
                "character_id": row[1],
                "owner_id": row[2],
                "is_npc": bool(row[3]),
                "initiative": float(row[4] or 0),
                "defense_uses": defense_uses,
                "effect_uses": effect_uses,
                "created_at": row[7],
                "character_name": row[8],
            }
        )
    return participants


def spend_character_resource(
    connection: sqlite3.Connection,
    character_id: int,
    resource_type: str,
    cost: int,
) -> tuple[int, int] | None:
    """Spend PF or ER for an effect and return the old and new values."""
    column_map = {"pf": "current_pf", "er": "current_er"}
    column = column_map.get(str(resource_type).lower())
    if column is None or int(cost) <= 0:
        return None

    row = connection.execute(
        f"SELECT {column} FROM characters WHERE character_id = ?",
        (character_id,),
    ).fetchone()
    if row is None:
        return None

    old_value = int(row[0] or 0)
    new_value = max(0, old_value - int(cost))
    connection.execute(
        f"UPDATE characters SET {column} = ? WHERE character_id = ?",
        (new_value, character_id),
    )
    return old_value, new_value



def update_pending_attack_attempts(
    connection: sqlite3.Connection,
    attack_id: int,
    defense_attempts: int,
    status: str = "pending",
) -> None:
    """Store the number of defense attempts and reopen or close the attack."""
    connection.execute(
        """
        UPDATE pending_attacks
        SET defense_attempts = ?, status = ?
        WHERE attack_id = ?
        """,
        (int(defense_attempts), status, attack_id),
    )


def set_character_aim_evaluate(
    connection: sqlite3.Connection,
    character_id: int,
    *,
    aim: int | None = None,
    evaluate: int | None = None,
) -> None:
    """Set aim/evaluate conditions and clear the defensive stance."""
    current = get_character_conditions_by_id(connection, character_id)
    new_aim = current["aim"] if aim is None else int(aim)
    new_evaluate = current["evaluate"] if evaluate is None else int(evaluate)

    connection.execute(
        """
        INSERT INTO next_turn_conditions (
            character_id, aim, evaluate, shock, feint, no_defense, defense_bonus
        )
        VALUES (?, ?, ?, ?, ?, 0, 0)
        ON CONFLICT(character_id) DO UPDATE SET
            aim = excluded.aim,
            evaluate = excluded.evaluate,
            no_defense = 0,
            defense_bonus = 0
        """,
        (
            character_id,
            new_aim,
            new_evaluate,
            current["shock"],
            current["feint"],
        ),
    )


def get_equipped_ranged_weapons(
    connection: sqlite3.Connection, character_id: int
) -> list[dict]:
    """Return the character's equipped ranged weapons."""
    rows = connection.execute(
        """
        SELECT
            crw.character_ranged_id,
            w.ranged_weapon_id,
            w.name,
            w.skill_id,
            s.name AS skill_name,
            w.damage,
            w.acc,
            w.range_half,
            w.range_max,
            w.rof,
            w.shots,
            w.min_st,
            w.recoil,
            w.weight,
            w.cost,
            crw.quantity,
            crw.current_shots
        FROM character_ranged_weapons crw
        JOIN ranged_weapons w ON crw.ranged_weapon_id = w.ranged_weapon_id
        LEFT JOIN skills s ON w.skill_id = s.skill_id
        WHERE crw.character_id = ? AND crw.is_equipped = 1
        ORDER BY w.name COLLATE NOCASE ASC
        """,
        (character_id,),
    ).fetchall()

    return [
        {
            "character_ranged_id": row[0],
            "ranged_weapon_id": row[1],
            "weapon_name": row[2],
            "skill_id": row[3],
            "skill_name": row[4],
            "damage": row[5],
            "acc": row[6],
            "range_half": row[7],
            "range_max": row[8],
            "rof": row[9],
            "shots": row[10],
            "min_st": row[11],
            "recoil": row[12],
            "weight": row[13],
            "cost": row[14],
            "quantity": row[15],
            "current_shots": row[16],
        }
        for row in rows
    ]


def get_all_equipped_ranged_weapons(
    connection: sqlite3.Connection, search: str = "", limit: int = 25
) -> list[dict]:
    """Return equipped ranged weapons across characters for GM autocomplete."""
    pattern = f"%{search.strip()}%"
    rows = connection.execute(
        """
        SELECT
            c.character_id,
            c.name AS character_name,
            c.is_npc,
            w.name,
            w.ranged_weapon_id,
            w.damage,
            w.skill_id,
            s.name AS skill_name
        FROM character_ranged_weapons crw
        JOIN characters c ON crw.character_id = c.character_id
        JOIN ranged_weapons w ON crw.ranged_weapon_id = w.ranged_weapon_id
        LEFT JOIN skills s ON w.skill_id = s.skill_id
        WHERE crw.is_equipped = 1
          AND (c.name LIKE ? OR w.name LIKE ?)
        ORDER BY c.name COLLATE NOCASE ASC, w.name COLLATE NOCASE ASC
        LIMIT ?
        """,
        (pattern, pattern, int(limit)),
    ).fetchall()

    return [
        {
            "character_id": row[0],
            "character_name": row[1],
            "is_npc": bool(row[2]),
            "weapon_name": row[3],
            "ranged_weapon_id": row[4],
            "damage": row[5],
            "skill_id": row[6],
            "skill_name": row[7],
        }
        for row in rows
    ]


def set_combat_session_active(
    connection: sqlite3.Connection,
    session_id: int,
    active_character_id: int | None,
    round_number: int,
) -> None:
    """Store the active character and current round without committing."""
    connection.execute(
        """
        UPDATE combat_sessions
        SET active_character_id = ?, round_number = ?
        WHERE session_id = ?
        """,
        (active_character_id, int(round_number), session_id),
    )


def set_combat_session_panel(
    connection: sqlite3.Connection, session_id: int, message_id: int
) -> None:
    """Attach the public panel message id to a session without committing."""
    connection.execute(
        "UPDATE combat_sessions SET panel_message_id = ? WHERE session_id = ?",
        (message_id, session_id),
    )


def set_participant_initiative(
    connection: sqlite3.Connection,
    session_id: int,
    character_id: int,
    initiative: float,
) -> None:
    """Set one participant's initiative without committing."""
    connection.execute(
        """
        UPDATE combat_participants
        SET initiative = ?
        WHERE session_id = ? AND character_id = ?
        """,
        (float(initiative), session_id, character_id),
    )


def add_combat_log(
    connection: sqlite3.Connection,
    *,
    session_id: int | None,
    channel_id: int,
    event_type: str,
    actor_character_id: int | None = None,
    target_character_id: int | None = None,
    value: int | None = None,
    hp_before: int | None = None,
    hp_after: int | None = None,
    description: str | None = None,
) -> int:
    """Append one combat log record and return its primary key."""
    cursor = connection.execute(
        """
        INSERT INTO combat_log (
            session_id, channel_id, event_type,
            actor_character_id, target_character_id, value,
            hp_before, hp_after, description
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session_id,
            channel_id,
            event_type,
            actor_character_id,
            target_character_id,
            value,
            hp_before,
            hp_after,
            description,
        ),
    )
    return int(cursor.lastrowid)


def get_recent_combat_log(
    connection: sqlite3.Connection, session_id: int, limit: int = 5
) -> list[dict]:
    """Return the most recent combat log entries for one session."""
    rows = connection.execute(
        """
        SELECT log_id, event_type, actor_character_id, target_character_id,
               value, hp_before, hp_after, description, reverted, created_at
        FROM combat_log
        WHERE session_id = ?
        ORDER BY log_id DESC
        LIMIT ?
        """,
        (session_id, int(limit)),
    ).fetchall()

    return [
        {
            "log_id": row[0],
            "event_type": row[1],
            "actor_character_id": row[2],
            "target_character_id": row[3],
            "value": row[4],
            "hp_before": row[5],
            "hp_after": row[6],
            "description": row[7],
            "reverted": bool(row[8]),
            "created_at": row[9],
        }
        for row in rows
    ]


def get_last_damage_log(
    connection: sqlite3.Connection,
    channel_id: int,
    session_id: int | None = None,
) -> dict | None:
    """Return the latest unreverted damage event in a channel or session."""
    query = """
        SELECT log_id, session_id, channel_id, event_type, target_character_id,
               value, hp_before, hp_after, description, reverted
        FROM combat_log
        WHERE channel_id = ? AND event_type = 'damage' AND reverted = 0
    """
    parameters: list[object] = [channel_id]
    if session_id is not None:
        query += " AND session_id = ?"
        parameters.append(session_id)
    query += " ORDER BY log_id DESC LIMIT 1"
    row = connection.execute(query, tuple(parameters)).fetchone()
    if row is None:
        return None
    return {
        "log_id": row[0],
        "session_id": row[1],
        "channel_id": row[2],
        "event_type": row[3],
        "target_character_id": row[4],
        "value": row[5],
        "hp_before": row[6],
        "hp_after": row[7],
        "description": row[8],
        "reverted": bool(row[9]),
    }


def mark_combat_log_reverted(
    connection: sqlite3.Connection, log_id: int
) -> None:
    """Mark a combat log entry as reverted without committing."""
    connection.execute(
        "UPDATE combat_log SET reverted = 1 WHERE log_id = ?",
        (log_id,),
    )


def set_character_current_pv(
    connection: sqlite3.Connection, character_id: int, value: int
) -> tuple[int, int]:
    """Set current PV directly for a GM undo and return old and new values."""
    row = connection.execute(
        "SELECT current_pv FROM characters WHERE character_id = ?",
        (character_id,),
    ).fetchone()
    if row is None:
        raise ValueError(
            f"Database Anomaly: No character sheet linked to character_id {character_id}."
        )
    old_value = int(row[0] or 0)
    connection.execute(
        "UPDATE characters SET current_pv = ? WHERE character_id = ?",
        (int(value), character_id),
    )
    return old_value, int(value)
