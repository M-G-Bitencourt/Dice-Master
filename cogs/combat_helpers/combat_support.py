"""Shared presentation and user helpers for the combat cog."""

from __future__ import annotations

import discord


def _clamp(value: str, limit: int) -> str:
    """Clamp a string to a Discord payload limit."""
    return str(value)[:limit]


def _friendly_character_error(error: Exception) -> str:
    """Translate database character errors into user-facing Portuguese."""
    message = str(error)
    if "No character found assigned" in message:
        return "Você não possui um personagem ativo atribuído à sua conta."
    if "No character sheet linked" in message:
        return "Personagem não encontrado."
    if "invalid literal" in message or "'NoneType'" in message:
        return "Identificador de personagem ou arma inválido."
    return message


def _is_gm_user(user: discord.abc.User, dm_id: int) -> bool:
    """Return True when the user is the configured GM or a guild administrator."""
    if int(getattr(user, "id", 0)) == int(dm_id):
        return True

    permissions = getattr(user, "guild_permissions", None)
    return bool(permissions and permissions.administrator)


def _can_defend(
    user: discord.abc.User, pending: dict, dm_id: int
) -> bool:
    """Return True when the user may resolve the pending attack."""
    if _is_gm_user(user, dm_id):
        return True

    target_owner_id = pending.get("target_owner_id")
    if target_owner_id is None:
        return False

    return int(getattr(user, "id", 0)) == int(target_owner_id)


def _max_pv(profile: dict) -> int:
    """Return the effective maximum PV from the denormalized character row."""
    return int(profile["st"]) + int(profile["additional_max_pv"] or 0)


def _format_modifiers(breakdown: dict) -> str:
    """Render the modifier stack for the attack embed."""
    parts = [f"Base {breakdown['base']}"]
    parts.extend(
        f"{entry['label']} {entry['value']:+d}"
        for entry in breakdown["modifiers"]
    )
    parts.append(f"= NH {breakdown['effective']}")
    return _clamp("\n".join(parts), 1000)


def _roll_result_text(outcome: dict) -> str:
    """Render the attack outcome for the embed."""
    if outcome["critical_success"]:
        return "SUCESSO DECISIVO"
    if outcome["success"]:
        return f"SUCESSO por {outcome['margin']}"
    if outcome["critical_failure"]:
        return "FALHA CRÍTICA"
    return f"FALHA por {abs(outcome['margin'])}"
