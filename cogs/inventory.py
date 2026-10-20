from pathlib import Path
import sqlite3
import discord
from discord import app_commands
from discord.ext import commands

from utils.ansi import (
    ACCENT_COLOR,
    DANGER_COLOR,
    INFO_COLOR,
    LABEL_COLOR,
    MODE_COLOR,
    NEUTRAL_COLOR,
    SUCCESS_COLOR,
    WARN_COLOR,
    ansi,
    clamp_code_block,
    code_block,
    sanitize,
)
from utils.db_functions import (
    get_character_inventory_data,
    get_character_strength,
    get_character_thumbnail_by_id,
)
from utils.i18n import (
    catalog_label,
    catalog_label_from_value,
    get_locale,
    locale_context,
    t as tr,
)
from utils.locale_service import apply_interaction_locale


def _badge_label(is_equipped: bool) -> str:
    """Renders the plain ASCII equipment status badge for field names."""
    if is_equipped:
        return catalog_label("equipment_badges", "equipped")
    return catalog_label("equipment_badges", "stored")


def _stat(label: str, value: str, value_color: str = NEUTRAL_COLOR) -> str:
    """Renders a colored label/value pair inside a code block."""
    return f"{ansi(label, LABEL_COLOR)} {ansi(value, value_color)}"


def _encumbrance_level(total_weight: float, strength: int) -> tuple[str, int, str]:
    """Calculates the GURPS 4e metric encumbrance level for the carried weight."""
    basic_lift = (strength * strength) / 10.0

    thresholds = [
        (basic_lift, catalog_label("encumbrance", "none"), 0, SUCCESS_COLOR),
        (basic_lift * 2, catalog_label("encumbrance", "light"), -1, WARN_COLOR),
        (basic_lift * 3, catalog_label("encumbrance", "medium"), -2, DANGER_COLOR),
        (basic_lift * 6, catalog_label("encumbrance", "heavy"), -3, DANGER_COLOR),
        (basic_lift * 10, catalog_label("encumbrance", "extra_heavy"), -4, DANGER_COLOR),
    ]

    for limit, label, penalty, color in thresholds:
        if total_weight <= limit:
            return label, penalty, color

    return catalog_label("encumbrance", "extra_heavy"), -4, DANGER_COLOR


MELEE_FIELD_BUDGET = 950


def _chunk_melee_mode_lines(header: str, mode_lines: list[str]) -> list[list[str]]:
    """Splits colored mode lines into chunks that fit a single embed field."""
    if not mode_lines:
        return [[header]]

    chunks: list[list[str]] = []
    current = [header]
    current_has_mode = False

    for line in mode_lines:
        separator = [ansi("-" * 40, NEUTRAL_COLOR)] if current_has_mode else []
        candidate = current + separator + [line]

        if current_has_mode and len(code_block(candidate)) > MELEE_FIELD_BUDGET:
            chunks.append(current)
            current = [line]
        else:
            current = candidate

        current_has_mode = True

    chunks.append(current)
    return chunks


def _build_melee_fields(data: dict) -> tuple[list[tuple[str, str]], float, int]:
    """Builds the melee weapon fields with attack mode sub-lines."""
    fields = []
    total_weight = 0.0
    equipped_count = 0

    for weapon in data["melee_weapons"]:
        equipped_count += int(weapon["is_equipped"])
        item_weight = weapon["weight"] * weapon["quantity"]
        total_weight += item_weight

        header = _stat(tr("Weight"), f'{item_weight:.2f} kg', ACCENT_COLOR)
        if weapon["min_st"] > 0:
            header += f"  {_stat(tr('Min ST'), str(weapon['min_st']))}"

        mode_lines = []
        for mode in weapon["modes"]:
            dmg_sign = (
                f"{mode['damage_modifier']:+d}"
                if mode["damage_modifier"] != 0
                else ""
            )
            damage_base = catalog_label_from_value("damage_bases", mode["damage_base"])
            raw_damage_type = str(mode["damage_type"] or "")
            damage_type = catalog_label_from_value("damage_types", raw_damage_type)
            if raw_damage_type and raw_damage_type == raw_damage_type.lower():
                damage_type = damage_type.lower()
            dmg_display = f"{damage_base}{dmg_sign} {damage_type}".strip()
            notes = (
                f" {ansi('(' + mode['notes'] + ')', NEUTRAL_COLOR)}"
                if mode["notes"]
                else ""
            )

            mode_name = catalog_label_from_value("mode_names", mode["mode_name"])
            parry = catalog_label_from_value("parry", mode["parry"])
            mode_lines.append(
                f"{ansi(mode_name + ':', MODE_COLOR)} "
                f"{ansi(dmg_display, DANGER_COLOR)} | "
                f"{ansi(tr('Reach'), LABEL_COLOR)} {sanitize(mode['reach'])} | "
                f"{ansi(tr('Parry'), LABEL_COLOR)} {sanitize(parry)}{notes}"
            )

        display_weapon_name = catalog_label_from_value("weapon_names", weapon["name"])
        weapon_name = (
            f"{_badge_label(weapon['is_equipped'])} "
            f"{display_weapon_name} (x{weapon['quantity']})"
        )

        for index, chunk in enumerate(_chunk_melee_mode_lines(header, mode_lines)):
            field_name = (
                weapon_name if index == 0 else f"{weapon_name} - {tr('Modes (cont.)')}"
            )
            fields.append((field_name, code_block(chunk)))

    return fields, total_weight, equipped_count


def _build_ranged_fields(data: dict) -> tuple[list[tuple[str, str]], float, int]:
    """Builds the ranged weapon fields with firing statistics."""
    fields = []
    total_weight = 0.0
    equipped_count = 0

    for weapon in data["ranged_weapons"]:
        equipped_count += int(weapon["is_equipped"])
        item_weight = weapon["weight"] * weapon["quantity"]
        total_weight += item_weight

        range_display = f"{weapon['range_half']}/{weapon['range_max']}"

        lines = [
            _stat(tr("Weight"), f'{item_weight:.2f} kg', ACCENT_COLOR),
            f"{_stat(tr('Damage'), weapon['damage'], DANGER_COLOR)} | {_stat(tr('Accuracy'), str(weapon['acc']))}",
            f"{_stat(tr('Range'), range_display)} | {_stat(tr('Shots'), str(weapon['shots']))}",
        ]

        fields.append(
            (
                f"{_badge_label(weapon['is_equipped'])} "
                f"{weapon['name']} (x{weapon['quantity']})",
                code_block(lines),
            )
        )

    return fields, total_weight, equipped_count


def _build_armor_fields(
    data: dict,
) -> tuple[list[tuple[str, str]], float, int, bool]:
    """Builds the modular armor fields with damage resistance and value."""
    fields = []
    total_weight = 0.0
    equipped_count = 0
    has_flexible = False

    for armor in data["armors"]:
        equipped_count += int(armor["is_equipped"])
        item_weight = armor["weight"] * armor["quantity"]
        item_cost = armor["cost"] * armor["quantity"]
        total_weight += item_weight
        has_flexible = has_flexible or bool(armor["is_flexible"])

        dr_display = f"{armor['dr']}*" if armor["is_flexible"] else f"{armor['dr']}"

        location = catalog_label_from_value("body_parts", armor["location"])
        lines = [
            f"{_stat(tr('Weight'), f'{item_weight:.2f} kg', ACCENT_COLOR)} | "
            f"{_stat(tr('Value'), f'$ {item_cost:.2f}', SUCCESS_COLOR)}",
            f"{_stat(tr('DR'), dr_display, INFO_COLOR)} | {_stat(tr('Location'), location)}",
        ]

        fields.append(
            (
                f"{_badge_label(armor['is_equipped'])} "
                f"{armor['name']} (x{armor['quantity']})",
                code_block(lines),
            )
        )

    return fields, total_weight, equipped_count, has_flexible


def _build_item_fields(data: dict) -> tuple[list[tuple[str, str]], float]:
    """Builds the general item fields with weight and description."""
    fields = []
    total_weight = 0.0

    for item in data["items"]:
        item_weight = item["weight"] * item["quantity"]
        total_weight += item_weight

        quantity_display = str(item["quantity"])

        lines = [
            f"{_stat(tr('Weight'), f'{item_weight:.2f} kg', ACCENT_COLOR)} | "
            f"{_stat(tr('Qty'), f'x{quantity_display}')}"
        ]
        if item["description"]:
            lines.append(ansi(item["description"], NEUTRAL_COLOR))

        fields.append((f"{item['name']}", code_block(lines)))

    return fields, total_weight


def _build_summary_page(
    data: dict,
    total_weight: float,
    equipped_count: int,
    item_count: int,
    strength: int | None,
) -> dict:
    """Builds the golden summary page with the core inventory metrics."""
    if item_count == 0:
        description = f"*{tr('No equipment or items recorded.')}*"
    else:
        description = f"*{tr('Equipment and load record for the character.')}*"

    fields = [
        (tr("Money"), code_block([ansi(f"$ {data['money']}", SUCCESS_COLOR)]), True),
        (
            tr("Total Weight"),
            code_block([ansi(f"{total_weight:.2f} kg", ACCENT_COLOR)]),
            True,
        ),
        (tr("Equipped"), code_block([ansi(str(equipped_count), SUCCESS_COLOR)]), True),
        (tr("Items"), code_block([ansi(str(item_count), NEUTRAL_COLOR)]), True),
    ]

    if strength is not None:
        label, penalty, color = _encumbrance_level(total_weight, strength)
        penalty_text = f" ({penalty})" if penalty else ""
        fields.append(
            (
                tr("Load"),
                code_block([ansi(f"{label}{penalty_text}", color)]),
                True,
            )
        )

    return {
        "title": tr("Inventory: {character}", character=data["character_name"]),
        "color": discord.Color.gold(),
        "description": description,
        "fields": fields,
    }


def _paginate_fields(
    fields: list[tuple[str, str]],
    title: str,
    description: str | None,
    budget: int = 5400,
) -> list[list[tuple[str, str]]]:
    """Splits item fields into pages respecting field count and payload budgets."""
    chunks = []
    current: list[tuple[str, str]] = []
    used = len(title) + len(description or "") + 64

    for field in fields:
        name, value = field
        entry_size = len(name) + len(value)

        if current and (len(current) >= 25 or used + entry_size > budget):
            chunks.append(current)
            current = []
            used = len(title) + 64

        current.append(field)
        used += entry_size

    if current:
        chunks.append(current)

    return chunks


def _append_category_pages(
    pages: list[dict],
    character_name: str,
    title: str,
    color: discord.Color,
    fields: list[tuple[str, str]],
    weight: float,
    legend: str | None = None,
    item_count: int | None = None,
) -> None:
    """Appends the paginated pages of a single inventory category."""
    if not fields:
        return

    total_items = len(fields) if item_count is None else item_count
    base_title = f"{title}: {character_name}"
    count_label = tr("item") if total_items == 1 else tr("items")
    description = f"*{total_items} {count_label} - {weight:.2f} kg*"
    if legend:
        description += f"\n{legend}"

    for index, chunk in enumerate(_paginate_fields(fields, base_title, description)):
        pages.append(
            {
                "title": base_title if index == 0 else f"{base_title} ({tr('continuation')})",
                "color": color,
                "description": description if index == 0 else None,
                "fields": [(name, value, False) for name, value in chunk],
            }
        )


def build_inventory_pages(
    data: dict, strength: int | None = None, locale: str | None = None
) -> list[dict]:
    """Builds the paginated inventory pages with ANSI colored item fields."""
    with locale_context(locale or get_locale()):
        return _build_inventory_pages(data, strength)


def _build_inventory_pages(data: dict, strength: int | None = None) -> list[dict]:
    melee_fields, melee_weight, melee_equipped = _build_melee_fields(data)
    ranged_fields, ranged_weight, ranged_equipped = _build_ranged_fields(data)
    armor_fields, armor_weight, armor_equipped, has_flexible = _build_armor_fields(data)
    item_fields, item_weight = _build_item_fields(data)

    item_count = (
        len(data["melee_weapons"])
        + len(data["ranged_weapons"])
        + len(data["armors"])
        + len(data["items"])
    )
    total_weight = melee_weight + ranged_weight + armor_weight + item_weight
    equipped_count = melee_equipped + ranged_equipped + armor_equipped

    pages = [
        _build_summary_page(data, total_weight, equipped_count, item_count, strength)
    ]

    _append_category_pages(
        pages,
        data["character_name"],
        tr("Melee Weapons"),
        discord.Color.dark_red(),
        melee_fields,
        melee_weight,
        item_count=len(data["melee_weapons"]),
    )
    _append_category_pages(
        pages,
        data["character_name"],
        tr("Ranged Weapons"),
        discord.Color.dark_teal(),
        ranged_fields,
        ranged_weight,
        item_count=len(data["ranged_weapons"]),
    )
    _append_category_pages(
        pages,
        data["character_name"],
        tr("Armor"),
        discord.Color.dark_blue(),
        armor_fields,
        armor_weight,
        f"* {tr('Flexible DR')}" if has_flexible else None,
        item_count=len(data["armors"]),
    )
    _append_category_pages(
        pages,
        data["character_name"],
        tr("General Items"),
        discord.Color.dark_grey(),
        item_fields,
        item_weight,
        item_count=len(data["items"]),
    )

    return pages


class InventoryView(discord.ui.View):
    """Paginated view rendering one inventory page at a time."""

    def __init__(
        self,
        pages: list[dict],
        author_id: int,
        thumbnail_url: str | None = None,
        back_callback=None,
        locale: str | None = None,
    ):
        super().__init__(timeout=None)
        self.pages = pages
        self.author_id = author_id
        self.thumbnail_url = thumbnail_url
        self.back_callback = back_callback
        self.locale = locale
        self.current_page = 0

        with locale_context(self.locale or get_locale()):
            self.previous_button = discord.ui.Button(
                label=f"< {tr('Previous')}",
                style=discord.ButtonStyle.secondary,
            )
            self.previous_button.callback = self.previous_page
            self.add_item(self.previous_button)

            self.next_button = discord.ui.Button(
                label=f"{tr('Next')} >",
                style=discord.ButtonStyle.secondary,
            )
            self.next_button.callback = self.next_page
            self.add_item(self.next_button)

            if back_callback is not None:
                back_button = discord.ui.Button(
                    label=tr("Back"),
                    style=discord.ButtonStyle.secondary,
                )
                back_button.callback = self.go_back
                self.add_item(back_button)

            self._sync_buttons()

    def _sync_buttons(self) -> None:
        """Refreshes the navigation button states for the current page."""
        self.previous_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page >= len(self.pages) - 1

    def build_embed(self) -> discord.Embed:
        """Renders the current page as a single clamped embed with page footer."""
        with locale_context(self.locale or get_locale()):
            return self._build_embed()

    def _build_embed(self) -> discord.Embed:
        page = self.pages[self.current_page]

        embed = discord.Embed(
            title=page["title"][:256],
            color=page["color"],
        )

        if page.get("description"):
            embed.description = page["description"][:4000]

        for name, value, inline in page["fields"]:
            embed.add_field(
                name=name[:256],
                value=clamp_code_block(value, 1000),
                inline=inline,
            )

        if self.thumbnail_url:
            embed.set_thumbnail(url=self.thumbnail_url)

        embed.set_footer(
            text=tr(
                "Page {current} of {total}",
                current=self.current_page + 1,
                total=len(self.pages),
            )
        )
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Restricts interaction to the user who invoked the command."""
        with locale_context(self.locale or get_locale()):
            if interaction.user.id != self.author_id:
                await interaction.response.send_message(
                    tr("Error: only the user who invoked this command can interact with this menu."),
                    ephemeral=True,
                )
                return False
            return True

    async def previous_page(self, interaction: discord.Interaction):
        """Moves the view to the previous inventory page."""
        if self.current_page > 0:
            self.current_page -= 1
            self._sync_buttons()
            await interaction.response.edit_message(
                embed=self.build_embed(),
                view=self,
            )

    async def next_page(self, interaction: discord.Interaction):
        """Moves the view to the next inventory page."""
        if self.current_page < len(self.pages) - 1:
            self.current_page += 1
            self._sync_buttons()
            await interaction.response.edit_message(
                embed=self.build_embed(),
                view=self,
            )

    async def go_back(self, interaction: discord.Interaction):
        """Delegates navigation back to the parent view when configured."""
        await self.back_callback(interaction)


class Inventory(commands.Cog):
    """Cog responsible for character inventory management and monetary transactions."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        project_root = Path(__file__).resolve().parent.parent
        database_path = project_root / "data" / "database.db"

        # Persistent database connection
        self.db_connection = sqlite3.connect(database_path)
        self.db_connection.execute("PRAGMA foreign_keys = ON;")

    async def character_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        """Dynamically queries the database for characters matching user input."""
        cursor = self.db_connection.cursor()
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
        name="manage_money",
        description="Add or remove money from a character's inventory.",
    )
    @app_commands.rename(character="character", money="money")
    @app_commands.describe(
        character="Character that will receive the transaction.",
        money="Amount to add or remove.",
    )
    @app_commands.autocomplete(character=character_autocomplete)
    @app_commands.default_permissions(administrator=True)
    async def manage_money(
        self, interaction: discord.Interaction, character: str, money: int
    ):
        """Modifies a character's financial balance atomically within the database layer."""
        apply_interaction_locale(interaction, self.db_connection)
        await interaction.response.defer(ephemeral=True)

        try:
            target_character_id = int(character)
        except ValueError:
            await interaction.followup.send(
                tr("**Processing error:** the supplied character identifier is invalid."),
                ephemeral=True,
            )
            return

        cursor = self.db_connection.cursor()
        cursor.execute(
            "SELECT name, money FROM characters WHERE character_id = ?",
            (target_character_id,),
        )
        row = cursor.fetchone()

        if row is None:
            await interaction.followup.send(
                tr(
                    "**Consistency error:** no entity was found under ID `{character_id}`.",
                    character_id=target_character_id,
                ),
                ephemeral=True,
            )
            return

        character_name = row[0]
        previous_balance = row[1]
        updated_balance = previous_balance + money

        cursor.execute(
            "UPDATE characters SET money = ? WHERE character_id = ?",
            (updated_balance, target_character_id),
        )
        self.db_connection.commit()

        finance_embed = discord.Embed(
            title=tr("ASSET CHANGE: {character}", character=character_name),
            color=discord.Color.green() if money >= 0 else discord.Color.red(),
        )

        transaction_type = tr("Income") if money >= 0 else tr("Expense")

        finance_embed.add_field(
            name=tr("Approved Transaction"),
            value=tr(
                "Type: `{type}`\nFlow: `{money:+d} $`",
                type=transaction_type,
                money=money,
            ),
            inline=False,
        )

        finance_embed.add_field(
            name=tr("Balance Statement"),
            value=tr(
                "Previous: `{previous} $`\nUpdated: `{updated} $`",
                previous=previous_balance,
                updated=updated_balance,
            ),
            inline=False,
        )

        character_file, thumbnail_url = get_character_thumbnail_by_id(
            self.db_connection, target_character_id
        )

        if thumbnail_url:
            finance_embed.set_thumbnail(url=thumbnail_url)

        if character_file is not None:
            await interaction.followup.send(
                embed=finance_embed, file=character_file, ephemeral=True
            )
        else:
            await interaction.followup.send(embed=finance_embed, ephemeral=True)

    @app_commands.command(
        name="inventory",
        description="Display your character's complete inventory, weapons, armor, and equipment.",
    )
    async def view_inventory(self, interaction: discord.Interaction):
        """Displays the paginated character inventory using the persistent connection."""
        locale = apply_interaction_locale(interaction, self.db_connection)
        await interaction.response.defer(ephemeral=True)

        data = get_character_inventory_data(
            self.db_connection, interaction.user.id
        )

        if not data:
            await interaction.followup.send(
                tr("**You do not have an active character assigned to your account!**"),
                ephemeral=True,
            )
            return

        try:
            strength = get_character_strength(self.db_connection, interaction.user.id)
        except ValueError:
            strength = None

        pages = build_inventory_pages(data, strength, locale)
        character_file, thumbnail_url = get_character_thumbnail_by_id(
            self.db_connection, data["character_id"]
        )
        view = InventoryView(
            pages=pages,
            author_id=interaction.user.id,
            thumbnail_url=thumbnail_url,
            locale=locale,
        )

        if character_file is not None:
            await interaction.followup.send(
                embed=view.build_embed(),
                file=character_file,
                view=view,
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                embed=view.build_embed(),
                view=view,
                ephemeral=True,
            )


async def setup(bot: commands.Bot) -> None:
    """Mandatory asynchronous entry point to load the extension."""
    await bot.add_cog(Inventory(bot))
