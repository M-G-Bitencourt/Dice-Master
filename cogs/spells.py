import discord
from discord import app_commands
from discord.ext import commands
from pathlib import Path

import sqlite3

from utils.db_functions import (
    _resolve_character_id,
    get_character_spells_data,
)


class SpellSelect(discord.ui.Select):
    """Dropdown component for inspecting details of a specific character spell."""

    def __init__(self, spells_chunk: list[dict]):
        options = [
            discord.SelectOption(
                label=m["name"][:100],
                value=str(m["spell_id"]),
                description=f"NH {m['nh']} | Custo: {m['cost']} {m['resource']} | {m['attribute']}/{m['difficulty']}"[:100],
            )
            for m in spells_chunk
        ]
        super().__init__(
            placeholder="Selecione uma magia para inspecionar...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        """Updates the interaction message with the full rules embed of the selected spell."""
        view: SpellListView = self.view  # type: ignore
        selected_id = int(self.values[0])
        selected_spell = view.spells_by_id.get(selected_id)

        if not selected_spell:
            await interaction.response.send_message(
                "Erro: Magia não localizada no registro atual.", ephemeral=True
            )
            return

        desc_raw = (
            selected_spell["description"]
            or "Nenhuma descrição detalhada disponível."
        )

        # Header containing essential metrics at the top of the card
        header = (
            f"**NH:** `{selected_spell['nh']}` | "
            f"**Custo:** `{selected_spell['cost']} {selected_spell['resource']}`\n"
            f"**Nível Relativo:** `{selected_spell['relative_display']}` | "
            f"**Dificuldade:** `{selected_spell['attribute']} / {selected_spell['difficulty']}`\n\n"
            f"**Descrição e Regras:**\n"
        )

        # The embed description allows up to 4000 characters (vs 1000 in a field)
        max_desc_len = 4000 - len(header)
        if len(desc_raw) > max_desc_len:
            desc_text = desc_raw[: max_desc_len - 3] + "..."
        else:
            desc_text = desc_raw

        embed = discord.Embed(
            title=f"Magia: {selected_spell['name']}"[:256],
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
    ):
        super().__init__(timeout=None)
        self.character_name = character_name
        self.spells = spells
        self.author_id = author_id
        self.back_callback = back_callback
        self.spells_by_id = {m["spell_id"]: m for m in spells}
        self.page_size = 25
        self.current_page = 0
        self.total_pages = max(1, (len(spells) - 1) // self.page_size + 1)

        self.update_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Restricts interaction to the user who invoked the command."""
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Erro: Apenas o usuário que invocou o comando pode interagir com este menu.",
                ephemeral=True,
            )
            return False
        return True

    def build_content(self) -> str:
        """Renders the compact formatted Markdown list for the current page, grouped by school."""
        start_idx = self.current_page * self.page_size
        end_idx = start_idx + self.page_size
        page_spells = self.spells[start_idx:end_idx]

        lines = [f"# Magias: **{self.character_name}**"]
        if self.total_pages > 1:
            lines.append(f"*Página {self.current_page + 1} de {self.total_pages}*")
        lines.append("---")

        current_school = None
        for m in page_spells:
            school = m.get("school", "Sem Escola")
            if school != current_school:
                lines.append(f"## {school}")
                current_school = school

            lines.append(
                f"- **{m['name']}** (NH `{m['nh']}`) | Custo `{m['cost']} {m['resource']}`"
            )

        lines.append("---")
        lines.append("*Selecione uma magia no menu abaixo para inspecionar seus detalhes.*")
        return "\n".join(lines)[:1900]

    def update_components(self):
        """Refreshes the active components based on the current page slice."""
        self.clear_items()

        start_idx = self.current_page * self.page_size
        end_idx = start_idx + self.page_size
        page_spells = self.spells[start_idx:end_idx]

        self.add_item(SpellSelect(page_spells))

        if self.total_pages > 1:
            prev_button = discord.ui.Button(
                label="< Anterior",
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
                label="Próxima >",
                style=discord.ButtonStyle.secondary,
                disabled=(self.current_page >= self.total_pages - 1),
            )
            next_button.callback = self.next_page
            self.add_item(next_button)

        if self.back_callback is not None:
            back_button = discord.ui.Button(
                label="Voltar",
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

    async def character_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        """Dynamically queries the database for characters matching the user's keystrokes."""
        cursor = self.db_connection.cursor()
        search_pattern = f"%{current}%"

        cursor.execute(
            "SELECT character_id, name FROM characters WHERE name LIKE ? LIMIT 25",
            (search_pattern,),
        )

        return [
            app_commands.Choice(name=row[1], value=str(row[0]))
            for row in cursor.fetchall()
        ]

    @app_commands.command(
        name="master_list_spells",
        description="Exibe a lista de magias com cálculo de NH e inspeção detalhada.",
    )
    @app_commands.autocomplete(character=character_autocomplete)
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        character="Personagem a ser consultado (apenas administradores podem consultar terceiros)."
    )
    async def master_list_spells(
        self,
        interaction: discord.Interaction,
        character: str | None = None,
    ):
        """Renders character spells with effective NH calculation and inspection dropdown."""
        await interaction.response.defer(ephemeral=True)

        if character is not None:
            try:
                target_char_id = int(character)
            except ValueError:
                await interaction.followup.send(
                    "Erro de processamento: O identificador do personagem fornecido é inválido.",
                    ephemeral=True,
                )
                return
        else:
            try:
                target_char_id = _resolve_character_id(
                    self.db_connection, interaction.user.id
                )
            except ValueError:
                await interaction.followup.send(
                    "Erro: Você não possui um personagem ativo atribuído à sua conta.",
                    ephemeral=True,
                )
                return

        spells_data = get_character_spells_data(
            self.db_connection, target_char_id
        )

        if not spells_data:
            await interaction.followup.send(
                f"Erro de consistência: Personagem com ID `{target_char_id}` não foi localizado.",
                ephemeral=True,
            )
            return

        if not spells_data["spells"]:
            await interaction.followup.send(
                f"O personagem {spells_data['character_name']} não possui nenhuma magia cadastrada.",
                ephemeral=True,
            )
            return

        view = SpellListView(
            character_name=spells_data["character_name"],
            spells=spells_data["spells"],
            author_id=interaction.user.id,
        )

        await interaction.followup.send(
            content=view.build_content(),
            view=view,
            ephemeral=True,
        )

    @app_commands.command(
        name="list_spells",
        description="Exibe a lista de magias do seu personagem com cálculo de NH e inspeção detalhada.",
    )
    async def list_spells(self, interaction: discord.Interaction):
        """Renders the caller's character spells with effective NH calculation and inspection dropdown."""
        await interaction.response.defer(ephemeral=True)

        try:
            target_char_id = _resolve_character_id(
                self.db_connection, interaction.user.id
            )
        except ValueError:
            await interaction.followup.send(
                "Erro: Você não possui um personagem ativo atribuído à sua conta.",
                ephemeral=True,
            )
            return

        spells_data = get_character_spells_data(
            self.db_connection, target_char_id
        )

        if not spells_data:
            await interaction.followup.send(
                f"Erro de consistência: Personagem com ID `{target_char_id}` não foi localizado.",
                ephemeral=True,
            )
            return

        if not spells_data["spells"]:
            await interaction.followup.send(
                f"O personagem {spells_data['character_name']} não possui nenhuma magia cadastrada.",
                ephemeral=True,
            )
            return

        view = SpellListView(
            character_name=spells_data["character_name"],
            spells=spells_data["spells"],
            author_id=interaction.user.id,
        )

        await interaction.followup.send(
            content=view.build_content(),
            view=view,
            ephemeral=True,
        )

async def setup(bot: commands.Bot) -> None:
    """Mandatory asynchronous entry point to load the extension."""
    await bot.add_cog(Spells(bot))