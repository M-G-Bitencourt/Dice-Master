import discord
from discord import app_commands
from discord.ext import commands

from pathlib import Path
import sqlite3

from utils.db_functions import get_character_thumbnail_by_id


class Inventory(commands.Cog):
    """

    """

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
            (search_pattern,)
        )
        
        fetched_characters = cursor.fetchall()
        
        return [
            app_commands.Choice(name=row[1], value=str(row[0]))
            for row in fetched_characters
        ]


    @app_commands.command(name="manage_money", description="Adiciona ou remove dinheiro do inventário do perssonagem")
    @app_commands.autocomplete(character=character_autocomplete)
    @app_commands.default_permissions(administrator=True)
    async def manage_money(
        self, 
        interaction: discord.Interaction, 
        character: str,
        money: int
    ):
        """
        Modifies a character's financial balance atomically within the SQLite persistence layer.
        Supports positive increments (deposits) and negative increments (withdrawals).
        """
        # TEMPORAL AXIOM: Securing the network token immediately before transactional processing
        await interaction.response.defer(ephemeral=True)

        # Casting the string ID originating from the autocomplete payload back to an integer
        try:
            target_character_id = int(character)
        except ValueError:
            await interaction.followup.send(
                "Erro de processamento: O identificador do personagem fornecido é estruturalmente inválido.",
                ephemeral=True
            )
            return

        # Establishing a direct cursor to evaluate the financial delta and extract entity names
        cursor = self.db_connection.cursor()
        cursor.execute(
            "SELECT name, money FROM characters WHERE character_id = ?", 
            (target_character_id,)
        )
        row = cursor.fetchone()

        if row is None:
            await interaction.followup.send(
                f"Erro de consistência: Nenhuma entidade foi localizada sob o ID {target_character_id}.",
                ephemeral=True
            )
            return

        character_name = row[0]
        previous_balance = row[1]
        updated_balance = previous_balance + money

        # Executing the atomic arithmetic mutation directly into the persistence matrix
        cursor.execute(
            "UPDATE characters SET money = ? WHERE character_id = ?",
            (updated_balance, target_character_id)
        )
        self.db_connection.commit()

        # Embed presentation construction with dynamic color assignment based on the delta sign
        finance_embed = discord.Embed(
            title=f"MUTAÇÃO PATRIMONIAL: {character_name}",
            color=discord.Color.green() if money >= 0 else discord.Color.red()
        )

        transaction_type = "Entrada" if money >= 0 else "Saída"
        
        finance_embed.add_field(
            name="Transação Homologada",
            value=f"Tipo: `{transaction_type}`\nFluxo: `{money:+d} $`",
            inline=False
        )

        finance_embed.add_field(
            name="Demonstrativo de Saldos",
            value=f"Anterior: `{previous_balance} $`\nAtualizado: `{updated_balance} $`",
            inline=False
        )

        # Binary asset pipeline extraction using the primary key
        character_file, thumbnail_url = get_character_thumbnail_by_id(self.db_connection, target_character_id)

        if thumbnail_url:
            finance_embed.set_thumbnail(url=thumbnail_url)

        # Dispatches the final diagnostic card safely mapped to the non-ephemeral followup payload
        if character_file is not None:
            await interaction.followup.send(embed=finance_embed, file=character_file, ephemeral=True)
        else:
            await interaction.followup.send(embed=finance_embed, ephemeral=True)


async def setup(bot: commands.Bot):
    """
    Mandatory asynchronous entry point to load the extension.
    """
    await bot.add_cog(Inventory(bot))