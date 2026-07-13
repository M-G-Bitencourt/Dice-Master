import discord
from discord import app_commands
from discord.ext import commands

from random import randint
from pathlib import Path
import sqlite3

from utils.dice_mechanics import consume_deterministic_fate
from utils.dice_mechanics import hdm_dices
from utils.test_mechanics import quick_dispute
from utils.db_functions import get_character_thumbnail_payload


class Skill_tests(commands.Cog):
    """ """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        project_root = Path(__file__).resolve().parent.parent
        database_path = project_root / "data" / "database.db"

        # Establishing the persistent, active connection channel
        self.db_connection = sqlite3.connect(database_path)
        self.db_connection.execute("PRAGMA foreign_keys = ON;")

    # Test Command
    @app_commands.command(description="Realiza os testes de Habilidade")
    @app_commands.describe(
        nh="Seu Nível de Habilidade na perícia",
        modificador="Modificador de Dificuldade",
    )
    async def test(self, interaction: discord.Interaction, nh: int, modificador: int):
        """
        Resolves a foundational GURPS 3d6 success test against an effective skill level.
        Enforces immediate network deferral to shield the execution window against transaction latency.
        """
        # CRITICAL AXIOM: Instant network token preservation to prevent 3-second timeouts
        await interaction.response.defer(ephemeral=False)

        player_id = interaction.user.id

        # Processing transient fate state from the persistence layer
        pending_fate = consume_deterministic_fate(player_id)

        if pending_fate is not None:
            dices = hdm_dices(nh=nh, fate=pending_fate)
        else:
            dices = [randint(1, 6) for _ in range(3)]

        dice_pool = sum(dices)
        effective_sl = nh + modificador

        # Structural safeguard: Effective Skill Level cannot collapse below absolute zero
        if effective_sl < 0:
            effective_sl = 0

        # Embed initialization and state engine flags
        test_embed = discord.Embed()
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
        # INTERFACE CORE STYLING ROUTING
        # ==========================================
        if is_critical_failure:
            test_embed.title = "FALHA CRÍTICA!"
            test_embed.color = discord.Color.brand_red()
        elif is_success:
            if is_critical_success:
                test_embed.title = "SUCESSO DECISIVO!"
                test_embed.color = discord.Color.gold()
            else:
                test_embed.title = "SUCESSO!"
                test_embed.color = discord.Color.green()
        else:
            test_embed.title = "FALHA"
            test_embed.color = discord.Color.red()

        # Construction of the presentation embed matrix
        test_embed.add_field(
            name="Parada de Dados", value=f"`{dices} = {dice_pool}`", inline=False
        )

        modificador_sign = "+" if modificador >= 0 else "-"
        test_embed.add_field(
            name="Nível de Habilidade",
            value=f"NH Básico: {nh}\nModificador: {modificador}\n`NH Efetivo: {effective_sl}` -> {nh} {modificador_sign} {abs(modificador)}",
            inline=False,
        )

        # Evaluating margins based on clean boolean state instead of string title lookups
        if is_success:
            margin_of_victory = effective_sl - dice_pool
            test_embed.add_field(
                name="Margem de Vitória",
                value=f"`{effective_sl} - {dice_pool} = {margin_of_victory}`",
                inline=False,
            )
        else:
            margin_of_defeat = dice_pool - effective_sl
            test_embed.add_field(
                name="Margem de Derrota",
                value=f"`{dice_pool} - {effective_sl} = {margin_of_defeat}`",
                inline=False,
            )

        # Character visual asset extraction using the payload wrapper
        character_file, thumbnail_url = get_character_thumbnail_payload(
            self.db_connection, player_id
        )

        if thumbnail_url:
            test_embed.set_thumbnail(url=thumbnail_url)

        # Strict conditional dispatch protecting network payload against NoneType serialization
        if character_file is not None:
            await interaction.followup.send(embed=test_embed, file=character_file)
        else:
            await interaction.followup.send(embed=test_embed)

    # qkd Command
    @app_commands.command(description="Realiza uma disputá Rápida de habilidades")
    @app_commands.describe(
        nh1="Seu NH",
        modificador1="Seus modificadores de dificuldade",
        nh2="Nh do seu adversário",
        modificador2="Modificadores de dificuldade do seu adversário",
    )
    async def qkd(
        self,
        interaction: discord.Interaction,
        nh1: int,
        modificador1: int,
        nh2: int,
        modificador2: int,
    ):
        """
        Resolves a generic GURPS Quick Contest between two effective skill levels.
        Enforces immediate network deferral to shield against quick_dispute execution latency.
        """
        # CRITICAL AXIOM: Instant network token preservation to prevent 3-second timeouts
        await interaction.response.defer(ephemeral=False)

        player_id = interaction.user.id

        effective_sl1 = nh1 + modificador1
        effective_sl2 = nh2 + modificador2

        # Invoking the core relational dispute logic mapping
        result = quick_dispute(player_id, effective_sl1, effective_sl2)

        dice_pool1 = result["result1"]["dice_pool1"]
        success_roll1 = result["result1"]["success_roll1"]
        margin1 = result["result1"]["margin1"]
        dices1 = result["result1"]["dices1"]

        dice_pool2 = result["result2"]["dice_pool2"]
        success_roll2 = result["result2"]["success_roll2"]
        margin2 = result["result2"]["margin2"]
        dices2 = result["result2"]["dices2"]

        # Embed instantiation
        qkd_embed = discord.Embed()

        # ==========================================
        # CONTEST RESOLUTION STATE MACHINE
        # ==========================================
        if success_roll1 is True and success_roll2 is False:
            qkd_embed.title = "SUCESSO POR ROLAGEM!"
            qkd_embed.description = (
                "Você obteve um sucesso no teste e seu oponente um fracasso."
            )
            qkd_embed.color = discord.Color.green()

        elif success_roll1 is False and success_roll2 is True:
            qkd_embed.title = "FRACASSO POR ROLAGEM!"
            qkd_embed.description = (
                "Você obteve um fracasso no teste e seu oponente um sucesso."
            )
            qkd_embed.color = discord.Color.red()

        elif margin1 > margin2:
            qkd_embed.title = "SUCESSO POR MARGEM DE TESTE!"
            qkd_embed.color = discord.Color.green()
            qkd_embed.description = "Resultado decidido pela margem do teste."

        elif margin1 == margin2:
            qkd_embed.title = "EMPATE!"
            qkd_embed.color = discord.Color.dark_gray()
            qkd_embed.description = (
                "A disputa terminou em um equilíbrio absoluto de margens."
            )

        else:
            qkd_embed.title = "FRACASSO POR MARGEM DE TESTE!"
            qkd_embed.color = discord.Color.red()
            qkd_embed.description = "Resultado decidido pela margem do teste."

        # Generating dynamic signs for presentation cleanliness
        sign1 = "+" if modificador1 >= 0 else "-"
        sign2 = "+" if modificador2 >= 0 else "-"
        margin_difference = margin1 - margin2

        qkd_embed.add_field(
            name="Você",
            value=(
                f"`Dados: {dices1} = {dice_pool1}`\n"
                f"NH Base: {nh1}\n"
                f"Modificador: {modificador1}\n"
                f"`NH Efetivo: {effective_sl1}` -> {nh1} {sign1} {abs(modificador1)}\n"
                f"Sucesso: {'Sim' if success_roll1 else 'Não'}\n"
                f"`Margem: {margin1}`"
            ),
            inline=False,
        )
        qkd_embed.add_field(
            name="Oponente",
            value=(
                f"`Dados: {dices2} = {dice_pool2}`\n"
                f"NH Base: {nh2}\n"
                f"Modificador: {modificador2}\n"
                f"`NH Efetivo: {effective_sl2}` -> {nh2} {sign2} {abs(modificador2)}\n"
                f"Sucesso: {'Sim' if success_roll2 else 'Não'}\n"
                f"`Margem: {margin2}`"
            ),
            inline=False,
        )
        qkd_embed.add_field(
            name="Diferença das Margens de Sucesso",
            value=f"`{margin1} - ({margin2}) = {margin_difference}`",
            inline=False,
        )

        # Character visual asset extraction using the payload wrapper
        character_file, thumbnail_url = get_character_thumbnail_payload(
            self.db_connection, player_id
        )

        if thumbnail_url:
            qkd_embed.set_thumbnail(url=thumbnail_url)

        # Strict conditional dispatch protecting network payload against NoneType serialization
        if character_file is not None:
            await interaction.followup.send(embed=qkd_embed, file=character_file)
        else:
            await interaction.followup.send(embed=qkd_embed)


async def setup(bot: commands.Bot):
    """
    Mandatory asynchronous entry point to load the extension.
    """
    await bot.add_cog(Skill_tests(bot))
