"""Tests that every slash command exposes English source and pt-BR metadata."""

from __future__ import annotations

import re

import discord
import pytest
from discord.ext import commands

from cogs.admin import Admin
from cogs.battle import Battle
from cogs.combat import Combat
from cogs.help import Help
from cogs.inventory import Inventory
from cogs.other_tests import Other_tests
from cogs.settings import Settings
from cogs.sheet import Sheet
from cogs.skill_test import Skill_tests
from cogs.skills import Skills
from cogs.spells import Spells
from cogs.traits import Traits
from utils.discord_translator import DiceMasterTranslator

COMMAND_PATTERN = re.compile(r"^[a-z0-9_]{1,32}$")


@pytest.fixture
async def localized_bot(patched_sqlite):
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
    bot.config = {"BOT": {"DM_ID": "999"}}
    translator = DiceMasterTranslator()
    await translator.load()
    await bot.tree.set_translator(translator)

    try:
        for cog_type in (
            Battle,
            Admin,
            Combat,
            Other_tests,
            Skill_tests,
            Sheet,
            Skills,
            Inventory,
            Spells,
            Traits,
            Help,
            Settings,
        ):
            await bot.add_cog(cog_type(bot))

        yield bot, translator
    finally:
        await bot.close()


class TestCommandMetadata:
    async def test_every_command_has_portuguese_name_and_description(
        self, localized_bot
    ):
        bot, translator = localized_bot

        for command in bot.tree.get_commands():
            payload = await command.get_translated_payload(bot.tree, translator)

            assert COMMAND_PATTERN.match(command.name)
            assert len(command.description) <= 100
            assert payload["name_localizations"].get("pt-BR")
            assert payload["description_localizations"].get("pt-BR")

    async def test_every_parameter_has_portuguese_name_and_description(
        self, localized_bot
    ):
        bot, translator = localized_bot

        for command in bot.tree.get_commands():
            payload = await command.get_translated_payload(bot.tree, translator)
            for option in payload.get("options", []):
                assert option["name_localizations"].get("pt-BR"), (
                    command.name,
                    option["name"],
                )
                assert option["description_localizations"].get("pt-BR"), (
                    command.name,
                    option["name"],
                )

    async def test_choices_have_portuguese_localizations(self, localized_bot):
        bot, translator = localized_bot

        for command in bot.tree.get_commands():
            payload = await command.get_translated_payload(bot.tree, translator)
            if command.name == "language":
                continue
            for option in payload.get("options", []):
                for choice in option.get("choices", []):
                    assert choice["name_localizations"].get("pt-BR"), (
                        command.name,
                        option["name"],
                        choice["name"],
                    )

    async def test_combat_hit_location_choices_use_english_canonical_names(
        self, localized_bot
    ):
        bot, translator = localized_bot
        command = bot.tree.get_command("combat_attack")
        assert command is not None

        payload = await command.get_translated_payload(bot.tree, translator)
        hit_location = next(
            option for option in payload["options"] if option["name"] == "hit_location"
        )
        names = {
            choice["name"]: choice["name_localizations"].get("pt-BR")
            for choice in hit_location["choices"]
        }

        assert names["Torso (+0)"] == "Tronco (+0)"
        assert names["Skull (-7)"] == "Crânio (-7)"

    async def test_command_source_descriptions_are_english(self, localized_bot):
        bot, _ = localized_bot

        assert Battle.damage.description == "Calculate damage for an attack."
        assert Settings.language.description == (
            "Change the bot language for this server."
        )
        assert Combat.combat_attack.description.startswith(
            "Attack with an equipped weapon"
        )
