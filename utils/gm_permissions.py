"""Per-guild visibility for the GM shield context menu."""

from __future__ import annotations

import discord
from discord import AppCommandType
from discord.app_commands import AppCommand


CONTEXT_MENU_NAME = "GM Shield"


def _configured_dm_id(bot) -> int | None:
    try:
        return int(bot.config["BOT"]["DM_ID"])
    except (AttributeError, KeyError, TypeError, ValueError):
        return None


async def apply_gm_permissions(
    bot,
    commands: list[AppCommand] | None = None,
) -> bool:
    """Allow the context menu only for the configured DM in each guild."""
    dm_id = _configured_dm_id(bot)
    application_id = getattr(bot, "application_id", None)
    if dm_id is None or application_id is None:
        return False

    if commands is None:
        try:
            commands = await bot.tree.fetch_commands()
        except (discord.HTTPException, AttributeError):
            return False

    target = next(
        (
            command
            for command in commands
            if command.name == CONTEXT_MENU_NAME
            and command.type == AppCommandType.user
        ),
        None,
    )
    if target is None:
        return False

    applied = False
    for guild in getattr(bot, "guilds", []):
        payload = {
            "permissions": [
                {"id": str(guild.id), "type": 1, "permission": False},
                {"id": str(dm_id), "type": 2, "permission": True},
            ]
        }
        try:
            await bot.http.edit_application_command_permissions(
                application_id,
                guild.id,
                target.id,
                payload,
            )
            applied = True
        except (discord.HTTPException, AttributeError):
            continue
    return applied
