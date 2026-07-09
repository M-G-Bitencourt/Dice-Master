# LIBRARIES =====================================================
# Discord Libraries
import discord
from discord.ext import commands

# Other Libraries
import configparser
import sqlite3
from pathlib import Path

# ===============================================================

# CONFIGURATIONS ===============================================================================================================
# Configparser --------------------------------------------------
config = configparser.ConfigParser()  # init
config.read("config.ini")  # Definition of the configuration file


# Bot Class
class DiceMasterBot(commands.Bot):
    """
    Custom Discord bot implementation for the Dice Master system.

    This subclass extends commands.Bot to enforce architectural discipline,
    proper dependency injection, and correct asynchronous lifecycle management.

    Justification for Subclassing:
    ------------------------------
    A custom subclass is strictly mandatory due to two architectural requirements:

    1. State and Dependency Injection:
       By overriding the constructor (__init__), the class securely binds an external
       configuration object (bot_config) to self.config at instantiation time. This
       guarantees that vital parameters (such as 'DM_ID') are available in memory before any peripheral module is initialized, preventing runtime AttributeError anomalies
       within Cog constructors.

    2. Asynchronous Lifecycle Orchestration:
       By overriding setup_hook(), the bot gains an isolated, single-execution asynchronous
       window to load extensions via self.load_extension() before the WebSocket connection
       to the Discord gateway is established. This effectively prevents the dangerous
       anti-pattern of loading extensions inside on_ready(), which is highly volatile and
       subject to recurrent triggers during gateway reconnections.
    """

    def __init__(self, command_prefix, intents, bot_config):
        super().__init__(command_prefix=command_prefix, intents=intents)
        self.config = bot_config

    async def setup_hook(self):
        """
        Load extensions strictly inside the setup_hook, NEVER in on_ready.
        """
        extensions = [
            "cogs.battle",
            "cogs.deterministic_mock",
            "cogs.other_tests",
            "cogs.skill_test",
        ]

        for extension in extensions:
            try:
                await self.load_extension(extension)
                print(f"Successfully loaded: {extension}")
            except Exception as e:
                print(f"Failed to load {extension}: {e}")

    async def on_ready(self):
        print(f"Logged in as {self.user} (ID: {self.user.id})")


# Definition of permissions
intents = discord.Intents.default()
intents.message_content = True
bot = DiceMasterBot(
    command_prefix=config["BOT"]["Prefix"], intents=intents, bot_config=config
)  # The config['BOT']['Prefix'] defines the bot command prefix


# Init sql database
def initialize_system_database() -> None:
    """
    Validates the existence of the SQLite binary file. If absent, it constructs
    the database dynamically by reading and executing the DDL instructions
    from the initialization script.
    """
    # Defining the structural paths using the modern pathlib module
    base_directory = Path("data")
    binary_db_path = base_directory / "database.db"
    sql_schema_path = base_directory / "init.sql"

    # Step 1: Guarantee the directory topology exists before any file operation
    base_directory.mkdir(parents=True, exist_ok=True)

    # Step 2: Validate the existence of the binary database file
    if not binary_db_path.exists():

        # It is a fatal architectural error if the schema script is also missing
        if not sql_schema_path.exists():
            raise FileNotFoundError(
                f"Initialization aborted: The required DDL script '{sql_schema_path}' "
                "is missing from the filesystem."
            )

        # Step 3: Read the schema instructions and instantiate the database
        with open(sql_schema_path, "r", encoding="utf-8") as schema_file:
            schema_instructions = schema_file.read()

        with sqlite3.connect(binary_db_path) as connection:
            cursor = connection.cursor()
            cursor.executescript(schema_instructions)
            connection.commit()


# NORMAL COMMANDS ==================================================
# Sync command
@bot.command(name="sync")
@commands.is_owner()  # Ensures that only the bot owner can run this command
async def sync(ctx):
    try:
        syncs = await bot.tree.sync()
        await ctx.reply(f"{len(syncs)} Commands successfully synchronized")

    except Exception as e:
        await ctx.reply(f"Commands not synchronized {e}")


# Run the Bot
initialize_system_database()
bot.run(config["BOT"]["Token"])
