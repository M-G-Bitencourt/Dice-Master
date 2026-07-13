from random import randint


def hdm_dices(nh: int, fate: int):
    # --- SAFETY CHECKS (Prevents infinite loops) ---

    # If NH is 4 or less, any success will roll a 3 or 4 (Critical Success)
    if fate == 0 and nh <= 4:
        fate = 2

    # If NH is 26 or more, the worst possible success (16) will still have a margin >= 10 (Critical Success)
    if fate == 0 and nh >= 26:
        fate = 2

    if fate == 0:  # Normal Success
        while True:
            dices = [randint(1, 6) for _ in range(3)]
            dice_pool = sum(dices)
            if nh >= 15:
                if dice_pool <= nh and nh - dice_pool < 10:
                    return dices
            elif dice_pool <= nh and dice_pool > 4:
                return dices
    elif fate == 1:  # Normal Failure
        while True:
            dices = [randint(1, 6) for _ in range(3)]
            dice_pool = sum(dices)
            if nh >= 16:
                if dice_pool == 17:
                    return dices
            else:
                if dice_pool > nh and dice_pool < 17:
                    return dices
    elif fate == 2:  # Critical Success
        while True:
            dices = [randint(1, 6) for _ in range(3)]
            dice_pool = sum(dices)
            if nh >= 15:
                if nh - dice_pool >= 10:
                    return dices
            elif dice_pool <= 4:
                return dices
    else:  # fate == 3 - Critical Failure
        # This block checks if the effective skill is 15 or less.
        # If so, a roll of 17 is a critical failure; otherwise, only 18 is a critical failure.
        while True:
            dices = [randint(1, 6) for _ in range(3)]
            dice_pool = sum(dices)
            if nh <= 7:
                if dice_pool - nh >= 10:
                    return dices
            if nh <= 15:
                if dice_pool >= 17:
                    return dices
            elif dice_pool == 18:
                return dices


import sqlite3
from typing import Optional
from pathlib import Path

# Absolute path resolution ensuring the utility module always finds the database binary
BASE_DIRECTORY = Path(__file__).resolve().parent.parent
DATABASE_FILE_PATH = BASE_DIRECTORY / "data" / "database.db"


def consume_deterministic_fate(player_identifier: int) -> Optional[int]:
    """
    Queries the SQLite database for a deterministic fate assigned to a specific player.
    If a fate exists, it retrieves the value, purges the record to prevent
    infinite repetition, and returns the integer.
    Returns None otherwise.
    """
    try:
        with sqlite3.connect(DATABASE_FILE_PATH) as db_connection:
            db_cursor = db_connection.cursor()

            # Step 1: Query the existing deterministic state
            db_cursor.execute(
                "SELECT fate FROM hdm WHERE id_player = ?", (player_identifier,)
            )
            query_result = db_cursor.fetchone()

            if query_result is None:
                return None

            fate_value = query_result[0]

            # Step 2: Purge the record to consume the state strictly
            db_cursor.execute(
                "DELETE FROM hdm WHERE id_player = ?", (player_identifier,)
            )

            # Commit the transaction atomically
            db_connection.commit()

            return fate_value

    except sqlite3.Error:
        # Failsafe: return None to allow standard RNG roll in case of structural failure.
        # Warning: Exceptions are explicitly silenced here per the omission of logging.
        return None
