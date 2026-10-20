"""Tests for the per-server /language command."""

from __future__ import annotations

import discord
import pytest
from discord import app_commands

from cogs.settings import Settings
from helpers import FakeInteraction
from utils.db_functions import get_guild_locale
from utils.locale_service import resolve_locale


def admin_interaction(**overrides) -> FakeInteraction:
    interaction = FakeInteraction(**overrides)
    interaction.permissions = discord.Permissions(administrator=True)
    return interaction


def choice(value: str) -> app_commands.Choice[str]:
    return app_commands.Choice(name=value, value=value)


@pytest.fixture
def cog(make_cog):
    return make_cog(Settings)


class TestLanguageCommand:
    async def test_sets_portuguese_for_the_guild(self, cog, db):
        interaction = admin_interaction()

        await Settings.language.callback(cog, interaction, choice("pt-BR"))

        assert interaction.response.deferred[0]["kwargs"]["ephemeral"] is True
        assert get_guild_locale(db, 1) == "pt-BR"
        assert interaction.followup.sent[0]["args"][0] == (
            "Idioma definido para Português (Brasil)."
        )

    async def test_sets_english_for_the_guild(self, cog, db):
        interaction = admin_interaction()

        await Settings.language.callback(cog, interaction, choice("en-US"))

        assert get_guild_locale(db, 1) == "en-US"
        assert resolve_locale(FakeInteraction(), db) == "en-US"
        assert interaction.followup.sent[0]["args"][0] == (
            "Language set to English (US)."
        )

    async def test_rejects_non_administrators(self, cog, db):
        interaction = FakeInteraction()
        interaction.permissions = discord.Permissions.none()

        await Settings.language.callback(cog, interaction, choice("pt-BR"))

        assert get_guild_locale(db, 1) is None
        assert interaction.followup.sent[0]["args"][0] == (
            "Apenas administradores podem alterar o idioma do bot."
        )

    async def test_rejects_direct_messages(self, cog, db):
        interaction = admin_interaction(guild_id=None)

        await Settings.language.callback(cog, interaction, choice("pt-BR"))

        assert interaction.followup.sent[0]["args"][0] == (
            "Este comando só pode ser usado em um servidor."
        )

    async def test_rejects_unknown_locale(self, cog, db):
        interaction = admin_interaction()

        await Settings.language.callback(cog, interaction, choice("xx-YY"))

        assert get_guild_locale(db, 1) is None
        assert interaction.followup.sent[0]["args"][0] == "Erro: idioma inválido."
