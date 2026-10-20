"""Dynamic slash command catalog exposed through the /help command."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from utils.ansi import (
    DANGER_COLOR,
    LABEL_COLOR,
    NEUTRAL_COLOR,
    SUCCESS_COLOR,
    ansi,
    code_block,
)


HIDDEN_COMMANDS = frozenset({"hdm"})

CATEGORY_LABELS = {
    "Sheet": "FICHA",
    "Skill_tests": "TESTES DE HABILIDADE",
    "Other_tests": "TESTES GERAIS",
    "Battle": "COMBATE",
    "Combat": "COMBATE",
    "Skills": "PERÍCIAS",
    "Spells": "MAGIAS",
    "Traits": "TRAÇOS",
    "Inventory": "INVENTÁRIO",
    "Admin": "ADMINISTRAÇÃO",
    "Help": "AJUDA",
}

FALLBACK_CATEGORY = "OUTROS"

MAX_MESSAGE_CHARS = 1900
MAX_DESCRIPTION_CHARS = 1000


def _category_label(command: app_commands.Command) -> str:
    """Resolve the localized category label from the command's owning cog."""
    qualified_name = getattr(command.binding, "qualified_name", None)
    return CATEGORY_LABELS.get(qualified_name, FALLBACK_CATEGORY)


def _command_line(command: app_commands.Command) -> str:
    """Render a single command line with colored command and description."""
    permissions = command.default_permissions
    is_admin_only = bool(permissions and permissions.administrator)
    badge = f"{ansi('[ADMIN]', DANGER_COLOR)} " if is_admin_only else ""

    description = str(command.description)[:MAX_DESCRIPTION_CHARS].strip()

    return (
        f"  {badge}{ansi(f'/{command.name}', SUCCESS_COLOR)} - "
        f"{ansi(description, NEUTRAL_COLOR)}"
    )


def _group_by_category(
    commands: list[app_commands.Command],
) -> list[tuple[str, list[app_commands.Command]]]:
    """Group commands by their localized category, preserving the display order."""
    grouped: dict[str, list[app_commands.Command]] = {}

    for command in commands:
        grouped.setdefault(_category_label(command), []).append(command)

    ordered_labels = [
        label for label in CATEGORY_LABELS.values() if label in grouped
    ]
    if FALLBACK_CATEGORY in grouped:
        ordered_labels.append(FALLBACK_CATEGORY)

    return [
        (label, sorted(grouped[label], key=lambda command: command.name))
        for label in ordered_labels
    ]


def _paginate_categories(
    categories: list[tuple[str, list[app_commands.Command]]],
) -> list[list[str]]:
    """Split rendered category blocks into ANSI code blocks within the limit."""
    pages: list[list[str]] = []
    current_page: list[str] = []

    for label, category_commands in categories:
        header = ansi(f"[{label}]", LABEL_COLOR)
        block_lines = [header] + [
            _command_line(command) for command in category_commands
        ]

        separator = [""] if current_page else []
        if current_page and len(
            code_block(current_page + separator + block_lines)
        ) > MAX_MESSAGE_CHARS:
            pages.append(current_page)
            current_page = []

        if current_page:
            current_page.append("")
        else:
            current_page = [header]
            block_lines = block_lines[1:]

        for line in block_lines:
            if len(current_page) > 1 and len(
                code_block(current_page + [line])
            ) > MAX_MESSAGE_CHARS:
                pages.append(current_page)
                current_page = [header, line]
            else:
                current_page.append(line)

    if current_page:
        pages.append(current_page)

    return pages


def build_help_messages(commands: list[app_commands.Command]) -> list[str]:
    """Build plain message payloads with the complete command catalog."""
    visible_commands = [
        command for command in commands if command.name not in HIDDEN_COMMANDS
    ]

    pages = _paginate_categories(_group_by_category(visible_commands))

    admin_note = ansi(
        "Comandos marcados com [ADMIN] exigem permissão de administrador.",
        NEUTRAL_COLOR,
    )

    if pages and len(code_block(pages[-1] + ["", admin_note])) <= MAX_MESSAGE_CHARS:
        pages[-1].extend(["", admin_note])
    else:
        pages.append([admin_note])

    return [code_block(lines) for lines in pages]


class Help(commands.Cog):
    """Cog responsible for exposing the dynamic slash command catalog."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="help",
        description="Lista todos os comandos disponíveis com suas descrições",
    )
    async def help_command(self, interaction: discord.Interaction):
        messages = build_help_messages(self.bot.tree.get_commands())

        await interaction.response.send_message(
            content=messages[0], ephemeral=True
        )

        for message in messages[1:]:
            await interaction.followup.send(content=message, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    """
    Asynchronous entry point required by discord.py to load the extension.
    """
    await bot.add_cog(Help(bot))
