import sqlite3
import discord
from discord import app_commands
from discord.ext import commands
from pathlib import Path


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
        self.db_connection.execute("PRAGMA foreign_keys = ON;")

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
        player="O jogador que terá o teste alterado",
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
        player: discord.Member,
        fate: app_commands.Choice[int],
    ):
        # State validation using the pre-loaded instance attribute
        if interact.user.id != self.designated_dm_id:
            await interact.response.send_message(
                "Erro. Você não tem permissão para usar os comandos de Debug",
                ephemeral=True,
            )
            return

        player_identifier = player.id
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
            content=f"A próxima rolagem de {player.mention} será {fate.name}",
            ephemeral=True,
        )

    # manage_character_resource_pool --------------------------------------------
    @app_commands.command(
        name="manage_character_resource_pool",
        description="Permite editar o PV o PF e a RE dos jogadores",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.choices(
        resource=[
            app_commands.Choice(name="pv", value="hp"),
            app_commands.Choice(name="pf", value="fp"),
            app_commands.Choice(name="er", value="er"),
        ]
    )
    @app_commands.describe(
        player="O jogador que terá os recursos alterados",
        resource="O recurso que será alterado",
        value="O valor que será somado ou subtraído",
    )
    async def manage_character_resource_pool(
        self,
        interact: discord.Interaction,
        player: discord.Member,
        resource: app_commands.Choice[str],
        value: int,
    ):
        # 1. IMMEDIATE DEFERRAL: Extending the temporal execution limit to 15 minutes
        await interact.response.defer(ephemeral=False)

        target_player_id = player.id
        resource_key = resource.value

        # 2. Strict Matrix Extraction: Utilizing ONLY the denormalized profile function
        try:
            character_data = get_character_profile(self.db_connection, target_player_id)
        except ValueError as e:
            await interact.followup.send(f"Erro de processamento: {e}")
            return

        character_name = character_data["name"]

        # 3. Lexical Translation: Mapping the Discord choice to the database dictionary keys
        reading_map = {"hp": "current_pv", "fp": "current_pf", "er": "current_er"}

        dict_key = reading_map[resource_key]
        current_value = character_data[dict_key]

        new_value = current_value + value

        # 4. Database state mutation: set_character_resource handles the SQL mapping internally
        set_character_resource(
            self.db_connection, target_player_id, resource_key, new_value
        )

        # 5. UI Presentation Pipeline
        modifier_sign = "+" if value >= 0 else ""

        transaction_embed = discord.Embed(
            title="Alteração do Mestre", color=discord.Color.purple()
        )

        transaction_embed.add_field(
            name="Balanço da Mutação",
            value=(
                f"Personagem: `{character_name}`\n"
                f"Recurso Afetado: `{resource.name.upper()}`\n"
                f"Modificador Aplicado: `{modifier_sign}{value}`\n"
                f"Transição de Estado: `{current_value}` -> `{new_value}`"
            ),
            inline=False,
        )

        # 6. MANDATORY FOLLOWUP: The initial interaction token was consumed by .defer()
        await interact.followup.send(embed=transaction_embed)

    # restore_character_resources
    @app_commands.command(
        name="restore_character_resources",
        description="Restaura incondicionalmente todos os recursos vitais aos seus tetos estruturais máximos",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        player="O jogador cujo personagem receberá a restauração absoluta"
    )
    async def restore_character_resources(
        self, interact: discord.Interaction, player: discord.Member
    ):
        # 1. IMMEDIATE DEFERRAL: Extending the temporal execution limit to 15 minutes
        await interact.response.defer(ephemeral=False)

        target_player_id = player.id

        # 2. Strict Matrix Extraction: Utilizing the denormalized profile function
        try:
            character_data = get_character_profile(self.db_connection, target_player_id)
        except ValueError as e:
            await interact.followup.send(f"Erro de processamento: {e}")
            return

        character_name = character_data["name"]

        # 3. Maximum Threshold Calculation based on GURPS strict structural formulas
        max_pv = character_data["st"] + character_data["additional_max_pv"]
        max_pf = character_data["ht"] + character_data["additional_max_pf"]
        max_er = character_data["energy_reserve"]

        # 4. State Capture for historical/UI feedback before mutation
        old_pv = character_data["current_pv"]
        old_pf = character_data["current_pf"]
        old_er = character_data["current_er"]

        # 5. Database state mutation: Maintaining encapsulation by utilizing the setter thrice
        set_character_resource(self.db_connection, target_player_id, "hp", max_pv)
        set_character_resource(self.db_connection, target_player_id, "fp", max_pf)
        set_character_resource(self.db_connection, target_player_id, "er", max_er)

        # 6. UI Presentation Pipeline
        restoration_embed = discord.Embed(
            title="Restauração Estrutural Absoluta",
            description=f"Os fluxos vitais do personagem pertencente ao indivíduo {player.mention} foram compulsoriamente elevados aos seus limites sistêmicos.",
            color=discord.Color.brand_green(),
        )

        restoration_embed.add_field(
            name="Balanço da Mutação",
            value=(
                f"Personagem: `{character_name}`\n\n"
                f"**PV (Hit Points):** `{old_pv}` -> `{max_pv}`\n"
                f"**PF (Fatigue Points):** `{old_pf}` -> `{max_pf}`\n"
                f"**ER (Energy Reserve):** `{old_er}` -> `{max_er}`"
            ),
            inline=False,
        )

        # 7. MANDATORY FOLLOWUP: The initial interaction token was consumed by .defer()
        await interact.followup.send(embed=restoration_embed)

    # switch_character --------------------------------------------------
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
            (search_pattern,),
        )

        fetched_characters = cursor.fetchall()

        return [
            app_commands.Choice(name=row[1], value=str(row[0]))
            for row in fetched_characters
        ]

    @app_commands.command(
        name="switch_character",
        description="Transfere o controle do seu usuário para um novo personagem.",
    )
    @app_commands.autocomplete(character=character_autocomplete)
    @app_commands.describe(character="O nome do personagem que você deseja assumir.")
    async def switch_character(self, interaction: discord.Interaction, character: str):
        target_player_id = interaction.user.id

        # Casting the string ID back to an integer for relational integrity
        try:
            new_character_id = int(character)
        except ValueError:
            await interaction.response.send_message(
                "Erro de processamento: O identificador do personagem é inválido.",
                ephemeral=True,
            )
            return

        cursor = self.db_connection.cursor()

        # Step 1: Nullify the player_id assignment in the current active character
        cursor.execute(
            """
            UPDATE characters 
            SET owner_id = NULL 
            WHERE owner_id = ?
            """,
            (target_player_id,),
        )

        # Step 2: Assign the player_id to the newly selected character
        cursor.execute(
            """
            UPDATE characters 
            SET owner_id = ? 
            WHERE character_id = ?
            """,
            (target_player_id, new_character_id),
        )

        self.db_connection.commit()

        # Ephemeral retrieval of the new character's nomenclature for the UI validation
        cursor.execute(
            "SELECT name FROM characters WHERE character_id = ?", (new_character_id,)
        )
        row = cursor.fetchone()
        new_character_name = row[0] if row else "Entidade Desconhecida"

        # Tactical UI Response
        transference_embed = discord.Embed(
            title="Sincronização de Avatar Concluída",
            description=f"{interaction.user.mention} agora está jogando com **{new_character_name}**.",
            color=discord.Color.teal(),
        )

        await interaction.response.send_message(embed=transference_embed)

    # ================================
    # NEXT TURN CONDITIONS BLOCK
    # =================================

    # manage_next_turn_conditions -----------------------------------------
    @app_commands.command(
        name="manage_next_turn_conditions",
        description="Permite gerenciar as condições de próximo turno",
    )
    @app_commands.autocomplete(character=character_autocomplete)
    @app_commands.choices(
        condition=[
            app_commands.Choice(name="Apontar", value="aim"),
            app_commands.Choice(name="Avaliar", value="evaluate"),
            app_commands.Choice(name="Choque", value="shock"),
            app_commands.Choice(name="Finta", value="feint"),
        ]
    )
    @app_commands.describe(
        character="O personagem que sofrerá a intervenção tática",
        condition="Condição que será alterada",
        value="Valor que será atribuído à condição",
    )
    @app_commands.default_permissions(administrator=True)
    async def manage_next_turn_conditions(
        self,
        interaction: discord.Interaction,
        character: str,
        condition: app_commands.Choice[str],
        value: int,
    ):
        # Casting the string ID originating from the autocomplete payload back to an integer
        try:
            target_character_id = int(character)
        except ValueError:
            await interaction.response.send_message(
                "Erro de processamento: O identificador do personagem fornecido é inválido.",
                ephemeral=True,
            )
            return

        condition_column = condition.value
        cursor = self.db_connection.cursor()

        # SQLite UPSERT structure to guarantee atomic existence and update
        # String interpolation is mathematically safe here due to strict Discord choice validation
        upsert_query = f"""
            INSERT INTO next_turn_conditions (character_id, {condition_column})
            VALUES (?, ?)
            ON CONFLICT(character_id) 
            DO UPDATE SET {condition_column} = excluded.{condition_column}
        """

        cursor.execute(upsert_query, (target_character_id, value))
        self.db_connection.commit()

        # Ephemeral retrieval of the character's name for the UI validation
        cursor.execute(
            "SELECT name FROM characters WHERE character_id = ?", (target_character_id,)
        )
        row = cursor.fetchone()
        target_character_name = row[0] if row else "Entidade Desconhecida"

        # UI Presentation Pipeline
        tactical_embed = discord.Embed(
            title="Mudança do Mestre Nas Condições de Próximo Turno",
            description=f"**{target_character_name}** teve suas condições de próximo turno alteradas.",
            color=discord.Color.dark_red(),
        )

        tactical_embed.add_field(
            name="Parâmetro Afetado", value=f"`{condition.name.upper()}`", inline=True
        )
        tactical_embed.add_field(
            name="Novo Valor Alocado", value=f"`{value}`", inline=True
        )

        await interaction.response.send_message(embed=tactical_embed)

    # clear_next_turn_conditions --------------------------------------------
    @app_commands.command(
        name="clear_next_turn_conditions",
        description="Purga absolutamente todas as condições de próximo turno de um personagem, zerando-as.",
    )
    @app_commands.autocomplete(character=character_autocomplete)
    @app_commands.describe(character="O personagem que terá suas condições obliteradas")
    @app_commands.default_permissions(administrator=True)
    async def clear_next_turn_conditions(
        self, interaction: discord.Interaction, character: str
    ):
        # Casting the string ID originating from the autocomplete payload back to an integer
        try:
            target_character_id = int(character)
        except ValueError:
            await interaction.response.send_message(
                "Erro de processamento: O identificador do personagem fornecido é inválido.",
                ephemeral=True,
            )
            return

        cursor = self.db_connection.cursor()

        # SQLite UPSERT structure to guarantee atomic existence and total zeroing of all conditions simultaneously
        upsert_query = """
            INSERT INTO next_turn_conditions (character_id, aim, evaluate, shock, feint)
            VALUES (?, 0, 0, 0, 0)
            ON CONFLICT(character_id) 
            DO UPDATE SET 
                aim = 0, 
                evaluate = 0, 
                shock = 0, 
                feint = 0
        """

        cursor.execute(upsert_query, (target_character_id,))
        self.db_connection.commit()

        # Ephemeral retrieval of the character's nomenclature for the UI validation
        cursor.execute(
            "SELECT name FROM characters WHERE character_id = ?", (target_character_id,)
        )
        row = cursor.fetchone()
        target_character_name = row[0] if row else "Entidade Desconhecida"

        # UI Presentation Pipeline
        tactical_embed = discord.Embed(
            title="Purgação de Estado Tático",
            description=f"Todas as variáveis de combate para o próximo turno de **{target_character_name}** foram matematicamente reduzidas ao zero absoluto.",
            color=discord.Color.light_grey(),
        )

        await interaction.response.send_message(embed=tactical_embed)

    # view_next_turn_conditions ----------------------------------------------
    @app_commands.command(
        name="view_next_turn_conditions",
        description="Exibe analiticamente as condições de próximo turno vigentes de um personagem.",
    )
    @app_commands.autocomplete(character=character_autocomplete)
    @app_commands.describe(
        character="O personagem cujas condições operacionais serão inspecionadas"
    )
    async def view_next_turn_conditions(
        self, interaction: discord.Interaction, character: str
    ):
        # Casting the string ID originating from the autocomplete payload back to an integer
        try:
            target_character_id = int(character)
        except ValueError:
            await interaction.response.send_message(
                "Erro de processamento: O identificador do personagem fornecido é inválido.",
                ephemeral=True,
            )
            return

        cursor = self.db_connection.cursor()

        # Executing a LEFT JOIN to capture the character's name even if no tactical row exists yet
        cursor.execute(
            """
            SELECT c.name, n.aim, n.evaluate, n.shock, n.feint
            FROM characters c
            LEFT JOIN next_turn_conditions n ON c.character_id = n.character_id
            WHERE c.character_id = ?
            """,
            (target_character_id,),
        )
        row = cursor.fetchone()

        if not row:
            await interaction.response.send_message(
                "Erro de processamento: A entidade especificada não foi localizada na matriz fundacional.",
                ephemeral=True,
            )
            return

        character_name, aim, evaluate, shock, feint = row

        # Defensive coercion: if the LEFT JOIN yielded NULL (None), the structural value is inherently 0
        aim = aim if aim is not None else 0
        evaluate = evaluate if evaluate is not None else 0
        shock = shock if shock is not None else 0
        feint = feint if feint is not None else 0

        # UI Presentation Pipeline
        inspection_embed = discord.Embed(
            title=f"Diagnóstico de Estado Tático — {character_name}",
            color=discord.Color.blue(),
        )

        inspection_embed.add_field(name="Apontar (Aim)", value=f"`{aim}`", inline=True)
        inspection_embed.add_field(
            name="Avaliar (Evaluate)", value=f"`{evaluate}`", inline=True
        )
        inspection_embed.add_field(
            name="Choque (Shock)", value=f"`{shock}`", inline=True
        )
        inspection_embed.add_field(
            name="Finta (Feint)", value=f"`{feint}`", inline=True
        )

        await interaction.response.send_message(embed=inspection_embed)


async def setup(bot: commands.Bot):
    """
    Asynchronous entry point required by discord.py to load the extension.
    """
    await bot.add_cog(Admin(bot))
