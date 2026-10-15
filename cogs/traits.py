import discord
from discord import app_commands
from discord.ext import commands
from pathlib import Path

import sqlite3

from utils.db_functions import (
    _resolve_character_id,
    get_character_traits_data,
)

class TraitSelect(discord.ui.Select):
    """Dropdown component for inspecting details of a specific character trait."""

    def __init__(self, traits_chunk: list[dict]):
        options = [
            discord.SelectOption(
                label=t["name"][:100],
                value=t["trait_key"],
                description=f"{t['category']} | Custo: {t['cost']} pts"[:100],
            )
            for t in traits_chunk
        ]
        super().__init__(
            placeholder="Selecione uma característica para inspecionar...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        """Updates the interaction message with the full rules embed of the selected trait."""
        view: TraitListView = self.view  # type: ignore
        selected_key = self.values[0]
        selected_trait = view.traits_by_key.get(selected_key)

        if not selected_trait:
            await interaction.response.send_message(
                "Erro: Característica não localizada no registro atual.", ephemeral=True
            )
            return

        desc_raw = (
            selected_trait["description"]
            or "Nenhuma descrição detalhada disponível."
        )

        notes_raw = (selected_trait["notes"] or "").strip()
        notes_text = notes_raw[:1000] if notes_raw else "Nenhuma observação registrada."

        # Header containing essential point cost and per-character notes
        header = (
            f"**Custo:** `{selected_trait['cost']} pts`\n"
            f"**Observações:** {notes_text}\n\n"
            f"**Descrição e Regras:**\n"
        )

        # The embed description allows up to 4096 characters
        max_desc_len = 4096 - len(header)
        if len(desc_raw) > max_desc_len:
            desc_text = desc_raw[: max_desc_len - 3] + "..."
        else:
            desc_text = desc_raw

        is_advantage = selected_trait["category"] == "Vantagem"
        embed = discord.Embed(
            title=f"{selected_trait['category']}: {selected_trait['name']}",
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
    ):
        super().__init__(timeout=180.0)
        self.character_name = character_name
        self.traits = traits
        self.author_id = author_id
        self.back_callback = back_callback
        self.traits_by_key = {t["trait_key"]: t for t in traits}
        self.page_size = 25
        self.current_page = 0
        self.total_pages = max(1, (len(traits) - 1) // self.page_size + 1)

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
        """Renders the compact formatted Markdown list for the current page, grouped by category."""
        start_idx = self.current_page * self.page_size
        end_idx = start_idx + self.page_size
        page_traits = self.traits[start_idx:end_idx]

        lines = [f"# Vantagens e Desvantagens: **{self.character_name}**"]
        if self.total_pages > 1:
            lines.append(f"*Página {self.current_page + 1} de {self.total_pages}*")
        lines.append("---")

        page_advantages = [t for t in page_traits if t["category"] == "Vantagem"]
        page_disadvantages = [t for t in page_traits if t["category"] == "Desvantagem"]

        if page_advantages:
            lines.append("## Vantagens")
            for t in page_advantages:
                lines.append(f"- **{t['name']}** (Custo `{t['cost']} pts`)")

        if page_disadvantages:
            lines.append("## Desvantagens")
            for t in page_disadvantages:
                lines.append(f"- **{t['name']}** (Custo `{t['cost']} pts`)")

        lines.append("---")
        lines.append("*Selecione uma característica no menu abaixo para inspecionar seus detalhes.*")
        return "\n".join(lines)[:1900]

    def update_components(self):
        """Refreshes the active components based on the current page slice."""
        self.clear_items()

        start_idx = self.current_page * self.page_size
        end_idx = start_idx + self.page_size
        page_traits = self.traits[start_idx:end_idx]

        self.add_item(TraitSelect(page_traits))

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

    async def on_timeout(self):
        """Disables interactive components when the view times out."""
        for item in self.children:
            item.disabled = True

class Traits(commands.Cog):
    """Cog responsible for character advantage and disadvantage inspection."""

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
        name="master_list_traits",
        description="Exibe a lista de vantagens e desvantagens com inspeção detalhada.",
    )
    @app_commands.autocomplete(character=character_autocomplete)
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        character="Personagem a ser consultado (apenas administradores podem consultar terceiros)."
    )
    async def master_list_traits(
        self,
        interaction: discord.Interaction,
        character: str | None = None,
    ):
        """Renders character advantages and disadvantages with inspection dropdown."""
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

        traits_data = get_character_traits_data(
            self.db_connection, target_char_id
        )

        if not traits_data:
            await interaction.followup.send(
                f"Erro de consistência: Personagem com ID `{target_char_id}` não foi localizado.",
                ephemeral=True,
            )
            return

        if not traits_data["advantages"] and not traits_data["disadvantages"]:
            await interaction.followup.send(
                f"O personagem {traits_data['character_name']} não possui nenhuma vantagem ou desvantagem cadastrada.",
                ephemeral=True,
            )
            return

        view = TraitListView(
            character_name=traits_data["character_name"],
            traits=traits_data["advantages"] + traits_data["disadvantages"],
            author_id=interaction.user.id,
        )

        await interaction.followup.send(
            content=view.build_content(),
            view=view,
            ephemeral=True,
        )

    @app_commands.command(
        name="list_traits",
        description="Exibe a lista de vantagens e desvantagens do seu personagem com inspeção detalhada.",
    )
    async def list_traits(self, interaction: discord.Interaction):
        """Renders the caller's character advantages and disadvantages with inspection dropdown."""
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

        traits_data = get_character_traits_data(
            self.db_connection, target_char_id
        )

        if not traits_data:
            await interaction.followup.send(
                f"Erro de consistência: Personagem com ID `{target_char_id}` não foi localizado.",
                ephemeral=True,
            )
            return

        if not traits_data["advantages"] and not traits_data["disadvantages"]:
            await interaction.followup.send(
                f"O personagem {traits_data['character_name']} não possui nenhuma vantagem ou desvantagem cadastrada.",
                ephemeral=True,
            )
            return

        view = TraitListView(
            character_name=traits_data["character_name"],
            traits=traits_data["advantages"] + traits_data["disadvantages"],
            author_id=interaction.user.id,
        )

        await interaction.followup.send(
            content=view.build_content(),
            view=view,
            ephemeral=True,
        )

async def setup(bot: commands.Bot) -> None:
    """Mandatory asynchronous entry point to load the extension."""
    await bot.add_cog(Traits(bot))
