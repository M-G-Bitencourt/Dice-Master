"""Server language settings exposed through the /language command."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from utils.db_functions import set_guild_locale
from utils.i18n import available_locales, normalize_locale, set_locale, t
from utils.locale_service import apply_interaction_locale


LANGUAGE_CHOICES = [
    app_commands.Choice(
        name=f"{catalog.native_name} ({catalog.code})",
        value=catalog.code,
    )
    for catalog in available_locales()
]


class Settings(commands.Cog):
    """Cog responsible for per-server bot preferences."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        project_root = Path(__file__).resolve().parent.parent
        database_path = project_root / "data" / "database.db"

        self.db_connection = sqlite3.connect(database_path)
        self.db_connection.execute("PRAGMA foreign_keys = ON;")

    @app_commands.command(
        name="language",
        description="Change the bot language for this server.",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(language="Language the bot will use in this server.")
    @app_commands.choices(language=LANGUAGE_CHOICES)
    async def language(
        self,
        interaction: discord.Interaction,
        language: app_commands.Choice[str],
    ):
        apply_interaction_locale(interaction, self.db_connection)
        await interaction.response.defer(ephemeral=True)

        permissions = getattr(interaction, "permissions", None)
        if permissions is None:
            permissions = getattr(interaction.user, "guild_permissions", None)

        if not permissions or not permissions.administrator:
            await interaction.followup.send(
                t("Only administrators can change the bot language."),
                ephemeral=True,
            )
            return

        guild_id = getattr(interaction, "guild_id", None)
        if guild_id is None:
            await interaction.followup.send(
                t("This command can only be used in a server."),
                ephemeral=True,
            )
            return

        locale = normalize_locale(language.value)
        if locale is None:
            await interaction.followup.send(
                t("Error: invalid language."),
                ephemeral=True,
            )
            return

        set_guild_locale(self.db_connection, int(guild_id), locale)
        set_locale(locale)

        display_name = next(
            (
                catalog.native_name
                for catalog in available_locales()
                if catalog.code == locale
            ),
            locale,
        )

        await interaction.followup.send(
            t("Language set to {language}.", language=display_name),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    """Mandatory asynchronous entry point to load the extension."""
    await bot.add_cog(Settings(bot))
