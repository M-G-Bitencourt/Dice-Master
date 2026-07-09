import discord
from discord import app_commands
from discord.ext import commands

from random import randint

from utils.dice_mechanics import consume_deterministic_fate
from utils.dice_mechanics import hdm_dices


class Other_tests(commands.Cog):
    """ """

    def __init__(self, bot: commands.Bot):
        self.bot = bot

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
    @app_commands.command(description="Realiza a rolagem de um teste de reação")
    @app_commands.describe(modificador="Soma dos modificadores de reação que você tem")
    async def react(self, interact: discord.Interaction, modificador: int):
        player_id = interact.user.id

        # The first part of the if-block validates whether the user is included in the
        # `pending_controls` dictionary. If so, it initiates the validation of which "fate"
        # was chosen by the DM and returns a matching result. The second part runs the dice
        # selection normally.
        fate = consume_deterministic_fate(player_id)

        if fate is not None:

            # Safeguards: The minimum and maximum that 3d6 can roll with the current modifier
            min_possible = 3 + modificador
            max_possible = 18 + modificador

            if fate == 0:  # Sucesso (Total between 10 and 15)
                if max_possible < 10:
                    dices = [6, 6, 6]
                elif min_possible > 15:
                    dices = [1, 1, 1]
                else:
                    while True:
                        dices = [randint(1, 6) for _ in range(3)]
                        if 10 <= sum(dices) + modificador <= 15:
                            break

            elif fate == 1:  # Fracasso (Total between 4 and 9)
                if max_possible < 4:
                    dices = [6, 6, 6]
                elif min_possible > 9:
                    dices = [1, 1, 1]
                else:
                    while True:
                        dices = [randint(1, 6) for _ in range(3)]
                        if 4 <= sum(dices) + modificador <= 9:
                            break

            elif fate == 2:  # Sucesso Decisivo (Total 16 or more)
                if max_possible < 16:
                    dices = [6, 6, 6]
                else:
                    while True:
                        dices = [randint(1, 6) for _ in range(3)]
                        if sum(dices) + modificador >= 16:
                            break

            else:  # Fracasso Decisivo (Total 3 or less)
                if min_possible > 3:
                    dices = [1, 1, 1]
                else:
                    while True:
                        dices = [randint(1, 6) for _ in range(3)]
                        if sum(dices) + modificador <= 3:
                            break

        else:
            dices = [randint(1, 6) for _ in range(3)]

        dice_pool = sum(dices)
        total = dice_pool + modificador

        # Embeds
        react_embed = discord.Embed()

        if total <= 0:
            react_embed.title = "REAÇÃO DESASTROSA"
            react_embed.color = discord.Color.red()
        elif total <= 3:
            react_embed.title = "REAÇÃO MUITO RUIM"
            react_embed.color = discord.Color.red()
        elif total <= 6:
            react_embed.title = "REAÇÃO RUIM"
            react_embed.color = discord.Color.orange()
        elif total <= 9:
            react_embed.title = "REAÇÃO FRACA"
            react_embed.color = discord.Color.yellow()
        elif total <= 12:
            react_embed.title = "REAÇÃO NEUTRA"
            react_embed.color = discord.Color.greyple()
        elif total <= 15:
            react_embed.title = "REAÇÃO BOA"
            react_embed.color = discord.Color.green()
        elif total <= 18:
            react_embed.title = "REAÇÃO MUITO BOA"
            react_embed.color = discord.Color.green()
        else:
            react_embed.title = "REAÇÃO EXCELENTE"
            react_embed.color = discord.Color.blue()

        react_embed.add_field(
            name="Dados",
            value=f"`Dados: {dices} = {dice_pool}`\nModificador: {modificador}\n\n**Total: {total}**",
            inline=False,
        )

        await interact.response.send_message(embed=react_embed)

    # Panic -----------------------------------------------------------
    @app_commands.command(description="Realiza uma verificação de Pânico")
    @app_commands.describe(
        vontade="Seu Valor de Vontade",
        modificador="Soma dos modificadores de dificuldade",
    )
    async def panic(
        self, interact: discord.Interaction, vontade: int, modificador: int
    ):
        player_id = interact.user.id

        # Dice Roll
        pending_fate = consume_deterministic_fate(player_id)

        if pending_fate is not None:
            dices = hdm_dices(nh=vontade, fate=pending_fate)

        else:
            dices = [randint(1, 6) for _ in range(3)]

        dice_pool = sum(dices)
        effective_nh = vontade + modificador

        if effective_nh < 0:  # Ensures effective NH is never less than 0
            effective_nh = 0

        # Embeds
        panic_embed = discord.Embed()

        # Validation of success
        if dice_pool == 18:  # Verification of critical failures
            panic_embed.title = "FALHA CRÍTICA!"
            panic_embed.color = discord.Color.brand_red()

        elif dice_pool == 17:  # Verification of critical failures
            if effective_nh <= 15:
                panic_embed.title = "FALHA CRÍTICA!"
                panic_embed.color = discord.Color.brand_red()
            else:
                panic_embed.title = "FALHA"
                panic_embed.color = discord.Color.red()

        elif dice_pool <= effective_nh:  # If the roll was a success
            if dice_pool <= 4:
                panic_embed.title = "SUCESSO DECISIVO!"
                panic_embed.color = discord.Color.gold()

            else:
                if (
                    effective_nh - dice_pool >= 10
                ):  # Checks if the margin of success is 10 or greater
                    panic_embed.title = "SUCESSO DECISIVO!"
                    panic_embed.color = discord.Color.gold()

                else:
                    panic_embed.title = "SUCESSO!"
                    panic_embed.color = discord.Color.green()

        else:  # If the roll was not a success
            if (
                dice_pool - effective_nh >= 10
            ):  # Checks if the margin of failure is 10 or greater
                panic_embed.title = "FALHA CRÍTICA!"
                panic_embed.color = discord.Color.brand_red()
            else:
                panic_embed.title = "FALHA"
                panic_embed.color = discord.Color.red()

        if panic_embed.title == "SUCESSO DECISIVO!" or panic_embed.title == "SUCESSO!":
            # construction of the emdice_countbed
            panic_embed.title = "RESISTIU AO PÂNICO"
            panic_embed.add_field(
                name="Parada de Dados", value=f"`{dices} = {dice_pool}`", inline=False
            )
            panic_embed.add_field(
                name="Nível de Vontade",
                value=f"NH Basico: {vontade}\nModificador: {modificador}\n`NH Efetivo: {effective_nh}`",
                inline=False,
            )
            panic_embed.add_field(
                name="Margem de Vitória",
                value=f"{effective_nh} - {dice_pool} = {effective_nh - dice_pool}",
                inline=False,
            )
        else:
            panic_embed.title = "SUCUMBIU AO PÂNICO"
            dices_panic = [randint(1, 6) for _ in range(3)]
            dice_pool_panic = sum(dices_panic)

            panic_value = dice_pool_panic + (dice_pool - effective_nh)

            panic_embed.description = (
                "Tabela de pânico pode ser encontrada em GURPS Módulo Básico Pág: 361"
            )
            panic_embed.add_field(
                name="Valor do teste de Pânico",
                value=panic_value,
                inline=False,
            )

        await interact.response.send_message(embed=panic_embed)


async def setup(bot: commands.Bot):
    """
    Mandatory asynchronous entry point to load the extension.
    """
    await bot.add_cog(Other_tests(bot))
