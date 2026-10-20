"""Shared initiative advancement for the combat command and panel button."""

from __future__ import annotations

import sqlite3

from utils.i18n import t as tr
from utils.db_functions import (
    add_combat_log,
    clear_character_shock,
    get_active_combat_session,
    get_combat_participants,
    get_pending_attack_for_channel,
    reset_combat_participant_turn,
    set_character_combat_stance,
    set_combat_session_active,
)


def advance_combat_turn(
    connection: sqlite3.Connection, channel_id: int
) -> dict:
    """Advance to the next participant and return the updated state."""
    session = get_active_combat_session(connection, channel_id)
    if session is None:
        raise ValueError("No active combat in this channel.")

    if get_pending_attack_for_channel(connection, channel_id) is not None:
        raise ValueError(
            "Resolve the pending attack before advancing the turn."
        )

    participants = get_combat_participants(
        connection, int(session["session_id"])
    )
    if not participants:
        raise ValueError("No participants are registered in this combat.")

    ordered = sorted(
        participants,
        key=lambda participant: (
            -float(participant.get("initiative") or 0),
            int(participant["character_id"]),
        ),
    )
    active_character_id = session.get("active_character_id")
    current_index = None
    for index, participant in enumerate(ordered):
        if int(participant["character_id"]) == int(
            active_character_id or -1
        ):
            current_index = index
            break

    next_index = 0 if current_index is None else current_index + 1
    round_number = int(session.get("round_number") or 1)
    if next_index >= len(ordered):
        next_index = 0
        round_number += 1

    next_participant = ordered[next_index]
    next_character_id = int(next_participant["character_id"])

    with connection:
        if (
            active_character_id is not None
            and int(active_character_id) != next_character_id
        ):
            clear_character_shock(connection, int(active_character_id))
        reset_combat_participant_turn(
            connection,
            int(session["session_id"]),
            next_character_id,
        )
        set_character_combat_stance(
            connection,
            next_character_id,
            no_defense=0,
            defense_bonus=0,
        )
        set_combat_session_active(
            connection,
            int(session["session_id"]),
            next_character_id,
            round_number,
        )
        add_combat_log(
            connection,
            session_id=int(session["session_id"]),
            channel_id=channel_id,
            event_type="turn",
            actor_character_id=next_character_id,
            description=tr(
                "Turn of {character} (round {round}).",
                character=next_participant["character_name"],
                round=round_number,
            ),
        )

    updated_session = get_active_combat_session(connection, channel_id)
    return {
        "session": updated_session,
        "next_participant": next_participant,
        "round_number": round_number,
    }
