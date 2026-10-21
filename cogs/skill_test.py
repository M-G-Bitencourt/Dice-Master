import discord
from discord import app_commands
from discord.ext import commands

from random import randint
from pathlib import Path
import sqlite3

from utils.dice_mechanics import consume_deterministic_fate
from utils.dice_mechanics import hdm_dices
from utils.test_mechanics import build_quick_dispute_result, quick_dispute
from utils.db_functions import get_character_profile, get_character_thumbnail_payload
from utils.i18n import t as tr
from utils.gm_dice import select_dice_for_outcome, select_quick_contest_dice
from utils.gm_directives import gm_shield_store
from utils.locale_service import apply_interaction_locale


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
    @app_commands.command(description="Perform a skill test.")
    @app_commands.rename(nh="skill_level")
    @app_commands.describe(
        nh="Your effective skill level.",
    )
    async def test(self, interaction: discord.Interaction, nh: int):
        """
        Resolves a foundational GURPS 3d6 success test against an effective skill level.
        Enforces immediate network deferral to shield the execution window against transaction latency.
        """
        apply_interaction_locale(interaction, self.db_connection)

        # CRITICAL AXIOM: Instant network token preservation to prevent 3-second timeouts
        await interaction.response.defer(ephemeral=False)

        player_id = interaction.user.id

        # Structural safeguard: Effective Skill Level cannot collapse below absolute zero
        effective_sl = nh
        if effective_sl < 0:
            effective_sl = 0

        character_id = None
        try:
            character_id = get_character_profile(
                self.db_connection, player_id
            )["character_id"]
        except ValueError:
            character_id = None

        directive = gm_shield_store.consume(
            character_id=character_id,
            player_id=player_id,
            roll_kind="skill_test",
        )
        pending_fate = (
            None
            if directive is not None
            else consume_deterministic_fate(player_id, self.db_connection)
        )

        if directive is not None:
            dices = select_dice_for_outcome(effective_sl, directive.outcome)
        elif pending_fate is not None:
            dices = hdm_dices(nh=effective_sl, fate=pending_fate)
        else:
            dices = [randint(1, 6) for _ in range(3)]

        dice_pool = sum(dices)

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
            test_embed.title = tr("CRITICAL FAILURE!")
            test_embed.color = discord.Color.brand_red()
        elif is_success:
            if is_critical_success:
                test_embed.title = tr("CRITICAL SUCCESS!")
                test_embed.color = discord.Color.gold()
            else:
                test_embed.title = tr("SUCCESS!")
                test_embed.color = discord.Color.green()
        else:
            test_embed.title = tr("FAILURE")
            test_embed.color = discord.Color.red()

        # Construction of the presentation embed matrix
        test_embed.add_field(
            name=tr("Dice Pool"), value=f"`{dices} = {dice_pool}`", inline=False
        )

        test_embed.add_field(
            name=tr("Skill Level"),
            value=f"`{tr('Effective Skill')}: {effective_sl}`",
            inline=False,
        )

        # Evaluating margins based on clean boolean state instead of string title lookups
        if is_success:
            margin_of_victory = effective_sl - dice_pool
            test_embed.add_field(
                name=tr("Margin of Victory"),
                value=f"`{effective_sl} - {dice_pool} = {margin_of_victory}`",
                inline=False,
            )
        else:
            margin_of_defeat = dice_pool - effective_sl
            test_embed.add_field(
                name=tr("Margin of Defeat"),
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
    @app_commands.command(description="Resolve a quick contest and return the winner.")
    @app_commands.rename(nh1="attacker_skill", nh2="defender_skill")
    @app_commands.describe(
        nh1="Your skill level.",
        nh2="Your opponent's skill level.",
    )
    async def qkd(
        self,
        interaction: discord.Interaction,
        nh1: int,
        nh2: int,
    ):
        """
        Resolves a generic GURPS Quick Contest between two effective skill levels.
        Enforces immediate network deferral to shield against quick_dispute execution latency.
        """
        apply_interaction_locale(interaction, self.db_connection)

        # CRITICAL AXIOM: Instant network token preservation to prevent 3-second timeouts
        await interaction.response.defer(ephemeral=False)

        player_id = interaction.user.id

        effective_sl1 = nh1
        effective_sl2 = nh2

        character_id = None
        try:
            character_id = get_character_profile(
                self.db_connection, player_id
            )["character_id"]
        except ValueError:
            character_id = None

        directive = gm_shield_store.consume(
            character_id=character_id,
            player_id=player_id,
            roll_kind="quick_contest",
        )
        if directive is not None:
            dices1, dices2 = select_quick_contest_dice(
                effective_sl1, effective_sl2, directive.outcome
            )
            result = build_quick_dispute_result(
                dices1, dices2, effective_sl1, effective_sl2
            )
        else:
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
            qkd_embed.title = tr("SUCCESS BY ROLL!")
            qkd_embed.description = tr(
                "You succeeded on the test and your opponent failed."
            )
            qkd_embed.color = discord.Color.green()

        elif success_roll1 is False and success_roll2 is True:
            qkd_embed.title = tr("FAILURE BY ROLL!")
            qkd_embed.description = tr(
                "You failed the test and your opponent succeeded."
            )
            qkd_embed.color = discord.Color.red()

        elif margin1 > margin2:
            qkd_embed.title = tr("SUCCESS BY MARGIN!")
            qkd_embed.color = discord.Color.green()
            qkd_embed.description = tr("The result was decided by the test margin.")

        elif margin1 == margin2:
            qkd_embed.title = tr("TIE!")
            qkd_embed.color = discord.Color.dark_gray()
            qkd_embed.description = tr(
                "The contest ended in an exact tie of margins."
            )

        else:
            qkd_embed.title = tr("FAILURE BY MARGIN!")
            qkd_embed.color = discord.Color.red()
            qkd_embed.description = tr("The result was decided by the test margin.")

        # Generating dynamic signs for presentation cleanliness
        margin_difference = margin1 - margin2

        qkd_embed.add_field(
            name=tr("You"),
            value=(
                f"`{tr('Dice')}: {dices1} = {dice_pool1}`\n"
                f"`{tr('Effective Skill')}: {effective_sl1}`\n"
                f"{tr('Success')}: {tr('Yes') if success_roll1 else tr('No')}\n"
                f"`{tr('Margin')}: {margin1}`"
            ),
            inline=False,
        )
        qkd_embed.add_field(
            name=tr("Opponent"),
            value=(
                f"`{tr('Dice')}: {dices2} = {dice_pool2}`\n"
                f"`{tr('Effective Skill')}: {effective_sl2}`\n"
                f"{tr('Success')}: {tr('Yes') if success_roll2 else tr('No')}\n"
                f"`{tr('Margin')}: {margin2}`"
            ),
            inline=False,
        )
        qkd_embed.add_field(
            name=tr("Margin Difference"),
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
