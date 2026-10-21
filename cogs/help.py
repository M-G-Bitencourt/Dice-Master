"""Dynamic slash command catalog exposed through the /help command."""

from __future__ import annotations

import sqlite3
from pathlib import Path

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
from utils.i18n import (
    catalog_label,
    command_display_description,
    command_display_name,
    get_locale,
    locale_context,
    t as tr,
)
from utils.locale_service import apply_interaction_locale


HIDDEN_COMMANDS = frozenset({"hdm"})

CATEGORY_ORDER = (
    "Sheet",
    "Skill_tests",
    "Other_tests",
    "Battle",
    "Combat",
    "Skills",
    "Spells",
    "Traits",
    "Inventory",
    "Admin",
    "Help",
    "Settings",
)

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
    "Settings": "CONFIGURAÇÕES",
}

FALLBACK_CATEGORY = "OUTROS"

MAX_MESSAGE_CHARS = 1900
MAX_DESCRIPTION_CHARS = 1000


def _category_label(command: app_commands.Command) -> str:
    """Resolve the localized category label from the command's owning cog."""
    qualified_name = getattr(command.binding, "qualified_name", None)
    key = str(qualified_name) if qualified_name else "other"
    if key not in CATEGORY_ORDER and key != "other":
        key = "other"
    return catalog_label("help_categories", key)


def _command_line(command: app_commands.Command) -> str:
    """Render a single command line with colored command and description."""
    permissions = command.default_permissions
    is_admin_only = bool(permissions and permissions.administrator)
    badge = f"{ansi('[ADMIN]', DANGER_COLOR)} " if is_admin_only else ""

    description = command_display_description(
        command.name,
        str(command.description),
    )[:MAX_DESCRIPTION_CHARS].strip()

    localized_name = command_display_name(command.name)
    name_label = ansi(f"/{command.name}", SUCCESS_COLOR)
    if localized_name != command.name:
        name_label += f" ({localized_name})"

    return (
        f"  {badge}{name_label} - "
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
        catalog_label("help_categories", name)
        for name in CATEGORY_ORDER
        if catalog_label("help_categories", name) in grouped
    ]
    fallback = catalog_label("help_categories", "other")
    if fallback in grouped:
        ordered_labels.append(fallback)

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


def build_help_messages(
    commands: list[app_commands.Command], locale: str | None = None
) -> list[str]:
    """Build plain message payloads with the complete command catalog."""
    with locale_context(locale or get_locale()):
        visible_commands = [
            command
            for command in commands
            if command.name not in HIDDEN_COMMANDS
            and not isinstance(command, app_commands.ContextMenu)
        ]

        pages = _paginate_categories(_group_by_category(visible_commands))

        admin_note = ansi(
            tr("Commands marked with [ADMIN] require administrator permission."),
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
        project_root = Path(__file__).resolve().parent.parent
        database_path = project_root / "data" / "database.db"
        self.db_connection = sqlite3.connect(database_path)
        self.db_connection.execute("PRAGMA foreign_keys = ON;")

    @app_commands.command(
        name="help",
        description="List all available commands and their descriptions.",
    )
    async def help_command(self, interaction: discord.Interaction):
        apply_interaction_locale(interaction, self.db_connection)
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
