import discord
from discord import app_commands
from discord.ext import commands

from random import randint
from pathlib import Path
import sqlite3

from utils.dice_mechanics import consume_deterministic_fate
from utils.dice_mechanics import hdm_dices
from utils.db_functions import get_character_thumbnail_payload


class Other_tests(commands.Cog):
    """ """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        project_root = Path(__file__).resolve().parent.parent
        database_path = project_root / "data" / "database.db"

        # Establishing the persistent, active connection channel
        self.db_connection = sqlite3.connect(database_path)
        self.db_connection.execute("PRAGMA foreign_keys = ON;")

    # Roll Command ---------------------------------------------------
    @app_commands.command(
        description="Rola Genericamente um número de dados com algum modiificador"
    )
    @app_commands.describe(
        num_dados="Número de dados que serão rolados",
        modificador="Qualquer modificador que precise ser aplicado",
    )
    async def roll(
        self, interact: discord.Interaction, num_dados: int, modificador: int
    ):
        dices = [randint(1, 6) for _ in range(num_dados)]
        dice_pool = sum(dices)

        # Embed
        roll_embed = discord.Embed()

        roll_embed.title = "ROLAGEM"
        roll_embed.color = discord.Color.green()
        roll_embed.add_field(
            name="Rolagem",
            value=f"`Dados: {dices} = {dice_pool}`\nModificador: {modificador}\n\n**Total:** {dice_pool + modificador}",
        )

        await interact.response.send_message(embed=roll_embed)

    # Reaction Test ---------------------------------------------------
    @app_commands.command(
        name="react",
        description="Executa a rolagem de um teste de reação baseado nas tabelas canônicas do GURPS.",
    )
    @app_commands.describe(
        modifier="Soma dos modificadores de reação ativos na entidade"
    )
    async def react(self, interaction: discord.Interaction, modifier: int):
        """
        Resolves a GURPS Reaction Test, handling deterministic fate constraints.
        Enforces immediate network deferral to guarantee safety against while-loop execution spikes.
        """
        # CRITICAL AXIOM: Securing the network payload token before processing database and RNG loops
        await interaction.response.defer(ephemeral=False)

        player_id = interaction.user.id

        # Processing transient database state
        fate = consume_deterministic_fate(player_id)

        if fate is not None:
            # Mathematical safeguards: absolute limits for 3d6 bounds compounded by the modifier
            min_possible = 3 + modifier
            max_possible = 18 + modifier

            if fate == 0:  # Success bracket (Total between 10 and 15)
                if max_possible < 10:
                    dices = [6, 6, 6]
                elif min_possible > 15:
                    dices = [1, 1, 1]
                else:
                    while True:
                        dices = [randint(1, 6) for _ in range(3)]
                        if 10 <= sum(dices) + modifier <= 15:
                            break

            elif fate == 1:  # Failure bracket (Total between 4 and 9)
                if max_possible < 4:
                    dices = [6, 6, 6]
                elif min_possible > 9:
                    dices = [1, 1, 1]
                else:
                    while True:
                        dices = [randint(1, 6) for _ in range(3)]
                        if 4 <= sum(dices) + modifier <= 9:
                            break

            elif fate == 2:  # Critical Success bracket (Total 16 or higher)
                if max_possible < 16:
                    dices = [6, 6, 6]
                else:
                    while True:
                        dices = [randint(1, 6) for _ in range(3)]
                        if sum(dices) + modifier >= 16:
                            break

            else:  # Critical Failure bracket (Total 3 or lower)
                if min_possible > 3:
                    dices = [1, 1, 1]
                else:
                    while True:
                        dices = [randint(1, 6) for _ in range(3)]
                        if sum(dices) + modifier <= 3:
                            break
        else:
            dices = [randint(1, 6) for _ in range(3)]

        dice_pool = sum(dices)
        total_score = dice_pool + modifier

        # Embed initialization and color routing pipeline
        react_embed = discord.Embed()

        if total_score <= 0:
            react_embed.title = "REAÇÃO DESASTROSA"
            react_embed.color = discord.Color.red()
        elif total_score <= 3:
            react_embed.title = "REAÇÃO MUITO RUIM"
            react_embed.color = discord.Color.red()
        elif total_score <= 6:
            react_embed.title = "REAÇÃO RUIM"
            react_embed.color = discord.Color.orange()
        elif total_score <= 9:
            react_embed.title = "REAÇÃO FRACA"
            react_embed.color = discord.Color.yellow()
        elif total_score <= 12:
            react_embed.title = "REAÇÃO NEUTRA"
            react_embed.color = discord.Color.greyple()
        elif total_score <= 15:
            react_embed.title = "REAÇÃO BOA"
            react_embed.color = discord.Color.green()
        elif total_score <= 18:
            react_embed.title = "REAÇÃO MUITO BOA"
            react_embed.color = discord.Color.green()
        else:
            react_embed.title = "REAÇÃO EXCELENTE"
            react_embed.color = discord.Color.blue()

        react_embed.add_field(
            name="Métricas da Rolagem",
            value=f"`Dados: {dices} = {dice_pool}`\nModificador: `{modifier: +d}`\n\n**Resultado Final: {total_score}**",
            inline=False,
        )

        # Character visual asset extraction using the payload wrapper
        character_file, thumbnail_url = get_character_thumbnail_payload(
            self.db_connection, player_id
        )

        if thumbnail_url:
            react_embed.set_thumbnail(url=thumbnail_url)

        # Strict conditional dispatch protecting network payload against NoneType serialization
        if character_file is not None:
            await interaction.followup.send(embed=react_embed, file=character_file)
        else:
            await interaction.followup.send(embed=react_embed)

    # Panic -----------------------------------------------------------
    @app_commands.command(description="Realiza uma verificação de Pânico")
    @app_commands.describe(
        vontade="Seu Valor de Vontade",
        modificador="Soma dos modificadores de dificuldade",
    )
    async def panic(
        self, interaction: discord.Interaction, vontade: int, modificador: int
    ):
        """
        Resolves a GURPS Fright Check, evaluating panic table thresholds upon failure.
        Enforces immediate network token preservation to prevent interface timeouts.
        """
        # CRITICAL AXIOM: Immediate network token preservation.
        # Extends the interaction lifecycle to 15 minutes before any processing occurs.
        await interaction.response.defer(ephemeral=False)

        player_id = interaction.user.id

        # Database transaction: consuming transient fate state
        pending_fate = consume_deterministic_fate(player_id)

        if pending_fate is not None:
            dices = hdm_dices(nh=vontade, fate=pending_fate)
        else:
            dices = [randint(1, 6) for _ in range(3)]

        dice_pool = sum(dices)
        effective_sl = vontade + modificador

        # Structural safeguard: Effective Skill Level cannot drop below absolute zero
        if effective_sl < 0:
            effective_sl = 0

        # Embed initialization
        panic_embed = discord.Embed()
        is_success = False
        is_critical_success = False
        is_critical_failure = False

        # ==========================================
        # SUCCESS RESOLUTION STATE MACHINE
        # ==========================================
        if dice_pool == 18:
            is_critical_failure = True
        elif dice_pool == 17:
            if effective_sl <= 15:
                is_critical_failure = True
            else:
                is_critical_failure = False
        elif dice_pool <= effective_sl:
            is_success = True
            if dice_pool <= 4 or (effective_sl - dice_pool >= 10):
                is_critical_success = True
        else:
            if dice_pool - effective_sl >= 10:
                is_critical_failure = True

        # ==========================================
        # POST-ROLL PRESENTATION PIPELINE
        # ==========================================
        if is_success:
            panic_embed.title = "RESISTIU AO PÂNICO"
            panic_embed.color = (
                discord.Color.gold() if is_critical_success else discord.Color.green()
            )

            modificador_sign = "+" if modificador >= 0 else "-"
            margin_of_victory = effective_sl - dice_pool

            panic_embed.add_field(
                name="Parada de Dados", value=f"`{dices} = {dice_pool}`", inline=False
            )
            panic_embed.add_field(
                name="Nível de Vontade",
                value=f"NH Básico: {vontade}\nModificador: {modificador}\n`NH Efetivo: {effective_sl}` -> {vontade} {modificador_sign} {abs(modificador)}",
                inline=False,
            )
            panic_embed.add_field(
                name="Margem de Vitória",
                value=f"`{effective_sl} - {dice_pool} = {margin_of_victory}`",
                inline=False,
            )
        else:
            panic_embed.title = "SUCUMBIU AO PÂNICO"
            panic_embed.color = (
                discord.Color.brand_red()
                if is_critical_failure
                else discord.Color.red()
            )

            # Executing secondary panic metrics calculation (3d6 + failure margin)
            panic_dices = [randint(1, 6) for _ in range(3)]
            panic_dice_pool = sum(panic_dices)
            failure_margin = dice_pool - effective_sl

            # GURPS Axiom: Critical failures automatically add a flat +10 penalty to the panic roll
            if is_critical_failure:
                panic_value = panic_dice_pool + failure_margin + 10
                critical_notice = (
                    "\n⚠️ **FALHA CRÍTICA: +10 adicionado ao resultado final!**"
                )
            else:
                panic_value = panic_dice_pool + failure_margin
                critical_notice = ""

            panic_embed.description = f"A tabela de consequências de pânico encontra-se no Módulo Básico, pág. 361.{critical_notice}"

            panic_embed.add_field(
                name="Métricas de Fracasso",
                value=f"Dados do Teste: `{dices} = {dice_pool}`\nMargem de Fracasso: `{failure_margin}`",
                inline=False,
            )
            panic_embed.add_field(
                name="Rolagem na Tabela de Pânicos",
                value=f"Dados: `{panic_dices} = {panic_dice_pool}`\n**Valor Final do Pânico:** `{panic_value}`",
                inline=False,
            )

        # Character visual asset lookup using the payload wrapper
        character_file, thumbnail_url = get_character_thumbnail_payload(
            self.db_connection, player_id
        )

        if thumbnail_url:
            panic_embed.set_thumbnail(url=thumbnail_url)

        # Strict conditional dispatch protecting network payload against NoneType serialization
        if character_file is not None:
            await interaction.followup.send(embed=panic_embed, file=character_file)
        else:
            await interaction.followup.send(embed=panic_embed)


async def setup(bot: commands.Bot):
    """
    Mandatory asynchronous entry point to load the extension.
    """
    await bot.add_cog(Other_tests(bot))
