from random import randint
import sqlite3
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from utils.test_mechanics import quick_dispute
from utils.dice_mechanics import consume_deterministic_fate
from utils.dice_mechanics import hdm_dices

from utils.db_functions import *


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
    critical_dices = [6 for _ in range(dice_count)]

    dice_sum = sum(dices)
    critical_dice_sum = sum(critical_dices)

    if strong == 1:
        if dice_count > 1:
            damage = dice_sum + st_mod + weapon_dmg + dice_count
            critical_damage = critical_dice_sum + st_mod + weapon_dmg + dice_count
        else:
            damage = dice_sum + st_mod + weapon_dmg + 2
            critical_damage = critical_dice_sum + st_mod + weapon_dmg + 2
    else:
        damage = dice_sum + st_mod + weapon_dmg
        critical_damage = critical_dice_sum + st_mod + weapon_dmg

    data = {
        "critical_damage": critical_damage,
        "damage": damage,
        "dice_count": dice_count,
        "dices": dices,
        "st_mod": st_mod,
        "dice_sum": dice_sum,
    }

    return data


# Command Cog
class Battle(commands.Cog):
    """
    Orchestrates the tactical combat simulation engine for the Dice-Master system,
    adhering strictly to the mechanical canons of the GURPS 4th Edition framework.

    This cog manages the lifecycle of physical confrontations, encapsulating melee
    engagements, ranged ballistic actions, and active defense resolution pipelines.
    It interfaces dynamically with the relational database backend to track transient
    combat states—such as shock penalties, aim variables, feints, and evaluative
    maneuvers—while mutating character resource pools based on regional injury
    multipliers and limb crippling thresholds.

    Attributes:
        bot (commands.Bot): The core Discord bot instance executing the application.
        db_connection (sqlite3.Connection): The active relational database handle
            utilized for persisting combat states and retrieving character matrices.
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
            "Pé (-4)": -4,
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
        atk_type: app_commands.Choice[int],
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
    @app_commands.command(name="atk", description="Realiza um ataque corpo a corpo")
    @app_commands.describe(
        nh="Seu Nível de Habilidade",
        local="Local onde você irá atacar",
        gdp_geb="É Golpe de Ponta ou Golpe em Balanço?",
        weapon_dmg="Dano da arma",
        damage_type="Tipo de dano",
        strong="Apenas coloque sim, se você estiver usadno o ataque total forte",
    )
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
            app_commands.Choice(name="Pé (-4)", value=10),
        ],
        gdp_geb=[
            app_commands.Choice(name="GdP", value=11),
            app_commands.Choice(name="GeB", value=12),
        ],
        damage_type=[
            app_commands.Choice(name="Contusão", value=4),
            app_commands.Choice(name="Corte", value=5),
            app_commands.Choice(name="Perf", value=7),
        ],
        strong=[
            app_commands.Choice(name="Não", value=0),
            app_commands.Choice(name="Sim", value=1),
        ],
    )
    async def atk_meele(
        self,
        interaction: discord.Interaction,
        nh: int,
        local: app_commands.Choice[int],
        gdp_geb: app_commands.Choice[int],
        weapon_dmg: int,
        damage_type: app_commands.Choice[int],
        strong: app_commands.Choice[int] | None = None,
    ):
        strong_value = strong.value if strong is not None else 0
        player_id = interaction.user.id

        # Hardcoded penalty dictionary to avoid brittle string-name lookups
        location_penalties = {
            0: 0,
            1: -3,
            2: -7,
            3: -9,
            4: -5,
            5: -5,
            6: -3,
            7: -2,
            8: -2,
            9: -4,
            10: -4,
        }
        local_difficulty = location_penalties.get(local.value, 0)

        # Database state collection with defensive fallbacks
        evaluate_raw = get_player_condition(self.db_connection, player_id, "evaluate")
        evaluate_modifier = min(evaluate_raw, 3) if evaluate_raw is not None else 0

        shock_raw = get_player_condition(self.db_connection, player_id, "shock")
        shock = shock_raw if shock_raw is not None else 0

        feint_raw = get_player_condition(self.db_connection, player_id, "feint")
        feint_value = feint_raw if feint_raw is not None else 0

        st = get_character_strength(self.db_connection, player_id)

        # Mathematical correction: shock is a penalty and must be subtracted
        total_modifiers = local_difficulty + evaluate_modifier - shock
        effective_nh = max(0, nh + total_modifiers)

        # Ephemeral database state purge
        clear_player_conditions(self.db_connection, player_id)
        clear_current_attack(self.db_connection)

        # Dice roll mechanics execution
        pending_fate = consume_deterministic_fate(player_id)
        if pending_fate is not None:
            dices = hdm_dices(nh=effective_nh, fate=pending_fate)
        else:
            dices = [randint(1, 6) for _ in range(3)]

        dice_pool = sum(dices)

        # Embed and state engine initialization
        atk_melee_embed = discord.Embed()
        is_success = False
        is_critical_success = False
        is_critical_failure = False
        critical_failure_dices = []

        # ==========================================
        # SUCCESS RESOLUTION STATE MACHINE
        # ==========================================
        if dice_pool == 18:
            is_critical_failure = True
        elif dice_pool == 17:
            is_critical_failure = True if effective_nh <= 15 else False
        elif dice_pool <= effective_nh:
            if dice_pool <= 4 or (effective_nh - dice_pool >= 10):
                is_critical_success = True
                is_success = True
            else:
                is_success = True
        else:
            if dice_pool - effective_nh >= 10:
                is_critical_failure = True

        # ==========================================
        # POST-ROLL LOGIC & DATA PERSISTENCE
        # ==========================================
        if is_critical_failure:
            atk_melee_embed.title = "FALHA CRÍTICA!"
            atk_melee_embed.color = discord.Color.brand_red()
            critical_failure_dices = [randint(1, 6) for _ in range(3)]
        elif is_success:
            if is_critical_success:
                atk_melee_embed.title = "GOLPE FULMINANTE!"
                atk_melee_embed.color = discord.Color.gold()
            else:
                atk_melee_embed.title = "SUCESSO!"
                atk_melee_embed.color = discord.Color.green()

            # Resolved duplication anomaly: damage_func is called exactly once here
            atk_form = 0 if gdp_geb.value == 11 else 1  # 0 for GdP, 1 for GeB
            damage_data = damage_func(st, atk_form, weapon_dmg, strong_value)
            raw_damage = damage_data["damage"]
            critical_raw_damage = damage_data["critical_damage"]

            save_current_attack(
                self.db_connection,
                raw_damage,
                damage_type.value,
                local.value,
                feint_value,
                critical_raw_damage,
            )
        else:
            atk_melee_embed.title = "FALHA"
            atk_melee_embed.color = discord.Color.red()

        # ==========================================
        # UI PRESENTATION GENERATION
        # ==========================================
        modifier_sign = "+" if total_modifiers >= 0 else "-"
        weapon_dmg_sign = "+" if weapon_dmg >= 0 else "-"
        strong_status_string = "Sim" if strong_value == 1 else "Não"

        atk_melee_embed.add_field(
            name="Modificadores",
            value=(
                f"Local Escolhido: {local.name}\n"
                f"Penalidade de Choque: `-{shock}`\n"
                f"Bônus de Avaliação: `+{evaluate_modifier}`\n"
                f"TOTAL: ({local_difficulty}) + ({evaluate_modifier}) - ({shock}) = `{total_modifiers}`"
            ),
            inline=False,
        )

        atk_melee_embed.add_field(
            name="Dados Técnicos",
            value=(
                f"Fórmula: {gdp_geb.name} {weapon_dmg_sign} {abs(weapon_dmg)}\n"
                f"Ataque Forte: {strong_status_string}\n\n"
                f"NH Básico: {nh}\n"
                f"NH Efetivo: `{effective_nh}` -> {nh} {modifier_sign} {abs(total_modifiers)}\n"
                f"Rolagem dos Dados: {dices} = `{dice_pool}`"
            ),
            inline=False,
        )

        if is_critical_failure:
            atk_melee_embed.add_field(
                name="Tabela de Falhas Críticas (Combate Corpo a Corpo)",
                value=f"Dados: `{critical_failure_dices} = {sum(critical_failure_dices)}`",
                inline=False,
            )

        await interaction.response.send_message(embed=atk_melee_embed)

    # ranged_attack ------------------------------------------------------
    @app_commands.command(
        name="ranged_attack",
        description="Realiza um ataque a distância com uma arma motora",
    )
    @app_commands.describe(
        nh="Seu Nível de Habilidade",
        local="Local onde você irá atacar",
        weapon_dmg="Dano da arma",
        damage_type="Tipo de dano",
    )
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
            app_commands.Choice(name="Pé (-4)", value=10),
        ],
        damage_type=[
            app_commands.Choice(name="Contusão", value=4),
            app_commands.Choice(name="Perfurante", value=7),
        ],
    )
    async def ranged_atk(
        self,
        interaction: discord.Interaction,
        nh: int,
        local: app_commands.Choice[int],
        weapon_dmg: int,
        damage_type: app_commands.Choice[int],
    ):
        player_id = interaction.user.id

        # Internal dictionary mapping to bypass fragile string lookups on local.name
        location_penalties = {
            0: 0,
            1: -3,
            2: -7,
            3: -9,
            4: -5,
            5: -5,
            6: -3,
            7: -2,
            8: -2,
            9: -4,
            10: -4,
        }
        local_difficulty = location_penalties.get(local.value, 0)

        # Database state collection
        aim_value = get_player_condition(self.db_connection, player_id, "aim")
        aim_modifier = min(aim_value, 3) if aim_value is not None else 0
        shock = get_player_condition(self.db_connection, player_id, "shock")
        st = get_character_strength(self.db_connection, player_id)

        # Tactical math correction: Shock is a penalty, it must be subtracted
        total_modifiers = local_difficulty + aim_modifier - shock
        effective_nh = max(0, nh + total_modifiers)
        feint_value = 0

        # Housekeeping pipeline: purging obsolete transient states
        clear_player_conditions(self.db_connection, player_id)
        clear_current_attack(self.db_connection)

        # Execution of the dice rolling mechanics
        pending_fate = consume_deterministic_fate(player_id)
        if pending_fate is not None:
            dices = hdm_dices(nh=effective_nh, fate=pending_fate)
        else:
            dices = [randint(1, 6) for _ in range(3)]

        dice_pool = sum(dices)

        # Embed state initialization
        ranged_embed = discord.Embed()
        is_success = False
        is_critical_success = False
        is_critical_failure = False
        critical_failure_dices = []

        # ==========================================
        # SUCCESS RESOLUTION STATE MACHINE
        # ==========================================
        if dice_pool == 18:
            is_critical_failure = True
        elif dice_pool == 17:
            is_critical_failure = True if effective_nh <= 15 else False
        elif dice_pool <= effective_nh:
            if dice_pool <= 4 or (effective_nh - dice_pool >= 10):
                is_critical_success = True
                is_success = True
            else:
                is_success = True
        else:
            if dice_pool - effective_nh >= 10:
                is_critical_failure = True

        # ==========================================
        # POST-ROLL UTILITY AND DATABASE PERSISTENCE
        # ==========================================
        if is_critical_failure:
            ranged_embed.title = "FALHA CRÍTICA!"
            ranged_embed.color = discord.Color.brand_red()
            critical_failure_dices = [randint(1, 6) for _ in range(3)]
        elif is_success:
            if is_critical_success:
                ranged_embed.title = "SUCESSO DECISIVO!"
                ranged_embed.color = discord.Color.gold()
            else:
                ranged_embed.title = "SUCESSO!"
                ranged_embed.color = discord.Color.green()

            # Resolved scope anomaly: damage_func is now evaluated safely once upon success
            damage_data = damage_func(st, 0, weapon_dmg)
            raw_damage = damage_data["damage"]
            critical_raw_damage = damage_data["critical_damage"]

            save_current_attack(
                self.db_connection,
                raw_damage,
                damage_type.value,
                local.value,
                feint_value,
                critical_raw_damage,
            )
        else:
            ranged_embed.title = "FALHA"
            ranged_embed.color = discord.Color.red()

        # ==========================================
        # UI PRESENTATION GENERATION
        # ==========================================
        modifier_sign = "+" if total_modifiers >= 0 else "-"
        weapon_dmg_sign = "+" if weapon_dmg >= 0 else "-"

        ranged_embed.add_field(
            name="Modificadores",
            value=(
                f"Local Escolhido: {local.name}\n"
                f"Penalidade de Choque: `-{shock}`\n"
                f"Bônus de Mira (Aim): `+{aim_modifier}`\n"
                f"TOTAL: ({local_difficulty}) + ({aim_modifier}) - ({shock}) = `{total_modifiers}`"
            ),
            inline=False,
        )

        ranged_embed.add_field(
            name="Resultados Balísticos",
            value=(
                f"Fórmula de Dano: GdP {weapon_dmg_sign} {abs(weapon_dmg)}\n\n"
                f"NH Base: {nh}\n"
                f"NH Efetivo: `{effective_nh}` -> {nh} {modifier_sign} {abs(total_modifiers)}\n"
                f"Rolagem dos Dados: {dices} = `{dice_pool}`"
            ),
            inline=False,
        )

        if is_critical_failure:
            ranged_embed.add_field(
                name="Tabela de Falhas Críticas (Armas à Distância)",
                value=f"Dados: `{critical_failure_dices} = {sum(critical_failure_dices)}`",
                inline=False,
            )

        await interaction.response.send_message(embed=ranged_embed)

    # Def --------------------------------------------------------------
    @app_commands.command(name="def", description="Realiza uma defesa ativa")
    @app_commands.describe(
        nh="Seu nível de habilidade na defesa",
        rd="Redução de dano no local atacado",
        receive_atk="Escolha se você vai receber o ataque ou se o usuário recebeu um crítico",
    )
    @app_commands.choices(
        receive_atk=[
            app_commands.Choice(name="Desistir da Defesa", value=1),
            app_commands.Choice(name="Crítico do Oponente", value=2),
        ]
    )
    async def defense(
        self,
        interaction: discord.Interaction,
        nh: int,
        rd: int,
        receive_atk: app_commands.Choice[int] | None = None,
    ):
        # Safe extraction of the optional parameter to prevent AttributeError
        receive_atk_value = receive_atk.value if receive_atk is not None else 0
        player_id = interaction.user.id

        # Database state collection
        current_attack = get_current_attack(self.db_connection)
        dmg_type = current_attack["dmg_type"]
        hit_location = current_attack["hit_location"]
        feint = current_attack["feint"]
        raw_damage = current_attack["raw_damage"]
        critical_raw_damage = current_attack["critical_damage"]

        character_data = get_character_profile(self.db_connection, player_id)
        st = character_data["st"]
        additional_max_pv = character_data["additional_max_pv"]

        character_resources = get_character_resources(self.db_connection, player_id)
        current_hp = character_resources["hp"]

        # Hit locations lookup configuration
        hit_locations_map = {
            0: "Tronco",
            1: "Órgãos Vitais",
            2: "Crânio",
            3: "Olho",
            4: "Rosto",
            5: "Pescoço",
            6: "Virilha",
            7: "Braço",
            8: "Perna",
            9: "Mão",
            10: "Pé",
        }

        defense_embed = discord.Embed()

        # Core flags for state machine resolution
        is_waived = receive_atk_value == 1
        is_opponent_critical = receive_atk_value == 2
        is_defense_successful = False
        is_critical_failure = False

        effective_nh = max(0, nh - feint)

        # ==========================================
        # DEFENSE ROLL RESOLUTION PIPELINE
        # ==========================================
        if is_waived:
            defense_embed.title = "DEFESA ABANDONADA"
            defense_embed.description = (
                "Você optou por não esboçar qualquer reação defensiva."
            )
            defense_embed.color = discord.Color.dark_red()
        elif is_opponent_critical:
            defense_embed.title = "ATAQUE CRÍTICO RECEBIDO"
            defense_embed.description = "O oponente desferiu um acerto crítico. A defesa é matematicamente impossível."
            defense_embed.color = discord.Color.magenta()
        else:
            # Deterministic fate vs standard RNG execution
            pending_fate = consume_deterministic_fate(player_id)
            if pending_fate is not None:
                dices = hdm_dices(nh=effective_nh, fate=pending_fate)
            else:
                dices = [randint(1, 6) for _ in range(3)]

            dice_pool = sum(dices)

            # Strict GURPS success/failure threshold logic
            if dice_pool == 18:
                is_critical_failure = True
            elif dice_pool == 17:
                is_critical_failure = True if effective_nh <= 15 else False
            elif dice_pool <= effective_nh:
                if dice_pool <= 4 or (effective_nh - dice_pool >= 10):
                    is_defense_successful = True
                    defense_embed.title = "SUCESSO DECISIVO!"
                    defense_embed.color = discord.Color.gold()
                    defense_embed.description = (
                        "Seu sucesso decisivo transformou o ataque do oponente em uma falha crítica!\n"
                        "Role o revés na tabela de falhas críticas (MB pág. 556)."
                    )
                    critical_dices = [randint(1, 6) for _ in range(3)]
                    critical_dice_sum = sum(critical_dices)
                    defense_embed.add_field(
                        name="Tabela de Falhas Críticas (Oponente)",
                        value=f"Dados: `{critical_dices} = {critical_dice_sum}`",
                        inline=False,
                    )
                else:
                    is_defense_successful = True
                    defense_embed.title = "SUCESSO!"
                    defense_embed.color = discord.Color.green()
                    defense_embed.description = (
                        "Você conseguiu evitar o ataque inimigo."
                    )
            else:
                if dice_pool - effective_nh >= 10:
                    is_critical_failure = True

            if is_critical_failure:
                defense_embed.title = "FALHA CRÍTICA!"
                defense_embed.color = discord.Color.brand_red()
                defense_embed.description = "Sua defesa colapsou fragorosamente."
            elif not is_defense_successful:
                defense_embed.title = "FALHA!"
                defense_embed.color = discord.Color.red()
                defense_embed.description = "Você foi incapaz de evitar o ataque."

            defense_embed.add_field(
                name="Rolagem de Defesa",
                value=f"NH Efetivo: `{nh} - {feint}(finta) = {effective_nh}`\nDados: `{dices} = {dice_pool}`",
                inline=False,
            )

        # ==========================================
        # DAMAGE & INJURY CALCULATION PIPELINE
        # ==========================================
        suffers_damage = (
            is_waived
            or is_opponent_critical
            or is_critical_failure
            or not is_defense_successful
        )

        if suffers_damage:
            # Determine initial base damage profile
            chosen_damage = (
                critical_raw_damage
                if (is_critical_failure or is_opponent_critical)
                else raw_damage
            )

            # GURPS Rule: Skull hit location natively provides an extra +2 DR protection
            effective_rd = rd + 2 if hit_location == 2 else rd

            # Penetrating damage calculation capped at a logical floor of 0
            penetrating_damage = max(0, chosen_damage - effective_rd)

            local_damage_multiplier = 1.0
            appendage_hp = None
            amputation = False
            incapacitation = False

            # Hit location multiplier taxonomy routing
            if hit_location == 1:  # Vitals
                if dmg_type in (7, 8, 9, 10, 11):  # Piercing family or Impaling
                    local_damage_multiplier = 3.0
            elif hit_location in (2, 3):  # Skull or Eye
                local_damage_multiplier = 4.0
            elif hit_location == 4:  # Face
                if dmg_type == 3:  # Corrosion
                    local_damage_multiplier = 1.5
            elif hit_location == 5:  # Neck
                if dmg_type in (3, 4):  # Corrosion, Crushing
                    local_damage_multiplier = 1.5
                elif dmg_type == 5:  # Cutting
                    local_damage_multiplier = 2.0
            elif hit_location in (7, 8):  # Limb (Arm/Leg)
                appendage_hp = (st + additional_max_pv) / 2
            elif hit_location in (9, 10):  # Extremity (Hand/Foot)
                appendage_hp = (st + additional_max_pv) / 3

            # Apply multiplier to determine standard injury
            final_injury = penetrating_damage * local_damage_multiplier

            # Evaluation of appendage crippling thresholds
            if appendage_hp is not None:
                if final_injury >= appendage_hp * 2:
                    amputation = True
                    final_injury = appendage_hp  # Injury capped at structural maximum
                elif final_injury >= appendage_hp:
                    incapacitation = True
                    final_injury = appendage_hp  # Injury capped at structural maximum

            # Enforcing integer conversion before mutating database state
            final_injury = int(final_injury)
            new_hp = current_hp - final_injury
            set_character_resource(self.db_connection, player_id, "hp", new_hp)

            # Building UI presentation fields for damage impact
            location_name = hit_locations_map.get(hit_location, "Desconhecido")
            injury_status_msg = ""
            if amputation:
                injury_status_msg = f"\n **{location_name.upper()} AMPUTADO!!**"
            elif incapacitation:
                injury_status_msg = f"\n **{location_name.upper()} INCAPACITADO!!**"

            defense_embed.add_field(
                name="Resolução de Impacto",
                value=(
                    f"Local Atingido: **{location_name}**\n"
                    f"Modificador Anatômico: `{local_damage_multiplier}x`\n\n"
                    f"Dano Base: `{chosen_damage}`\n"
                    f"Dano Penetrante: `{chosen_damage} - {effective_rd}(RD) = {penetrating_damage}`\n"
                    f"`Lesão Total Realizada: {final_injury}`"
                    f"{injury_status_msg}"
                ),
                inline=False,
            )
            defense_embed.add_field(
                name="Métricas Vitais do Personagem",
                value=f"PV Anterior: `{current_hp}`\nPV Atual: `{new_hp}`",
                inline=False,
            )
        else:
            # Shielding metrics if the defensive maneuver was flawless
            defense_embed.add_field(
                name="Métricas Vitais do Personagem",
                value=f"Integridade preservada. PV permanece em `{current_hp}`.",
                inline=False,
            )

        # Unified single payload transmission
        await interaction.response.send_message(embed=defense_embed)

    # Fnt ---------------------------------------------------------
    @app_commands.command(description="Realiza uma finta")
    @app_commands.describe(
        nh1="Seu nível de habilidade", nh2="Nível de habilidade do seu oponente"
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
            set_player_condition(
                self.db_connection, player_id, "feint", margin1
            )  # Add the value in the SQL

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
                name="Margem de Sucesso", value=f"`{margin1}`", inline=False
            )

        elif success_roll1 is False:
            fnt_embed.title = "A FINTA FOI UM FRACASSO"
            fnt_embed.description = "Vcê fracassou no teste de fina"
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
            set_player_condition(
                self.db_connection, player_id, "feint", margin1 - margin2
            )  # Add the value in the SQL

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
                inline=False,
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
                inline=False,
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
                inline=False,
            )

        await interaction.response.send_message(embed=fnt_embed)

    # Apt (aim command) -------------------------------------------
    @app_commands.command(
        name="apt", description="Aponta com uma arma de combate a distância"
    )
    async def aim(self, interaction: discord.Interaction):
        player_id = interaction.user.id

        # cleaning up the tables
        set_player_condition(self.db_connection, player_id, "evaluate", 0)

        aim_value = get_player_condition(self.db_connection, player_id, "aim")

        aim_value += 1

        set_player_condition(self.db_connection, player_id, "aim", aim_value)

        await interaction.response.send_message(f"{aim_value}º Turno apontando.")

    # Avaliaar (evaluate command) -------------------------------------------
    @app_commands.command(
        name="eval",
        description="Estuda o oponente para conseguir um bônus na próxima rolagem",
    )
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
