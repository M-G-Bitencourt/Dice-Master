from pathlib import Path
import sqlite3
import discord
from discord import app_commands
from discord.ext import commands

from utils.db_functions import (
    get_character_inventory_data,
    get_character_thumbnail_by_id,
)


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
        data = get_character_inventory_data(
            self.db_connection, interaction.user.id
        )

        if not data:
            await interaction.response.send_message(
                "**Você não possui um personagem ativo atribuído à sua conta!**",
                ephemeral=True,
            )
            return

        total_weight = 0.0

        # --- SECTION 1: MELEE WEAPONS WITH ATTACK MODES ---
        melee_text = ""
        for weapon in data["melee_weapons"]:
            eq_tag = "🔹 `[EQUIPADO]` " if weapon["is_equipped"] else "▫️ "
            st_text = f" | *ST Mín:* `{weapon['min_st']}`" if weapon["min_st"] > 0 else ""
            item_weight = weapon["weight"] * weapon["quantity"]
            total_weight += item_weight

            melee_text += (
                f"{eq_tag}**{weapon['name']}** (x{weapon['quantity']}) — "
                f"*Peso:* `{item_weight:.2f} kg`{st_text}\n"
            )

            # Attack Modes Sub-listing
            for mode in weapon["modes"]:
                dmg_sign = f"{mode['damage_modifier']:+d}" if mode["damage_modifier"] != 0 else ""
                dmg_display = f"{mode['damage_base']}{dmg_sign} {mode['damage_type']}".strip()
                notes_display = f" (*{mode['notes']}*)" if mode["notes"] else ""

                melee_text += (
                    f"   └ ▫️ *{mode['mode_name']}:* `{dmg_display}` | "
                    f"*Alc:* `{mode['reach']}` | *Ap:* `{mode['parry']}`"
                    f"{notes_display}\n"
                )

        if not melee_text:
            melee_text = "*Nenhuma arma corpo a corpo no inventário.*\n"

        # --- SECTION 2: RANGED WEAPONS ---
        ranged_text = ""
        for weapon in data["ranged_weapons"]:
            eq_tag = "🔹 `[EQUIPADO]` " if weapon["is_equipped"] else "▫️ "
            item_weight = weapon["weight"] * weapon["quantity"]
            total_weight += item_weight

            ranged_text += (
                f"{eq_tag}**{weapon['name']}** (x{weapon['quantity']}) — "
                f"*Dano:* `{weapon['damage']}` | *Acc:* `{weapon['acc']}` | "
                f"*Alcance:* `{weapon['range_half']}/{weapon['range_max']}` | "
                f"*Tiros:* `{weapon['shots']}` | *Peso:* `{item_weight:.2f} kg`\n"
            )

        if not ranged_text:
            ranged_text = "*Nenhuma arma a distância no inventário.*\n"

        # --- SECTION 3: MODULAR ARMOR ---
        armors_text = ""
        for armor in data["armors"]:
            eq_tag = "🛡️ `[EQUIPADO]` " if armor["is_equipped"] else "▫️ "
            dr_display = f"{armor['dr']}*" if armor["is_flexible"] else f"{armor['dr']}"
            item_weight = armor["weight"] * armor["quantity"]
            item_cost = armor["cost"] * armor["quantity"]
            total_weight += item_weight

            armors_text += (
                f"{eq_tag}**{armor['name']}** (x{armor['quantity']}) — "
                f"*RD:* `{dr_display}` | *Local:* `{armor['location']}` | "
                f"*Peso:* `{item_weight:.2f} kg` | *Valor:* `$ {item_cost:.2f}`\n"
            )

        if not armors_text:
            armors_text = "*Nenhuma armadura no inventário.*\n"

        # --- SECTION 4: GENERAL ITEMS ---
        items_text = ""
        for item in data["items"]:
            desc_str = f" (*{item['description']}*)" if item["description"] else ""
            item_weight = item["weight"] * item["quantity"]
            total_weight += item_weight

            items_text += (
                f"📦 **{item['name']}** (x{item['quantity']}){desc_str} — "
                f"`{item_weight:.2f} kg`\n"
            )

        if not items_text:
            items_text = "*Nenhum item geral no inventário.*\n"

        # --- MESSAGE ASSEMBLY ---
        message = (
            f"# Inventário: **{data['character_name']}**\n"
            f"---\n"
            f"### ⚔️ Armas Corpo a Corpo\n"
            f"{melee_text}\n"
            f"### 🏹 Armas a Distância\n"
            f"{ranged_text}\n"
            f"### 🛡️ Armaduras\n"
            f"{armors_text}\n"
            f"### 📦 Itens Gerais\n"
            f"{items_text}\n"
            f"---\n"
            f"📊 **Peso Total:** `{total_weight:.2f} kg` | 💰 **Riqueza:** `$ {data['money']}`"
        )

        await interaction.response.send_message(message, ephemeral=True)


async def setup(bot: commands.Bot):
    """Mandatory asynchronous entry point to load the extension."""
    await bot.add_cog(Inventory(bot))
