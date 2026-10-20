"""Tests for the dynamic slash command catalog exposed by /help."""

from __future__ import annotations

import re
import types

import discord
from discord.ext import commands

from cogs.admin import Admin
from cogs.battle import Battle
from cogs.help import (
    CATEGORY_LABELS,
    FALLBACK_CATEGORY,
    HIDDEN_COMMANDS,
    MAX_DESCRIPTION_CHARS,
    MAX_MESSAGE_CHARS,
    Help,
    build_help_messages,
    setup,
)
from cogs.inventory import Inventory
from cogs.other_tests import Other_tests
from cogs.settings import Settings
from cogs.sheet import Sheet
from cogs.skill_test import Skill_tests
from cogs.skills import Skills
from cogs.spells import Spells
from cogs.traits import Traits
from helpers import FakeBot, FakeInteraction
from utils.ansi import (
    DANGER_COLOR,
    LABEL_COLOR,
    NEUTRAL_COLOR,
    SUCCESS_COLOR,
    ansi,
)

ANSI_ESCAPE = re.compile("\u001b\\[[0-9;]*m")


def make_command(
    name: str,
    description: str = "Descrição de teste",
    cog_name: str = "Battle",
    administrator_only: bool = False,
):
    """Build a lightweight app command stub consumable by build_help_messages."""
    binding = types.SimpleNamespace(qualified_name=cog_name)
    default_permissions = (
        discord.Permissions(administrator=True) if administrator_only else None
    )
    return types.SimpleNamespace(
        name=name,
        description=description,
        binding=binding,
        default_permissions=default_permissions,
    )


def joined_messages(messages: list[str]) -> str:
    return "\n".join(messages)


def plain_text(messages: list[str]) -> str:
    return ANSI_ESCAPE.sub("", joined_messages(messages))


def colored_command(name: str) -> str:
    return ansi(f"/{name}", SUCCESS_COLOR)


def colored_description(description: str) -> str:
    return ansi(description, NEUTRAL_COLOR)


def colored_label(label: str) -> str:
    return ansi(f"[{label}]", LABEL_COLOR)


class TestHiddenCommands:
    def test_hdm_is_never_listed(self):
        messages = build_help_messages(
            [make_command("roll"), make_command("hdm", "Comando oculto")]
        )

        text = plain_text(messages)
        assert "/hdm" not in text
        assert "/roll" in text

    def test_hidden_registry_contains_hdm(self):
        assert "hdm" in HIDDEN_COMMANDS


class TestCatalogContent:
    def test_every_visible_command_is_listed_with_its_description(self):
        commands = [
            make_command("roll_test", "Rola dados", "Other_tests"),
            make_command("atk_test", "Realiza um ataque", "Battle"),
            make_command("sheet_test", "Envia a ficha", "Sheet"),
        ]

        text = joined_messages(build_help_messages(commands))

        for command in commands:
            assert colored_command(command.name) in text
            assert colored_description(command.description) in text

    def test_category_labels_use_the_yellow_palette_color(self):
        messages = build_help_messages([make_command("atk", "Ataque", "Battle")])

        assert colored_label("COMBATE") in joined_messages(messages)

    def test_administrator_commands_receive_the_admin_badge(self):
        commands = [
            make_command("manage_xp", "Gerencia XP", "Admin", administrator_only=True),
            make_command("switch_character", "Troca personagem", "Admin"),
        ]

        text = joined_messages(build_help_messages(commands))
        admin_badge = ansi("[ADMIN]", DANGER_COLOR)

        assert f"{admin_badge} {colored_command('manage_xp')}" in text
        assert f"{admin_badge} {colored_command('switch_character')}" not in text
        assert ansi("[ADMIN]", LABEL_COLOR) not in text
        assert colored_label("ADMINISTRAÇÃO") in text

    def test_categories_follow_the_localized_display_order(self):
        commands = [
            make_command("inventory", "Inventário", "Inventory"),
            make_command("atk", "Ataque", "Battle"),
            make_command("help", "Ajuda", "Help"),
            make_command("sheet", "Ficha", "Sheet"),
            make_command("manage_xp", "XP", "Admin", administrator_only=True),
        ]

        text = plain_text(build_help_messages(commands))
        expected_order = [
            "[FICHA]",
            "[COMBATE]",
            "[INVENTÁRIO]",
            "[ADMINISTRAÇÃO]",
            "[AJUDA]",
        ]

        positions = [text.index(label) for label in expected_order]
        assert positions == sorted(positions)

    def test_commands_from_unknown_cogs_fall_back_to_outros(self):
        text = plain_text(
            build_help_messages([make_command("foo", "Foo", "Unknown")])
        )

        assert f"[{FALLBACK_CATEGORY}]" in text

    def test_commands_are_sorted_alphabetically_inside_a_category(self):
        text = plain_text(
            build_help_messages(
                [
                    make_command("zeta", "Z", "Battle"),
                    make_command("alpha", "A", "Battle"),
                ]
            )
        )

        assert text.index("/alpha") < text.index("/zeta")

    def test_admin_permission_note_is_present(self):
        text = plain_text(build_help_messages([make_command("atk")]))

        assert (
            "Comandos marcados com [ADMIN] exigem permissão de administrador." in text
        )


class TestPayloadLimits:
    def test_every_message_respects_the_length_limit_and_fence(self):
        commands = [
            make_command(f"command_{index}", "x" * 500, "Battle")
            for index in range(20)
        ]

        messages = build_help_messages(commands)

        assert len(messages) > 1
        for message in messages:
            assert message.startswith("```ansi\n")
            assert message.endswith("\n```")
            assert len(message) <= MAX_MESSAGE_CHARS

    def test_descriptions_are_clamped_before_rendering(self):
        messages = build_help_messages(
            [make_command("command", "x" * 1500, "Battle")]
        )

        text = plain_text(messages)
        assert "x" * MAX_DESCRIPTION_CHARS in text
        assert "x" * (MAX_DESCRIPTION_CHARS + 1) not in text

    def test_split_category_repeats_its_header_on_the_next_message(self):
        commands = [
            make_command(f"command_{index}", "x" * 500, "Battle")
            for index in range(20)
        ]

        text = joined_messages(build_help_messages(commands))

        assert text.count(colored_label("COMBATE")) > 1


class TestHelpCommand:
    async def test_response_is_ephemeral_and_uses_content(self):
        commands = [make_command("roll", "Rola dados", "Other_tests")]
        bot = FakeBot()
        bot.tree = types.SimpleNamespace(get_commands=lambda: commands)
        cog = Help(bot)
        interaction = FakeInteraction()

        await Help.help_command.callback(cog, interaction)

        assert interaction.response.deferred == []
        payload = interaction.response.messages[0]["kwargs"]
        assert payload["ephemeral"] is True
        assert "content" in payload
        assert "embeds" not in payload
        assert "/hdm" not in plain_text([payload["content"]])

    async def test_additional_pages_are_sent_through_ephemeral_followups(self):
        commands = [
            make_command(f"command_{index}", "x" * 500, "Battle")
            for index in range(20)
        ]
        bot = FakeBot()
        bot.tree = types.SimpleNamespace(get_commands=lambda: commands)
        cog = Help(bot)
        interaction = FakeInteraction()

        await Help.help_command.callback(cog, interaction)

        payloads = [interaction.response.messages[0]["kwargs"]]
        payloads.extend(message["kwargs"] for message in interaction.followup.sent)

        assert len(payloads) > 1
        for payload in payloads:
            assert payload["ephemeral"] is True
            assert "embeds" not in payload
            assert len(payload["content"]) <= MAX_MESSAGE_CHARS


class TestSetup:
    async def test_setup_registers_the_help_cog_and_slash_command(self):
        bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())

        try:
            await setup(bot)

            assert isinstance(bot.get_cog("Help"), Help)
            assert bot.tree.get_command("help") is not None
        finally:
            await bot.close()


class TestProductionCatalog:
    async def test_help_lists_every_production_command_except_hdm(
        self, patched_sqlite
    ):
        bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
        bot.config = {"BOT": {"DM_ID": "999"}}

        try:
            for cog_type in (
                Battle,
                Admin,
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

            registered_commands = bot.tree.get_commands()
            assert any(command.name == "hdm" for command in registered_commands)

            interaction = FakeInteraction()
            cog = bot.get_cog("Help")

            await Help.help_command.callback(cog, interaction)

            payloads = [interaction.response.messages[0]["kwargs"]]
            payloads.extend(
                message["kwargs"] for message in interaction.followup.sent
            )
            text = joined_messages(
                [payload["content"] for payload in payloads]
            )

            for payload in payloads:
                assert payload["ephemeral"] is True
                assert "embeds" not in payload
                assert len(payload["content"]) <= MAX_MESSAGE_CHARS

            assert "/hdm" not in plain_text(
                [payload["content"] for payload in payloads]
            )

            for command in registered_commands:
                if command.name in HIDDEN_COMMANDS:
                    continue
                assert colored_command(command.name) in text
        finally:
            await bot.close()
