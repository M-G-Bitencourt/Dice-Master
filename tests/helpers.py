"""Shared factories, stubs and utilities for the Dice Master test suite."""

from __future__ import annotations

import sqlite3
from typing import Iterable, Sequence


class BudgetRng:
    """Deterministic randint replacement with an explicit call budget.

    The production code contains unbounded ``while True`` loops that keep
    rolling until a predicate holds. This stub raises as soon as the budget
    is exhausted, surfacing accidental infinite loops as test failures.
    """

    def __init__(self, values: Sequence[int], budget: int | None = None):
        if not values:
            raise ValueError("BudgetRng requires at least one value")
        self._values = [int(value) for value in values]
        self._budget = budget if budget is not None else len(self._values) * 4 + 10
        self.calls = 0

    def __call__(self, start: int, end: int) -> int:
        if self.calls >= self._budget:
            raise AssertionError(
                "RNG budget exhausted: the code under test appears to be looping"
            )
        value = self._values[self.calls % len(self._values)]
        self.calls += 1
        if not start <= value <= end:
            raise AssertionError(
                f"Stub value {value} is outside the requested range [{start}, {end}]"
            )
        return value


def dice_sequence(*rolls: Iterable[int]) -> list[int]:
    """Flatten sequences of individual rolls into a single RNG value list."""
    return [value for roll in rolls for value in roll]


def patch_rng(monkeypatch, module, values: Sequence[int], budget: int | None = None):
    """Replace the ``randint`` reference bound inside a module with a BudgetRng."""
    rng = BudgetRng(values, budget=budget)
    monkeypatch.setattr(module, "randint", rng)
    return rng


class FakeUser:
    def __init__(self, user_id: int = 1):
        self.id = user_id
        self.mention = f"<@{user_id}>"


class FakeResponse:
    def __init__(self):
        self.deferred = []
        self.messages = []
        self.edits = []

    async def defer(self, *args, **kwargs):
        self.deferred.append({"args": args, "kwargs": kwargs})

    async def send_message(self, *args, **kwargs):
        self.messages.append({"args": args, "kwargs": kwargs})

    async def edit_message(self, *args, **kwargs):
        self.edits.append({"args": args, "kwargs": kwargs})


class FakeFollowup:
    def __init__(self):
        self.sent = []

    async def send(self, *args, **kwargs):
        self.sent.append({"args": args, "kwargs": kwargs})


class FakeMessage:
    def __init__(self, message_id: int = 1):
        self.id = message_id
        self.embeds = []
        self.views = []
        self.deleted = False

    async def edit(self, *args, **kwargs):
        self.embeds.append(kwargs.get("embed"))
        self.views.append(kwargs.get("view"))

    async def delete(self):
        self.deleted = True


class FakeInteraction:
    def __init__(
        self,
        user_id: int = 1,
        message=None,
        channel_id: int = 100,
        guild_id: int = 1,
        original_message: FakeMessage | None = None,
    ):
        self.user = FakeUser(user_id)
        self.response = FakeResponse()
        self.followup = FakeFollowup()
        self.message = message
        self.channel_id = channel_id
        self.guild_id = guild_id
        self.channel = None
        self._original_message = original_message or FakeMessage()
        self.edited = []

    async def edit_original_response(self, *args, **kwargs):
        self.edited.append({"args": args, "kwargs": kwargs})

    async def original_response(self):
        return self._original_message


class FakeBot:
    def __init__(self, config: dict | None = None):
        self.config = config if config is not None else {"BOT": {"DM_ID": "999"}}


DEFAULT_CHARACTER = {
    "owner_id": 1,
    "is_npc": 0,
    "name": "Cobaia",
    "st": 10,
    "dx": 10,
    "iq": 10,
    "ht": 10,
    "additional_max_pv": 0,
    "additional_vont": 0,
    "additional_per": 0,
    "additional_max_pf": 0,
    "additional_basic_speed": 0,
    "additional_basic_move": 0,
    "energy_reserve": 0,
    "normal_diffuse_homogeneous_unded": 0,
    "money": 0,
    "current_pv": 10,
    "current_pf": 10,
    "current_er": 0,
    "current_points": 0,
}


def _insert_row(connection: sqlite3.Connection, table: str, data: dict) -> int:
    columns = ", ".join(data)
    placeholders = ", ".join("?" for _ in data)
    cursor = connection.cursor()
    cursor.execute(
        f"INSERT INTO {table} ({columns}) VALUES ({placeholders})",
        tuple(data.values()),
    )
    connection.commit()
    return int(cursor.lastrowid)


def insert_character(connection: sqlite3.Connection, **overrides) -> int:
    data = {**DEFAULT_CHARACTER, **overrides}
    return _insert_row(connection, "characters", data)


def insert_attack(
    connection: sqlite3.Connection,
    raw_damage: int = 0,
    dmg_type: int = 4,
    hit_location: int = 0,
    feint: int = 0,
    critical_damage: int = 0,
) -> int:
    return _insert_row(
        connection,
        "current_attacks",
        {
            "raw_damage": raw_damage,
            "dmg_type": dmg_type,
            "hit_location": hit_location,
            "feint": feint,
            "critical_damage": critical_damage,
        },
    )


def insert_combat_effect(
    connection: sqlite3.Connection,
    name: str,
    applies_to: str,
    *,
    target: str | None = None,
    value: int = 0,
    uses_per_turn: int = 0,
    notes: str | None = None,
) -> int:
    """Insert one effect into the external catalog and return its id."""
    return _insert_row(
        connection,
        "combat_effects",
        {
            "name": name,
            "applies_to": applies_to,
            "target": target,
            "value": int(value),
            "uses_per_turn": int(uses_per_turn),
            "notes": notes,
        },
    )


def link_combat_effect(
    connection: sqlite3.Connection, character_id: int, effect_id: int
) -> None:
    """Link one catalog effect to a character."""
    _insert_row(
        connection,
        "character_combat_effects",
        {"character_id": character_id, "effect_id": effect_id},
    )


def insert_hdm(connection: sqlite3.Connection, player_id: int, fate: int) -> int:
    return _insert_row(connection, "hdm", {"id_player": player_id, "fate": fate})


def insert_skill(
    connection: sqlite3.Connection,
    name: str = "Espada Curta",
    attribute: str = "DX",
    difficulty_id: int = 2,
    description: str = "Perícia de teste",
) -> int:
    return _insert_row(
        connection,
        "skills",
        {
            "name": name,
            "attribute": attribute,
            "difficulty_id": difficulty_id,
            "description": description,
        },
    )


def insert_spell_class(connection: sqlite3.Connection, class_name: str = "Fogo") -> int:
    return _insert_row(connection, "spell_classes", {"class": class_name})


def insert_spell(
    connection: sqlite3.Connection,
    name: str = "Bola de Fogo",
    attribute: str = "IQ",
    class_id: int | None = 1,
    difficulty_id: int = 2,
    cost: int = 1,
    resource: str = "PF",
    description: str = "Magia de teste",
) -> int:
    return _insert_row(
        connection,
        "spells",
        {
            "name": name,
            "attribute": attribute,
            "class": class_id,
            "difficulty_id": difficulty_id,
            "cost": cost,
            "resource": resource,
            "description": description,
        },
    )


def insert_advantage(
    connection: sqlite3.Connection,
    name: str = "Reflexos de Combate",
    cost: int = 15,
    description: str = "Vantagem de teste",
) -> int:
    return _insert_row(
        connection,
        "advantages",
        {"name": name, "cost": cost, "description": description},
    )


def insert_disadvantage(
    connection: sqlite3.Connection,
    name: str = "Miopia",
    cost: int = -10,
    description: str = "Desvantagem de teste",
) -> int:
    return _insert_row(
        connection,
        "disadvantages",
        {"name": name, "cost": cost, "description": description},
    )


def link_skill(
    connection: sqlite3.Connection, character_id: int, skill_id: int, relative_level: int
) -> int:
    return _insert_row(
        connection,
        "character_skills",
        {
            "character_id": character_id,
            "skill_id": skill_id,
            "relative_level": relative_level,
        },
    )


def link_spell(
    connection: sqlite3.Connection, character_id: int, spell_id: int, relative_level: int
) -> int:
    return _insert_row(
        connection,
        "character_spells",
        {
            "character_id": character_id,
            "spell_id": spell_id,
            "relative_level": relative_level,
        },
    )


def link_advantage(
    connection: sqlite3.Connection,
    character_id: int,
    advantage_id: int,
    notes: str | None = None,
) -> int:
    return _insert_row(
        connection,
        "character_advantages",
        {
            "character_id": character_id,
            "advantage_id": advantage_id,
            "notes": notes,
        },
    )


def link_disadvantage(
    connection: sqlite3.Connection,
    character_id: int,
    disadvantage_id: int,
    notes: str | None = None,
) -> int:
    return _insert_row(
        connection,
        "character_disadvantages",
        {
            "character_id": character_id,
            "disadvantage_id": disadvantage_id,
            "notes": notes,
        },
    )


def insert_body_part(
    connection: sqlite3.Connection,
    name: str = "Tronco",
    factor: float = 1.0,
    hit_location_roll: str = "9-11",
    notes: str = "",
) -> int:
    return _insert_row(
        connection,
        "body_parts",
        {
            "name": name,
            "cost_weight_factor": factor,
            "hit_location_roll": hit_location_roll,
            "notes": notes,
        },
    )


def insert_armor_material(
    connection: sqlite3.Connection,
    name: str = "Couro Médio",
    dr: int = 2,
    is_flexible: int = 1,
    cost_torso: float = 100.0,
    weight_torso: float = 5.0,
    tl: int = 1,
    don_time: int = 30,
    notes: str = "",
) -> int:
    return _insert_row(
        connection,
        "armor_materials",
        {
            "name": name,
            "tl": tl,
            "dr": dr,
            "is_flexible": is_flexible,
            "cost_torso": cost_torso,
            "weight_torso": weight_torso,
            "don_time": don_time,
            "notes": notes,
        },
    )


def link_armor(
    connection: sqlite3.Connection,
    character_id: int,
    material_id: int,
    body_part_id: int,
    quantity: int = 1,
    is_equipped: int = 0,
    custom_name: str | None = None,
) -> int:
    return _insert_row(
        connection,
        "character_armors",
        {
            "character_id": character_id,
            "material_id": material_id,
            "body_part_id": body_part_id,
            "custom_name": custom_name,
            "quantity": quantity,
            "is_equipped": is_equipped,
        },
    )


def insert_melee_weapon(
    connection: sqlite3.Connection,
    name: str = "Machado",
    tl: int = 0,
    min_st: int = 10,
    is_two_handed: int = 0,
    weight: float = 2.0,
    cost: float = 50.0,
    description: str = "",
) -> int:
    return _insert_row(
        connection,
        "melee_weapons",
        {
            "name": name,
            "tl": tl,
            "min_st": min_st,
            "is_two_handed": is_two_handed,
            "weight": weight,
            "cost": cost,
            "description": description,
        },
    )


def insert_melee_mode(
    connection: sqlite3.Connection,
    melee_weapon_id: int,
    skill_id: int,
    mode_name: str = "Padrão",
    damage_base: str = "GeB",
    damage_modifier: int = 0,
    damage_type: str = "corte",
    reach: str = "1",
    parry: str = "0U",
    notes: str = "",
) -> int:
    return _insert_row(
        connection,
        "melee_weapon_modes",
        {
            "melee_weapon_id": melee_weapon_id,
            "mode_name": mode_name,
            "skill_id": skill_id,
            "damage_base": damage_base,
            "damage_modifier": damage_modifier,
            "damage_type": damage_type,
            "reach": reach,
            "parry": parry,
            "notes": notes,
        },
    )


def link_melee_weapon(
    connection: sqlite3.Connection,
    character_id: int,
    melee_weapon_id: int,
    quantity: int = 1,
    is_equipped: int = 0,
    custom_name: str | None = None,
) -> int:
    return _insert_row(
        connection,
        "character_melee_weapons",
        {
            "character_id": character_id,
            "melee_weapon_id": melee_weapon_id,
            "custom_name": custom_name,
            "quantity": quantity,
            "is_equipped": is_equipped,
        },
    )


def insert_ranged_weapon(
    connection: sqlite3.Connection,
    name: str = "Pistola",
    skill_id: int | None = None,
    damage: str = "2d+1 pi+",
    acc: int = 2,
    range_half: int = 150,
    range_max: int = 1500,
    rof: int = 1,
    shots: str = "7(3)",
    min_st: int = 8,
    recoil: int = 2,
    weight: float = 1.0,
    cost: float = 200.0,
    description: str = "",
) -> int:
    return _insert_row(
        connection,
        "ranged_weapons",
        {
            "name": name,
            "skill_id": skill_id,
            "damage": damage,
            "acc": acc,
            "range_half": range_half,
            "range_max": range_max,
            "rof": rof,
            "shots": shots,
            "min_st": min_st,
            "recoil": recoil,
            "weight": weight,
            "cost": cost,
            "description": description,
        },
    )


def link_ranged_weapon(
    connection: sqlite3.Connection,
    character_id: int,
    ranged_weapon_id: int,
    quantity: int = 1,
    current_shots: int = 0,
    is_equipped: int = 0,
) -> int:
    return _insert_row(
        connection,
        "character_ranged_weapons",
        {
            "character_id": character_id,
            "ranged_weapon_id": ranged_weapon_id,
            "quantity": quantity,
            "current_shots": current_shots,
            "is_equipped": is_equipped,
        },
    )


def insert_item(
    connection: sqlite3.Connection,
    name: str = "Corda",
    weight: float = 1.0,
    cost: float = 10.0,
    description: str = "",
) -> int:
    return _insert_row(
        connection,
        "items",
        {"name": name, "weight": weight, "cost": cost, "description": description},
    )


def link_item(
    connection: sqlite3.Connection,
    character_id: int,
    item_id: int,
    quantity: int = 1,
    is_equipped: int = 0,
) -> int:
    return _insert_row(
        connection,
        "character_items",
        {
            "character_id": character_id,
            "item_id": item_id,
            "quantity": quantity,
            "is_equipped": is_equipped,
        },
    )
