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


def _badge_label(is_equipped: bool) -> str:
    """Renders the plain ASCII equipment status badge for field names."""
    if is_equipped:
        return "[EQUIPADO]"
    return "[GUARDADO]"


def _stat(label: str, value: str, value_color: str = NEUTRAL_COLOR) -> str:
    """Renders a colored label/value pair inside a code block."""
    return f"{ansi(label, LABEL_COLOR)} {ansi(value, value_color)}"


def _encumbrance_level(total_weight: float, strength: int) -> tuple[str, int, str]:
    """Calculates the GURPS 4e metric encumbrance level for the carried weight."""
    basic_lift = (strength * strength) / 10.0

    thresholds = [
        (basic_lift, "Nenhuma", 0, SUCCESS_COLOR),
        (basic_lift * 2, "Leve", -1, WARN_COLOR),
        (basic_lift * 3, "Média", -2, DANGER_COLOR),
        (basic_lift * 6, "Pesada", -3, DANGER_COLOR),
        (basic_lift * 10, "Muito Pesada", -4, DANGER_COLOR),
    ]

    for limit, label, penalty, color in thresholds:
        if total_weight <= limit:
            return label, penalty, color

    return "Muito Pesada", -4, DANGER_COLOR


def _build_melee_fields(data: dict) -> tuple[list[tuple[str, str]], float, int]:
    """Builds the melee weapon fields with attack mode sub-lines."""
    fields = []
    total_weight = 0.0
    equipped_count = 0

    for weapon in data["melee_weapons"]:
        equipped_count += int(weapon["is_equipped"])
        item_weight = weapon["weight"] * weapon["quantity"]
        total_weight += item_weight

        header = _stat('Peso', f'{item_weight:.2f} kg', ACCENT_COLOR)
        if weapon["min_st"] > 0:
            header += f"  {_stat('ST Mín', str(weapon['min_st']))}"

        lines = [header]
        for index, mode in enumerate(weapon["modes"]):
            if index > 0:
                lines.append(ansi("-" * 40, NEUTRAL_COLOR))

            dmg_sign = (
                f"{mode['damage_modifier']:+d}"
                if mode["damage_modifier"] != 0
                else ""
            )
            dmg_display = (
                f"{mode['damage_base']}{dmg_sign} {mode['damage_type']}".strip()
            )
            notes = (
                f" {ansi('(' + mode['notes'] + ')', NEUTRAL_COLOR)}"
                if mode["notes"]
                else ""
            )

            lines.append(
                f"{ansi(mode['mode_name'] + ':', MODE_COLOR)} "
                f"{ansi(dmg_display, DANGER_COLOR)} | "
                f"{ansi('Alc', LABEL_COLOR)} {sanitize(mode['reach'])} | "
                f"{ansi('Ap', LABEL_COLOR)} {sanitize(mode['parry'])}{notes}"
            )

        fields.append(
            (
                f"{_badge_label(weapon['is_equipped'])} "
                f"{weapon['name']} (x{weapon['quantity']})",
                code_block(lines),
            )
        )

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
            _stat('Peso', f'{item_weight:.2f} kg', ACCENT_COLOR),
            f"{_stat('Dano', weapon['damage'], DANGER_COLOR)} | {_stat('Precisão', str(weapon['acc']))}",
            f"{_stat('Alcance', range_display)} | {_stat('Tiros', str(weapon['shots']))}",
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

        lines = [
            f"{_stat('Peso', f'{item_weight:.2f} kg', ACCENT_COLOR)} | "
            f"{_stat('Valor', f'$ {item_cost:.2f}', SUCCESS_COLOR)}",
            f"{_stat('RD', dr_display, INFO_COLOR)} | {_stat('Local', armor['location'])}",
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
            f"{_stat('Peso', f'{item_weight:.2f} kg', ACCENT_COLOR)} | "
            f"{_stat('Qtd', f'x{quantity_display}')}"
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
        description = "*Nenhum equipamento ou item registrado.*"
    else:
        description = "*Registro de equipamento e carga do personagem.*"

    fields = [
        ("Dinheiro", code_block([ansi(f"$ {data['money']}", SUCCESS_COLOR)]), True),
        (
            "Peso Total",
            code_block([ansi(f"{total_weight:.2f} kg", ACCENT_COLOR)]),
            True,
        ),
        ("Equipados", code_block([ansi(str(equipped_count), SUCCESS_COLOR)]), True),
        ("Itens", code_block([ansi(str(item_count), NEUTRAL_COLOR)]), True),
    ]

    if strength is not None:
        label, penalty, color = _encumbrance_level(total_weight, strength)
        penalty_text = f" ({penalty})" if penalty else ""
        fields.append(
            (
                "Carga",
                code_block([ansi(f"{label}{penalty_text}", color)]),
                True,
            )
        )

    return {
        "title": f"Inventário: {data['character_name']}",
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
) -> None:
    """Appends the paginated pages of a single inventory category."""
    if not fields:
        return

    base_title = f"{title}: {character_name}"
    count_label = "item" if len(fields) == 1 else "itens"
    description = f"*{len(fields)} {count_label} - {weight:.2f} kg*"
    if legend:
        description += f"\n{legend}"

    for index, chunk in enumerate(_paginate_fields(fields, base_title, description)):
        pages.append(
            {
                "title": base_title if index == 0 else f"{base_title} (continuação)",
                "color": color,
                "description": description if index == 0 else None,
                "fields": [(name, value, False) for name, value in chunk],
            }
        )


def build_inventory_pages(data: dict, strength: int | None = None) -> list[dict]:
    """Builds the paginated inventory pages with ANSI colored item fields."""
    melee_fields, melee_weight, melee_equipped = _build_melee_fields(data)
    ranged_fields, ranged_weight, ranged_equipped = _build_ranged_fields(data)
    armor_fields, armor_weight, armor_equipped, has_flexible = _build_armor_fields(data)
    item_fields, item_weight = _build_item_fields(data)

    item_count = (
        len(melee_fields) + len(ranged_fields) + len(armor_fields) + len(item_fields)
    )
    total_weight = melee_weight + ranged_weight + armor_weight + item_weight
    equipped_count = melee_equipped + ranged_equipped + armor_equipped

    pages = [
        _build_summary_page(data, total_weight, equipped_count, item_count, strength)
    ]

    _append_category_pages(
        pages,
        data["character_name"],
        "Armas Corpo a Corpo",
        discord.Color.dark_red(),
        melee_fields,
        melee_weight,
    )
    _append_category_pages(
        pages,
        data["character_name"],
        "Armas a Distância",
        discord.Color.dark_teal(),
        ranged_fields,
        ranged_weight,
    )
    _append_category_pages(
        pages,
        data["character_name"],
        "Armaduras",
        discord.Color.dark_blue(),
        armor_fields,
        armor_weight,
        "* RD flexível" if has_flexible else None,
    )
    _append_category_pages(
        pages,
        data["character_name"],
        "Itens Gerais",
        discord.Color.dark_grey(),
        item_fields,
        item_weight,
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
    ):
        super().__init__(timeout=None)
        self.pages = pages
        self.author_id = author_id
        self.thumbnail_url = thumbnail_url
        self.back_callback = back_callback
        self.current_page = 0

        self.previous_button = discord.ui.Button(
            label="< Anterior",
            style=discord.ButtonStyle.secondary,
        )
        self.previous_button.callback = self.previous_page
        self.add_item(self.previous_button)

        self.next_button = discord.ui.Button(
            label="Próxima >",
            style=discord.ButtonStyle.secondary,
        )
        self.next_button.callback = self.next_page
        self.add_item(self.next_button)

        if back_callback is not None:
            back_button = discord.ui.Button(
                label="Voltar",
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

        embed.set_footer(text=f"Página {self.current_page + 1} de {len(self.pages)}")
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Restricts interaction to the user who invoked the command."""
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Erro: Apenas o usuário que invocou o comando pode interagir com este menu.",
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
        description="Adiciona ou remove dinheiro do inventário do personagem.",
    )
    @app_commands.autocomplete(character=character_autocomplete)
    @app_commands.default_permissions(administrator=True)
    async def manage_money(
        self, interaction: discord.Interaction, character: str, money: int
    ):
        """Modifies a character's financial balance atomically within the database layer."""
        await interaction.response.defer(ephemeral=True)

        try:
            target_character_id = int(character)
        except ValueError:
            await interaction.followup.send(
                "**Erro de processamento:** O identificador do personagem fornecido é inválido.",
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
                f"**Erro de consistência:** Nenhuma entidade foi localizada sob o ID `{target_character_id}`.",
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
            title=f"MUTAÇÃO PATRIMONIAL: {character_name}",
            color=discord.Color.green() if money >= 0 else discord.Color.red(),
        )

        transaction_type = "Entrada" if money >= 0 else "Saída"

        finance_embed.add_field(
            name="Transação Homologada",
            value=f"Tipo: `{transaction_type}`\nFluxo: `{money:+d} $`",
            inline=False,
        )

        finance_embed.add_field(
            name="Demonstrativo de Saldos",
            value=f"Anterior: `{previous_balance} $`\nAtualizado: `{updated_balance} $`",
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
        description="Exibe o inventário completo, armas, armaduras e equipamentos do seu personagem.",
    )
    async def view_inventory(self, interaction: discord.Interaction):
        """Displays the paginated character inventory using the persistent connection."""
        await interaction.response.defer(ephemeral=True)

        data = get_character_inventory_data(
            self.db_connection, interaction.user.id
        )

        if not data:
            await interaction.followup.send(
                "**Você não possui um personagem ativo atribuído à sua conta!**",
                ephemeral=True,
            )
            return

        try:
            strength = get_character_strength(self.db_connection, interaction.user.id)
        except ValueError:
            strength = None

        pages = build_inventory_pages(data, strength)
        character_file, thumbnail_url = get_character_thumbnail_by_id(
            self.db_connection, data["character_id"]
        )
        view = InventoryView(
            pages=pages,
            author_id=interaction.user.id,
            thumbnail_url=thumbnail_url,
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
