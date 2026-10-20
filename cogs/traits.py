import discord
from discord.ext import commands
from pathlib import Path

import sqlite3

from utils.i18n import catalog_label_from_value, get_locale, locale_context, t as tr
from utils.ansi import (
    DANGER_COLOR,
    LABEL_COLOR,
    NEUTRAL_COLOR,
    SUCCESS_COLOR,
    ansi,
    clamp_code_block,
    code_block,
    pad,
    paginate_rows,
    sanitize,
    truncate_visible,
)



def build_trait_row(trait: dict) -> str:
    """Builds one aligned ANSI row for the compact trait list."""
    name = truncate_visible(trait["name"], 30)
    cost = int(trait["cost"])
    cost_display = f"{cost:+d} pts"
    cost_color = SUCCESS_COLOR if cost >= 0 else DANGER_COLOR

    return (
        f"{ansi(pad(name, 30), NEUTRAL_COLOR)}  "
        f"{ansi(cost_display, cost_color)}"
    )


def build_trait_header(trait: dict) -> str:
    """Builds the colored point cost header for a trait detail card."""
    cost = int(trait["cost"])
    cost_display = f"{cost:+d} pts"
    cost_color = SUCCESS_COLOR if cost >= 0 else DANGER_COLOR

    return code_block(
        [f"{ansi(tr('Cost'), LABEL_COLOR)} {ansi(cost_display, cost_color)}"]
    )


class TraitSelect(discord.ui.Select):
    """Dropdown component for inspecting details of a specific character trait."""

    def __init__(self, traits_chunk: list[dict]):
        options = [
            discord.SelectOption(
                label=t["name"][:100],
                value=t["trait_key"],
                description=f"{catalog_label_from_value('trait_categories', t['category'])} | {tr('Cost')}: {t['cost']} pts"[:100],
            )
            for t in traits_chunk
        ]
        super().__init__(
            placeholder=tr("Select a trait to inspect..."),
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        """Updates the interaction message with the full rules embed of the selected trait."""
        view: TraitListView = self.view  # type: ignore
        with locale_context(view.locale or get_locale()):
            selected_key = self.values[0]
            selected_trait = view.traits_by_key.get(selected_key)

            if not selected_trait:
                await interaction.response.send_message(
                    tr("Error: trait not found in the current record."),
                    ephemeral=True,
                )
                return

            desc_raw = (
                selected_trait["description"]
                if selected_trait["description"]
                != "Nenhuma descrição detalhada disponível."
                else tr("No detailed description available.")
            )

            notes_raw = (selected_trait["notes"] or "").strip()
            notes_text = (
                notes_raw[:1000]
                if notes_raw
                else tr("No notes recorded.")
            )

            header = (
                build_trait_header(selected_trait)
                + f"\n**{tr('Notes:')}** {notes_text}\n\n"
                + f"**{tr('Description and Rules:')}**\n"
            )

            max_desc_len = 4000 - len(header)
            if len(desc_raw) > max_desc_len:
                desc_text = desc_raw[: max_desc_len - 3] + "..."
            else:
                desc_text = desc_raw

            category = catalog_label_from_value(
                "trait_categories", selected_trait["category"]
            )
            is_advantage = selected_trait["category"] == "Vantagem"
            embed = discord.Embed(
                title=f"{category}: {selected_trait['name']}"[:256],
                description=header + desc_text,
                color=discord.Color.gold() if is_advantage else discord.Color.dark_red(),
            )

            await interaction.response.edit_message(
                content=view.build_content(),
                embed=embed,
                view=view,
            )


class TraitListView(discord.ui.View):
    """Interactive view managing the paginated compact trait list and dropdown."""

    def __init__(
        self,
        character_name: str,
        traits: list[dict],
        author_id: int,
        back_callback=None,
        locale: str | None = None,
    ):
        super().__init__(timeout=None)
        self.character_name = character_name
        self.traits = traits
        self.author_id = author_id
        self.back_callback = back_callback
        self.locale = locale
        self.traits_by_key = {t["trait_key"]: t for t in traits}

        rows = []
        current_category = None
        for trait in traits:
            if trait["category"] != current_category:
                current_category = trait["category"]
                rows.append((None, ansi(current_category.upper(), LABEL_COLOR)))
            rows.append((trait, build_trait_row(trait)))

        self.pages = paginate_rows(rows, base_length=300) or [[]]
        self.current_page = 0
        self.total_pages = len(self.pages)

        self.update_components()

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

    def build_content(self) -> str:
        """Renders the colored ANSI list for the current page, grouped by category."""
        with locale_context(self.locale or get_locale()):
            page_rows = self.pages[self.current_page]

            lines = [
                tr(
                    "# Advantages and Disadvantages: **{character}**",
                    character=sanitize(self.character_name),
                )
            ]
            if self.total_pages > 1:
                lines.append(
                    tr(
                        "*Page {current} of {total}*",
                        current=self.current_page + 1,
                        total=self.total_pages,
                    )
                )
            lines.append("---")

            block_lines = [line for _, line in page_rows]
            if page_rows and page_rows[0][0] is not None:
                category = catalog_label_from_value(
                    "trait_categories", page_rows[0][0]["category"]
                )
                block_lines.insert(0, ansi(category.upper(), LABEL_COLOR))

            lines.append(code_block(block_lines))
            lines.append("---")
            lines.append(
                f"*{tr('Select a trait from the menu below to inspect its details.')}*"
            )

            return clamp_code_block("\n".join(lines), 1900)

    def update_components(self):
        """Refreshes the active components based on the current page slice."""
        self.clear_items()

        page_traits = [
            trait for trait, _ in self.pages[self.current_page] if trait is not None
        ]

        with locale_context(self.locale or get_locale()):
            self.add_item(TraitSelect(page_traits))

            if self.total_pages > 1:
                prev_button = discord.ui.Button(
                    label=f"< {tr('Previous')}",
                    style=discord.ButtonStyle.secondary,
                    disabled=(self.current_page == 0),
                )
                prev_button.callback = self.previous_page
                self.add_item(prev_button)

                indicator_button = discord.ui.Button(
                    label=f"{self.current_page + 1} / {self.total_pages}",
                    style=discord.ButtonStyle.primary,
                    disabled=True,
                )
                self.add_item(indicator_button)

                next_button = discord.ui.Button(
                    label=f"{tr('Next')} >",
                    style=discord.ButtonStyle.secondary,
                    disabled=(self.current_page >= self.total_pages - 1),
                )
                next_button.callback = self.next_page
                self.add_item(next_button)

            if self.back_callback is not None:
                back_button = discord.ui.Button(
                    label=tr("Back"),
                    style=discord.ButtonStyle.secondary,
                )
                back_button.callback = self.go_back
                self.add_item(back_button)

    async def go_back(self, interaction: discord.Interaction):
        """Delegates navigation back to the parent view when configured."""
        await self.back_callback(interaction)

    async def previous_page(self, interaction: discord.Interaction):
        """Moves view to the previous page."""
        if self.current_page > 0:
            self.current_page -= 1
            self.update_components()
            await interaction.response.edit_message(
                content=self.build_content(),
                embed=None,
                view=self,
            )

    async def next_page(self, interaction: discord.Interaction):
        """Moves view to the next page."""
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            self.update_components()
            await interaction.response.edit_message(
                content=self.build_content(),
                embed=None,
                view=self,
            )


class Traits(commands.Cog):
    """Cog responsible for character advantage and disadvantage inspection."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        project_root = Path(__file__).resolve().parent.parent
        database_path = project_root / "data" / "database.db"

        self.db_connection = sqlite3.connect(database_path)
        self.db_connection.execute("PRAGMA foreign_keys = ON;")


async def setup(bot: commands.Bot) -> None:
    """Mandatory asynchronous entry point to load the extension."""
    await bot.add_cog(Traits(bot))
