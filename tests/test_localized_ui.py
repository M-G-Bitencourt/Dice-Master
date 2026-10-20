"""English UI tests for the main sheet, inventory, help and combat builders."""

from __future__ import annotations

import types

import discord

from cogs.combat_helpers.combat_embeds import (
    _add_health_fields,
    _build_attack_embed,
    _build_defense_embed,
    build_panel_embed,
)
from cogs.combat_helpers.combat_rules import _defense_options
from cogs.help import build_help_messages
from cogs.inventory import build_inventory_pages
from cogs.sheet import build_sheet_embed
from cogs.skills import build_skill_header, build_skill_row
from cogs.spells import build_spell_header, build_spell_row
from cogs.traits import build_trait_header, build_trait_row
from utils.i18n import locale_context


def sheet_profile() -> dict:
    return {
        "character_id": 1,
        "owner_id": 1,
        "is_npc": False,
        "name": "Hero",
        "st": 12,
        "dx": 11,
        "iq": 13,
        "ht": 10,
        "additional_max_pv": 2,
        "additional_vont": 3,
        "additional_per": -1,
        "additional_max_pf": 1,
        "additional_basic_speed": 0,
        "additional_basic_move": 0,
        "energy_reserve": 5,
        "normal_diffuse_homogeneous_unded": 0,
        "money": 42,
        "current_pv": 10,
        "current_pf": 9,
        "current_er": 3,
        "current_points": 7,
    }


def inventory_data() -> dict:
    return {
        "character_id": 1,
        "character_name": "Hero",
        "money": 25,
        "melee_weapons": [
            {
                "name": "Machado",
                "weight": 2.5,
                "quantity": 1,
                "is_equipped": 1,
                "min_st": 11,
                "modes": [
                    {
                        "mode_name": "Padrão",
                        "damage_base": "GeB",
                        "damage_modifier": 2,
                        "damage_type": "corte",
                        "reach": "1",
                        "parry": "0U",
                        "notes": "",
                        "attack_modifier": 0,
                    }
                ],
            }
        ],
        "ranged_weapons": [],
        "armors": [
            {
                "name": "Couro",
                "weight": 5.0,
                "cost": 100.0,
                "quantity": 1,
                "is_equipped": 1,
                "is_flexible": 1,
                "dr": 2,
                "location": "Tronco",
            }
        ],
        "items": [
            {
                "name": "Corda",
                "weight": 1.0,
                "quantity": 2,
                "description": "Rope",
            }
        ],
    }


def assert_field(embed: discord.Embed, name: str) -> str:
    for field in embed.fields:
        if field.name == name:
            return field.value
    raise AssertionError(name)


class TestEnglishSheet:
    def test_sheet_uses_english_labels_and_hp_fp_er(self):
        with locale_context("en-US"):
            embed = build_sheet_embed(sheet_profile())

        assert "**Unspent Points:** `7`" in embed.description
        assert "**Money:** `42`" in embed.description
        assert "**HP:**" not in embed.description
        assert_field(embed, "Basic Attributes")
        secondary = assert_field(embed, "Secondary Characteristics")
        assert "Max HP: `14`" in secondary
        assert "Max FP: `11`" in secondary
        assert "Will: `16`" in secondary
        assert "Perception: `12`" in secondary
        resources = assert_field(embed, "Current Resources (HP - FP - ER)")
        assert "HP" in resources
        assert "FP" in resources
        assert "ER" in resources


class TestEnglishInventory:
    def test_inventory_uses_english_titles_badges_and_labels(self):
        with locale_context("en-US"):
            pages = build_inventory_pages(inventory_data(), strength=10)

        assert pages[0]["title"] == "Inventory: Hero"
        assert_field_names = [field[0] for field in pages[0]["fields"]]
        assert "Money" in assert_field_names
        assert "Total Weight" in assert_field_names
        assert "Load" in assert_field_names

        melee_page = next(page for page in pages if "Melee Weapons" in page["title"])
        assert "[EQUIPPED]" in melee_page["fields"][0][0]
        assert "Weight" in melee_page["fields"][0][1]
        assert "sw+2 cutting" in melee_page["fields"][0][1].lower()
        assert "Reach" in melee_page["fields"][0][1]
        assert "Parry" in melee_page["fields"][0][1]

        armor_page = next(page for page in pages if "Armor" in page["title"])
        assert "Torso" in armor_page["fields"][0][1]
        assert "Flexible DR" in armor_page["description"]


class TestEnglishListRows:
    def test_skill_spell_and_trait_rows_use_english_metrics(self):
        skill = {
            "skill_id": 1,
            "name": "Stealth",
            "nh": 12,
            "relative_display": "DX+1",
            "difficulty": "Medium",
            "attribute": "DX",
            "description": "Rules",
        }
        spell = {
            "spell_id": 1,
            "name": "Fireball",
            "nh": 14,
            "cost": 2,
            "resource": "FP",
            "relative_display": "IQ+1",
            "difficulty": "Hard",
            "attribute": "IQ",
            "school": "Fire",
            "description": "Rules",
        }
        trait = {
            "trait_key": "adv_1",
            "category": "Vantagem",
            "name": "Combat Reflexes",
            "cost": 15,
            "description": "Rules",
            "notes": "Notes",
        }

        with locale_context("en-US"):
            assert "Skill" in build_skill_row(skill)
            assert "Skill" in build_skill_header(skill)
            assert "Relative Level" in build_skill_header(skill)
            assert "Skill" in build_spell_row(spell)
            assert "Cost" in build_spell_header(spell)
            assert "Relative Level" in build_spell_header(spell)
            assert "pts" in build_trait_row(trait)
            assert "Cost" in build_trait_header(trait)


class TestEnglishHelp:
    def test_help_uses_english_categories_and_note(self):
        command = types.SimpleNamespace(
            name="sheet_test",
            description="Test description",
            binding=types.SimpleNamespace(qualified_name="Sheet"),
            default_permissions=None,
        )

        messages = build_help_messages([command], locale="en-US")
        text = "\n".join(messages)

        assert "[CHARACTER SHEET]" in text
        assert "Commands marked with [ADMIN] require administrator permission." in text


class TestEnglishCombatEmbeds:
    def test_attack_defense_and_panel_use_english_labels(self):
        outcome = {
            "critical_success": False,
            "success": True,
            "critical_failure": False,
            "margin": 2,
        }
        damage_data = {
            "expression": "2d+1 cut",
            "dices": [3, 4],
            "damage": 8,
            "total_modifier": 1,
            "critical_dices": [],
            "critical_damage": 8,
        }

        with locale_context("en-US"):
            attack = _build_attack_embed(
                actor_name="Hero",
                target_name="Foe",
                target_owner_id=2,
                weapon_name="Sword",
                mode_name="Slash",
                maneuver_label="Normal Attack",
                hit_location_name="Torso",
                damage_type_label="Cutting",
                attack_roll=9,
                attack_dices=[3, 3, 3],
                breakdown={"base": 12, "modifiers": [], "total": 0, "effective": 12},
                outcome=outcome,
                damage_data=damage_data,
                rd=2,
                rd_warnings=[],
                defense_options=[],
                awaiting_defense=False,
            )
            panel = build_panel_embed(None, None)
            defense = _build_defense_embed(
                defense_label="Dodge 8",
                waive=False,
                dices=[3, 3, 3],
                effective_nh=8,
                outcome=outcome,
                injury_data=None,
                chosen_damage=0,
                old_pv=10,
                new_pv=10,
                profile=sheet_profile(),
                rd=2,
                rd_warnings=[],
            )

        assert attack.title == "Attack: Hero -> Foe"
        assert_field(attack, "Roll")
        assert_field(attack, "Modifiers")
        damage_field = assert_field(attack, "Damage")
        assert "Weapon damage: 2d+1 cut" in damage_field
        assert "Total damage: 8 Cutting" in damage_field

        assert panel.title == "Combat Panel"
        assert "No active session in this channel." in panel.description

        assert defense.title == "Successful defense: Hero"
        assert_field(defense, "Defense")
        assert_field(defense, "Applied damage")

    def test_health_fields_and_defense_options_are_english(self):
        embed = discord.Embed()
        health = {
            "wounded": True,
            "current_pv": 4,
            "max_pv": 10,
            "move": 2,
            "dodge": 4,
            "checks": [
                {
                    "label": "0 PV",
                    "label_key": "zero_hp",
                    "dices": [3, 3, 3],
                    "target": 10,
                    "success": True,
                    "margin": 1,
                    "effect": "consciente",
                    "effect_key": "conscious",
                }
            ],
            "status": "consciente",
            "status_key": "conscious",
        }
        data = {
            "profile": {
                "st": 10,
                "dx": 10,
                "ht": 10,
                "additional_max_pv": 0,
                "additional_basic_speed": 0,
                "current_pv": 4,
            },
            "encumbrance_penalty": 0,
            "skill_by_id": {},
            "melee_modes": [],
            "conditions": {"no_defense": 0, "defense_bonus": 0},
        }

        with locale_context("en-US"):
            _add_health_fields(embed, health)
            options = _defense_options(data)

        names = [field.name for field in embed.fields]
        assert "Injury State" in names
        assert "HT Checks" in names
        assert "Character Status" in names
        assert options[0]["label"].startswith("Dodge")
