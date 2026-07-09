import sqlite3

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
    Retrieves the comprehensive attribute matrix for a specific character
    designated by the owner's unique Discord identifier.
    """
    cursor = connection.cursor()

    # Explicitly listing all 17 columns to avoid the fragility of SELECT *
    cursor.execute(
        """
        SELECT 
            character_id, owner_id, is_npc, name, st, dx, iq, ht, 
            additional_max_pv, additional_vont, additional_per, 
            additional_max_pf, additional_basic_speed, additional_basic_move, 
            energy_reserve, normal_diffuse_homogeneous_unded, money
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
    }


# SQL FUNCTIONS (character_resource_pools)
def get_character_resources(connection: sqlite3.Connection, player_id: int) -> dict:
    """
    Retrieves all volatile resource pools for a given player and constructs a dictionary mapping.
    Raises ValueError if the player lacks an assigned character.
    """
    character_id = _resolve_character_id(connection, player_id)
    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT resource, value 
        FROM character_resource_pools 
        WHERE character_id = ?
        """,
        (character_id,),
    )

    rows = cursor.fetchall()

    # Dictionary comprehension for optimal mapping: {"HP": 10, "FP": 12}
    return {row[0]: row[1] for row in rows}


def set_character_resource(
    connection: sqlite3.Connection, player_id: int, resource_name: str, new_value: int
) -> None:
    """
    Mutates the absolute value of a specific resource pool for a character.
    If the resource does not exist in the relational schema, it automatically instantiates it.
    """
    character_id = _resolve_character_id(connection, player_id)
    cursor = connection.cursor()

    cursor.execute(
        """
        UPDATE character_resource_pools 
        SET value = ? 
        WHERE character_id = ? AND resource = ?
        """,
        (new_value, character_id, resource_name),
    )

    # Structural fallback: If no rows were mutated, the resource metric is absent.
    if cursor.rowcount == 0:
        cursor.execute(
            """
            INSERT INTO character_resource_pools (character_id, resource, value)
            VALUES (?, ?, ?)
            """,
            (character_id, resource_name, new_value),
        )

    connection.commit()

