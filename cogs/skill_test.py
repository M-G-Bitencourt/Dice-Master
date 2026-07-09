import discord
from discord import app_commands
from discord.ext import commands

from random import randint

from utils.dice_mechanics import consume_deterministic_fate
from utils.dice_mechanics import hdm_dices
from utils.test_mechanics import quick_dispute


class Skill_tests(commands.Cog):
    """ """

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # Test Command
    @app_commands.command(description="Realiza os testes de Habilidade")
    @app_commands.describe(
        nh="Seu Nível de Habilidade na perícia",
        modificador="Modificador de Dificuldade",
    )
    async def test(self, interact: discord.Interaction, nh: int, modificador: int):

        player_id = interact.user.id

        # Dice Roll
        pending_fate = consume_deterministic_fate(player_id)

        if pending_fate is not None:
            dices = hdm_dices(nh=nh, fate=pending_fate)
        else:
            dices = [randint(1, 6) for _ in range(3)]

        dice_pool = sum(dices)
        effective_nh = nh + modificador

        if effective_nh < 0:  # Ensures effective NH is never less than 0
            effective_nh = 0

        # Embeds
        test_embed = discord.Embed()

        # Validation of success
        if dice_pool == 18:  # Verification of critical failures
            test_embed.title = "FALHA CRÍTICA!"
            test_embed.color = discord.Color.brand_red()

        elif dice_pool == 17:  # Verification of critical failures
            if effective_nh <= 15:
                test_embed.title = "FALHA CRÍTICA!"
                test_embed.color = discord.Color.brand_red()
            else:
                test_embed.title = "FALHA"
                test_embed.color = discord.Color.red()

        elif dice_pool <= effective_nh:  # If the roll was a success
            if dice_pool <= 4:
                test_embed.title = "SUCESSO DECISIVO!"
                test_embed.color = discord.Color.gold()

            else:
                if (
                    effective_nh - dice_pool >= 10
                ):  # Checks if the margin of success is 10 or greater
                    test_embed.title = "SUCESSO DECISIVO!"
                    test_embed.color = discord.Color.gold()

                else:
                    test_embed.title = "SUCESSO!"
                    test_embed.color = discord.Color.green()

        else:  # If the roll was not a success
            if (
                dice_pool - effective_nh >= 10
            ):  # Checks if the margin of failure is 10 or greater
                test_embed.title = "FALHA CRÍTICA!"
                test_embed.color = discord.Color.brand_red()
            else:
                test_embed.title = "FALHA"
                test_embed.color = discord.Color.red()

        # construction of the emdice_countbed
        test_embed.add_field(
            name="Parada de Dados", value=f"`{dices} = {dice_pool}`", inline=False
        )
        test_embed.add_field(
            name="Nível de Habilidade",
            value=f"NH Basico: {nh}\nModificador: {modificador}\n`NH Efetivo: {effective_nh}`",
            inline=False,
        )

        if test_embed.title == "SUCESSO DECISIVO!" or test_embed.title == "SUCESSO!":
            test_embed.add_field(
                name="Margem de Vitória",
                value=f"{effective_nh} - {dice_pool} = {effective_nh - dice_pool}",
                inline=False,
            )
        else:
            test_embed.add_field(
                name="Margem de Derrota",
                value=f"{dice_pool} - {effective_nh} = {dice_pool - effective_nh}",
                inline=False,
            )

        await interact.response.send_message(embed=test_embed)

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
        interact: discord.Interaction,
        nh1: int,
        modificador1: int,
        nh2: int,
        modificador2: int,
    ):

        player_id = interact.user.id

        effective_nh1 = nh1 + modificador1
        effective_nh2 = nh2 + modificador2

        result = quick_dispute(player_id, effective_nh1, effective_nh2)

        dice_pool1 = result["result1"]["dice_pool1"]
        success_roll1 = result["result1"]["success_roll1"]
        margin1 = result["result1"]["margin1"]
        dices1 = result["result1"]["dices1"]

        dice_pool2 = result["result2"]["dice_pool2"]
        success_roll2 = result["result2"]["success_roll2"]
        margin2 = result["result2"]["margin2"]
        dices2 = result["result2"]["dices2"]

        # Embed
        qkd_embed = discord.Embed()

        if success_roll1 is True and success_roll2 is False:
            qkd_embed.title = "SUCESSO POR ROLAGEM!"
            qkd_embed.description = (
                "Você obteve um sucesso no teste e seu oponente um fracasso"
            )
            qkd_embed.color = discord.Color.green()

        elif success_roll1 is False and success_roll2 is True:
            qkd_embed.title = "FRACASSO POR ROLAGEM!"
            qkd_embed.description = (
                "Você obteve um fracasso no teste e seu oponente um sucesso"
            )
            qkd_embed.color = discord.Color.red()

        elif margin1 > margin2:
            qkd_embed.title = "SUCESSO POR MARGEM DE TESTE!"
            qkd_embed.color = discord.Color.green()
            qkd_embed.description = "Resultado decidido pela margem do teste."

        elif margin1 == margin2:
            qkd_embed.title = "EMPATE!"
            qkd_embed.color = discord.Color.greyple()
            qkd_embed.description = "Empate"

        else:
            qkd_embed.title = "FRACASSO POR MARGEM DE TESTE!"
            qkd_embed.color = discord.Color.red()
            qkd_embed.description = "Resultado decidido pela margem do teste."

        qkd_embed.add_field(
            name="Você",
            value=f"`Dados: {dices1} = {dice_pool1}`\nNH Base: {nh1}\nModificador: {modificador1}\n`NH Efetivo: {effective_nh1}`\nSucesso: {"Sim" if success_roll1 is True else "Não"}\n`Margem: {margin1}`",
            inline=False,
        )
        qkd_embed.add_field(
            name="Oponente",
            value=f"`Dados: {dices2} = {dice_pool2}`\nNH Base: {nh2}\nModificador: {modificador2}\n`NH Efetivo: {effective_nh2}`\nSucesso: {"Sim" if success_roll2 is True else "Não"}\n`Margem: {margin2}`",
            inline=False,
        )
        qkd_embed.add_field(
            name="Diferença das Margens de Sucesso",
            value=f"`{margin1} - ({margin2}) = {margin1 - margin2}`",
            inline=False,
        )

        await interact.response.send_message(embed=qkd_embed)


async def setup(bot: commands.Bot):
    """
    Mandatory asynchronous entry point to load the extension.
    """
    await bot.add_cog(Skill_tests(bot))
