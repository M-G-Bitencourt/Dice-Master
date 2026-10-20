import sqlite3
import discord
from discord import app_commands
from discord.ext import commands
from pathlib import Path


from utils.ansi import code_block, resource_bar
from utils.i18n import catalog_label, t as tr
from utils.locale_service import apply_interaction_locale
from utils.db_functions import set_character_resource
from utils.db_functions import get_character_profile
from utils.db_functions import get_character_thumbnail_by_id

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
        name="hdm", description="Debug command used to force the next roll outcome."
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        player="Player whose next test will be changed.",
        fate="Next result forced for the player.",
    )
    @app_commands.choices(
        fate=[
            app_commands.Choice(name="Success", value=0),
            app_commands.Choice(name="Failure", value=1),
            app_commands.Choice(name="Critical Success", value=2),
            app_commands.Choice(name="Critical Failure", value=3),
        ]
    )
    async def deterministic_mock_command(
        self,
        interact: discord.Interaction,
        player: discord.Member,
        fate: app_commands.Choice[int],
    ):
        apply_interaction_locale(interact, self.db_connection)

        # State validation using the pre-loaded instance attribute
        if interact.user.id != self.designated_dm_id:
            await interact.response.send_message(
                tr("Error. You do not have permission to use debug commands."),
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
                tr(
                    "Processing error: structural database failure. {detail}",
                    detail=database_exception,
                ),
                ephemeral=True,
            )
            return

        await interact.response.send_message(
            content=tr(
                "The next roll for {player} will be {fate}.",
                player=player.mention,
                fate=catalog_label("fate", str(fate.value)),
            ),
            ephemeral=True,
        )

    # manage_character_resource_pool --------------------------------------------
    @app_commands.command(
        name="manage_character_resource_pool",
        description="Edit a player's HP, FP, and ER.",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.choices(
        resource=[
            app_commands.Choice(name="HP", value="hp"),
            app_commands.Choice(name="FP", value="fp"),
            app_commands.Choice(name="ER", value="er"),
        ]
    )
    @app_commands.describe(
        player="Player whose resources will be changed.",
        resource="Resource to change.",
        value="Value added to or subtracted from the resource.",
    )
    async def manage_character_resource_pool(
        self,
        interact: discord.Interaction,
        player: discord.Member,
        resource: app_commands.Choice[str],
        value: int,
    ):
        apply_interaction_locale(interact, self.db_connection)

        # 1. IMMEDIATE DEFERRAL: Extending the temporal execution limit to 15 minutes
        await interact.response.defer(ephemeral=False)

        target_player_id = player.id
        resource_key = resource.value

        # 2. Strict Matrix Extraction: Utilizing ONLY the denormalized profile function
        try:
            character_data = get_character_profile(self.db_connection, target_player_id)
        except ValueError as e:
            await interact.followup.send(
                tr("Processing error: {detail}", detail=e)
            )
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

        max_pv = character_data["st"] + character_data["additional_max_pv"]
        max_pf = character_data["ht"] + character_data["additional_max_pf"]
        max_er = character_data["energy_reserve"]

        pv_current = new_value if resource_key == "hp" else character_data["current_pv"]
        pf_current = new_value if resource_key == "fp" else character_data["current_pf"]
        er_current = new_value if resource_key == "er" else character_data["current_er"]

        transaction_embed = discord.Embed(
            title=tr("GM Adjustment"), color=discord.Color.purple()
        )

        transaction_embed.add_field(
            name=tr("Mutation Balance"),
            value=tr(
                "Character: `{character}`\nAffected Resource: `{resource}`\nApplied Modifier: `{modifier}`\nState Transition: `{current}` -> `{new}`",
                character=character_name,
                resource=catalog_label("resources", resource.value).upper(),
                modifier=f"{modifier_sign}{value}",
                current=current_value,
                new=new_value,
            ),
            inline=False,
        )

        transaction_embed.add_field(
            name=tr("Current State"),
            value=code_block(
                [
                    resource_bar(catalog_label("resources", "hp"), int(pv_current), int(max_pv)),
                    resource_bar(catalog_label("resources", "fp"), int(pf_current), int(max_pf)),
                    resource_bar(catalog_label("resources", "er"), int(er_current), int(max_er)),
                ]
            ),
            inline=False,
        )

        # 6. MANDATORY FOLLOWUP: The initial interaction token was consumed by .defer()
        await interact.followup.send(embed=transaction_embed)

    # restore_character_resources
    @app_commands.command(
        name="restore_character_resources",
        description="Unconditionally restore all vital resources to their maximum caps.",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        player="Player whose character will be fully restored."
    )
    async def restore_character_resources(
        self, interact: discord.Interaction, player: discord.Member
    ):
        apply_interaction_locale(interact, self.db_connection)

        # 1. IMMEDIATE DEFERRAL: Extending the temporal execution limit to 15 minutes
        await interact.response.defer(ephemeral=False)

        target_player_id = player.id

        # 2. Strict Matrix Extraction: Utilizing the denormalized profile function
        try:
            character_data = get_character_profile(self.db_connection, target_player_id)
        except ValueError as e:
            await interact.followup.send(
                tr("Processing error: {detail}", detail=e)
            )
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
            title=tr("Absolute Structural Restoration"),
            description=tr(
                "The vital flows of the character belonging to {player} were forcibly raised to their systemic limits.",
                player=player.mention,
            ),
            color=discord.Color.brand_green(),
        )

        restoration_embed.add_field(
            name=tr("Mutation Balance"),
            value=tr(
                "Character: `{character}`\n\n**HP (Hit Points):** `{old_hp}` -> `{max_hp}`\n**FP (Fatigue Points):** `{old_fp}` -> `{max_fp}`\n**ER (Energy Reserve):** `{old_er}` -> `{max_er}`",
                character=character_name,
                old_hp=old_pv,
                max_hp=max_pv,
                old_fp=old_pf,
                max_fp=max_pf,
                old_er=old_er,
                max_er=max_er,
            ),
            inline=False,
        )

        restoration_embed.add_field(
            name=tr("Restored State"),
            value=code_block(
                [
                    resource_bar(catalog_label("resources", "hp"), int(max_pv), int(max_pv)),
                    resource_bar(catalog_label("resources", "fp"), int(max_pf), int(max_pf)),
                    resource_bar(catalog_label("resources", "er"), int(max_er), int(max_er)),
                ]
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
        description="Transfer your active character to another character.",
    )
    @app_commands.autocomplete(character=character_autocomplete)
    @app_commands.describe(character="Name of the character you want to assume.")
    async def switch_character(self, interaction: discord.Interaction, character: str):
        apply_interaction_locale(interaction, self.db_connection)
        target_player_id = interaction.user.id

        # Casting the string ID back to an integer for relational integrity
        try:
            new_character_id = int(character)
        except ValueError:
            await interaction.response.send_message(
                tr("Processing error: invalid character identifier."),
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
        new_character_name = row[0] if row else tr("Unknown Entity")

        # Tactical UI Response
        transference_embed = discord.Embed(
            title=tr("Avatar Synchronization Complete"),
            description=tr(
                "{user} is now playing **{character}**.",
                user=interaction.user.mention,
                character=new_character_name,
            ),
            color=discord.Color.teal(),
        )

        await interaction.response.send_message(embed=transference_embed)

    # manage_xp
    @app_commands.command(
        name="manage_xp",
        description="Add or remove character points from a character.",
    )
    @app_commands.describe(
        character="Select the character by name.",
        points="Point amount (for example 5 to add or -3 to remove).",
    )
    @app_commands.autocomplete(character=character_autocomplete)
    @app_commands.default_permissions(administrator=True)
    async def manage_xp(
        self, interaction: discord.Interaction, character: str, points: int
    ):
        """Modifies a character's available points/XP atomically within the database layer."""
        apply_interaction_locale(interaction, self.db_connection)
        await interaction.response.defer(ephemeral=True)

        # 1. Parse and validate the target character primary key
        try:
            target_character_id = int(character)
        except ValueError:
            await interaction.followup.send(
                tr("[ERROR] **Processing error:** the supplied character identifier is invalid."),
                ephemeral=True,
            )
            return

        cursor = self.db_connection.cursor()
        cursor.execute(
            "SELECT name, current_points FROM characters WHERE character_id = ?",
            (target_character_id,),
        )
        row = cursor.fetchone()

        if row is None:
            await interaction.followup.send(
                tr(
                    "[ERROR] **Consistency error:** no entity was found under ID `{character_id}`.",
                    character_id=target_character_id,
                ),
                ephemeral=True,
            )
            return

        character_name = row[0]
        previous_points = row[1] if row[1] is not None else 0
        updated_points = previous_points + points

        # 2. Update character points
        cursor.execute(
            "UPDATE characters SET current_points = ? WHERE character_id = ?",
            (updated_points, target_character_id),
        )
        self.db_connection.commit()

        # 3. Assemble confirmation embed
        is_addition = points >= 0
        xp_embed = discord.Embed(
            title=tr("POINT ADJUSTMENT (XP): {character}", character=character_name),
            color=discord.Color.green() if is_addition else discord.Color.red(),
        )

        transaction_type = (
            tr("Grant (+XP)") if is_addition else tr("Deduction (-XP)")
        )

        xp_embed.add_field(
            name=tr("Approved Operation"),
            value=tr(
                "Type: `{type}`\nAdjustment: `{points:+d} pts`",
                type=transaction_type,
                points=points,
            ),
            inline=False,
        )

        xp_embed.add_field(
            name=tr("Points Breakdown"),
            value=tr(
                "Previous: `{previous} pts`\nCurrent: `{current} pts`",
                previous=previous_points,
                current=updated_points,
            ),
            inline=False,
        )

        # 4. Attach character thumbnail if present
        character_file, thumbnail_url = get_character_thumbnail_by_id(
            self.db_connection, target_character_id
        )

        if thumbnail_url:
            xp_embed.set_thumbnail(url=thumbnail_url)

        if character_file is not None:
            await interaction.followup.send(
                embed=xp_embed, file=character_file, ephemeral=True
            )
        else:
            await interaction.followup.send(embed=xp_embed, ephemeral=True)
    # ================================
    # NEXT TURN CONDITIONS BLOCK
    # =================================

    # manage_next_turn_conditions -----------------------------------------
    @app_commands.command(
        name="manage_next_turn_conditions",
        description="Manage a character's next-turn conditions.",
    )
    @app_commands.autocomplete(character=character_autocomplete)
    @app_commands.choices(
        condition=[
            app_commands.Choice(name="Aim", value="aim"),
            app_commands.Choice(name="Evaluate", value="evaluate"),
            app_commands.Choice(name="Shock", value="shock"),
            app_commands.Choice(name="Feint", value="feint"),
        ]
    )
    @app_commands.describe(
        character="Character that will receive the tactical change.",
        condition="Condition that will be changed.",
        value="New value assigned to the condition.",
    )
    @app_commands.default_permissions(administrator=True)
    async def manage_next_turn_conditions(
        self,
        interaction: discord.Interaction,
        character: str,
        condition: app_commands.Choice[str],
        value: int,
    ):
        apply_interaction_locale(interaction, self.db_connection)

        # Casting the string ID originating from the autocomplete payload back to an integer
        try:
            target_character_id = int(character)
        except ValueError:
            await interaction.response.send_message(
                tr("Processing error: the supplied character identifier is invalid."),
                ephemeral=True,
            )
            return

        condition_column = condition.value
        cursor = self.db_connection.cursor()

        # Existence validation to prevent foreign key integrity failures
        cursor.execute(
            "SELECT name FROM characters WHERE character_id = ?",
            (target_character_id,),
        )
        row = cursor.fetchone()

        if row is None:
            await interaction.response.send_message(
                tr("Processing error: character not found."),
                ephemeral=True,
            )
            return

        target_character_name = row[0]

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

        # UI Presentation Pipeline
        tactical_embed = discord.Embed(
            title=tr("GM Change to Next-Turn Conditions"),
            description=tr(
                "**{character}** had their next-turn conditions changed.",
                character=target_character_name,
            ),
            color=discord.Color.dark_red(),
        )

        tactical_embed.add_field(
            name=tr("Affected Parameter"),
            value=f"`{catalog_label('condition_names', condition.value).upper()}`",
            inline=True,
        )
        tactical_embed.add_field(
            name=tr("New Assigned Value"), value=f"`{value}`", inline=True
        )

        await interaction.response.send_message(embed=tactical_embed)

    # clear_next_turn_conditions --------------------------------------------
    @app_commands.command(
        name="clear_next_turn_conditions",
        description="Clear all next-turn conditions for a character.",
    )
    @app_commands.autocomplete(character=character_autocomplete)
    @app_commands.describe(character="Character whose conditions will be cleared.")
    @app_commands.default_permissions(administrator=True)
    async def clear_next_turn_conditions(
        self, interaction: discord.Interaction, character: str
    ):
        apply_interaction_locale(interaction, self.db_connection)

        # Casting the string ID originating from the autocomplete payload back to an integer
        try:
            target_character_id = int(character)
        except ValueError:
            await interaction.response.send_message(
                tr("Processing error: the supplied character identifier is invalid."),
                ephemeral=True,
            )
            return

        cursor = self.db_connection.cursor()

        # Existence validation to prevent foreign key integrity failures
        cursor.execute(
            "SELECT name FROM characters WHERE character_id = ?",
            (target_character_id,),
        )
        row = cursor.fetchone()

        if row is None:
            await interaction.response.send_message(
                tr("Processing error: character not found."),
                ephemeral=True,
            )
            return

        target_character_name = row[0]

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

        # UI Presentation Pipeline
        tactical_embed = discord.Embed(
            title=tr("Tactical State Purge"),
            description=tr(
                "All combat variables for **{character}**'s next turn were reduced to absolute zero.",
                character=target_character_name,
            ),
            color=discord.Color.light_grey(),
        )

        await interaction.response.send_message(embed=tactical_embed)

    # view_next_turn_conditions ----------------------------------------------
    @app_commands.command(
        name="view_next_turn_conditions",
        description="View a character's current next-turn conditions.",
    )
    @app_commands.autocomplete(character=character_autocomplete)
    @app_commands.describe(
        character="Character whose conditions will be inspected."
    )
    async def view_next_turn_conditions(
        self, interaction: discord.Interaction, character: str
    ):
        apply_interaction_locale(interaction, self.db_connection)

        # Casting the string ID originating from the autocomplete payload back to an integer
        try:
            target_character_id = int(character)
        except ValueError:
            await interaction.response.send_message(
                tr("Processing error: the supplied character identifier is invalid."),
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
                tr("Processing error: the specified entity was not found."),
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
            title=tr("Tactical State Diagnosis - {character}", character=character_name),
            color=discord.Color.blue(),
        )

        inspection_embed.add_field(
            name=catalog_label("condition_fields", "aim"),
            value=f"`{aim}`",
            inline=True,
        )
        inspection_embed.add_field(
            name=catalog_label("condition_fields", "evaluate"),
            value=f"`{evaluate}`",
            inline=True,
        )
        inspection_embed.add_field(
            name=catalog_label("condition_fields", "shock"),
            value=f"`{shock}`",
            inline=True,
        )
        inspection_embed.add_field(
            name=catalog_label("condition_fields", "feint"),
            value=f"`{feint}`",
            inline=True,
        )

        await interaction.response.send_message(embed=inspection_embed)


async def setup(bot: commands.Bot):
    """
    Asynchronous entry point required by discord.py to load the extension.
    """
    await bot.add_cog(Admin(bot))
