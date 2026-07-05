import discord
from discord import app_commands
from discord.ext import commands

from random import randint
import sqlite3
from pathlib import Path

from utils.test_mechanics import quick_dispute
from utils.dice_mechanics import consume_deterministic_fate
from utils.dice_mechanics import hdm_dices


# SQL FUNCTIONS (next_turn_conditions)
VALID_COLUMNS = {"aim", "evaluate", "shock", "feint"} # Valid structural columns to prevent unauthorized SQL string injection

def _resolve_character_id(connection: sqlite3.Connection, player_id: int) -> int:
    """
    Internal helper to map the Discord player_id (owner_id) to the internal character_id.
    Raises a ValueError if the structural integrity is broken and no character is assigned.
    """
    cursor = connection.cursor()
    cursor.execute("SELECT character_id FROM characters WHERE owner_id = ?", (player_id,))
    row = cursor.fetchone()
    
    if row is None:
        raise ValueError(f"Database Anomaly: No character found assigned to owner_id {player_id}.")
    return int(row[0])

def clear_player_conditions(connection: sqlite3.Connection, player_id: int) -> None:
    """
    Resolves the character identity and purges all transient modifiers by resetting columns to zero.
    """
    character_id = _resolve_character_id(connection, player_id)
    cursor = connection.cursor()
    cursor.execute("""
        UPDATE next_turn_conditions
        SET aim = 0, evaluate = 0, shock = 0, feint = 0
        WHERE character_id = ?
    """, (character_id,))
    connection.commit()

def set_player_condition(connection: sqlite3.Connection, player_id: int, column_name: str, value: int) -> None:
    """
    Resolves the character identity and executes an atomic upsert on the targeted validated column.
    """
    if column_name.lower() not in VALID_COLUMNS:
        raise ValueError(f"Abnormal operation detected: '{column_name}' is not a valid condition column.")

    character_id = _resolve_character_id(connection, player_id)
    cursor = connection.cursor()
    
    query = f"""
        INSERT INTO next_turn_conditions (character_id, {column_name})
        VALUES (?, ?)
        ON CONFLICT(character_id) DO UPDATE SET
            {column_name} = excluded.{column_name}
    """
    cursor.execute(query, (character_id, value))
    connection.commit()

def get_player_condition(connection: sqlite3.Connection, player_id: int, column_name: str) -> int:
    """
    Queries a condition column. Returns 0 if the character lacks an entry or doesn't exist.
    """
    if column_name.lower() not in VALID_COLUMNS:
        raise ValueError(f"Abnormal operation detected: '{column_name}' is not a valid condition column.")

    try:
        character_id = _resolve_character_id(connection, player_id)
    except ValueError:
        # Defensive fallback: if the player has no character registered, return the neutral modifier 0
        return 0

    cursor = connection.cursor()
    query = f"SELECT {column_name} FROM next_turn_conditions WHERE character_id = ?"
    cursor.execute(query, (character_id,))
    row = cursor.fetchone()
    
    if row is not None and row[0] is not None:
        return int(row[0])
    return 0

# SQL FUNCTIONS (current_attacks)
def clear_current_attack(connection: sqlite3.Connection) -> None:
    """
    Truncates the current_attacks table, ensuring no transient attack state persists.
    """
    cursor = connection.cursor()
    cursor.execute("DELETE FROM current_attacks")
    connection.commit()

def save_current_attack(
    connection: sqlite3.Connection, 
    raw_damage: int, 
    dmg_type: int, 
    hit_location: int, 
    feint: int, 
    critical: int
) -> None:
    """
    Enforces a single-state invariant by clearing the table before injecting 
    the new monolithic attack parameters.
    """
    cursor = connection.cursor()
    
    # First, purge the volatile state to ensure only one row ever exists
    cursor.execute("DELETE FROM current_attacks")
    
    # Inject the new state vector
    cursor.execute("""
        INSERT INTO current_attacks (raw_damage, dmg_type, hit_location, feint, critical)
        VALUES (?, ?, ?, ?, ?)
    """, (raw_damage, dmg_type, hit_location, feint, critical))
    
    connection.commit()

def get_current_attack(connection: sqlite3.Connection) -> dict:
    """
    Queries the solitary attack state record. 
    Returns an empty dictionary if the combat pipeline is currently vacant.
    """
    cursor = connection.cursor()
    cursor.execute("""
        SELECT raw_damage, dmg_type, hit_location, feint, critical 
        FROM current_attacks 
        LIMIT 1
    """)
    row = cursor.fetchone()
    
    if row is None:
        return {}
        
    return {
        "raw_damage": row[0],
        "dmg_type": row[1],
        "hit_location": row[2],
        "feint": row[3],
        "critical": row[4]
    }

#SQL FUNCTIONS (characters)
def get_character_strength(connection: sqlite3.Connection, owner_id: int) -> int:
    """
    Retrieves the raw Strength (ST) attribute for a character owned by the given owner_id.
    Raises a ValueError if no character entity is bound to the provided identifier.
    """
    cursor = connection.cursor()
    
    # Selecting the exact scalar attribute filtered by the owner's unique token
    cursor.execute("SELECT st FROM characters WHERE owner_id = ?", (owner_id,))
    row = cursor.fetchone()
    
    if row is None:
        raise ValueError(f"Database Anomaly: Access denied or character non-existent for owner_id {owner_id}.")
        
    return int(row[0])

# Other
def damage_func(st: int, gdp_geb: int, weapon_dmg: int, strong: int | None = None):
    # The damage table maps the damage caused by different ST levels. Information retrieved from the GURPS Basic Set book.
    damage_table = {
        1: ([1, -6], [1, -5]),
        2: ([1, -6], [1, -5]),
        3: ([1, -5], [1, -4]),
        4: ([1, -5], [1, -4]),
        5: ([1, -4], [1, -3]),
        6: ([1, -4], [1, -3]),
        7: ([1, -3], [1, -2]),
        8: ([1, -3], [1, -2]),
        9: ([1, -2], [1, -1]),
        10: ([1, -2], [1, 0]),
        11: ([1, -1], [1, 1]),
        12: ([1, -1], [1, 2]),
        13: ([1, 0], [2, -1]),
        14: ([1, 0], [2, 0]),
        15: ([1, 1], [2, 1]),
        16: ([1, 1], [2, 2]),
        17: ([1, 2], [3, -1]),
        18: ([1, 2], [3, 0]),
        19: ([2, -1], [3, 1]),
        20: ([2, -1], [3, 2]),
        21: ([2, 0], [4, -1]),
        22: ([2, 0], [4, 0]),
        23: ([2, 1], [4, 1]),
        24: ([2, 1], [4, 2]),
        25: ([2, 2], [5, -1]),
        26: ([2, 2], [5, 0]),
        27: ([3, -1], [5, 1]),
        28: ([3, -1], [5, 1]),
        29: ([3, 0], [5, 2]),
        30: ([3, 0], [5, 2]),
        31: ([3, 1], [6, -1]),
        32: ([3, 1], [6, -1]),
        33: ([3, 2], [6, 0]),
        34: ([3, 2], [6, 0]),
        35: ([4, -1], [6, 1]),
        36: ([4, -1], [6, 1]),
        37: ([4, 0], [6, 2]),
        38: ([4, 0], [6, 2]),
        39: ([4, 1], [7, -1]),
        40: ([4, 1], [7, -1]),
        45: ([5, 0], [7, 1]),
        50: ([5, 2], [8, -1]),
        55: ([6, 0], [8, 1]),
        60: ([7, -1], [9, 0]),
        65: ([7, 1], [9, 2]),
        70: ([8, 0], [10, 0]),
        75: ([8, 2], [10, 2]),
        80: ([9, 0], [11, 0]),
        85: ([9, 2], [11, 2]),
        90: ([10, 0], [12, 0]),
        95: ([10, 2], [12, 2]),
        100: ([11, 0], [13, 0]),
    }

    if st <= 0:
        basic_damage = ([0, 0], [0, 0])
    # Rule for ST above 100: adds 1d to GdP and GeB for every 10 whole points
    elif st > 100:
        extra_dice = (st - 100) // 10
        gdp_dice = 11 + extra_dice
        geb_dice = 13 + extra_dice
        basic_damage = ([gdp_dice, 0], [geb_dice, 0])
    # If the ST is exactly in the table, returns it directly
    elif st in damage_table:
        basic_damage = damage_table[st]
    # If it is between 40 and 100 and not in the table, rounds down to the nearest multiple of 5
    else:
        rounded_st = (st // 5) * 5
        basic_damage = damage_table[rounded_st]

    # Here it takes the value (0 or 1) stored in the atk_type choice and uses it to look up the correct value in the dictionary
    dice_count, st_mod = basic_damage[gdp_geb] 

    # Damage calculation
    dices = [randint(1, 6) for _ in range(dice_count)]
    dice_sum = sum(dices)

    if strong is 1:
        if dice_count > 1:
            damage = dice_sum + st_mod + weapon_dmg + dice_count
        else:
            damage = dice_sum + st_mod + weapon_dmg + 2
    else:
        damage = dice_sum + st_mod + weapon_dmg

    data = {
        "damage": damage,
        "dice_count": dice_count,
        "dices": dices,
        "st_mod": st_mod,
        "dice_sum": dice_sum
    }

    return data

# Command Cog
class Battle(commands.Cog):
    """
    
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        project_root = Path(__file__).resolve().parent.parent
        database_path = project_root / "data" / "database.db"
        
        # Establishing the persistent, active connection channel
        self.db_connection = sqlite3.connect(database_path)

        # Create the body parts dict with the difficulty 
        self.body_parts_difficulty = {
            "Tronco (0)": 0,
            "Órgãos Vitais (-3)": -3,
            "Crânio (-7)": -7,
            "Olho (-9)": -9,
            "Rosto (-5)": -5,
            "Pescoço (-5)": -5,
            "Virilha (-3)": -3,
            "Braço (-2)": -2,
            "Perna (-2)": -2,
            "Mão (-4)": -4,
            "Pé (-4)": -4

        }

    # Damage Command ------------------------------------------------
    @app_commands.command(description="Calcula dano de um ataque")
    @app_commands.describe(
        st="Força do seu personagem",
        modificador="Modificador de dano dado pela arma",
        atk_type="Escoha se é um golpe de ponta ou um golpe em Balanço",
    )
    @app_commands.choices(
        atk_type=[
            app_commands.Choice(name="Golpe de Ponta", value=0),
            app_commands.Choice(name="Golpe em Balanço", value=1),
        ]
    )
    async def dmg(
        self,
        interact: discord.Interaction,
        st: int,
        modificador: int,
        atk_type: app_commands.Choice[int]
    ):

        # Embed

        damage_data = damage_func(st, atk_type.value, modificador)

        st_mod = damage_data["st_mod"]
        dice_count = damage_data["dice_count"]
        dices = damage_data["dices"]
        dice_sum = damage_data["dice_sum"]
        damage_value = damage_data["damage"]

        dmg_embed = discord.Embed()
        signal = "+" if st_mod >= 0 else "-"

        dmg_embed.title = "DANO"
        dmg_embed.color = discord.Color.brand_red()
        dmg_embed.add_field(name="Força", value=st, inline=False)
        dmg_embed.add_field(
            name="Tipo de Ataque",
            value=f"{atk_type.name}\n{dice_count}d {signal} {abs(st_mod)}",
            inline=False,
        )
        dmg_embed.add_field(
            name="Resultado da Rolagem",
            value=f"\n`Dados: {dices} = {dice_sum}`\nModificador de Força: {st_mod}\nModificador de Arma: {modificador}\n\n**Total:** {damage_value}",
            inline=False,
        )

        await interact.response.send_message(embed=dmg_embed)

    # atk_melee ---------------------------------------------------------
    @app_commands.command(name="atk", description="Realiza um ataque")
    @app_commands.choices(
        local=[
            app_commands.Choice(name="Tronco (0)", value=0),
            app_commands.Choice(name="Órgãos Vitais (-3)", value=1),
            app_commands.Choice(name="Crânio (-7)", value=2),
            app_commands.Choice(name="Olho (-9)", value=3),
            app_commands.Choice(name="Rosto (-5)", value=4),
            app_commands.Choice(name="Pescoço (-5)", value=5),
            app_commands.Choice(name="Virilha (-3)", value=6),
            app_commands.Choice(name="Braço (-2)", value=7),
            app_commands.Choice(name="Perna (-2)", value=8),
            app_commands.Choice(name="Mão (-4)", value=9),
            app_commands.Choice(name="Pé (-4)", value=10)
        ],
        gdp_geb=[
            app_commands.Choice(name="GdP", value=11),
            app_commands.Choice(name="GeB", value=12)
        ],
        damage_type=[
            app_commands.Choice(name="Contusão", value=0),
            app_commands.Choice(name="Corte", value=1),
            app_commands.Choice(name="Perf", value=2),
        ],
        strong=[
            app_commands.Choice(name="Não", value=0),
            app_commands.Choice(name="Sim", value=1)
        ]
    )
    async def atk_meele(
        self,
        interaction: discord.Interaction,
        nh: int,
        local:app_commands.Choice[int],
        gdp_geb:app_commands.Choice[int],
        weapon_dmg:int,
        damage_type:app_commands.Choice[int],
        strong: app_commands.Choice[int] | None = None
    ):
        player_id = interaction.user.id

        # Database data collection
        evaluate_value = get_player_condition(self.db_connection, player_id, "evaluate")
        evaluate_modifier = evaluate_value if evaluate_value < 3 else 3

        shock = get_player_condition(self.db_connection, player_id, "shock")
        local_difficulty = self.body_parts_difficulty[local.name]
        effective_nh = nh + local_difficulty + evaluate_modifier + shock
        st = get_character_strength(self.db_connection, player_id)
        feint = get_player_condition(self.db_connection, player_id, "feint")

        # cleaning up the tables
        clear_player_conditions(self.db_connection, player_id)
        clear_current_attack(self.db_connection)

        # Dice Roll
        pending_fate = consume_deterministic_fate(player_id)

        if pending_fate is not None:
            dices = hdm_dices(nh=effective_nh, fate=pending_fate)
        else:
            dices = [randint(1, 6) for _ in range(3)]
        
        dice_pool = sum(dices)

        if effective_nh < 0:  # Ensures effective NH is never less than 0
            effective_nh = 0
        
        atk_melee_embed = discord.Embed()
        # Initializing the variable is necessary so the text editor stops thinking the code will cause an error.
        critical_failure_dice = 0

        # Validation of success
        if dice_pool == 18:  # Verification of critical failures
            atk_melee_embed.title = "FALHA CRÍTICA!"
            atk_melee_embed.color = discord.Color.brand_red()
            critical_failure_dice = [randint(1, 6) for _ in range(3)]

        elif dice_pool == 17:  # Verification of critical failures
            if effective_nh <= 15:
                atk_melee_embed.title = "FALHA CRÍTICA!"
                atk_melee_embed.color = discord.Color.brand_red()
                critical_failure_dice = [randint(1, 6) for _ in range(3)]
            else:
                atk_melee_embed.title = "FALHA"
                atk_melee_embed.color = discord.Color.red()

        elif dice_pool <= effective_nh:  # If the roll was a success
            if dice_pool <= 4:
                atk_melee_embed.title = "GOLPE FULMINANTE!"
                atk_melee_embed.color = discord.Color.gold()
                decisive_success_dices = [randint(1, 6) for _ in range(3)]

                # SQL insertion
                atk_form = 0 if gdp_geb.value == 11 else 1 # 0 if GdP, 1 if GeB
                damage_data = damage_func(st, atk_form, weapon_dmg, strong.value)
                raw_damage = damage_data["damage"]
                save_current_attack(self.db_connection, raw_damage, damage_type.value, local.value, feint, decisive_success_dices)

            else:
                if (
                    effective_nh - dice_pool >= 10
                ):  # Checks if the margin of success is 10 or greater
                    atk_melee_embed.title = "GOLPE FULMINANTE"
                    atk_melee_embed.color = discord.Color.gold()
                    decisive_success_dices = [randint(1, 6) for _ in range(3)]

                    # SQL insertion
                    atk_form = 0 if gdp_geb.value == 11 else 1 # 0 if GdP, 1 if GeB
                    damage_data = damage_func(st, atk_form, weapon_dmg, strong.value)
                    raw_damage = damage_data["damage"]
                    save_current_attack(self.db_connection, raw_damage, damage_type.value, local.value, feint, decisive_success_dices)
                
                else:
                    atk_melee_embed.title = "SUCESSO!"
                    atk_melee_embed.color = discord.Color.green()

                    # SQL insertion
                    atk_form = 0 if gdp_geb.value == 11 else 1 # 0 if GdP, 1 if GeB
                    damage_data = damage_func(st, atk_form, weapon_dmg, strong.value)
                    raw_damage = damage_data["damage"]
                    save_current_attack(self.db_connection, raw_damage, damage_type.value, local.value, feint, 0)

        else:  # If the roll was not a success
            if (
                dice_pool - effective_nh >= 10
            ):  # Checks if the margin of failure is 10 or greater
                atk_melee_embed.title = "FALHA CRÍTICA!"
                atk_melee_embed.color = discord.Color.brand_red()
                critical_failure_dice = [randint(1, 6) for _ in range(3)]

            else:
                atk_melee_embed.title = "FALHA"
                atk_melee_embed.color = discord.Color.red()
        
        # O sistema não está mostrando o valor com as modificações de local choque etc. Colocar isso na embed
        total_modifiers = local_difficulty + shock + evaluate_modifier
        signal_modifier = "-" if total_modifiers < 0 else "+"
        signal_weapon_dmg = "-" if weapon_dmg < 0 else "+"
        is_strong = "Não" if strong == None or strong.value == 0 else "Sim"

        atk_melee_embed.add_field(
            name="Modificadores",
            value=(
                f"Local: {local.name}\n"
                f"Choque: {shock}\n"
                f"Avaliação: {evaluate_modifier}\n"
                f"TOTAL: ({local_difficulty}) + ({shock}) + ({evaluate_modifier}) = `{total_modifiers}`"
            ),
            inline=False
        )
        
        atk_melee_embed.add_field(
            name="Dados",
            value=(
                f"{gdp_geb.name} {signal_weapon_dmg} {abs(weapon_dmg)}\n"
                f"Forte: {is_strong}\n\n"
                f"NH Básico: {nh}\n"
                f"NH Efetivo: `{effective_nh}` -> {nh} {signal_modifier} {abs(total_modifiers)}\n"
                f"Parada de Dados: {dices} = `{dice_pool}`"
            ),
            inline=False
        )

        if atk_melee_embed.title == "FALHA CRÍTICA!":
            atk_melee_embed.add_field(
                name="Falha Crítica",
                value=f"Valor da rolagem Crítica: {critical_failure_dice} = {sum(critical_failure_dice)}"
            )

        await interaction.response.send_message(embed=atk_melee_embed)

    # Fnt ---------------------------------------------------------
    @app_commands.command(description="Realiza uma finta")
    @app_commands.describe(
        nh1="Seu nível de habilidade",
        nh2="Nível de habilidade do seu oponente"
    )
    async def fnt(self, interaction: discord.Interaction, nh1: int, nh2: int):
        player_id = interaction.user.id

        shock = get_player_condition(self.db_connection, player_id, "shock")

        effective_nh1 = nh1 - shock

        # cleaning up the tables
        clear_player_conditions(self.db_connection, player_id)
        clear_current_attack(self.db_connection)

        result = quick_dispute(player_id, effective_nh1, nh2)

        dice_pool1 = result["result1"]["dice_pool1"]
        success_roll1 = result["result1"]["success_roll1"]
        margin1 = result["result1"]["margin1"]
        dices1 = result["result1"]["dices1"]

        dice_pool2 = result["result2"]["dice_pool2"]
        success_roll2 = result["result2"]["success_roll2"]
        margin2 = result["result2"]["margin2"]
        dices2 = result["result2"]["dices2"]


        fnt_embed = discord.Embed()

        if success_roll1 is True and success_roll2 is False:
            fnt_embed.title = "A FINTA FOI UM SUCESSO"
            fnt_embed.description = (
                "Você obteve um sucesso no teste e seu oponente um fracasso!\n\n"
                "Sua margem de sucesso será usada como penalidade para a próxima defesa inimiga"
            )
            fnt_embed.color = discord.Color.green()
            set_player_condition(self.db_connection, player_id, "feint", margin1) # Add the value in the SQL

            fnt_embed.add_field(
                name="Você",
                value=f"NH: {effective_nh1}\n`Dados: {dices1} = {dice_pool1}`\nSucesso: Sim\n`Margem: {margin1}`",
                inline=False,
            )
            fnt_embed.add_field(
                name="Oponente",
                value=f"NH: {nh2}\n`Dados: {dices2} = {dice_pool2}`\nSucesso: Não",
                inline=False,
            )
            fnt_embed.add_field(
                name="Margem de Sucesso",
                value=f"`{margin1}`",
                inline=False
            )

        elif success_roll1 is False:
            fnt_embed.title = "A FINTA FOI UM FRACASSO"
            fnt_embed.description = (
                "Vcê fracassou no teste de fina"
            )
            fnt_embed.color = discord.Color.red()

            fnt_embed.add_field(
                name="Você",
                value=f"NH: {effective_nh1}\n`Dados: {dices1} = {dice_pool1}`\nSucesso: Não",
                inline=False,
            )

        elif margin1 > margin2:
            fnt_embed.title = "A FINTA FOI UM SUCESSO!"
            fnt_embed.color = discord.Color.green()
            fnt_embed.description = "Resultado decidido pela margem do teste."
            set_player_condition(self.db_connection, player_id, "feint", margin1 - margin2)# Add the value in the SQL             

            fnt_embed.add_field(
                name="Você",
                value=f"NH: {effective_nh1}\n`Dados: {dices1} = {dice_pool1}`\nSucesso: Sim\n`Margem: {margin1}`",
                inline=False,
            )
            fnt_embed.add_field(
                name="Oponente",
                value=f"NH: {nh2}\n`Dados: {dices2} = {dice_pool2}`\nSucesso: Sim\n`Margem: {margin2}`",
                inline=False,
            )
            fnt_embed.add_field(
                name="Margem de Vitória",
                value=f"`{margin1} - {margin2} = {margin1 - margin2}`",
                inline=False
            )

        elif margin1 == margin2:
            fnt_embed.title = "EMPATE!"
            fnt_embed.color = discord.Color.greyple()
            fnt_embed.description = "Empate"

            fnt_embed.add_field(
                name="Você",
                value=f"NH: {effective_nh1}\n`Dados: {dices1} = {dice_pool1}`\nSucesso: Sim\n`Margem: {margin1}`",
                inline=False,
            )
            fnt_embed.add_field(
                name="Oponente",
                value=f"NH: {nh2}\n`Dados: {dices2} = {dice_pool2}`\nSucesso: Sim\n`Margem: {margin2}`",
                inline=False,
            )
            fnt_embed.add_field(
                name="Margem de Vitória",
                value=f"`{margin1} - {margin2} = {margin1 - margin2}`",
                inline=False
            )

        else:
            fnt_embed.title = "A FINTA FOI UM FRACASSO"
            fnt_embed.color = discord.Color.red()

            fnt_embed.description = "Resultado decidido pela margem do teste."
            fnt_embed.add_field(
                name="Você",
                value=f"NH: {effective_nh1}\n`Dados: {dices1} = {dice_pool1}`\nSucesso: Sim\n`Margem: {margin1}`",
                inline=False,
            )
            fnt_embed.add_field(
                name="Oponente",
                value=f"NH: {nh2}\n`Dados: {dices2} = {dice_pool2}`\nSucesso: Sim\n`Margem: {margin2}`",
                inline=False,
            )
            fnt_embed.add_field(
                name="Margem de Vitória",
                value=f"`{margin1} - {margin2} = {margin1 - margin2}`",
                inline=False
            )

        await interaction.response.send_message(embed=fnt_embed)

    # Apt (aim command) -------------------------------------------
    @app_commands.command(name="apt",description="Aponta com uma arma de combate a distância")
    async def aim(self, interaction: discord.Interaction):
        player_id = interaction.user.id
        
        # cleaning up the tables
        set_player_condition(self.db_connection, player_id, "evaluate", 0)

        aim_value = get_player_condition(self.db_connection, player_id, "aim")

        aim_value += 1

        set_player_condition(self.db_connection, player_id, "aim", aim_value)

        await interaction.response.send_message(f"{aim_value}º Turno apontando.")
    
    # Avaliaar (evaluate command) -------------------------------------------
    @app_commands.command(name="avaliar",description="Estuda o oponente para conseguir um bônus na próxima rolagem")
    async def evaluate(self, interaction: discord.Interaction):
        player_id = interaction.user.id
        #   cleaning up the tables
        set_player_condition(self.db_connection, player_id, "aim", 0)

        evaluate_value = get_player_condition(self.db_connection, player_id, "evaluate")

        evaluate_value += 1

        set_player_condition(self.db_connection, player_id, "evaluate", evaluate_value)

        await interaction.response.send_message(f"{evaluate_value}º Turno Avaliando.")

async def setup(bot: commands.Bot):
    """
    Mandatory asynchronous entry point to load the extension.
    """
    await bot.add_cog(Battle(bot))