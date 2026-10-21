import discord
from discord import app_commands
from discord.ext import commands

from random import randint
from pathlib import Path
import sqlite3

from utils.dice_mechanics import consume_deterministic_fate
from utils.dice_mechanics import hdm_dices
from utils.db_functions import (
    get_character_thumbnail_payload,
    get_optional_character_id,
)
from utils.i18n import t as tr
from utils.gm_dice import (
    select_dice_for_outcome,
    select_preset_dice,
    select_reaction_dice,
)
from utils.gm_directives import gm_shield_store
from utils.locale_service import apply_interaction_locale


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
        description="Roll a number of d6 and apply a modifier."
    )
    @app_commands.rename(num_dados="dice_count", modificador="modifier")
    @app_commands.describe(
        num_dados="Number of dice to roll.",
        modificador="Modifier applied to the total.",
    )
    async def roll(
        self, interact: discord.Interaction, num_dados: int, modificador: int
    ):
        apply_interaction_locale(interact, self.db_connection)

        character_id = get_optional_character_id(
            self.db_connection, interact.user.id
        )
        directive = gm_shield_store.consume(
            character_id=character_id,
            player_id=interact.user.id,
            roll_kind="generic_roll",
        )

        if directive is not None and num_dados > 0:
            dices, total = select_preset_dice(
                num_dados,
                modificador,
                str(directive.payload.get("preset", "average")),
                directive.payload.get("exact_total"),
            )
            dice_pool = sum(dices)
        else:
            dices = [randint(1, 6) for _ in range(max(0, num_dados))]
            dice_pool = sum(dices)
            total = dice_pool + modificador

        # Embed
        roll_embed = discord.Embed()

        roll_embed.title = tr("ROLL")
        roll_embed.color = discord.Color.green()
        roll_embed.add_field(
            name=tr("Roll"),
            value=f"`{tr('Dice')}: {dices} = {dice_pool}`\n{tr('Modifier')}: {modificador}\n\n**{tr('Total')}:** {total}",
        )

        await interact.response.send_message(embed=roll_embed)

    # Reaction Test ---------------------------------------------------
    @app_commands.command(
        name="react",
        description="Roll a reaction test using the GURPS reaction table.",
    )
    @app_commands.describe(
        modifier="Sum of active reaction modifiers on the character."
    )
    async def react(self, interaction: discord.Interaction, modifier: int):
        """
        Resolves a GURPS Reaction Test, handling deterministic fate constraints.
        Enforces immediate network deferral to guarantee safety against while-loop execution spikes.
        """
        apply_interaction_locale(interaction, self.db_connection)

        # CRITICAL AXIOM: Securing the network payload token before processing database and RNG loops
        await interaction.response.defer(ephemeral=False)

        player_id = interaction.user.id
        character_id = get_optional_character_id(
            self.db_connection, player_id
        )
        directive = gm_shield_store.consume(
            character_id=character_id,
            player_id=player_id,
            roll_kind="reaction",
        )

        # Processing transient database state
        fate = (
            None
            if directive is not None
            else consume_deterministic_fate(player_id, self.db_connection)
        )

        if directive is not None:
            dices = select_reaction_dice(modifier, directive.outcome)
        elif fate is not None:
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
            react_embed.title = tr("DISASTROUS REACTION")
            react_embed.color = discord.Color.red()
        elif total_score <= 3:
            react_embed.title = tr("VERY BAD REACTION")
            react_embed.color = discord.Color.red()
        elif total_score <= 6:
            react_embed.title = tr("BAD REACTION")
            react_embed.color = discord.Color.orange()
        elif total_score <= 9:
            react_embed.title = tr("WEAK REACTION")
            react_embed.color = discord.Color.yellow()
        elif total_score <= 12:
            react_embed.title = tr("NEUTRAL REACTION")
            react_embed.color = discord.Color.greyple()
        elif total_score <= 15:
            react_embed.title = tr("GOOD REACTION")
            react_embed.color = discord.Color.green()
        elif total_score <= 18:
            react_embed.title = tr("VERY GOOD REACTION")
            react_embed.color = discord.Color.green()
        else:
            react_embed.title = tr("EXCELLENT REACTION")
            react_embed.color = discord.Color.blue()

        react_embed.add_field(
            name=tr("Roll Metrics"),
            value=f"`{tr('Dice')}: {dices} = {dice_pool}`\n{tr('Modifier')}: `{modifier:+d}`\n\n**{tr('Final Result')}: {total_score}**",
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
    @app_commands.command(description="Perform a panic check.")
    @app_commands.rename(vontade="will", modificador="modifier")
    @app_commands.describe(
        vontade="Your Will score.",
        modificador="Sum of difficulty modifiers.",
    )
    async def panic(
        self, interaction: discord.Interaction, vontade: int, modificador: int
    ):
        """
        Resolves a GURPS Fright Check, evaluating panic table thresholds upon failure.
        Enforces immediate network token preservation to prevent interface timeouts.
        """
        apply_interaction_locale(interaction, self.db_connection)

        # CRITICAL AXIOM: Immediate network token preservation.
        # Extends the interaction lifecycle to 15 minutes before any processing occurs.
        await interaction.response.defer(ephemeral=False)

        player_id = interaction.user.id
        effective_sl = max(0, vontade + modificador)
        character_id = get_optional_character_id(
            self.db_connection, player_id
        )
        directive = gm_shield_store.consume(
            character_id=character_id,
            player_id=player_id,
            roll_kind="panic",
        )

        # Database transaction: consuming transient fate state
        pending_fate = (
            None
            if directive is not None
            else consume_deterministic_fate(player_id, self.db_connection)
        )

        if directive is not None:
            dices = select_dice_for_outcome(effective_sl, directive.outcome)
        elif pending_fate is not None:
            dices = hdm_dices(nh=vontade, fate=pending_fate)
        else:
            dices = [randint(1, 6) for _ in range(3)]

        dice_pool = sum(dices)

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
            panic_embed.title = tr("RESISTED PANIC")
            panic_embed.color = (
                discord.Color.gold() if is_critical_success else discord.Color.green()
            )

            modificador_sign = "+" if modificador >= 0 else "-"
            margin_of_victory = effective_sl - dice_pool

            panic_embed.add_field(
                name=tr("Dice Pool"), value=f"`{dices} = {dice_pool}`", inline=False
            )
            panic_embed.add_field(
                name=tr("Will Level"),
                value=f"{tr('Base Skill')}: {vontade}\n{tr('Modifier')}: {modificador}\n`{tr('Effective Skill')}: {effective_sl}` -> {vontade} {modificador_sign} {abs(modificador)}",
                inline=False,
            )
            panic_embed.add_field(
                name=tr("Margin of Victory"),
                value=f"`{effective_sl} - {dice_pool} = {margin_of_victory}`",
                inline=False,
            )
        else:
            panic_embed.title = tr("SUCCUMBED TO PANIC")
            panic_embed.color = (
                discord.Color.brand_red()
                if is_critical_failure
                else discord.Color.red()
            )

            # Executing secondary panic metrics calculation (3d6 + failure margin)
            table_directive = gm_shield_store.consume(
                character_id=character_id,
                player_id=player_id,
                roll_kind="panic_table",
            )
            if table_directive is not None:
                panic_dices, panic_total = select_preset_dice(
                    3,
                    0,
                    str(table_directive.payload.get("preset", "average")),
                    table_directive.payload.get("exact_total"),
                )
                panic_dice_pool = panic_total
            else:
                panic_dices = [randint(1, 6) for _ in range(3)]
                panic_dice_pool = sum(panic_dices)
            failure_margin = dice_pool - effective_sl

            # GURPS Axiom: Critical failures automatically add a flat +10 penalty to the panic roll
            if is_critical_failure:
                panic_value = panic_dice_pool + failure_margin + 10
                critical_notice = "\n" + tr(
                    "**[CRITICAL FAILURE: +10 added to the final result!]**"
                )
            else:
                panic_value = panic_dice_pool + failure_margin
                critical_notice = ""

            panic_embed.description = tr(
                "The panic consequence table is in the Basic Set, p. 361."
            ) + critical_notice

            panic_embed.add_field(
                name=tr("Failure Metrics"),
                value=f"{tr('Test Dice')}: `{dices} = {dice_pool}`\n{tr('Failure Margin')}: `{failure_margin}`",
                inline=False,
            )
            panic_embed.add_field(
                name=tr("Panic Table Roll"),
                value=f"{tr('Dice')}: `{panic_dices} = {panic_dice_pool}`\n**{tr('Final Panic Value')}:** `{panic_value}`",
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
