"""Tests for the hidden GM shield context menu."""

from __future__ import annotations

import discord
import pytest
from discord.ext import commands

from cogs.help import build_help_messages
from cogs.gm_shield import setup as setup_gm_shield
from cogs.gm_shield.cog import GMShield
from helpers import FakeBot, FakeInteraction, FakeUser, insert_character
from utils.discord_translator import DiceMasterTranslator


@pytest.fixture
def cog(make_cog):
    return make_cog(GMShield)


class TestGMShieldContextMenu:
    async def test_dm_opens_an_ephemeral_hub(self, cog, db):
        insert_character(db, owner_id=42, name="Alvo")
        interaction = FakeInteraction(user_id=999)

        await GMShield.open_panel(
            cog, interaction, FakeUser(user_id=42)
        )

        payload = interaction.response.messages[0]["kwargs"]
        assert payload["ephemeral"] is True
        assert "Alvo" in payload["embed"].title
        assert payload["view"] is not None

    async def test_non_dm_is_rejected_ephemerally(self, cog, db):
        insert_character(db, owner_id=42, name="Alvo")
        interaction = FakeInteraction(user_id=1)

        await GMShield.open_panel(
            cog, interaction, FakeUser(user_id=42)
        )

        message = interaction.response.messages[0]
        assert message["kwargs"]["ephemeral"] is True
        assert message["args"][0] == (
            "Erro: apenas o mestre pode usar este painel."
        )

    async def test_member_without_character_is_rejected(self, cog, db):
        interaction = FakeInteraction(user_id=999)

        await GMShield.open_panel(
            cog, interaction, FakeUser(user_id=42)
        )

        message = interaction.response.messages[0]
        assert message["kwargs"]["ephemeral"] is True
        assert message["args"][0] == (
            "Erro: este membro não possui personagem ativo."
        )

    async def test_context_menu_is_hidden_from_help_and_localized(
        self, patched_sqlite
    ):
        bot = commands.Bot(
            command_prefix="!", intents=discord.Intents.none()
        )
        bot.config = {"BOT": {"DM_ID": "999"}}
        translator = DiceMasterTranslator()
        await translator.load()
        await bot.tree.set_translator(translator)

        try:
            await setup_gm_shield(bot)
            command = bot.tree.get_commands()[0]

            assert command.name == "GM Shield"
            assert command.default_permissions == discord.Permissions(0)
            assert command.guild_only is True

            payload = await command.get_translated_payload(
                bot.tree, translator
            )
            assert payload["name_localizations"]["pt-BR"] == (
                "Escudo do Mestre"
            )

            help_text = "\n".join(
                build_help_messages(bot.tree.get_commands())
            )
            assert "GM Shield" not in help_text
        finally:
            await bot.close()
