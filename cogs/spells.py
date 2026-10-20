import discord
from discord.ext import commands
from pathlib import Path

import sqlite3

from utils.i18n import catalog_label_from_value, get_locale, locale_context, t as tr
from utils.ansi import (
    ACCENT_COLOR,
    LABEL_COLOR,
    NEUTRAL_COLOR,
    SUCCESS_COLOR,
    WARN_COLOR,
    ansi,
    clamp_code_block,
    code_block,
    pad,
    paginate_rows,
    sanitize,
    truncate_visible,
)



def build_spell_row(spell: dict) -> str:
    """Builds one aligned ANSI row for the compact spell list."""
    name = truncate_visible(spell["name"], 26)
    nh_display = str(spell["nh"])
    cost_display = f"{spell['cost']} {spell['resource']}"

    return (
        f"{ansi(pad(name, 26), NEUTRAL_COLOR)}  "
        f"{ansi(tr('Skill'), LABEL_COLOR)} {pad(ansi(nh_display, SUCCESS_COLOR), 5)} "
        f"{ansi(cost_display, WARN_COLOR)}"
    )


def build_spell_header(spell: dict) -> str:
    """Builds the colored metric header for a spell detail card."""
    nh_display = str(spell["nh"])
    cost_display = f"{spell['cost']} {spell['resource']}"
    relative_display = spell["relative_display"]
    difficulty_display = f"{spell['attribute']} / {spell['difficulty']}"

    lines = [
        f"{ansi(tr('Skill'), LABEL_COLOR)} {ansi(nh_display, SUCCESS_COLOR)} | "
        f"{ansi(tr('Cost'), LABEL_COLOR)} {ansi(cost_display, WARN_COLOR)}",
        f"{ansi(tr('Relative Level'), LABEL_COLOR)} {ansi(relative_display, ACCENT_COLOR)} | "
        f"{ansi(tr('Difficulty'), LABEL_COLOR)} {ansi(difficulty_display, NEUTRAL_COLOR)}",
    ]

    return code_block(lines) + f"\n**{tr('Description and Rules:')}**\n"


class SpellSelect(discord.ui.Select):
    """Dropdown component for inspecting details of a specific character spell."""

    def __init__(self, spells_chunk: list[dict]):
        options = [
            discord.SelectOption(
                label=m["name"][:100],
                value=str(m["spell_id"]),
                description=f"{tr('Skill')} {m['nh']} | {tr('Cost')}: {m['cost']} {m['resource']} | {m['attribute']}/{m['difficulty']}"[:100],
            )
            for m in spells_chunk
        ]
        super().__init__(
            placeholder=tr("Select a spell to inspect..."),
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        """Updates the interaction message with the full rules embed of the selected spell."""
        view: SpellListView = self.view  # type: ignore
        with locale_context(view.locale or get_locale()):
            selected_id = int(self.values[0])
            selected_spell = view.spells_by_id.get(selected_id)

            if not selected_spell:
                await interaction.response.send_message(
                    tr("Error: spell not found in the current record."),
                    ephemeral=True,
                )
                return

            desc_raw = (
                selected_spell["description"]
                if selected_spell["description"]
                != "Nenhuma descrição detalhada disponível."
                else tr("No detailed description available.")
            )

            header = build_spell_header(selected_spell)

            max_desc_len = 4000 - len(header)
            if len(desc_raw) > max_desc_len:
                desc_text = desc_raw[: max_desc_len - 3] + "..."
            else:
                desc_text = desc_raw

            embed = discord.Embed(
                title=tr("Spell: {name}", name=selected_spell["name"])[:256],
                description=header + desc_text,
                color=discord.Color.purple(),
            )

            await interaction.response.edit_message(
                content=view.build_content(),
                embed=embed,
                view=view,
            )


class SpellListView(discord.ui.View):
    """Interactive view managing the paginated compact spell list and dropdown."""

    def __init__(
        self,
        character_name: str,
        spells: list[dict],
        author_id: int,
        back_callback=None,
        locale: str | None = None,
    ):
        super().__init__(timeout=None)
        self.character_name = character_name
        self.spells = spells
        self.author_id = author_id
        self.back_callback = back_callback
        self.locale = locale
        self.spells_by_id = {m["spell_id"]: m for m in spells}

        rows = []
        current_school = None
        for spell in spells:
            school = spell.get("school", "Sem Escola")
            if school != current_school:
                current_school = school
                rows.append((None, ansi(school, LABEL_COLOR)))
            rows.append((spell, build_spell_row(spell)))

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
        """Renders the colored ANSI list for the current page, grouped by school."""
        with locale_context(self.locale or get_locale()):
            page_rows = self.pages[self.current_page]

            lines = [tr("# Spells: **{character}**", character=sanitize(self.character_name))]
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
                first = page_rows[0][0]
                school_name = first.get("school") or "Sem Escola"
                if school_name == "Sem Escola":
                    school_label = tr("No School")
                else:
                    school_label = catalog_label_from_value("schools", school_name)
                block_lines.insert(0, ansi(school_label, LABEL_COLOR))

            lines.append(code_block(block_lines))
            lines.append("---")
            lines.append(
                f"*{tr('Select a spell from the menu below to inspect its details.')}*"
            )

            return clamp_code_block("\n".join(lines), 1900)

    def update_components(self):
        """Refreshes the active components based on the current page slice."""
        self.clear_items()

        page_spells = [
            spell for spell, _ in self.pages[self.current_page] if spell is not None
        ]

        with locale_context(self.locale or get_locale()):
            self.add_item(SpellSelect(page_spells))

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


class Spells(commands.Cog):
    """Cog responsible for character spell management and inspection."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        project_root = Path(__file__).resolve().parent.parent
        database_path = project_root / "data" / "database.db"

        self.db_connection = sqlite3.connect(database_path)
        self.db_connection.execute("PRAGMA foreign_keys = ON;")


async def setup(bot: commands.Bot) -> None:
    """Mandatory asynchronous entry point to load the extension."""
    await bot.add_cog(Spells(bot))