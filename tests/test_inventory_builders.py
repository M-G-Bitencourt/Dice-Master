"""Tests for the pure inventory builders in cogs/inventory.py.

All inputs are hand-built dicts shaped exactly like the payload returned by
utils.db_functions.get_character_inventory_data, so the builders are validated
without any database access. String assertions rely on stable plain substrings
because the real payloads carry ANSI escape sequences from utils/ansi.py.
"""

from __future__ import annotations

import discord
import pytest

from cogs.inventory import (
    _append_category_pages,
    _badge_label,
    _build_armor_fields,
    _build_item_fields,
    _build_melee_fields,
    _build_ranged_fields,
    _build_summary_page,
    _encumbrance_level,
    _paginate_fields,
    _stat,
    build_inventory_pages,
)
from helpers import (
    insert_armor_material,
    insert_body_part,
    insert_character,
    insert_item,
    link_armor,
    link_item,
)
from utils.ansi import (
    ACCENT_COLOR,
    DANGER_COLOR,
    LABEL_COLOR,
    NEUTRAL_COLOR,
    SUCCESS_COLOR,
    WARN_COLOR,
)
from utils.db_functions import get_character_inventory_data


def melee_mode(**overrides) -> dict:
    mode = {
        "mode_name": "Corte",
        "skill_id": 1,
        "skill_name": "Machado",
        "damage_base": "GeB",
        "damage_modifier": 2,
        "damage_type": "corte",
        "reach": "1",
        "parry": "0U",
        "notes": "",
    }
    mode.update(overrides)
    return mode


def melee_weapon(**overrides) -> dict:
    weapon = {
        "character_melee_id": 1,
        "name": "Machado",
        "min_st": 11,
        "weight": 2.5,
        "cost": 50.0,
        "quantity": 1,
        "is_equipped": 0,
        "modes": [melee_mode()],
    }
    weapon.update(overrides)
    return weapon


def bulky_modes(count: int = 4) -> list[dict]:
    return [
        melee_mode(
            mode_name=f"Modo {index}",
            notes="Dano original: GeB+1. ST Mín 9. " + "detalhe " * 30,
        )
        for index in range(count)
    ]


def ranged_weapon(**overrides) -> dict:
    weapon = {
        "name": "Pistola",
        "damage": "2d+1 pi+",
        "acc": 2,
        "range_half": 150,
        "range_max": 1500,
        "shots": "7(3)",
        "weight": 1.0,
        "quantity": 1,
        "is_equipped": 0,
    }
    weapon.update(overrides)
    return weapon


def armor(**overrides) -> dict:
    piece = {
        "name": "Couro (Tronco)",
        "dr": 2,
        "is_flexible": 1,
        "location": "Tronco",
        "weight": 5.0,
        "cost": 100.0,
        "quantity": 1,
        "is_equipped": 0,
    }
    piece.update(overrides)
    return piece


def item(**overrides) -> dict:
    entry = {
        "name": "Corda",
        "weight": 1.0,
        "description": "",
        "quantity": 1,
    }
    entry.update(overrides)
    return entry


def inventory_data(**overrides) -> dict:
    data = {
        "character_id": 1,
        "character_name": "Cobaia",
        "money": 25,
        "melee_weapons": [],
        "ranged_weapons": [],
        "armors": [],
        "items": [],
    }
    data.update(overrides)
    return data


class TestBadgeLabel:
    def test_equipped_returns_equipado_badge(self):
        assert _badge_label(True) == "[EQUIPADO]"

    def test_stored_returns_guardado_badge(self):
        assert _badge_label(False) == "[GUARDADO]"

    def test_truthy_integer_uses_python_truthiness(self):
        assert _badge_label(1) == "[EQUIPADO]"


class TestStat:
    def test_prefixes_the_colored_label_and_appends_the_colored_value(self):
        rendered = _stat("Peso", "1.00 kg", ACCENT_COLOR)
        assert rendered.startswith(f"\x1b[{LABEL_COLOR}mPeso")
        assert "1.00 kg" in rendered
        assert rendered.endswith("\x1b[0m")

    def test_default_value_color_is_neutral(self):
        rendered = _stat("Qtd", "x3")
        assert f"\x1b[{NEUTRAL_COLOR}m" in rendered

    def test_sanitizes_backticks_from_the_value(self):
        rendered = _stat("Nome", "a`b")
        assert "`" not in rendered
        assert "a'b" in rendered


class TestEncumbranceLevel:
    @pytest.mark.parametrize(
        "strength, weight, expected",
        [
            (10, 0, ("Nenhuma", 0, SUCCESS_COLOR)),
            # ST 10 -> BL = 10. The exact boundary stays in the lighter bracket.
            (10, 10, ("Nenhuma", 0, SUCCESS_COLOR)),
            (10, 10.1, ("Leve", -1, WARN_COLOR)),
            (10, 20, ("Leve", -1, WARN_COLOR)),
            (10, 20.1, ("Média", -2, DANGER_COLOR)),
            (10, 30, ("Média", -2, DANGER_COLOR)),
            (10, 30.1, ("Pesada", -3, DANGER_COLOR)),
            (10, 60, ("Pesada", -3, DANGER_COLOR)),
            (10, 60.1, ("Muito Pesada", -4, DANGER_COLOR)),
            (10, 100, ("Muito Pesada", -4, DANGER_COLOR)),
            (10, 1000, ("Muito Pesada", -4, DANGER_COLOR)),
            # ST 12 -> BL = 14.4.
            (12, 14.4, ("Nenhuma", 0, SUCCESS_COLOR)),
            (12, 14.5, ("Leve", -1, WARN_COLOR)),
        ],
    )
    def test_thresholds_follow_basic_lift_bands(self, strength, weight, expected):
        assert _encumbrance_level(weight, strength) == expected

    def test_zero_strength_with_zero_weight_is_unencumbered(self):
        assert _encumbrance_level(0, 0) == ("Nenhuma", 0, SUCCESS_COLOR)

    def test_zero_strength_with_positive_weight_hits_the_fallback_branch(self):
        # BL = 0 makes every threshold zero, so any positive weight exits the
        # loop and drains into the explicit Muito Pesada fallback.
        assert _encumbrance_level(0.1, 0) == ("Muito Pesada", -4, DANGER_COLOR)

    def test_negative_weight_is_treated_as_unencumbered(self):
        # Current behavior: negative weight is below every threshold, so the
        # first branch (<= BL) wins. Pinned as-is; reported as an edge risk.
        assert _encumbrance_level(-5, 10) == ("Nenhuma", 0, SUCCESS_COLOR)


class TestBuildMeleeFields:
    def test_builds_equipped_weapon_with_mode_details(self):
        weapon = melee_weapon(
            name="Machado",
            min_st=11,
            weight=2.5,
            quantity=2,
            is_equipped=1,
            modes=[
                melee_mode(),
                melee_mode(
                    mode_name="Ponta",
                    damage_base="GdP",
                    damage_modifier=0,
                    damage_type="perfuração",
                    reach="C",
                    parry="0",
                    notes="Gancho",
                ),
            ],
        )

        fields, total_weight, equipped_count = _build_melee_fields(
            {"melee_weapons": [weapon]}
        )

        assert len(fields) == 1
        name, value = fields[0]
        assert name == "[EQUIPADO] Machado (x2)"
        assert total_weight == pytest.approx(5.0)
        assert equipped_count == 1
        assert "5.00 kg" in value
        assert "ST Mín" in value
        assert "11" in value
        assert "Corte:" in value
        assert "GeB+2 corte" in value
        assert "Alc" in value
        assert "0U" in value
        # The separator line only appears between consecutive modes.
        assert "-" * 40 in value
        assert "Ponta:" in value
        assert "GdP perfuração" in value
        assert "(Gancho)" in value
        assert value.count("-" * 40) == 1

    def test_modifier_zero_omits_the_sign(self):
        weapon = melee_weapon(
            modes=[melee_mode(damage_base="GdP", damage_modifier=0, damage_type="corte")]
        )

        _, value = _build_melee_fields({"melee_weapons": [weapon]})[0][0]

        assert "GdP corte" in value
        assert "GdP+0" not in value

    def test_zero_min_strength_omits_the_st_line(self):
        weapon = melee_weapon(min_st=0)

        _, value = _build_melee_fields({"melee_weapons": [weapon]})[0][0]

        assert "ST Mín" not in value

    def test_empty_mode_notes_have_no_parenthesis(self):
        weapon = melee_weapon(modes=[melee_mode(notes="")])

        _, value = _build_melee_fields({"melee_weapons": [weapon]})[0][0]

        assert "(" not in value

    def test_stored_weapon_uses_guardado_badge(self):
        fields, _, equipped_count = _build_melee_fields(
            {"melee_weapons": [melee_weapon(is_equipped=0)]}
        )

        assert fields[0][0].startswith("[GUARDADO] ")
        assert equipped_count == 0

    def test_multiple_weapons_accumulate_weight_and_equipped_count(self):
        data = {
            "melee_weapons": [
                melee_weapon(weight=2.0, quantity=1, is_equipped=1),
                melee_weapon(weight=3.0, quantity=2, is_equipped=0),
            ]
        }

        fields, total_weight, equipped_count = _build_melee_fields(data)

        assert len(fields) == 2
        assert total_weight == pytest.approx(8.0)
        assert equipped_count == 1

    def test_long_mode_lists_split_into_complete_continuation_fields(self):
        weapon = melee_weapon(
            name="Espada de Ossos",
            is_equipped=1,
            modes=bulky_modes(),
        )

        fields, total_weight, equipped_count = _build_melee_fields(
            {"melee_weapons": [weapon]}
        )

        assert len(fields) > 1
        assert fields[0][0] == "[EQUIPADO] Espada de Ossos (x1)"
        assert fields[1][0] == "[EQUIPADO] Espada de Ossos (x1) - Modos (cont.)"
        joined = "\n".join(value for _, value in fields)
        for index in range(4):
            assert f"Modo {index}:" in joined
        assert all(len(value) <= 1000 for _, value in fields)
        assert all(value.startswith("```ansi\n") for _, value in fields)
        assert all(value.endswith("\n```") for _, value in fields)
        assert total_weight == pytest.approx(2.5)
        assert equipped_count == 1

    def test_empty_weapon_list_yields_no_fields(self):
        assert _build_melee_fields({"melee_weapons": []}) == ([], 0.0, 0)


class TestBuildRangedFields:
    def test_builds_ranged_weapon_statistics(self):
        weapon = ranged_weapon(
            name="Pistola",
            damage="2d+1 pi+",
            acc=2,
            range_half=150,
            range_max=1500,
            shots="7(3)",
            weight=1.0,
            quantity=3,
            is_equipped=0,
        )

        fields, total_weight, equipped_count = _build_ranged_fields(
            {"ranged_weapons": [weapon]}
        )

        assert len(fields) == 1
        name, value = fields[0]
        assert name == "[GUARDADO] Pistola (x3)"
        assert total_weight == pytest.approx(3.0)
        assert equipped_count == 0
        assert "3.00 kg" in value
        assert "Dano" in value
        assert "2d+1 pi+" in value
        assert "Precisão" in value
        assert "2" in value
        assert "Alcance" in value
        assert "150/1500" in value
        assert "Tiros" in value
        assert "7(3)" in value

    def test_equipped_ranged_weapon_uses_equipado_badge(self):
        fields, _, equipped_count = _build_ranged_fields(
            {"ranged_weapons": [ranged_weapon(is_equipped=1)]}
        )

        assert fields[0][0].startswith("[EQUIPADO] ")
        assert equipped_count == 1

    def test_empty_weapon_list_yields_no_fields(self):
        assert _build_ranged_fields({"ranged_weapons": []}) == ([], 0.0, 0)


class TestBuildArmorFields:
    def test_multiplies_weight_and_cost_by_quantity(self):
        flexible = armor(
            name="Couro (Tronco)",
            dr=2,
            is_flexible=1,
            location="Tronco",
            weight=5.0,
            cost=100.0,
            quantity=2,
            is_equipped=1,
        )
        rigid = armor(
            name="Placas (Cabeça)",
            dr=5,
            is_flexible=0,
            location="Cabeça",
            weight=2.5,
            cost=150.0,
            quantity=1,
            is_equipped=0,
        )

        fields, total_weight, equipped_count, has_flexible = _build_armor_fields(
            {"armors": [flexible, rigid]}
        )

        assert len(fields) == 2
        assert total_weight == pytest.approx(12.5)
        assert equipped_count == 1
        assert has_flexible is True

        first_name, first_value = fields[0]
        assert first_name == "[EQUIPADO] Couro (Tronco) (x2)"
        assert "10.00 kg" in first_value
        assert "$ 200.00" in first_value
        assert "RD" in first_value
        assert "2*" in first_value
        assert "Local" in first_value
        assert "Tronco" in first_value

        second_name, second_value = fields[1]
        assert second_name == "[GUARDADO] Placas (Cabeça) (x1)"
        assert "2.50 kg" in second_value
        assert "$ 150.00" in second_value
        assert "5*" not in second_value
        assert "Cabeça" in second_value

    def test_all_rigid_armor_reports_no_flexible_piece(self):
        _, _, _, has_flexible = _build_armor_fields(
            {"armors": [armor(is_flexible=0)]}
        )

        assert has_flexible is False

    def test_flexible_flag_comes_from_a_single_piece(self):
        _, _, _, has_flexible = _build_armor_fields(
            {"armors": [armor(is_flexible=0), armor(is_flexible=1)]}
        )

        assert has_flexible is True

    def test_empty_armor_list_yields_no_fields(self):
        assert _build_armor_fields({"armors": []}) == ([], 0.0, 0, False)


class TestBuildItemFields:
    def test_builds_items_with_description_and_quantity(self):
        items = [
            item(name="Corda", weight=1.0, description="Corda `forte`", quantity=2),
            item(name="Rações", weight=1.5, description="", quantity=3),
        ]

        fields, total_weight = _build_item_fields({"items": items})

        assert len(fields) == 2
        assert total_weight == pytest.approx(6.5)

        name, value = fields[0]
        assert name == "Corda"
        assert "2.00 kg" in value
        assert "Qtd" in value
        assert "x2" in value
        # ansi() sanitizes backticks before painting the fragment.
        assert "Corda 'forte'" in value

        assert fields[1][0] == "Rações"
        assert "4.50 kg" in fields[1][1]
        assert "x3" in fields[1][1]
        assert "Rações" not in fields[1][1]

    def test_missing_description_skips_the_extra_line(self):
        fields, _ = _build_item_fields(
            {"items": [item(description="", quantity=1)]}
        )

        # One metadata line only: Peso | Qtd.
        assert fields[0][1].count("\n") == 2  # opening fence, line, closing fence

    def test_empty_item_list_yields_no_fields(self):
        assert _build_item_fields({"items": []}) == ([], 0.0)


class TestBuildSummaryPage:
    def test_empty_inventory_without_strength(self):
        page = _build_summary_page(inventory_data(), 0.0, 0, 0, None)

        assert page["title"] == "Inventário: Cobaia"
        assert page["color"] == discord.Color.gold()
        assert page["description"] == "*Nenhum equipamento ou item registrado.*"
        assert [field[0] for field in page["fields"]] == [
            "Dinheiro",
            "Peso Total",
            "Equipados",
            "Itens",
        ]
        assert all(len(field) == 3 and field[2] is True for field in page["fields"])
        values = {field[0]: field[1] for field in page["fields"]}
        assert "$ 25" in values["Dinheiro"]
        assert "0.00 kg" in values["Peso Total"]
        assert "0" in values["Equipados"]
        assert "0" in values["Itens"]

    def test_populated_inventory_without_strength(self):
        page = _build_summary_page(inventory_data(money=1234), 13.0, 2, 4, None)

        assert page["description"] == "*Registro de equipamento e carga do personagem.*"
        values = {field[0]: field[1] for field in page["fields"]}
        assert "$ 1234" in values["Dinheiro"]
        assert "13.00 kg" in values["Peso Total"]
        assert "2" in values["Equipados"]
        assert "4" in values["Itens"]
        assert "Carga" not in values

    def test_strength_adds_the_encumbrance_field(self):
        # BL 10, weight 15 -> Leve (-1).
        page = _build_summary_page(inventory_data(), 15.0, 0, 1, 10)

        values = {field[0]: field[1] for field in page["fields"]}
        assert "Carga" in values
        assert "Leve (-1)" in values["Carga"]

    def test_unencumbered_strength_has_no_penalty_parenthesis(self):
        page = _build_summary_page(inventory_data(), 5.0, 0, 1, 10)

        values = {field[0]: field[1] for field in page["fields"]}
        assert "Nenhuma" in values["Carga"]
        assert "(0)" not in values["Carga"]
        assert "(-1)" not in values["Carga"]


class TestPaginateFields:
    def test_empty_field_list_returns_no_pages(self):
        assert _paginate_fields([], "T", None) == []

    def test_splits_when_the_budget_is_exceeded(self):
        fields = [("a", "1234"), ("b", "5678")]

        pages = _paginate_fields(fields, "T", None, budget=70)

        assert pages == [[("a", "1234")], [("b", "5678")]]

    def test_stays_on_page_when_the_budget_is_exactly_reached(self):
        fields = [("a", "1234"), ("b", "")]

        pages = _paginate_fields(fields, "T", None, budget=71)

        assert pages == [fields]

    def test_caps_each_page_at_twenty_five_fields(self):
        fields = [(f"f{index}", "") for index in range(26)]

        pages = _paginate_fields(fields, "", None, budget=100000)

        assert [len(page) for page in pages] == [25, 1]
        assert pages[0][0] == ("f0", "")
        assert pages[1][-1] == ("f25", "")

    def test_description_only_counts_towards_the_first_page(self):
        # used = 1 + 1000 + 64 = 1065; "a" reaches 1066, "b" overflows.
        # The reset uses len(title) + 64 = 65, so "b" and "c" share page 2.
        fields = [("a", ""), ("b", ""), ("c", "")]

        pages = _paginate_fields(fields, "T", "d" * 1000, budget=1066)

        assert pages == [[("a", "")], [("b", ""), ("c", "")]]

    def test_preserves_field_order_and_tuples(self):
        fields = [("n1", "v1"), ("n2", "v2")]

        pages = _paginate_fields(fields, "T", None)

        assert pages == [fields]
        assert pages[0][0] is fields[0]

    def test_default_budget_splits_payloads_above_5400_characters(self):
        # Base use = 65; each 600-char field pushes the running total by 600.
        fields = [(f"f{index}", "x" * 595) for index in range(10)]

        pages = _paginate_fields(fields, "T", None)

        assert [len(page) for page in pages] == [8, 2]


class TestAppendCategoryPages:
    def test_empty_fields_append_nothing(self):
        pages = []

        _append_category_pages(
            pages, "Cobaia", "Itens Gerais", discord.Color.dark_grey(), [], 0.0
        )

        assert pages == []

    def test_single_field_uses_singular_description(self):
        pages = []
        fields = [("[EQUIPADO] Machado (x1)", "corpo")]

        _append_category_pages(
            pages,
            "Cobaia",
            "Armas Corpo a Corpo",
            discord.Color.dark_red(),
            fields,
            2.5,
        )

        assert len(pages) == 1
        page = pages[0]
        assert page["title"] == "Armas Corpo a Corpo: Cobaia"
        assert page["description"] == "*1 item - 2.50 kg*"
        assert page["color"] == discord.Color.dark_red()
        assert page["fields"] == [(fields[0][0], fields[0][1], False)]

    def test_multiple_fields_use_plural_description(self):
        pages = []
        fields = [("a", "1"), ("b", "2")]

        _append_category_pages(
            pages, "Cobaia", "Itens Gerais", discord.Color.dark_grey(), fields, 3.0
        )

        assert pages[0]["description"] == "*2 itens - 3.00 kg*"

    def test_legend_is_appended_to_the_first_page_description(self):
        pages = []

        _append_category_pages(
            pages,
            "Cobaia",
            "Armaduras",
            discord.Color.dark_blue(),
            [("a", "1")],
            5.0,
            legend="* RD flexível",
        )

        assert pages[0]["description"] == "*1 item - 5.00 kg*\n* RD flexível"

    def test_extra_chunks_become_continuation_pages(self):
        pages = []
        fields = [(f"item {index}", "x") for index in range(26)]

        _append_category_pages(
            pages, "Cobaia", "Itens Gerais", discord.Color.dark_grey(), fields, 10.0
        )

        assert len(pages) == 2
        assert pages[0]["title"] == "Itens Gerais: Cobaia"
        assert pages[0]["description"] == "*26 itens - 10.00 kg*"
        assert len(pages[0]["fields"]) == 25
        assert pages[1]["title"] == "Itens Gerais: Cobaia (continuação)"
        assert pages[1]["description"] is None
        assert len(pages[1]["fields"]) == 1


class TestBuildInventoryPages:
    def test_empty_inventory_produces_a_single_summary_page(self):
        pages = build_inventory_pages(inventory_data(), strength=10)

        assert len(pages) == 1
        assert pages[0]["title"] == "Inventário: Cobaia"
        assert "Carga" in [field[0] for field in pages[0]["fields"]]

    def test_pages_follow_the_category_order_and_summary_totals(self):
        data = inventory_data(
            melee_weapons=[
                melee_weapon(weight=2.0, quantity=2, is_equipped=1),
            ],
            ranged_weapons=[
                ranged_weapon(weight=1.0, quantity=1, is_equipped=1),
            ],
            armors=[
                armor(weight=5.0, cost=100.0, quantity=1, is_equipped=0),
            ],
            items=[
                item(weight=1.5, quantity=2),
            ],
        )

        pages = build_inventory_pages(data, strength=10)

        assert [page["title"] for page in pages] == [
            "Inventário: Cobaia",
            "Armas Corpo a Corpo: Cobaia",
            "Armas a Distância: Cobaia",
            "Armaduras: Cobaia",
            "Itens Gerais: Cobaia",
        ]

        summary = {field[0]: field[1] for field in pages[0]["fields"]}
        assert "13.00 kg" in summary["Peso Total"]
        assert "2" in summary["Equipados"]
        assert "4" in summary["Itens"]

        assert "*1 item - 4.00 kg*" == pages[1]["description"]
        assert "*1 item - 1.00 kg*" == pages[2]["description"]
        assert "*1 item - 5.00 kg*\n* RD flexível" == pages[3]["description"]
        assert "*1 item - 3.00 kg*" == pages[4]["description"]

    def test_continuation_fields_do_not_inflate_item_counts(self):
        data = inventory_data(
            melee_weapons=[melee_weapon(is_equipped=1, modes=bulky_modes())],
        )

        pages = build_inventory_pages(data, strength=10)

        summary = {field[0]: field[1] for field in pages[0]["fields"]}
        assert "1" in summary["Itens"]
        assert pages[1]["description"] == "*1 item - 2.50 kg*"
        melee_fields = [
            field
            for page in pages[1:]
            if page["title"].startswith("Armas Corpo a Corpo")
            for field in page["fields"]
        ]
        assert len(melee_fields) > 1

    def test_armor_legend_is_absent_when_all_pieces_are_rigid(self):
        data = inventory_data(armors=[armor(is_flexible=0)])

        pages = build_inventory_pages(data, strength=10)

        armor_page = pages[1]
        assert armor_page["title"] == "Armaduras: Cobaia"
        assert armor_page["description"] == "*1 item - 5.00 kg*"
        assert "RD flexível" not in armor_page["description"]

    def test_without_strength_the_summary_has_no_encumbrance_field(self):
        pages = build_inventory_pages(inventory_data())

        assert "Carga" not in [field[0] for field in pages[0]["fields"]]

    def test_database_payload_feeds_the_builders(self, db):
        # Integration cross-check of the real payload keys and the modular
        # armor formula: weight_torso * factor * quantity.
        character_id = insert_character(db)
        material_id = insert_armor_material(
            db, name="Couro Médio", dr=3, is_flexible=1, cost_torso=100.0, weight_torso=5.0
        )
        part_id = insert_body_part(db, name="Tronco", factor=0.5)
        link_armor(
            db, character_id, material_id, part_id, quantity=2, is_equipped=1
        )
        item_id = insert_item(db, name="Corda", weight=1.0, cost=10.0)
        link_item(db, character_id, item_id, quantity=3)

        data = get_character_inventory_data(db, owner_id=1)
        pages = build_inventory_pages(data, strength=10)

        titles = [page["title"] for page in pages]
        assert titles == [
            "Inventário: Cobaia",
            "Armaduras: Cobaia",
            "Itens Gerais: Cobaia",
        ]

        armor_value = pages[1]["fields"][0][1]
        assert "5.00 kg" in armor_value
        assert "$ 100.00" in armor_value

        item_value = pages[2]["fields"][0][1]
        assert "3.00 kg" in item_value
