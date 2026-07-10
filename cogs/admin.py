import sqlite3
import discord
from discord import app_commands
from discord.ext import commands
from pathlib import Path

from utils.db_functions import get_character_resources
from utils.db_functions import set_character_resource
from utils.db_functions import get_character_profile

# Dynamic resolution of the absolute path strictly for the database
BASE_DIRECTORY = Path(__file__).resolve().parent.parent
DATABASE_FILE_PATH = BASE_DIRECTORY / "data" / "database.db"


class Admin(commands.Cog):
    """
    Cog responsible for overriding standard dice rolls with deterministic outcomes.
    Restricted to administrative usage for debugging and narrative control.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        
        project_root = Path(__file__).resolve().parent.parent
        database_path = project_root / "data" / "database.db"

        # Establishing the persistent, active connection channel
        self.db_connection = sqlite3.connect(database_path)

        # Strict Dependency Injection: Extracting configuration from the injected bot memory.
        try:
            self.designated_dm_id = int(self.bot.config["BOT"]["DM_ID"])
        except AttributeError:
            raise RuntimeError(
                "Architectural Error: 'bot.config' must be injected in the main script before loading Cogs."
            )
        except (KeyError, ValueError) as error:
            raise ValueError(f"Configuration Malformation: {error}")

    @app_commands.command(
        name="hdm", description="Um comando feito para testar o código e debug"
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        jogador="O jogador que terá o teste alterado",
        fate="Escolha de qual será o próximo resultado do usuário",
    )
    @app_commands.choices(
        fate=[
            app_commands.Choice(name="Sucesso", value=0),
            app_commands.Choice(name="Fracasso", value=1),
            app_commands.Choice(name="Sucesso Decisivo", value=2),
            app_commands.Choice(name="Falha Crítica", value=3),
        ]
    )
    async def deterministic_mock_command(
        self,
        interact: discord.Interaction,
        jogador: discord.Member,
        fate: app_commands.Choice[int],
    ):
        # State validation using the pre-loaded instance attribute
        if interact.user.id != self.designated_dm_id:
            await interact.response.send_message(
                "Erro. Você não tem permissão para usar os comandos de Debug",
                ephemeral=True,
            )
            return

        player_identifier = jogador.id
        fate_integer_value = fate.value

        try:
            with sqlite3.connect(DATABASE_FILE_PATH) as db_connection:
                db_cursor = db_connection.cursor()

                db_cursor.execute(
                    """
                    INSERT INTO hdm (id_player, fate) 
                    VALUES (?, ?)
                    ON CONFLICT(id_player) DO UPDATE SET fate = excluded.fate
                    """,
                    (player_identifier, fate_integer_value),
                )

                db_connection.commit()

        except sqlite3.Error as database_exception:
            await interact.response.send_message(
                f"A structural database failure occurred: {database_exception}",
                ephemeral=True,
            )
            return

        await interact.response.send_message(
            content=f"A próxima rolagem de {jogador.mention} será {fate.name}",
            ephemeral=True,
        )

    # character_resource_pool --------------------------------------------
    @app_commands.command(
        name="crp",
        description="Permite editar o PV o PF e a RE dos jogadores"
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.choices(
        resource=[
            app_commands.Choice(name="pv", value="hp"),
            app_commands.Choice(name="pf", value="fp"),
            app_commands.Choice(name="re", value="er"),
        ]
    )
    @app_commands.describe(
        jogador="O jogador que terá os recursos alterados",
        resource="O recurso que será alterado",
        value="O valor que será somado ou subtraído"
    )
    async def character_resource_pool(
        self,
        interact: discord.Interaction,
        player: discord.Member,
        resource: app_commands.Choice[str],
        value: int
    ):
        target_player_id = player.id
        
        # Coercing the integer ID to a string to satisfy the TEXT schema and type hints
        resource_key = str(resource.value)

        # Correct invocation: retrieving the full dictionary of resources (expects exactly 2 arguments)
        character_resources = get_character_resources(self.db_connection, target_player_id)
        character_data = get_character_profile(self.db_connection, player.id)
        character_name = character_data["name"]
        
        # Extracting the specific resource safely from the dictionary, defaulting to 0 if absent
        current_value = character_resources.get(resource_key, 0)
            
        new_value = current_value + value

        # Database state mutation utilizing the exact string key
        set_character_resource(self.db_connection, target_player_id, resource_key, new_value)

        # UI Presentation Pipeline
        modifier_sign = "+" if value >= 0 else ""
        
        transaction_embed = discord.Embed(
            title="Alteração do Mestre",
            color=discord.Color.purple()
        )
        
        transaction_embed.add_field(
            name="Balanço da Mutação",
            value=(
                f"Personagem: {character_name} "
                f"Recurso Afetado: `{resource.name.upper()}`\n"
                f"Modificador Aplicado: `{modifier_sign}{value}`\n"
                f"Transição de Estado: `{current_value}` -> `{new_value}`"
            ),
            inline=False
        )

        await interact.response.send_message(embed=transaction_embed)

async def setup(bot: commands.Bot):
    """
    Asynchronous entry point required by discord.py to load the extension.
    """
    await bot.add_cog(Admin(bot))
