"""Shared presentation and user helpers for the combat cog."""

from __future__ import annotations

import discord

from utils.i18n import t as tr


def _clamp(value: str, limit: int) -> str:
    """Clamp a string to a Discord payload limit."""
    return str(value)[:limit]


def _friendly_character_error(error: Exception) -> str:
    """Translate database character errors into a localized user message."""
    message = str(error)
    if "No character found assigned" in message:
        return tr("You do not have an active character assigned to your account.")
    if "No character sheet linked" in message:
        return tr("Character not found.")
    if "invalid literal" in message or "'NoneType'" in message:
        return tr("Invalid character or weapon identifier.")
    if "não existe combate ativo" in message or "No active combat" in message:
        return tr("There is no active combat in this channel.")
    if "resolva o ataque pendente" in message or "Resolve the pending attack" in message:
        return tr("Resolve the pending attack before advancing the turn.")
    if "nenhum participante" in message or "No participants" in message:
        return tr("No participants are registered in this combat.")
    if "You cannot manage effects" in message:
        return tr("You cannot manage effects for this character.")
    if "Only the GM can choose another character" in message:
        return tr("Only the GM can choose another character as the actor.")
    if "selected weapon does not belong" in message:
        return tr("The selected weapon does not belong to the specified character.")
    if "no equipped melee weapon" in message:
        return tr("The character has no equipped melee weapon.")
    if "selected weapon is invalid" in message:
        return tr("The selected weapon is invalid.")
    if "selected weapon is not equipped" in message:
        return tr("The selected weapon is not equipped by the character.")
    if "no equipped ranged weapon" in message:
        return tr("The character has no equipped ranged weapon.")
    if "selected melee weapon is invalid" in message:
        return tr("The selected melee weapon is invalid.")
    if "selected ranged weapon is invalid" in message:
        return tr("The selected ranged weapon is invalid.")
    if "selected ranged weapon is not equipped" in message:
        return tr("The selected ranged weapon is not equipped by the character.")
    if "cannot feint themselves" in message:
        return tr("A character cannot feint themselves.")
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
    parts = [f"{tr('Base')} {breakdown['base']}"]
    parts.extend(
        f"{entry['label']} {entry['value']:+d}"
        for entry in breakdown["modifiers"]
    )
    parts.append(f"= {tr('Skill')} {breakdown['effective']}")
    return _clamp("\n".join(parts), 1000)


def _roll_result_text(outcome: dict) -> str:
    """Render the attack outcome for the embed."""
    if outcome["critical_success"]:
        return tr("CRITICAL SUCCESS")
    if outcome["success"]:
        return tr("SUCCESS by {margin}", margin=outcome["margin"])
    if outcome["critical_failure"]:
        return tr("CRITICAL FAILURE")
    return tr("FAILURE by {margin}", margin=abs(outcome["margin"]))
