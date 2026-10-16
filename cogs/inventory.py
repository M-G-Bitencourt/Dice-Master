from pathlib import Path
import sqlite3
import discord
from discord import app_commands
from discord.ext import commands

from utils.db_functions import (
    get_character_inventory_data,
    get_character_strength,
    get_character_thumbnail_by_id,
)


def _encumbrance_level(total_weight: float, strength: int) -> tuple[str, int]:
    """Calculates the GURPS 4e metric encumbrance level for the carried weight."""
    basic_lift = (strength * strength) / 10.0

    thresholds = [
        (basic_lift, "Nenhuma", 0),
        (basic_lift * 2, "Leve", -1),
        (basic_lift * 3, "Média", -2),
        (basic_lift * 6, "Pesada", -3),
        (basic_lift * 10, "Muito Pesada", -4),
    ]

    for limit, label, penalty in thresholds:
        if total_weight <= limit:
            return label, penalty

    return "Muito Pesada", -4


def _build_summary_embed(
    data: dict,
    total_weight: float,
    equipped_count: int,
    item_count: int,
    strength: int | None,
) -> discord.Embed:
    """Builds the inventory summary embed with money, weight and encumbrance fields."""
    summary_embed = discord.Embed(
        title=f"Inventário: {data['character_name']}"[:256],
        description="*Registro de equipamento e carga do personagem.*",
        color=discord.Color.gold(),
    )

    summary_fields = [
        ("Dinheiro", f"`$ {data['money']}`"),
        ("Peso Total", f"`{total_weight:.2f} kg`"),
        ("Equipados", f"`{equipped_count}`"),
        ("Itens", f"`{item_count}`"),
    ]

    if strength is not None:
        label, penalty = _encumbrance_level(total_weight, strength)
        penalty_text = f" ({penalty})" if penalty else ""
        summary_fields.append(("Carga", f"`{label}{penalty_text}`"))

    for name, value in summary_fields:
        summary_embed.add_field(name=name[:256], value=value[:1000], inline=True)

    return summary_embed


def _append_section(
    embeds: list[discord.Embed],
    title: str,
    color: discord.Color,
    fields: list[tuple[str, str]],
    legend: str | None = None,
) -> None:
    """Appends one section as item-box embeds, chunking at 25 fields per embed."""
    for index in range(0, len(fields), 25):
        chunk = fields[index : index + 25]
        section_embed = discord.Embed(
            title=(title if index == 0 else f"{title} (continuação)")[:256],
            color=color,
        )

        if legend and index == 0:
            section_embed.description = legend[:4000]

        for name, value in chunk:
            section_embed.add_field(name=name[:256], value=value[:1000], inline=False)

        embeds.append(section_embed)


def build_inventory_embeds(
    data: dict,
    strength: int | None = None,
) -> list[discord.Embed]:
    """Renders the inventory into colored section embeds with one box per item."""
    total_weight = 0.0
    equipped_count = 0

    melee_fields = []
    melee_weight = 0.0
    for weapon in data["melee_weapons"]:
        badge = "[EQUIPADO]" if weapon["is_equipped"] else "[GUARDADO]"
        equipped_count += int(weapon["is_equipped"])
        item_weight = weapon["weight"] * weapon["quantity"]
        total_weight += item_weight
        melee_weight += item_weight

        lines = [f"Peso: `{item_weight:.2f} kg`"]
        if weapon["min_st"] > 0:
            lines[0] += f" | ST Mín: `{weapon['min_st']}`"

        for mode in weapon["modes"]:
            dmg_sign = (
                f"{mode['damage_modifier']:+d}"
                if mode["damage_modifier"] != 0
                else ""
            )
            dmg_display = (
                f"{mode['damage_base']}{dmg_sign} {mode['damage_type']}".strip()
            )
            notes = f" ({mode['notes']})" if mode["notes"] else ""

            lines.append(
                f"- {mode['mode_name']}: `{dmg_display}` | "
                f"Alc `{mode['reach']}` | Ap `{mode['parry']}`{notes}"
            )

        melee_fields.append(
            (f"{badge} {weapon['name']} (x{weapon['quantity']})", "\n".join(lines))
        )

    ranged_fields = []
    ranged_weight = 0.0
    for weapon in data["ranged_weapons"]:
        badge = "[EQUIPADO]" if weapon["is_equipped"] else "[GUARDADO]"
        equipped_count += int(weapon["is_equipped"])
        item_weight = weapon["weight"] * weapon["quantity"]
        total_weight += item_weight
        ranged_weight += item_weight

        value = (
            f"Dano `{weapon['damage']}` | Acc `{weapon['acc']}`\n"
            f"Alcance `{weapon['range_half']}/{weapon['range_max']}` | "
            f"Tiros `{weapon['shots']}`\n"
            f"Peso `{item_weight:.2f} kg`"
        )

        ranged_fields.append(
            (f"{badge} {weapon['name']} (x{weapon['quantity']})", value)
        )

    armor_fields = []
    armor_weight = 0.0
    has_flexible_armor = False
    for armor in data["armors"]:
        badge = "[EQUIPADO]" if armor["is_equipped"] else "[GUARDADO]"
        equipped_count += int(armor["is_equipped"])
        item_weight = armor["weight"] * armor["quantity"]
        item_cost = armor["cost"] * armor["quantity"]
        total_weight += item_weight
        armor_weight += item_weight

        dr_display = f"{armor['dr']}*" if armor["is_flexible"] else f"{armor['dr']}"
        has_flexible_armor = has_flexible_armor or bool(armor["is_flexible"])

        value = (
            f"RD `{dr_display}` | Local `{armor['location']}`\n"
            f"Peso `{item_weight:.2f} kg` | Valor `$ {item_cost:.2f}`"
        )

        armor_fields.append(
            (f"{badge} {armor['name']} (x{armor['quantity']})", value)
        )

    item_fields = []
    item_weight_total = 0.0
    for item in data["items"]:
        item_weight = item["weight"] * item["quantity"]
        total_weight += item_weight
        item_weight_total += item_weight

        description = item["description"] or ""
        desc_text = f"\n*{description}*" if description else ""

        item_fields.append(
            (
                f"{item['name']} (x{item['quantity']})",
                f"Peso `{item_weight:.2f} kg`{desc_text}",
            )
        )

    item_count = (
        len(data["melee_weapons"])
        + len(data["ranged_weapons"])
        + len(data["armors"])
        + len(data["items"])
    )

    embeds = [
        _build_summary_embed(data, total_weight, equipped_count, item_count, strength)
    ]

    _append_section(
        embeds,
        f"Armas Corpo a Corpo [{len(melee_fields)}] - {melee_weight:.2f} kg",
        discord.Color.dark_red(),
        melee_fields,
    )

    _append_section(
        embeds,
        f"Armas a Distância [{len(ranged_fields)}] - {ranged_weight:.2f} kg",
        discord.Color.dark_teal(),
        ranged_fields,
    )

    armor_legend = "* RD flexível" if has_flexible_armor else None
    _append_section(
        embeds,
        f"Armaduras [{len(armor_fields)}] - {armor_weight:.2f} kg",
        discord.Color.dark_blue(),
        armor_fields,
        armor_legend,
    )

    _append_section(
        embeds,
        f"Itens Gerais [{len(item_fields)}] - {item_weight_total:.2f} kg",
        discord.Color.dark_grey(),
        item_fields,
    )

    if len(embeds) > 10:
        embeds = embeds[:10]
        note = "\n... (exibição truncada)"
        embeds[-1].description = ((embeds[-1].description or "") + note)[:4000]

    if item_count == 0:
        embeds[0].description = "*Nenhum equipamento ou item registrado.*"

    return embeds


class InventoryView(discord.ui.View):
    """Interactive view rendering the character inventory embeds."""

    def __init__(
        self,
        author_id: int,
        back_callback=None,
    ):
        super().__init__(timeout=None)
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

        try:
            strength = get_character_strength(self.db_connection, interaction.user.id)
        except ValueError:
            strength = None

        embeds = build_inventory_embeds(data, strength)
        view = InventoryView(author_id=interaction.user.id)

        character_file, thumbnail_url = get_character_thumbnail_by_id(
            self.db_connection, data["character_id"]
        )

        if thumbnail_url:
            embeds[0].set_thumbnail(url=thumbnail_url)

        if character_file is not None:
            await interaction.followup.send(
                embeds=embeds, file=character_file, view=view, ephemeral=True
            )
        else:
            await interaction.followup.send(
                embeds=embeds, view=view, ephemeral=True
            )


async def setup(bot: commands.Bot):
    """Mandatory asynchronous entry point to load the extension."""
    await bot.add_cog(Inventory(bot))
