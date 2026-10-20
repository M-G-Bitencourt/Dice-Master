"""Tests for the character query helpers in utils/db_functions.py.

Every dictionary key and value asserted here mirrors the real implementation.
"""

from __future__ import annotations

import pytest

from helpers import (
    insert_advantage,
    insert_armor_material,
    insert_body_part,
    insert_character,
    insert_disadvantage,
    insert_item,
    insert_melee_mode,
    insert_melee_weapon,
    insert_ranged_weapon,
    insert_skill,
    insert_spell,
    insert_spell_class,
    link_advantage,
    link_armor,
    link_disadvantage,
    link_item,
    link_melee_weapon,
    link_ranged_weapon,
    link_skill,
    link_spell,
)
from utils import db_functions
from utils.db_functions import (
    get_character_inventory_data,
    get_character_inventory_data_by_id,
    get_character_skills_data,
    get_character_spells_data,
    get_character_traits_data,
)

SKILL_KEYS = {
    "skill_id",
    "name",
    "attribute",
    "difficulty",
    "description",
    "relative_level",
    "relative_display",
    "nh",
}

SPELL_KEYS = {
    "spell_id",
    "name",
    "school",
    "attribute",
    "difficulty",
    "cost",
    "resource",
    "description",
    "relative_level",
    "relative_display",
    "nh",
}

TRAIT_KEYS = {
    "trait_key",
    "trait_id",
    "category",
    "name",
    "cost",
    "description",
    "notes",
}

MELEE_KEYS = {
    "character_melee_id",
    "name",
    "min_st",
    "weight",
    "cost",
    "quantity",
    "is_equipped",
    "modes",
}

MELEE_MODE_KEYS = {
    "mode_name",
    "skill_id",
    "skill_name",
    "damage_base",
    "damage_modifier",
    "damage_type",
    "reach",
    "parry",
    "notes",
}

RANGED_KEYS = {
    "name",
    "damage",
    "acc",
    "range_half",
    "range_max",
    "shots",
    "weight",
    "quantity",
    "is_equipped",
}

ARMOR_KEYS = {
    "name",
    "dr",
    "is_flexible",
    "location",
    "weight",
    "cost",
    "quantity",
    "is_equipped",
}

ITEM_KEYS = {"name", "weight", "description", "quantity"}

INVENTORY_KEYS = {
    "character_id",
    "character_name",
    "money",
    "melee_weapons",
    "ranged_weapons",
    "armors",
    "items",
}


def link_additional_stat(connection, character_id: int, stat_name: str, value: int) -> int:
    cursor = connection.cursor()
    cursor.execute("INSERT INTO additional_stats (stat) VALUES (?)", (stat_name,))
    stat_id = cursor.lastrowid
    cursor.execute(
        """
        INSERT INTO character_additional_stats (character_id, additional_stat_id, value)
        VALUES (?, ?, ?)
        """,
        (character_id, stat_id, value),
    )
    connection.commit()
    return int(stat_id)


class TestGetCharacterSkillsData:
    def test_returns_none_for_unknown_character(self, db):
        assert get_character_skills_data(db, 999) is None

    def test_item_contract_and_metadata_defaults(self, db):
        character_id = insert_character(db, name="Perita")
        skill_id = insert_skill(
            db, name="Furtividade", attribute="IQ", difficulty_id=None, description=None
        )
        link_skill(db, character_id, skill_id, 2)

        data = get_character_skills_data(db, character_id)

        assert set(data) == {"character_id", "character_name", "skills"}
        assert data["character_id"] == character_id
        assert data["character_name"] == "Perita"
        item = data["skills"][0]
        assert set(item) == SKILL_KEYS
        assert item == {
            "skill_id": skill_id,
            "name": "Furtividade",
            "attribute": "IQ",
            "difficulty": "M",
            "description": "Nenhuma descrição detalhada disponível.",
            "relative_level": 2,
            "relative_display": "IQ+2",
            "nh": 12,
        }

    def test_effective_skill_level_uses_attribute_plus_relative_level(self, db):
        character_id = insert_character(
            db, st=11, dx=12, iq=13, ht=14, additional_per=2, additional_vont=3
        )
        specs = {
            "DX skill": ("DX", 1, 13, "DX", "DX+1"),
            "IQ skill": ("IQ", -2, 11, "IQ", "IQ-2"),
            "HT skill": ("HT", 0, 14, "HT", "HT+0"),
            "ST skill": ("ST", 4, 15, "ST", "ST+4"),
            "Per skill": ("PER", 1, 16, "Per", "Per+1"),
            "Percepção skill": ("Percepção", 0, 15, "Per", "Per+0"),
            "Vont skill": ("VONT", 2, 18, "Vont", "Vont+2"),
            "Will skill": ("WILL", -1, 15, "Vont", "Vont-1"),
        }
        for name, (attribute, relative, _nh, _label, _display) in specs.items():
            skill_id = insert_skill(db, name=name, attribute=attribute)
            link_skill(db, character_id, skill_id, relative)

        data = get_character_skills_data(db, character_id)
        by_name = {item["name"]: item for item in data["skills"]}

        assert len(by_name) == len(specs)
        for name, (attribute, relative, nh, label, display) in specs.items():
            item = by_name[name]
            assert item["nh"] == nh
            assert item["attribute"] == label
            assert item["relative_level"] == relative
            assert item["relative_display"] == display

    def test_additional_stats_are_normalized_and_used_as_base(self, db):
        character_id = insert_character(db, dx=10)
        link_additional_stat(db, character_id, "  Vigor  ", 14)
        skill_id = insert_skill(db, name="Resistência", attribute="vIgOr")
        link_skill(db, character_id, skill_id, 2)

        item = get_character_skills_data(db, character_id)["skills"][0]

        assert item["nh"] == 16
        # The display label preserves the raw attribute text stored on the skill row.
        assert item["attribute"] == "vIgOr"

    def test_additional_stats_dict_normalizes_keys(self, db):
        character_id = insert_character(db)
        link_additional_stat(db, character_id, "  Vigor  ", 14)

        stats = db_functions._get_character_additional_stats_dict(db, character_id)

        assert stats == {"VIGOR": 14}

    def test_unknown_attribute_falls_back_to_dx(self, db):
        character_id = insert_character(db, dx=12)
        skill_id = insert_skill(db, name="Culinária", attribute="Culinária")
        link_skill(db, character_id, skill_id, 3)

        item = get_character_skills_data(db, character_id)["skills"][0]

        assert item["nh"] == 15
        assert item["attribute"] == "Culinária"

    def test_missing_attribute_falls_back_to_dx_label(self, db):
        character_id = insert_character(db, dx=12)
        skill_id = insert_skill(db, name="Global", attribute=None)
        link_skill(db, character_id, skill_id, 0)

        item = get_character_skills_data(db, character_id)["skills"][0]

        assert item["attribute"] == "DX"
        assert item["nh"] == 12

    def test_missing_relative_level_defaults_to_zero(self, db):
        character_id = insert_character(db, dx=12)
        skill_id = insert_skill(db, name="Global", attribute="DX")
        link_skill(db, character_id, skill_id, None)

        item = get_character_skills_data(db, character_id)["skills"][0]

        assert item["relative_level"] == 0
        assert item["relative_display"] == "DX+0"
        assert item["nh"] == 12

    def test_orders_by_name_case_insensitively(self, db):
        character_id = insert_character(db)
        for name in ("zeta", "Alpha", "beta"):
            link_skill(db, character_id, insert_skill(db, name=name), 0)

        names = [item["name"] for item in get_character_skills_data(db, character_id)["skills"]]

        assert names == ["Alpha", "beta", "zeta"]

    def test_keeps_the_catalog_difficulty_and_description(self, db):
        character_id = insert_character(db)
        skill_id = insert_skill(
            db, name="Esquiva", attribute="DX", difficulty_id=3, description="Descrição real"
        )
        link_skill(db, character_id, skill_id, 1)

        item = get_character_skills_data(db, character_id)["skills"][0]

        assert item["difficulty"] == "Hard"
        assert item["description"] == "Descrição real"


class TestGetCharacterSpellsData:
    def test_returns_none_for_unknown_character(self, db):
        assert get_character_spells_data(db, 999) is None

    def test_item_contract_and_fallbacks_for_missing_metadata(self, db):
        character_id = insert_character(db, name="Maga", iq=13)
        spell_id = insert_spell(
            db,
            name="Míssil Mágico",
            attribute=None,
            class_id=None,
            difficulty_id=None,
            cost=None,
            resource=None,
            description=None,
        )
        link_spell(db, character_id, spell_id, 0)

        data = get_character_spells_data(db, character_id)

        assert set(data) == {"character_id", "character_name", "spells"}
        assert data["character_id"] == character_id
        assert data["character_name"] == "Maga"
        item = data["spells"][0]
        assert set(item) == SPELL_KEYS
        assert item == {
            "spell_id": spell_id,
            "name": "Míssil Mágico",
            "school": "Sem Escola",
            "attribute": "IQ",
            "difficulty": "M",
            "cost": 0,
            "resource": "PF",
            "description": "Nenhuma descrição detalhada disponível.",
            "relative_level": 0,
            "relative_display": "IQ+0",
            "nh": 13,
        }

    def test_effective_skill_level_across_attributes(self, db):
        character_id = insert_character(
            db, st=11, dx=12, iq=13, ht=14, additional_per=2, additional_vont=3
        )
        specs = {
            "DX spell": ("DX", 1, 13, "DX"),
            "HT spell": ("HT", -1, 13, "HT"),
            "ST spell": ("ST", 2, 13, "ST"),
            "Per spell": ("Per", 1, 16, "Per"),
            "Vont spell": ("Vont", -3, 13, "Vont"),
            "Unknown spell": ("Astrologia", 4, 17, "Astrologia"),
        }
        for name, (attribute, relative, _nh, _label) in specs.items():
            spell_id = insert_spell(db, name=name, attribute=attribute, class_id=None)
            link_spell(db, character_id, spell_id, relative)

        data = get_character_spells_data(db, character_id)
        by_name = {item["name"]: item for item in data["spells"]}

        for name, (_attribute, relative, nh, label) in specs.items():
            item = by_name[name]
            assert item["nh"] == nh
            assert item["attribute"] == label
            assert item["relative_level"] == relative
            assert item["relative_display"] == f"{label}{relative:+d}"

    def test_resource_is_stripped_uppercased_and_defaults_to_pf(self, db):
        character_id = insert_character(db)
        first_id = insert_spell(db, name="A", resource=" er ", class_id=None)
        second_id = insert_spell(db, name="B", resource=None, class_id=None)
        link_spell(db, character_id, first_id, 0)
        link_spell(db, character_id, second_id, 0)

        resources = {
            item["name"]: item["resource"]
            for item in get_character_spells_data(db, character_id)["spells"]
        }

        assert resources == {"A": "ER", "B": "PF"}

    def test_real_school_is_used_and_order_is_school_then_name(self, db):
        character_id = insert_character(db)
        fogo_id = insert_spell_class(db, "Fogo")
        gelo_id = insert_spell_class(db, "Gelo")
        spells = (
            (insert_spell(db, name="Bola", class_id=None), 0),
            (insert_spell(db, name="Chama", class_id=fogo_id), 0),
            (insert_spell(db, name="Anel", class_id=fogo_id), 0),
            (insert_spell(db, name="Nevasca", class_id=gelo_id), 0),
        )
        for spell_id, relative in spells:
            link_spell(db, character_id, spell_id, relative)

        items = get_character_spells_data(db, character_id)["spells"]

        assert [item["name"] for item in items] == ["Bola", "Anel", "Chama", "Nevasca"]
        assert {item["name"]: item["school"] for item in items} == {
            "Bola": "Sem Escola",
            "Anel": "Fogo",
            "Chama": "Fogo",
            "Nevasca": "Gelo",
        }

    def test_keeps_catalog_difficulty_and_cost(self, db):
        character_id = insert_character(db)
        spell_id = insert_spell(db, name="Luz", difficulty_id=1, cost=2, class_id=None)
        link_spell(db, character_id, spell_id, 1)

        item = get_character_spells_data(db, character_id)["spells"][0]

        assert item["difficulty"] == "Easy"
        assert item["cost"] == 2


class TestGetCharacterTraitsData:
    def test_returns_none_for_unknown_character(self, db):
        assert get_character_traits_data(db, 999) is None

    def test_advantages_and_disadvantages_contract(self, db):
        character_id = insert_character(db, name="Traçada")
        advantage_id = insert_advantage(db, name="Reflexos", cost=15, description="Descrição vantagem")
        disadvantage_id = insert_disadvantage(db, name="Miopia", cost=-10, description=None)
        link_advantage(db, character_id, advantage_id, notes="Nota do jogador")
        link_disadvantage(db, character_id, disadvantage_id, notes=None)

        data = get_character_traits_data(db, character_id)

        assert set(data) == {"character_id", "character_name", "advantages", "disadvantages"}
        assert data["character_id"] == character_id
        assert data["character_name"] == "Traçada"

        advantage = data["advantages"][0]
        assert set(advantage) == TRAIT_KEYS
        assert advantage == {
            "trait_key": f"adv_{advantage_id}",
            "trait_id": advantage_id,
            "category": "Vantagem",
            "name": "Reflexos",
            "cost": 15,
            "description": "Descrição vantagem",
            "notes": "Nota do jogador",
        }

        disadvantage = data["disadvantages"][0]
        assert set(disadvantage) == TRAIT_KEYS
        assert disadvantage == {
            "trait_key": f"dis_{disadvantage_id}",
            "trait_id": disadvantage_id,
            "category": "Desvantagem",
            "name": "Miopia",
            "cost": -10,
            "description": "Nenhuma descrição detalhada disponível.",
            "notes": "",
        }

    def test_null_cost_defaults_to_zero_and_names_are_sorted(self, db):
        character_id = insert_character(db)
        zeta_id = insert_advantage(db, name="zeta", cost=None)
        alpha_id = insert_advantage(db, name="Alpha", cost=5)
        link_advantage(db, character_id, zeta_id)
        link_advantage(db, character_id, alpha_id)

        advantages = get_character_traits_data(db, character_id)["advantages"]

        assert [item["name"] for item in advantages] == ["Alpha", "zeta"]
        by_name = {item["name"]: item for item in advantages}
        assert by_name["zeta"]["cost"] == 0


class TestGetCharacterInventoryData:
    def test_returns_none_for_unknown_character(self, db):
        assert get_character_inventory_data_by_id(db, 999) is None

    def test_empty_inventory_returns_empty_collections(self, db):
        character_id = insert_character(db, name="Vazia", money=25)

        data = get_character_inventory_data_by_id(db, character_id)

        assert set(data) == INVENTORY_KEYS
        assert data["character_id"] == character_id
        assert data["character_name"] == "Vazia"
        assert data["money"] == 25
        assert data["melee_weapons"] == []
        assert data["ranged_weapons"] == []
        assert data["armors"] == []
        assert data["items"] == []

    def test_melee_weapons_include_modes_and_custom_name(self, db):
        character_id = insert_character(db)
        skill_id = insert_skill(db, name="Machado", attribute="DX")
        axe_id = insert_melee_weapon(db, name="Machado", min_st=11, weight=2.5, cost=60.0)
        insert_melee_mode(
            db,
            axe_id,
            skill_id,
            mode_name="Corte",
            damage_base="GeB",
            damage_modifier=2,
            damage_type="corte",
            reach="1",
            parry="0U",
            notes="Pesado",
        )
        insert_melee_mode(
            db,
            axe_id,
            skill_id,
            mode_name="Padrão",
            damage_base="GdP",
            damage_modifier=0,
            damage_type="perfuração",
            reach="1",
            parry="0",
            notes=None,
        )
        instance_id = link_melee_weapon(
            db, character_id, axe_id, quantity=1, is_equipped=1, custom_name="Fúria"
        )
        sword_id = insert_melee_weapon(db, name="Espada Longa", min_st=10, weight=1.5, cost=120.0)
        link_melee_weapon(db, character_id, sword_id, quantity=2, is_equipped=0)

        data = get_character_inventory_data_by_id(db, character_id)
        weapons = data["melee_weapons"]

        assert [item["name"] for item in weapons] == ["Fúria", "Espada Longa"]
        equipped = weapons[0]
        assert set(equipped) == MELEE_KEYS
        assert equipped == {
            "character_melee_id": instance_id,
            "name": "Fúria",
            "min_st": 11,
            "weight": 2.5,
            "cost": 60.0,
            "quantity": 1,
            "is_equipped": 1,
            "modes": [
                {
                    "mode_name": "Corte",
                    "skill_id": skill_id,
                    "skill_name": "Machado",
                    "damage_base": "GeB",
                    "damage_modifier": 2,
                    "damage_type": "corte",
                    "reach": "1",
                    "parry": "0U",
                    "notes": "Pesado",
                },
                {
                    "mode_name": "Padrão",
                    "skill_id": skill_id,
                    "skill_name": "Machado",
                    "damage_base": "GdP",
                    "damage_modifier": 0,
                    "damage_type": "perfuração",
                    "reach": "1",
                    "parry": "0",
                    "notes": None,
                },
            ],
        }
        assert all(set(mode) == MELEE_MODE_KEYS for mode in equipped["modes"])

    def test_melee_without_custom_name_uses_the_catalog_name(self, db):
        character_id = insert_character(db)
        weapon_id = insert_melee_weapon(db, name="Lança")
        link_melee_weapon(db, character_id, weapon_id)

        item = get_character_inventory_data_by_id(db, character_id)["melee_weapons"][0]

        assert item["name"] == "Lança"
        assert item["modes"] == []

    def test_ranged_weapons_are_equipped_first_and_keep_their_columns(self, db):
        character_id = insert_character(db)
        bow_id = insert_ranged_weapon(
            db,
            name="Arco Curto",
            damage="1d-1 imp",
            acc=3,
            range_half=75,
            range_max=100,
            shots="1(2)",
            weight=1.0,
        )
        link_ranged_weapon(db, character_id, bow_id, quantity=1, is_equipped=1)
        gun_id = insert_ranged_weapon(db, name="Zarabatana", weight=0.5)
        link_ranged_weapon(db, character_id, gun_id, quantity=3, is_equipped=0)

        weapons = get_character_inventory_data_by_id(db, character_id)["ranged_weapons"]

        assert [item["name"] for item in weapons] == ["Arco Curto", "Zarabatana"]
        assert set(weapons[0]) == RANGED_KEYS
        assert weapons[0] == {
            "name": "Arco Curto",
            "damage": "1d-1 imp",
            "acc": 3,
            "range_half": 75,
            "range_max": 100,
            "shots": "1(2)",
            "weight": 1.0,
            "quantity": 1,
            "is_equipped": 1,
        }
        assert weapons[1]["quantity"] == 3

    def test_armor_default_name_location_and_factor(self, db):
        character_id = insert_character(db)
        material_id = insert_armor_material(
            db,
            name="Couro Médio",
            dr=2,
            is_flexible=1,
            cost_torso=100.0,
            weight_torso=5.0,
        )
        torso_id = insert_body_part(db, name="Tronco", factor=0.5)
        head_id = insert_body_part(db, name="Cabeça", factor=0.25)
        link_armor(db, character_id, material_id, torso_id, quantity=1, is_equipped=1)
        link_armor(db, character_id, material_id, head_id, quantity=1, is_equipped=0, custom_name="Elmo")

        armors = get_character_inventory_data_by_id(db, character_id)["armors"]

        assert [item["name"] for item in armors] == ["Couro Médio (Tronco)", "Elmo"]
        torso = armors[0]
        assert set(torso) == ARMOR_KEYS
        assert torso == {
            "name": "Couro Médio (Tronco)",
            "dr": 2,
            "is_flexible": 1,
            "location": "Tronco",
            "weight": 2.5,
            "cost": 50.0,
            "quantity": 1,
            "is_equipped": 1,
        }
        assert armors[1] == {
            "name": "Elmo",
            "dr": 2,
            "is_flexible": 1,
            "location": "Cabeça",
            "weight": 1.25,
            "cost": 25.0,
            "quantity": 1,
            "is_equipped": 0,
        }

    def test_armor_weight_and_cost_ignore_quantity(self, db):
        # Suspicious behavior: AGENTS.md defines
        # final_weight = weight_torso * cost_weight_factor * quantity (same for cost),
        # but the SQL at utils/db_functions.py:515-516 never multiplies by quantity.
        # Pinning the current behavior; reported as a suspected bug.
        character_id = insert_character(db)
        material_id = insert_armor_material(
            db, name="Placas", cost_torso=200.0, weight_torso=8.0
        )
        torso_id = insert_body_part(db, name="Tronco", factor=0.25)
        link_armor(db, character_id, material_id, torso_id, quantity=3, is_equipped=1)

        armor = get_character_inventory_data_by_id(db, character_id)["armors"][0]

        assert armor["quantity"] == 3
        assert armor["weight"] == pytest.approx(2.0)  # 8.0 * 0.25, expected 6.0 with quantity
        assert armor["cost"] == pytest.approx(50.0)  # 200.0 * 0.25, expected 150.0 with quantity

    def test_items_keep_quantity_and_are_sorted_by_name(self, db):
        character_id = insert_character(db)
        rope_id = insert_item(db, name="Corda", weight=1.5, description="De escalada")
        torch_id = insert_item(db, name="Tocha", weight=0.5, description=None)
        link_item(db, character_id, rope_id, quantity=2)
        link_item(db, character_id, torch_id, quantity=3)

        items = get_character_inventory_data_by_id(db, character_id)["items"]

        assert [item["name"] for item in items] == ["Corda", "Tocha"]
        assert set(items[0]) == ITEM_KEYS
        assert items[0] == {
            "name": "Corda",
            "weight": 1.5,
            "description": "De escalada",
            "quantity": 2,
        }
        assert items[1] == {
            "name": "Tocha",
            "weight": 0.5,
            "description": None,
            "quantity": 3,
        }

    def test_owner_wrapper_resolves_the_character(self, db):
        character_id = insert_character(db, owner_id=55, name="Da owner")

        data = get_character_inventory_data(db, 55)

        assert data["character_id"] == character_id
        assert data["character_name"] == "Da owner"

    def test_owner_wrapper_returns_none_for_unknown_owner(self, db):
        assert get_character_inventory_data(db, 999) is None
