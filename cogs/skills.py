import discord
from discord import app_commands
from discord.ext import commands
from pathlib import Path

import sqlite3

from utils.ansi import (
    ACCENT_COLOR,
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
from utils.db_functions import (
    _resolve_character_id,
    get_character_skills_data,
)


def build_skill_row(skill: dict) -> str:
    """Builds one aligned ANSI row for the compact skill list."""
    name = truncate_visible(skill["name"], 30)
    relative_display = skill["relative_display"]
    nh_display = str(skill["nh"])

    return (
        f"{ansi(pad(name, 30), NEUTRAL_COLOR)}  "
        f"{pad(ansi(relative_display, ACCENT_COLOR), 7)} "
        f"{ansi('NH', LABEL_COLOR)} {ansi(nh_display, SUCCESS_COLOR)}"
    )


def build_skill_header(skill: dict) -> str:
    """Builds the colored metric header for a skill detail card."""
    nh_display = str(skill["nh"])
    relative_display = skill["relative_display"]
    difficulty_display = f"{skill['attribute']} / {skill['difficulty']}"

    lines = [
        f"{ansi('NH', LABEL_COLOR)} {ansi(nh_display, SUCCESS_COLOR)} | "
        f"{ansi('Nível Relativo', LABEL_COLOR)} {ansi(relative_display, ACCENT_COLOR)} | "
        f"{ansi('Dificuldade', LABEL_COLOR)} {ansi(difficulty_display, NEUTRAL_COLOR)}"
    ]

    return code_block(lines) + "\n**Descrição e Regras:**\n"


class SkillSelect(discord.ui.Select):
    """Dropdown component for inspecting details of a specific character skill."""

    def __init__(self, skills_chunk: list[dict]):
        options = [
            discord.SelectOption(
                label=s["name"][:100],
                value=str(s["skill_id"]),
                description=f"NH {s['nh']} | Base {s['relative_display']} ({s['difficulty']})"[:100],
            )
            for s in skills_chunk
        ]
        super().__init__(
            placeholder="Selecione uma perícia para inspecionar...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        """Updates the interaction message with the full rules embed of the selected skill."""
        view: SkillListView = self.view  # type: ignore
        selected_id = int(self.values[0])
        selected_skill = view.skills_by_id.get(selected_id)

        if not selected_skill:
            await interaction.response.send_message(
                "Erro: Perícia não localizada no registro atual.", ephemeral=True
            )
            return

        desc_raw = (
            selected_skill["description"]
            or "Nenhuma descrição detalhada disponível."
        )

        # Header containing essential combat metrics at the top of the card
        header = build_skill_header(selected_skill)

        # The embed description allows up to 4000 characters (vs 1000 in a field)
        max_desc_len = 4000 - len(header)
        if len(desc_raw) > max_desc_len:
            desc_text = desc_raw[: max_desc_len - 3] + "..."
        else:
            desc_text = desc_raw

        embed = discord.Embed(
            title=f"Perícia: {selected_skill['name']}"[:256],
            description=header + desc_text,
            color=discord.Color.blue(),
        )

        await interaction.response.edit_message(
            content=view.build_content(),
            embed=embed,
            view=view,
        )


class SkillListView(discord.ui.View):
    """Interactive view managing the paginated compact skill list and dropdown."""

    def __init__(
        self,
        character_name: str,
        skills: list[dict],
        author_id: int,
        back_callback=None,
    ):
        super().__init__(timeout=None)
        self.character_name = character_name
        self.skills = skills
        self.author_id = author_id
        self.back_callback = back_callback
        self.skills_by_id = {s["skill_id"]: s for s in skills}

        rows = [(skill, build_skill_row(skill)) for skill in skills]
        self.pages = paginate_rows(rows, base_length=300) or [[]]
        self.current_page = 0
        self.total_pages = len(self.pages)

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
        """Renders the colored ANSI list for the current page."""
        page_rows = self.pages[self.current_page]

        lines = [f"# Perícias: **{sanitize(self.character_name)}**"]
        if self.total_pages > 1:
            lines.append(f"*Página {self.current_page + 1} de {self.total_pages}*")
        lines.append("---")
        lines.append(code_block([line for _, line in page_rows]))
        lines.append("---")
        lines.append("*Selecione uma perícia no menu abaixo para inspecionar seus detalhes.*")

        return clamp_code_block("\n".join(lines), 1900)

    def update_components(self):
        """Refreshes the active components based on the current page slice."""
        self.clear_items()

        page_skills = [
            skill for skill, _ in self.pages[self.current_page] if skill is not None
        ]

        self.add_item(SkillSelect(page_skills))

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


class Skills(commands.Cog):
    """Cog responsible for character skill management and inspection."""

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
        name="master_list_skills",
        description="Exibe a lista de perícias com cálculo de NH e inspeção detalhada.",
    )
    @app_commands.autocomplete(character=character_autocomplete)
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        character="Personagem a ser consultado (apenas administradores podem consultar terceiros)."
    )
    async def master_list_skills(
        self,
        interaction: discord.Interaction,
        character: str | None = None,
    ):
        """Renders character skills with effective NH calculation and inspection dropdown."""
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

        skills_data = get_character_skills_data(
            self.db_connection, target_char_id
        )

        if not skills_data:
            await interaction.followup.send(
                f"Erro de consistência: Personagem com ID `{target_char_id}` não foi localizado.",
                ephemeral=True,
            )
            return

        if not skills_data["skills"]:
            await interaction.followup.send(
                f"O personagem {skills_data['character_name']} não possui nenhuma perícia cadastrada.",
                ephemeral=True,
            )
            return

        view = SkillListView(
            character_name=skills_data["character_name"],
            skills=skills_data["skills"],
            author_id=interaction.user.id,
        )

        await interaction.followup.send(
            content=view.build_content(),
            view=view,
            ephemeral=True,
        )

    @app_commands.command(
        name="list_skills",
        description="Exibe a lista de perícias do seu personagem com cálculo de NH e inspeção detalhada.",
    )
    async def list_skills(self, interaction: discord.Interaction):
        """Renders the caller's character skills with effective NH calculation and inspection dropdown."""
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

        skills_data = get_character_skills_data(
            self.db_connection, target_char_id
        )

        if not skills_data:
            await interaction.followup.send(
                f"Erro de consistência: Personagem com ID `{target_char_id}` não foi localizado.",
                ephemeral=True,
            )
            return

        if not skills_data["skills"]:
            await interaction.followup.send(
                f"O personagem {skills_data['character_name']} não possui nenhuma perícia cadastrada.",
                ephemeral=True,
            )
            return

        view = SkillListView(
            character_name=skills_data["character_name"],
            skills=skills_data["skills"],
            author_id=interaction.user.id,
        )

        await interaction.followup.send(
            content=view.build_content(),
            view=view,
            ephemeral=True,
        )

async def setup(bot: commands.Bot) -> None:
    """Mandatory asynchronous entry point to load the extension."""
    await bot.add_cog(Skills(bot))
