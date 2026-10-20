"""Resolve and apply the locale for one Discord interaction."""

from __future__ import annotations

import sqlite3

import discord

from utils.db_functions import get_guild_locale
from utils.i18n import default_locale, normalize_locale, set_locale


def resolve_locale(
    interaction: discord.Interaction, connection: sqlite3.Connection
) -> str:
    """Resolve the server locale, then the Discord client locale, then the default."""
    guild_id = getattr(interaction, "guild_id", None)
    if guild_id is not None:
        try:
            saved = get_guild_locale(connection, int(guild_id))
        except (sqlite3.Error, ValueError, TypeError):
            saved = None

        if saved:
            normalized = normalize_locale(saved)
            if normalized is not None:
                return normalized

        return default_locale()

    client_locale = getattr(interaction, "locale", None)
    if client_locale is not None:
        normalized = normalize_locale(
            getattr(client_locale, "value", str(client_locale))
        )
        if normalized is not None:
            return normalized

    return default_locale()


def apply_interaction_locale(
    interaction: discord.Interaction, connection: sqlite3.Connection
) -> str:
    """Resolve and store the locale in the current task context."""
    locale = resolve_locale(interaction, connection)
    set_locale(locale)
    return locale
