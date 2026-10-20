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


def consume_deterministic_fate(
    player_identifier: int,
    connection: sqlite3.Connection | None = None,
) -> Optional[int]:
    """
    Atomically consumes a deterministic fate assigned to a specific player.
    When a connection is supplied, the caller owns the transaction and must
    commit or roll it back. Returns None when no fate is registered.
    """
    try:
        if connection is not None:
            row = connection.execute(
                "DELETE FROM hdm WHERE id_player = ? RETURNING fate",
                (player_identifier,),
            ).fetchone()
            return int(row[0]) if row is not None else None

        with sqlite3.connect(DATABASE_FILE_PATH) as db_connection:
            row = db_connection.execute(
                "DELETE FROM hdm WHERE id_player = ? RETURNING fate",
                (player_identifier,),
            ).fetchone()
            db_connection.commit()
            return int(row[0]) if row is not None else None

    except sqlite3.Error:
        return None
