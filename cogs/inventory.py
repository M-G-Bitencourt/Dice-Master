from pathlib import Path
import sqlite3
import discord
from discord import app_commands
from discord.ext import commands

from utils.db_functions import (
    get_character_inventory_data,
    get_character_thumbnail_by_id,
)


def _clamp_embed_description(lines: list[str]) -> str:
    """Joins section lines and enforces Discord's embed description limit."""
    text = "\n".join(lines)
    if len(text) <= 4000:
        return text

    suffix = "\n... (exibição truncada)"
    return text[: 4000 - len(suffix)] + suffix


def _build_summary_embed(
    data: dict, total_weight: float, equipped_count: int
) -> discord.Embed:
    """Builds the inventory summary embed with money, weight and equipped count."""
    return discord.Embed(
        title=f"Inventário: {data['character_name']}",
        description=(
            f"**Dinheiro:** `$ {data['money']}`\n"
            f"**Peso Total:** `{total_weight:.2f} kg`\n"
            f"**Equipamentos Ativos:** `{equipped_count}`"
        ),
        color=discord.Color.gold(),
    )


def build_inventory_embeds(data: dict) -> list[discord.Embed]:
    """Renders the complete inventory into a list of sectioned embeds."""
    total_weight = 0.0
    equipped_count = 0

    melee_lines = []
    for weapon in data["melee_weapons"]:
        badge = "[EQUIPADO]" if weapon["is_equipped"] else "[GUARDADO]"
        equipped_count += int(weapon["is_equipped"])
        item_weight = weapon["weight"] * weapon["quantity"]
        total_weight += item_weight
        st_text = f" | ST Min `{weapon['min_st']}`" if weapon["min_st"] > 0 else ""

        melee_lines.append(
            f"**{badge}** {weapon['name']} (x{weapon['quantity']}) - "
            f"Peso `{item_weight:.2f} kg`{st_text}"
        )

        for mode in weapon["modes"]:
            dmg_sign = (
                f"{mode['damage_modifier']:+d}"
                if mode["damage_modifier"] != 0
                else ""
            )
            dmg_display = (
                f"{mode['damage_base']}{dmg_sign} {mode['damage_type']}".strip()
            )
            notes_display = f" | ({mode['notes']})" if mode["notes"] else ""

            melee_lines.append(
                f"  - {mode['mode_name']}: Dano `{dmg_display}` | "
                f"Alc `{mode['reach']}` | Ap `{mode['parry']}`{notes_display}"
            )

    ranged_lines = []
    for weapon in data["ranged_weapons"]:
        badge = "[EQUIPADO]" if weapon["is_equipped"] else "[GUARDADO]"
        equipped_count += int(weapon["is_equipped"])
        item_weight = weapon["weight"] * weapon["quantity"]
        total_weight += item_weight

        ranged_lines.append(
            f"**{badge}** {weapon['name']} (x{weapon['quantity']}) - "
            f"Dano `{weapon['damage']}` | Acc `{weapon['acc']}` | "
            f"Alcance `{weapon['range_half']}/{weapon['range_max']}` | "
            f"Tiros `{weapon['shots']}` | Peso `{item_weight:.2f} kg`"
        )

    armor_lines = []
    for armor in data["armors"]:
        badge = "[EQUIPADO]" if armor["is_equipped"] else "[GUARDADO]"
        equipped_count += int(armor["is_equipped"])
        dr_display = f"{armor['dr']}*" if armor["is_flexible"] else f"{armor['dr']}"
        item_weight = armor["weight"] * armor["quantity"]
        item_cost = armor["cost"] * armor["quantity"]
        total_weight += item_weight

        armor_lines.append(
            f"**{badge}** {armor['name']} (x{armor['quantity']}) - "
            f"RD `{dr_display}` | Local `{armor['location']}` | "
            f"Peso `{item_weight:.2f} kg` | Valor `$ {item_cost:.2f}`"
        )

    item_lines = []
    for item in data["items"]:
        desc_str = f" - ({item['description']})" if item["description"] else ""
        item_weight = item["weight"] * item["quantity"]
        total_weight += item_weight

        item_lines.append(
            f"- {item['name']} (x{item['quantity']}) - "
            f"Peso `{item_weight:.2f} kg`{desc_str}"
        )

    embeds = [_build_summary_embed(data, total_weight, equipped_count)]

    sections = [
        ("Armas Corpo a Corpo", discord.Color.dark_red(), melee_lines),
        ("Armas a Distância", discord.Color.dark_teal(), ranged_lines),
        ("Armaduras", discord.Color.dark_blue(), armor_lines),
        ("Itens Gerais", discord.Color.dark_grey(), item_lines),
    ]

    for title, color, lines in sections:
        if not lines:
            continue
        embeds.append(
            discord.Embed(
                title=title,
                description=_clamp_embed_description(lines),
                color=color,
            )
        )

    if len(embeds) == 1:
        embeds[0].description += "\n\n*Nenhum equipamento ou item registrado.*"

    return embeds


class InventoryView(discord.ui.View):
    """Interactive view rendering the character inventory embeds."""

    def __init__(
        self,
        embeds: list[discord.Embed],
        author_id: int,
        back_callback=None,
    ):
        super().__init__(timeout=180.0)
        self.embeds = embeds
        self.author_id = author_id
        self.back_callback = back_callback

        if back_callback is not None:
            back_button = discord.ui.Button(
                label="Voltar",
                style=discord.ButtonStyle.secondary,
            )
            back_button.callback = self.go_back
            self.add_item(back_button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Restricts interaction to the user who invoked the command."""
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Erro: Apenas o usuário que invocou o comando pode interagir com este menu.",
                ephemeral=True,
            )
            return False
        return True

    async def go_back(self, interaction: discord.Interaction):
        """Delegates navigation back to the parent view when configured."""
        await self.back_callback(interaction)

    async def on_timeout(self):
        """Disables interactive components when the view times out."""
        for item in self.children:
            item.disabled = True


class Inventory(commands.Cog):
    """Cog responsible for character inventory management and monetary transactions."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        project_root = Path(__file__).resolve().parent.parent
        database_path = project_root / "data" / "database.db"

        # Persistent database connection
        self.db_connection = sqlite3.connect(database_path)
        self.db_connection.execute("PRAGMA foreign_keys = ON;")

    async def character_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        """Dynamically queries the database for characters matching user input."""
        cursor = self.db_connection.cursor()
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

    @app_commands.command(
        name="manage_money",
        description="Adiciona ou remove dinheiro do inventário do personagem.",
    )
    @app_commands.autocomplete(character=character_autocomplete)
    @app_commands.default_permissions(administrator=True)
    async def manage_money(
        self, interaction: discord.Interaction, character: str, money: int
    ):
        """Modifies a character's financial balance atomically within the database layer."""
        await interaction.response.defer(ephemeral=True)

        try:
            target_character_id = int(character)
        except ValueError:
            await interaction.followup.send(
                "**Erro de processamento:** O identificador do personagem fornecido é inválido.",
                ephemeral=True,
            )
            return

        cursor = self.db_connection.cursor()
        cursor.execute(
            "SELECT name, money FROM characters WHERE character_id = ?",
            (target_character_id,),
        )
        row = cursor.fetchone()

        if row is None:
            await interaction.followup.send(
                f"**Erro de consistência:** Nenhuma entidade foi localizada sob o ID `{target_character_id}`.",
                ephemeral=True,
            )
            return

        character_name = row[0]
        previous_balance = row[1]
        updated_balance = previous_balance + money

        cursor.execute(
            "UPDATE characters SET money = ? WHERE character_id = ?",
            (updated_balance, target_character_id),
        )
        self.db_connection.commit()

        finance_embed = discord.Embed(
            title=f"MUTAÇÃO PATRIMONIAL: {character_name}",
            color=discord.Color.green() if money >= 0 else discord.Color.red(),
        )

        transaction_type = "Entrada" if money >= 0 else "Saída"

        finance_embed.add_field(
            name="Transação Homologada",
            value=f"Tipo: `{transaction_type}`\nFluxo: `{money:+d} $`",
            inline=False,
        )

        finance_embed.add_field(
            name="Demonstrativo de Saldos",
            value=f"Anterior: `{previous_balance} $`\nAtualizado: `{updated_balance} $`",
            inline=False,
        )

        character_file, thumbnail_url = get_character_thumbnail_by_id(
            self.db_connection, target_character_id
        )

        if thumbnail_url:
            finance_embed.set_thumbnail(url=thumbnail_url)

        if character_file is not None:
            await interaction.followup.send(
                embed=finance_embed, file=character_file, ephemeral=True
            )
        else:
            await interaction.followup.send(embed=finance_embed, ephemeral=True)

    @app_commands.command(
        name="inventory",
        description="Exibe o inventário completo, armas, armaduras e equipamentos do seu personagem.",
    )
    async def view_inventory(self, interaction: discord.Interaction):
        """Displays character inventory using the persistent database connection."""
        await interaction.response.defer(ephemeral=True)

        data = get_character_inventory_data(
            self.db_connection, interaction.user.id
        )

        if not data:
            await interaction.followup.send(
                "**Você não possui um personagem ativo atribuído à sua conta!**",
                ephemeral=True,
            )
            return

        embeds = build_inventory_embeds(data)
        view = InventoryView(embeds=embeds, author_id=interaction.user.id)

        await interaction.followup.send(embeds=embeds, view=view, ephemeral=True)


async def setup(bot: commands.Bot):
    """Mandatory asynchronous entry point to load the extension."""
    await bot.add_cog(Inventory(bot))
