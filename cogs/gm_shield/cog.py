"""DM-only context menu for GM shield controls."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import discord
from discord import AppCommandType, app_commands
from discord.ext import commands

from cogs.gm_shield.views import GMShieldHubView
from utils.db_functions import get_character_profile
from utils.i18n import t as tr
from utils.locale_service import apply_interaction_locale


class GMShield(commands.Cog):
    """Hidden DM tools exposed through a user context menu."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        project_root = Path(__file__).resolve().parents[2]
        database_path = project_root / "data" / "database.db"
        self.db_connection = sqlite3.connect(database_path)
        self.db_connection.execute("PRAGMA foreign_keys = ON;")

        try:
            self.dm_id = int(self.bot.config["BOT"]["DM_ID"])
        except AttributeError as error:
            raise RuntimeError(
                "Architectural Error: 'bot.config' must be injected before loading Cogs."
            ) from error
        except (KeyError, ValueError) as error:
            raise ValueError(f"Configuration Malformation: {error}") from error

    async def open_panel(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
    ):
        locale = apply_interaction_locale(interaction, self.db_connection)
        if interaction.user.id != self.dm_id:
            await interaction.response.send_message(
                tr("Error: only the GM can use this panel."),
                ephemeral=True,
            )
            return

        try:
            character = get_character_profile(
                self.db_connection, member.id
            )
        except ValueError:
            await interaction.response.send_message(
                tr("Error: this member has no active character."),
                ephemeral=True,
            )
            return

        hub = GMShieldHubView(
            connection=self.db_connection,
            dm_id=self.dm_id,
            player_id=member.id,
            character=character,
            locale=locale,
        )
        await interaction.response.send_message(
            embed=hub.build_embed(),
            view=hub,
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    cog = GMShield(bot)
    await bot.add_cog(cog)

    @app_commands.guild_only()
    @app_commands.default_permissions()
    async def gm_shield_callback(
        interaction: discord.Interaction,
        member: discord.Member,
    ):
        await cog.open_panel(interaction, member)

    if any(
        command.name == "GM Shield" and command.type == AppCommandType.user
        for command in bot.tree.get_commands()
    ):
        bot.tree.remove_command("GM Shield", type=AppCommandType.user)
    menu = app_commands.ContextMenu(
        name="GM Shield",
        callback=gm_shield_callback,
    )
    bot.tree.add_command(menu)
