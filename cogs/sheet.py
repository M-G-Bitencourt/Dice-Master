import discord
from discord import app_commands
from discord.ext import commands
from pathlib import Path

import sqlite3

from cogs.inventory import InventoryView, build_inventory_pages
from cogs.skills import SkillListView
from cogs.spells import SpellListView
from cogs.traits import TraitListView

from utils.ansi import code_block, resource_bar
from utils.i18n import catalog_label, get_locale, locale_context, t as tr
from utils.locale_service import apply_interaction_locale
from utils.db_functions import (
    get_character_inventory_data_by_id,
    get_character_profile,
    get_character_profile_by_id,
    get_character_skills_data,
    get_character_spells_data,
    get_character_thumbnail_by_id,
    get_character_thumbnail_payload,
    get_character_traits_data,
)


def build_sheet_embed(
    character: dict, locale: str | None = None
) -> discord.Embed:
    """Builds the core character sheet embed from a denormalized profile row."""
    with locale_context(locale or get_locale()):
        return _build_sheet_embed(character)


def _build_sheet_embed(character: dict) -> discord.Embed:
    # Basic Attributes
    st = int(character["st"])
    dx = int(character["dx"])
    iq = int(character["iq"])
    ht = int(character["ht"])
    base_er = int(character["energy_reserve"])

    # Secondary Characteristics
    max_pv = st + int(character["additional_max_pv"])
    max_pf = ht + int(character["additional_max_pf"])
    vont = iq + int(character["additional_vont"])
    per = iq + int(character["additional_per"])

    sheet_embed = discord.Embed(
        title=f"**{character['name']}**",
        color=discord.Color.gold(),
        description=(
            f"**{tr('Unspent Points')}:** `{character['current_points']}`\n"
            f"**{tr('Money')}:** `{character['money']}`"
        ),
    )

    sheet_embed.add_field(
        name=tr("Basic Attributes"),
        value=(
            f"**ST:** `{st}`\n"
            f"**DX:** `{dx}`\n"
            f"**IQ:** `{iq}`\n"
            f"**HT:** `{ht}`\n"
            f"**ER:** `{base_er}`"
        ),
        inline=False,
    )

    sheet_embed.add_field(
        name=tr("Secondary Characteristics"),
        value=(
            f"{tr('Max HP')}: `{max_pv}`\n"
            f"{tr('Max FP')}: `{max_pf}`\n"
            f"{tr('Will')}: `{vont}`\n"
            f"{tr('Perception')}: `{per}`\n"
        ),
        inline=False,
    )

    sheet_embed.add_field(
        name=tr("Current Resources (HP - FP - ER)"),
        value=code_block(
            [
                resource_bar(catalog_label("resources", "hp"), int(character["current_pv"]), max_pv),
                resource_bar(catalog_label("resources", "fp"), int(character["current_pf"]), max_pf),
                resource_bar(catalog_label("resources", "er"), int(character["current_er"]), base_er),
            ]
        ),
        inline=False,
    )

    return sheet_embed


def _attachment_kwargs(interaction: discord.Interaction, character_file) -> dict:
    """Reuses an already attached portrait, uploading only when it is missing."""
    if character_file is None:
        return {"attachments": []}

    message = interaction.message
    existing_filenames = (
        {attachment.filename for attachment in message.attachments}
        if message
        else set()
    )

    if character_file.filename in existing_filenames:
        return {}

    return {"attachments": [character_file]}


class SheetHubView(discord.ui.View):
    """Interactive hub exposing the character sheet inspection modules."""

    def __init__(
        self,
        db_connection: sqlite3.Connection,
        character_id: int,
        author_id: int,
        sheet_embed: discord.Embed,
        strength: int | None = None,
        locale: str | None = None,
    ):
        super().__init__(timeout=None)
        self.db_connection = db_connection
        self.character_id = character_id
        self.author_id = author_id
        self.sheet_embed = sheet_embed
        self.strength = strength
        self.locale = locale

        button_specs = [
            (tr("Inventory"), self.open_inventory),
            (tr("Skills"), self.open_skills),
            (tr("Advantages/Disadvantages"), self.open_traits),
            (tr("Spells"), self.open_spells),
        ]

        for label, callback in button_specs:
            button = discord.ui.Button(label=label, style=discord.ButtonStyle.primary)
            button.callback = callback
            self.add_item(button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Restricts interaction to the user who invoked the command."""
        with locale_context(self.locale or get_locale()):
            if interaction.user.id != self.author_id:
                await interaction.response.send_message(
                    tr("Error: only the user who invoked this command can interact with this menu."),
                    ephemeral=True,
                )
                return False
            return True

    async def restore_hub(self, interaction: discord.Interaction):
        with locale_context(self.locale or get_locale()):
            return await self._restore_hub(interaction)

    async def _restore_hub(self, interaction: discord.Interaction):
        """Restores the central sheet embed replacing any child inspection view."""
        await interaction.response.defer()

        character_file, _ = get_character_thumbnail_by_id(
            self.db_connection, self.character_id
        )

        hub_view = SheetHubView(
            db_connection=self.db_connection,
            character_id=self.character_id,
            author_id=self.author_id,
            sheet_embed=self.sheet_embed,
            strength=self.strength,
            locale=self.locale,
        )

        await interaction.edit_original_response(
            content=None,
            embed=self.sheet_embed,
            view=hub_view,
            **_attachment_kwargs(interaction, character_file),
        )

    async def open_inventory(self, interaction: discord.Interaction):
        """Renders the paginated inventory pages on the hub message."""
        with locale_context(self.locale or get_locale()):
            return await self._open_inventory(interaction)

    async def _open_inventory(self, interaction: discord.Interaction):
        await interaction.response.defer()

        data = get_character_inventory_data_by_id(
            self.db_connection, self.character_id
        )

        if not data:
            await interaction.followup.send(
                tr("Consistency error: no inventory is associated with the character."),
                ephemeral=True,
            )
            return

        pages = build_inventory_pages(data, self.strength, self.locale)

        character_file, thumbnail_url = get_character_thumbnail_by_id(
            self.db_connection, self.character_id
        )

        child_view = InventoryView(
            pages=pages,
            author_id=self.author_id,
            thumbnail_url=thumbnail_url,
            back_callback=self.restore_hub,
            locale=self.locale,
        )

        await interaction.edit_original_response(
            content=None,
            embed=child_view.build_embed(),
            view=child_view,
            **_attachment_kwargs(interaction, character_file),
        )

    async def open_skills(self, interaction: discord.Interaction):
        """Renders the paginated skill list on the hub message."""
        with locale_context(self.locale or get_locale()):
            return await self._open_skills(interaction)

    async def _open_skills(self, interaction: discord.Interaction):
        await interaction.response.defer()

        skills_data = get_character_skills_data(self.db_connection, self.character_id)

        if not skills_data:
            await interaction.followup.send(
                tr(
                    "Consistency error: character with ID `{character_id}` was not found.",
                    character_id=self.character_id,
                ),
                ephemeral=True,
            )
            return

        if not skills_data["skills"]:
            await interaction.followup.send(
                tr(
                    "Character {character} has no registered skills.",
                    character=skills_data["character_name"],
                ),
                ephemeral=True,
            )
            return

        child_view = SkillListView(
            character_name=skills_data["character_name"],
            skills=skills_data["skills"],
            author_id=self.author_id,
            back_callback=self.restore_hub,
            locale=self.locale,
        )

        await interaction.edit_original_response(
            content=child_view.build_content(),
            embed=None,
            view=child_view,
            attachments=[],
        )

    async def open_traits(self, interaction: discord.Interaction):
        """Renders the paginated trait list on the hub message."""
        with locale_context(self.locale or get_locale()):
            return await self._open_traits(interaction)

    async def _open_traits(self, interaction: discord.Interaction):
        await interaction.response.defer()

        traits_data = get_character_traits_data(self.db_connection, self.character_id)

        if not traits_data:
            await interaction.followup.send(
                tr(
                    "Consistency error: character with ID `{character_id}` was not found.",
                    character_id=self.character_id,
                ),
                ephemeral=True,
            )
            return

        if not traits_data["advantages"] and not traits_data["disadvantages"]:
            await interaction.followup.send(
                tr(
                    "Character {character} has no registered advantages or disadvantages.",
                    character=traits_data["character_name"],
                ),
                ephemeral=True,
            )
            return

        child_view = TraitListView(
            character_name=traits_data["character_name"],
            traits=traits_data["advantages"] + traits_data["disadvantages"],
            author_id=self.author_id,
            back_callback=self.restore_hub,
            locale=self.locale,
        )

        await interaction.edit_original_response(
            content=child_view.build_content(),
            embed=None,
            view=child_view,
            attachments=[],
        )

    async def open_spells(self, interaction: discord.Interaction):
        """Renders the paginated spell list on the hub message."""
        with locale_context(self.locale or get_locale()):
            return await self._open_spells(interaction)

    async def _open_spells(self, interaction: discord.Interaction):
        await interaction.response.defer()

        spells_data = get_character_spells_data(self.db_connection, self.character_id)

        if not spells_data:
            await interaction.followup.send(
                tr(
                    "Consistency error: character with ID `{character_id}` was not found.",
                    character_id=self.character_id,
                ),
                ephemeral=True,
            )
            return

        if not spells_data["spells"]:
            await interaction.followup.send(
                tr(
                    "Character {character} has no registered spells.",
                    character=spells_data["character_name"],
                ),
                ephemeral=True,
            )
            return

        child_view = SpellListView(
            character_name=spells_data["character_name"],
            spells=spells_data["spells"],
            author_id=self.author_id,
            back_callback=self.restore_hub,
            locale=self.locale,
        )

        await interaction.edit_original_response(
            content=child_view.build_content(),
            embed=None,
            view=child_view,
            attachments=[],
        )


class Sheet(commands.Cog):
    """ """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        project_root = Path(__file__).resolve().parent.parent
        database_path = project_root / "data" / "database.db"

        # Establishing the persistent, active connection channel
        self.db_connection = sqlite3.connect(database_path)
        self.db_connection.execute("PRAGMA foreign_keys = ON;")

    async def character_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        """
        Dynamically queries the database for characters matching the user's keystrokes.
        Limits the return pool to 25 instances, respecting Discord API constraints.
        """
        cursor = self.db_connection.cursor()

        # SQL Injection defensive parameterization with wildcard
        search_pattern = f"%{current}%"

        cursor.execute(
            """
            SELECT character_id, name 
            FROM characters 
            WHERE name LIKE ? 
            LIMIT 25
            """,
            (search_pattern,),
        )

        fetched_characters = cursor.fetchall()

        return [
            app_commands.Choice(name=row[1], value=str(row[0]))
            for row in fetched_characters
        ]

    # sheet ---------------------------------------------------
    @app_commands.command(
        name="sheet",
        description="Send your character sheet as an ephemeral message.",
    )
    async def sheet(self, interaction: discord.Interaction):
        locale = apply_interaction_locale(interaction, self.db_connection)

        # Immediate deferral to respect Discord's temporal strictures.
        await interaction.response.defer(ephemeral=True)

        player_id = interaction.user.id

        try:
            character = get_character_profile(self.db_connection, player_id)
        except ValueError as e:
            # Capturing database anomalies if the user lacks an active character matrix
            await interaction.followup.send(
                tr("Processing error: {detail}", detail=e), ephemeral=True
            )
            return

        sheet_embed = build_sheet_embed(character)

        # Binary asset pipeline extraction for the character thumbnail
        character_file, thumbnail_url = get_character_thumbnail_payload(
            self.db_connection, player_id
        )

        if thumbnail_url:
            sheet_embed.set_thumbnail(url=thumbnail_url)

        hub_view = SheetHubView(
            db_connection=self.db_connection,
            character_id=character["character_id"],
            author_id=interaction.user.id,
            sheet_embed=sheet_embed,
            strength=character["st"],
            locale=locale,
        )

        # Mandatory followup via webhook, transmitting the final embed with the hub
        if character_file is not None:
            await interaction.followup.send(
                embed=sheet_embed, file=character_file, view=hub_view, ephemeral=True
            )
        else:
            await interaction.followup.send(
                embed=sheet_embed, view=hub_view, ephemeral=True
            )

    @app_commands.command(
        name="sheet_view",
        description="Let the GM inspect any character sheet in the system.",
    )
    @app_commands.autocomplete(character=character_autocomplete)
    @app_commands.describe(
        character="Character that will be inspected."
    )
    @app_commands.default_permissions(administrator=True)
    async def sheet_view(self, interaction: discord.Interaction, character: str):
        locale = apply_interaction_locale(interaction, self.db_connection)

        # Immediate deferral to respect Discord's temporal strictures.
        await interaction.response.defer(ephemeral=True)

        # Casting the string ID originating from the autocomplete payload back to an integer
        try:
            target_character_id = int(character)
        except ValueError:
            await interaction.followup.send(
                tr(
                    "Processing error: the supplied character identifier is structurally invalid."
                )
            )
            return

        # Invoking the newly minted high-efficiency primary key extraction function
        try:
            character_data = get_character_profile_by_id(
                self.db_connection, target_character_id
            )
        except ValueError as e:
            await interaction.followup.send(
                tr("Processing error: {detail}", detail=e)
            )
            return

        sheet_view_embed = build_sheet_embed(character_data)

        # Binary asset pipeline extraction using the primary key
        character_file, thumbnail_url = get_character_thumbnail_by_id(
            self.db_connection, target_character_id
        )

        if thumbnail_url:
            sheet_view_embed.set_thumbnail(url=thumbnail_url)

        hub_view = SheetHubView(
            db_connection=self.db_connection,
            character_id=target_character_id,
            author_id=interaction.user.id,
            sheet_embed=sheet_view_embed,
            strength=character_data["st"],
            locale=locale,
        )

        # Strict conditional dispatch protecting network payload against NoneType serialization
        if character_file is not None:
            await interaction.followup.send(
                embed=sheet_view_embed,
                file=character_file,
                view=hub_view,
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                embed=sheet_view_embed, view=hub_view, ephemeral=True
            )


async def setup(bot: commands.Bot) -> None:
    """
    Mandatory asynchronous entry point to load the extension.
    """
    await bot.add_cog(Sheet(bot))
