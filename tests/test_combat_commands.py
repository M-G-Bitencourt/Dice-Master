"""Tests for the combat attack and defence flow."""

from __future__ import annotations

from types import SimpleNamespace

import discord

import cogs.battle as battle_module
import cogs.combat_helpers.combat_feint as combat_feint_module
import cogs.combat_helpers.combat_attack as combat_attack_module
import cogs.combat_helpers.combat_health as combat_health_module
import cogs.combat_helpers.combat_resolution as combat_resolution_module
from cogs.combat import Combat
from cogs.combat_helpers.combat_rules import _defense_options
from cogs.combat_helpers.combat_views import CombatPanelView, DefenseView
from helpers import (
    FakeInteraction,
    FakeMessage,
    insert_armor_material,
    insert_body_part,
    insert_character,
    insert_combat_effect,
    insert_item,
    insert_melee_mode,
    insert_melee_weapon,
    insert_ranged_weapon,
    insert_skill,
    link_armor,
    link_combat_effect,
    link_item,
    link_melee_weapon,
    link_ranged_weapon,
    patch_rng,
)
from utils.db_functions import (
    add_combat_log,
    get_active_combat_session,
    get_character_combat_effects,
    get_character_conditions_by_id,
    get_combat_participant,
    get_combat_participants,
    get_equipped_melee_modes,
    ensure_combat_participant,
    get_or_create_combat_session,
    get_pending_attack,
    get_pending_attack_for_channel,
    get_recent_combat_log,
    set_combat_session_active,
    set_character_shock,
    set_player_condition,
    set_combat_session_panel,
)


def build_combatants(db) -> tuple[int, int, int]:
    attacker_id = insert_character(db, owner_id=1, name="Atacante")
    target_id = insert_character(db, owner_id=2, name="Alvo")

    skill_id = insert_skill(
        db, name="Espadas Curtas", attribute="DX", difficulty_id=2
    )
    db.execute(
        "INSERT INTO character_skills (character_id, skill_id, relative_level) VALUES (?, ?, 4)",
        (attacker_id, skill_id),
    )

    weapon_id = insert_melee_weapon(db, name="Espada Curta")
    mode_id = insert_melee_mode(
        db,
        weapon_id,
        skill_id,
        mode_name="Corte",
        damage_base="GeB",
        damage_modifier=4,
        damage_type="corte",
        parry="0",
    )
    link_melee_weapon(db, attacker_id, weapon_id, is_equipped=1)

    torso = insert_body_part(db, name="Tronco", factor=1.0)
    material_id = insert_armor_material(
        db, name="Cota", dr=2, is_flexible=1
    )
    link_armor(db, target_id, material_id, torso, is_equipped=1)
    db.commit()

    return attacker_id, target_id, mode_id


def apply_heavy_load(db, character_id: int, weight: float = 25.0) -> None:
    """Add enough carried weight to impose a -2 encumbrance penalty at ST 10."""
    item_id = insert_item(db, name="Carga de teste", weight=weight)
    link_item(db, character_id, item_id)
    db.commit()


def join_combat(db, character_ids, active_character_id: int) -> dict:
    """Seed an active session with the given participants for a command test."""
    with db:
        session = get_or_create_combat_session(db, 1, 100)
        for character_id in character_ids:
            row = db.execute(
                "SELECT owner_id, is_npc FROM characters WHERE character_id = ?",
                (character_id,),
            ).fetchone()
            ensure_combat_participant(
                db,
                session_id=int(session["session_id"]),
                character_id=character_id,
                owner_id=row[0] if row else None,
                is_npc=bool(row[1]) if row else False,
            )
        set_combat_session_active(
            db,
            int(session["session_id"]),
            active_character_id,
            1,
        )
    return get_active_combat_session(db, 100)


async def invoke_attack_raw(
    cog, interaction, attacker_id: int, target_id: int, mode_id: int
):
    await Combat.combat_attack.callback(
        cog,
        interaction,
        alvo=str(target_id),
        arma=f"{attacker_id}:{mode_id}",
        personagem=None,
        local=SimpleNamespace(value=0),
        manobra=None,
        modificador=None,
        nh_manual=None,
    )


async def attack(cog, interaction, attacker_id: int, target_id: int, mode_id: int):
    join_combat(cog.db_connection, [attacker_id, target_id], attacker_id)
    await invoke_attack_raw(
        cog, interaction, attacker_id, target_id, mode_id
    )


class TestCombatAttack:
    async def test_auto_skill_and_weapon_create_pending_attack(
        self, make_cog, interaction, db, monkeypatch
    ):
        cog = make_cog(Combat)
        attacker_id, target_id, mode_id = build_combatants(db)
        patch_rng(monkeypatch, combat_attack_module, [3, 3, 3], budget=10)
        patch_rng(monkeypatch, combat_resolution_module, [3, 3, 3], budget=10)
        patch_rng(monkeypatch, battle_module, [1], budget=10)

        await attack(cog, interaction, attacker_id, target_id, mode_id)

        assert interaction.response.deferred
        embed = interaction.edited[0]["kwargs"]["embed"]
        assert embed.title == "Ataque: Atacante -> Alvo"
        assert "[3, 3, 3] = 9" in embed.fields[0].value
        assert "|" not in embed.fields[0].value
        assert "NH 14" in embed.fields[1].value
        assert isinstance(interaction.edited[0]["kwargs"]["view"], DefenseView)

        pending = get_pending_attack_for_channel(db, 100)
        assert pending is not None
        assert pending["status"] == "pending"
        assert pending["nh_base"] == 14
        assert pending["nh_effective"] == 14
        assert pending["raw_damage"] == 5
        assert pending["critical_damage"] == 10
        assert pending["rd"] == 2
        assert pending["target_character_id"] == target_id
        assert pending["message_id"] == interaction._original_message.id

    async def test_attack_embed_shows_expression_dice_modifiers_and_total(
        self, make_cog, interaction, db, monkeypatch
    ):
        cog = make_cog(Combat)
        attacker_id, target_id, mode_id = build_combatants(db)
        db.execute(
            "UPDATE characters SET st = 13 WHERE character_id = ?",
            (attacker_id,),
        )
        db.execute(
            "UPDATE melee_weapon_modes SET damage_modifier = 0 WHERE mode_id = ?",
            (mode_id,),
        )
        db.commit()
        patch_rng(monkeypatch, combat_attack_module, [3, 3, 3], budget=10)
        patch_rng(monkeypatch, battle_module, [1, 2], budget=10)

        await attack(cog, interaction, attacker_id, target_id, mode_id)

        pending = get_pending_attack_for_channel(db, 100)
        assert pending is not None
        assert pending["raw_damage"] == 2
        embed = interaction.edited[0]["kwargs"]["embed"]
        damage_field = next(
            field.value for field in embed.fields if field.name == "Dano"
        )
        assert "Dano da arma: 2d-1" in damage_field
        assert "Dados: `[1, 2] = 3`" in damage_field
        assert "Modificadores: -1" in damage_field
        assert "Dano total: 2 Corte" in damage_field

    async def test_shock_reduces_attack_and_is_consumed(
        self, make_cog, interaction, db, monkeypatch
    ):
        cog = make_cog(Combat)
        attacker_id, target_id, mode_id = build_combatants(db)
        set_player_condition(db, 1, "shock", 3)
        patch_rng(monkeypatch, combat_attack_module, [3, 3, 3], budget=10)
        patch_rng(monkeypatch, battle_module, [1], budget=10)

        await attack(cog, interaction, attacker_id, target_id, mode_id)

        pending = get_pending_attack_for_channel(db, 100)
        assert pending is not None
        assert pending["nh_base"] == 14
        assert pending["nh_effective"] == 11
        embed = interaction.edited[0]["kwargs"]["embed"]
        assert "Choque -3" in embed.fields[1].value
        assert get_character_conditions_by_id(db, attacker_id)["shock"] == 0

    async def test_encumbrance_reduces_melee_attack_nh(
        self, make_cog, interaction, db, monkeypatch
    ):
        cog = make_cog(Combat)
        attacker_id, target_id, mode_id = build_combatants(db)
        apply_heavy_load(db, attacker_id)
        patch_rng(monkeypatch, combat_attack_module, [3, 3, 3], budget=10)
        patch_rng(monkeypatch, combat_resolution_module, [3, 3, 3], budget=10)
        patch_rng(monkeypatch, battle_module, [1], budget=10)

        await attack(cog, interaction, attacker_id, target_id, mode_id)

        pending = get_pending_attack_for_channel(db, 100)
        assert pending is not None
        assert pending["nh_base"] == 14
        assert pending["nh_effective"] == 12
        embed = interaction.edited[0]["kwargs"]["embed"]
        assert "Carga -2" in embed.fields[1].value
        assert "= NH 12" in embed.fields[1].value

    async def test_melee_attack_rejects_mode_with_unowned_skill(
        self, make_cog, interaction, db
    ):
        cog = make_cog(Combat)
        attacker_id, target_id, mode_id = build_combatants(db)
        unowned_skill = insert_skill(db, name="Briga", attribute="DX")
        db.execute(
            "UPDATE melee_weapon_modes SET skill_id = ? WHERE mode_id = ?",
            (unowned_skill, mode_id),
        )
        db.commit()
        join_combat(db, [attacker_id, target_id], attacker_id)

        await invoke_attack_raw(
            cog, interaction, attacker_id, target_id, mode_id
        )

        assert "não possui a perícia" in interaction.edited[0]["kwargs"]["content"]
        assert get_pending_attack_for_channel(db, 100) is None

    async def test_unarmed_soco_uses_brawling_default(
        self, make_cog, interaction, db, monkeypatch
    ):
        cog = make_cog(Combat)
        attacker_id, target_id, _ = build_combatants(db)
        modes = get_equipped_melee_modes(db, attacker_id)
        soco = next(mode for mode in modes if mode["mode_name"] == "Soco")
        join_combat(db, [attacker_id, target_id], attacker_id)
        patch_rng(monkeypatch, combat_attack_module, [1, 2, 2], budget=10)
        patch_rng(monkeypatch, battle_module, [1], budget=10)

        await Combat.combat_attack.callback(
            cog,
            interaction,
            alvo=str(target_id),
            arma=f"{attacker_id}:{soco['mode_id']}",
            personagem=None,
            local=SimpleNamespace(value=0),
            manobra=None,
            modificador=None,
            nh_manual=None,
        )

        pending = get_pending_attack_for_channel(db, 100)
        assert pending is not None
        assert pending["mode_name"] == "Soco"
        assert pending["nh_base"] == 6
        assert pending["nh_effective"] == 6

    async def test_unarmed_chute_applies_minus_two_to_attack(
        self, make_cog, interaction, db, monkeypatch
    ):
        cog = make_cog(Combat)
        attacker_id, target_id, _ = build_combatants(db)
        modes = get_equipped_melee_modes(db, attacker_id)
        chute = next(mode for mode in modes if mode["mode_name"] == "Chute")
        join_combat(db, [attacker_id, target_id], attacker_id)
        patch_rng(monkeypatch, combat_attack_module, [1, 2, 2], budget=10)
        patch_rng(monkeypatch, battle_module, [1], budget=10)

        await Combat.combat_attack.callback(
            cog,
            interaction,
            alvo=str(target_id),
            arma=f"{attacker_id}:{chute['mode_id']}",
            personagem=None,
            local=SimpleNamespace(value=0),
            manobra=None,
            modificador=None,
            nh_manual=10,
        )

        pending = get_pending_attack_for_channel(db, 100)
        assert pending is not None
        assert pending["mode_name"] == "Chute"
        assert pending["nh_base"] == 10
        assert pending["nh_effective"] == 8

    async def test_ranged_attack_uses_weapon_damage_expression(
        self, make_cog, interaction, db, monkeypatch
    ):
        cog = make_cog(Combat)
        attacker_id, target_id, mode_id = build_combatants(db)
        skill_id = insert_skill(db, name="Arco", attribute="DX")
        db.execute(
            "INSERT INTO character_skills (character_id, skill_id, relative_level) VALUES (?, ?, 4)",
            (attacker_id, skill_id),
        )
        ranged_id = insert_ranged_weapon(
            db,
            name="Arco",
            skill_id=skill_id,
            damage="2d+1 imp",
            min_st=8,
        )
        link_ranged_weapon(db, attacker_id, ranged_id, is_equipped=1)
        db.commit()
        join_combat(db, [attacker_id, target_id], attacker_id)

        patch_rng(monkeypatch, combat_attack_module, [3, 3, 3, 4, 5], budget=20)
        patch_rng(monkeypatch, combat_resolution_module, [3, 3, 3, 4, 5], budget=20)
        patch_rng(monkeypatch, battle_module, [1], budget=20)

        await Combat.combat_attack.callback(
            cog,
            interaction,
            alvo=str(target_id),
            arma=f"ranged:{attacker_id}:{ranged_id}",
            personagem=None,
            local=SimpleNamespace(value=0),
            manobra=None,
            modificador=None,
            nh_manual=None,
        )

        pending = get_pending_attack_for_channel(db, 100)
        assert pending is not None
        assert pending["attack_kind"] == "ranged"
        assert pending["ranged_weapon_id"] == ranged_id
        assert pending["damage_type"] == 7
        assert pending["raw_damage"] == 10
        assert pending["critical_damage"] == 13
        embed = interaction.edited[0]["kwargs"]["embed"]
        assert "Arco (Disparo)" in embed.description
        damage_field = next(
            field.value for field in embed.fields if field.name == "Dano"
        )
        assert "Dano da arma: 2d+1 imp" in damage_field
        assert "Dados: `[4, 5] = 9`" in damage_field
        assert "Modificadores: +1" in damage_field
        assert "Dano total: 10 Perfuração" in damage_field

    async def test_encumbrance_reduces_ranged_attack_nh(
        self, make_cog, interaction, db, monkeypatch
    ):
        cog = make_cog(Combat)
        attacker_id, target_id, _ = build_combatants(db)
        skill_id = insert_skill(db, name="Arco", attribute="DX")
        db.execute(
            "INSERT INTO character_skills (character_id, skill_id, relative_level) VALUES (?, ?, 4)",
            (attacker_id, skill_id),
        )
        ranged_id = insert_ranged_weapon(
            db,
            name="Arco",
            skill_id=skill_id,
            damage="2d+1 imp",
            min_st=8,
        )
        link_ranged_weapon(db, attacker_id, ranged_id, is_equipped=1)
        apply_heavy_load(db, attacker_id)
        join_combat(db, [attacker_id, target_id], attacker_id)
        patch_rng(monkeypatch, combat_attack_module, [3, 3, 3, 4, 5], budget=20)
        patch_rng(monkeypatch, combat_resolution_module, [3, 3, 3, 4, 5], budget=20)
        patch_rng(monkeypatch, battle_module, [1], budget=20)

        await Combat.combat_attack.callback(
            cog,
            interaction,
            alvo=str(target_id),
            arma=f"ranged:{attacker_id}:{ranged_id}",
            personagem=None,
            local=SimpleNamespace(value=0),
            manobra=None,
            modificador=None,
            nh_manual=None,
        )

        pending = get_pending_attack_for_channel(db, 100)
        assert pending is not None
        assert pending["nh_base"] == 14
        assert pending["nh_effective"] == 12
        embed = interaction.edited[0]["kwargs"]["embed"]
        assert "Carga -2" in embed.fields[1].value

    async def test_ranged_attack_rejects_weapon_without_skill(
        self, make_cog, interaction, db
    ):
        cog = make_cog(Combat)
        attacker_id, target_id, _ = build_combatants(db)
        ranged_id = insert_ranged_weapon(
            db, name="Arco sem perícia", damage="2d+1 imp"
        )
        link_ranged_weapon(db, attacker_id, ranged_id, is_equipped=1)
        db.commit()
        join_combat(db, [attacker_id, target_id], attacker_id)

        await Combat.combat_attack.callback(
            cog,
            interaction,
            alvo=str(target_id),
            arma=f"ranged:{attacker_id}:{ranged_id}",
            personagem=None,
            local=SimpleNamespace(value=0),
            manobra=None,
            modificador=None,
            nh_manual=None,
        )

        assert "não possui uma perícia configurada" in interaction.edited[0]["kwargs"]["content"]
        assert get_pending_attack_for_channel(db, 100) is None

    async def test_ranged_attack_rejects_unowned_weapon_skill(
        self, make_cog, interaction, db
    ):
        cog = make_cog(Combat)
        attacker_id, target_id, _ = build_combatants(db)
        unowned_skill = insert_skill(db, name="Arco", attribute="DX")
        ranged_id = insert_ranged_weapon(
            db,
            name="Arco",
            skill_id=unowned_skill,
            damage="2d+1 imp",
        )
        link_ranged_weapon(db, attacker_id, ranged_id, is_equipped=1)
        db.commit()
        join_combat(db, [attacker_id, target_id], attacker_id)

        await Combat.combat_attack.callback(
            cog,
            interaction,
            alvo=str(target_id),
            arma=f"ranged:{attacker_id}:{ranged_id}",
            personagem=None,
            local=SimpleNamespace(value=0),
            manobra=None,
            modificador=None,
            nh_manual=None,
        )

        assert "não possui a perícia" in interaction.edited[0]["kwargs"]["content"]
        assert get_pending_attack_for_channel(db, 100) is None

    async def test_failed_attack_does_not_create_pending_attack(
        self, make_cog, interaction, db, monkeypatch
    ):
        cog = make_cog(Combat)
        attacker_id, target_id, mode_id = build_combatants(db)
        patch_rng(monkeypatch, combat_attack_module, [6, 6, 6], budget=10)
        patch_rng(monkeypatch, combat_resolution_module, [6, 6, 6], budget=10)

        await attack(cog, interaction, attacker_id, target_id, mode_id)

        assert get_pending_attack_for_channel(db, 100) is None
        embed = interaction.edited[0]["kwargs"]["embed"]
        assert embed.title == "Ataque: Atacante -> Alvo"
        assert "FALHA CRÍTICA" in embed.fields[0].value

    async def test_critical_success_applies_damage_without_defence(
        self, make_cog, interaction, db, monkeypatch
    ):
        cog = make_cog(Combat)
        attacker_id, target_id, mode_id = build_combatants(db)
        patch_rng(monkeypatch, combat_attack_module, [1, 1, 1], budget=10)
        patch_rng(monkeypatch, combat_resolution_module, [1, 1, 1], budget=10)
        patch_rng(monkeypatch, battle_module, [1], budget=10)

        await attack(cog, interaction, attacker_id, target_id, mode_id)

        assert get_pending_attack_for_channel(db, 100) is None
        row = db.execute(
            "SELECT current_pv FROM characters WHERE character_id = ?",
            (target_id,),
        ).fetchone()
        assert row == (-2,)
        assert get_character_conditions_by_id(db, target_id)["shock"] == 4
        embed = interaction.edited[0]["kwargs"]["embed"]
        assert "Dano total:" in embed.fields[2].value
        assert "Dados críticos:" in embed.fields[2].value
        assert any(field.name == "Testes de HT" for field in embed.fields)


class TestWeaponAutocomplete:
    async def test_player_only_sees_own_weapons(
        self, make_cog, interaction, db
    ):
        cog = make_cog(Combat)
        attacker_id, target_id, _ = build_combatants(db)
        target_skill = insert_skill(db, name="Bastão", attribute="DX")
        target_weapon = insert_melee_weapon(db, name="Bastão")
        insert_melee_mode(
            db, target_weapon, target_skill, mode_name="Golpe"
        )
        link_melee_weapon(db, target_id, target_weapon, is_equipped=1)
        join_combat(db, [attacker_id, target_id], attacker_id)

        choices = await Combat.weapon_autocomplete(
            cog, interaction, ""
        )

        assert {choice.value.split(":")[1] for choice in choices} == {
            str(attacker_id)
        }

    async def test_gm_sees_only_participant_weapons(
        self, make_cog, db
    ):
        cog = make_cog(Combat)
        attacker_id, target_id, _ = build_combatants(db)
        target_skill = insert_skill(db, name="Bastão", attribute="DX")
        target_weapon = insert_melee_weapon(db, name="Bastão")
        insert_melee_mode(
            db, target_weapon, target_skill, mode_name="Golpe"
        )
        link_melee_weapon(db, target_id, target_weapon, is_equipped=1)
        outsider_id = insert_character(db, owner_id=3, name="Nefer")
        outsider_weapon = insert_melee_weapon(db, name="Lança")
        insert_melee_mode(
            db, outsider_weapon, target_skill, mode_name="Estocada"
        )
        link_melee_weapon(db, outsider_id, outsider_weapon, is_equipped=1)
        join_combat(db, [attacker_id, target_id], attacker_id)

        gm_interaction = FakeInteraction(
            user_id=999, channel_id=100, guild_id=1
        )
        choices = await Combat.weapon_autocomplete(
            cog, gm_interaction, ""
        )

        participant_ids = {
            choice.value.split(":")[1] for choice in choices
        }
        assert participant_ids == {str(attacker_id), str(target_id)}
        assert str(outsider_id) not in participant_ids


class TestCombatEffects:
    async def test_dx_and_basic_speed_effects_change_attack_and_dodge(
        self, make_cog, interaction, db, monkeypatch
    ):
        cog = make_cog(Combat)
        attacker_id, target_id, mode_id = build_combatants(db)
        dx_effect = insert_combat_effect(
            db, "DX extra", "dx", value=2
        )
        link_combat_effect(db, attacker_id, dx_effect)
        speed_effect = insert_combat_effect(
            db, "Velocidade extra", "basic_speed", value=1
        )
        link_combat_effect(db, target_id, speed_effect)
        db.commit()
        patch_rng(monkeypatch, combat_attack_module, [3, 3, 3], budget=10)
        patch_rng(monkeypatch, combat_resolution_module, [3, 3, 3], budget=10)
        patch_rng(monkeypatch, battle_module, [1], budget=10)

        await attack(cog, interaction, attacker_id, target_id, mode_id)

        pending = get_pending_attack_for_channel(db, 100)
        assert pending["nh_effective"] == 16
        view = interaction.edited[0]["kwargs"]["view"]
        assert view.children[0].option["value"] == 9

    async def test_passive_rd_effect_is_not_consumed(
        self, make_cog, interaction, db, monkeypatch
    ):
        cog = make_cog(Combat)
        attacker_id, target_id, mode_id = build_combatants(db)
        effect_id = insert_combat_effect(
            db,
            "Pele de Pedra",
            "rd",
            value=2,
            uses_per_turn=1,
        )
        link_combat_effect(db, target_id, effect_id)
        db.commit()
        patch_rng(monkeypatch, combat_attack_module, [3, 3, 3], budget=10)
        patch_rng(monkeypatch, combat_resolution_module, [3, 3, 3], budget=10)
        patch_rng(monkeypatch, battle_module, [1], budget=10)

        await attack(cog, interaction, attacker_id, target_id, mode_id)

        pending = get_pending_attack_for_channel(db, 100)
        assert pending["rd"] == 4
        participant = get_combat_participant(
            db, pending["session_id"], target_id
        )
        assert participant["effect_uses"] == {}

    async def test_attack_and_damage_effects_are_applied_and_consumed(
        self, make_cog, interaction, db, monkeypatch
    ):
        cog = make_cog(Combat)
        attacker_id, target_id, mode_id = build_combatants(db)
        attack_effect = insert_combat_effect(
            db,
            "Fúria",
            "attack",
            target=None,
            value=2,
            uses_per_turn=1,
            notes=None,
        )
        link_combat_effect(db, attacker_id, attack_effect)
        damage_effect = insert_combat_effect(
            db,
            "Golpe Pesado",
            "damage",
            target=None,
            value=3,
            uses_per_turn=1,
            notes=None,
        )
        link_combat_effect(db, attacker_id, damage_effect)
        db.commit()
        patch_rng(monkeypatch, combat_attack_module, [3, 3, 3], budget=10)
        patch_rng(monkeypatch, combat_resolution_module, [3, 3, 3], budget=10)
        patch_rng(monkeypatch, battle_module, [1], budget=10)

        await attack(cog, interaction, attacker_id, target_id, mode_id)

        pending = get_pending_attack_for_channel(db, 100)
        assert pending["nh_effective"] == 16
        assert pending["raw_damage"] == 8
        assert pending["critical_damage"] == 13
        embed = interaction.edited[0]["kwargs"]["embed"]
        assert "Fúria +2" in embed.fields[1].value
        assert "|" not in embed.fields[1].value
        assert "\nFúria +2" in embed.fields[1].value

        participant = get_combat_participant(
            db, pending["session_id"], attacker_id
        )
        assert participant["effect_uses"][str(attack_effect)] == 1
        assert participant["effect_uses"][str(damage_effect)] == 1

    async def test_defence_effect_bonus(
        self, make_cog, interaction, db, monkeypatch
    ):
        cog = make_cog(Combat)
        attacker_id, target_id, mode_id = build_combatants(db)
        effect_id = insert_combat_effect(
            db,
            "Escudo Arcano",
            "defense",
            target=None,
            value=2,
            uses_per_turn=0,
            notes=None,
        )
        link_combat_effect(db, target_id, effect_id)
        db.commit()
        patch_rng(monkeypatch, combat_attack_module, [3, 3, 3], budget=10)
        patch_rng(monkeypatch, combat_resolution_module, [3, 3, 3], budget=10)
        patch_rng(monkeypatch, battle_module, [1], budget=10)

        await attack(cog, interaction, attacker_id, target_id, mode_id)
        view = interaction.edited[0]["kwargs"]["view"]
        assert view.children[0].option["value"] == 10

        pending_before = get_pending_attack_for_channel(db, 100)
        target_interaction = FakeInteraction(
            user_id=2,
            message=FakeMessage(55),
            channel_id=100,
            guild_id=1,
        )
        patch_rng(monkeypatch, combat_attack_module, [1, 1, 1], budget=10)
        patch_rng(monkeypatch, combat_resolution_module, [1, 1, 1], budget=10)
        await view.handle_defense(
            target_interaction, view.children[0].option
        )

        pending = get_pending_attack_for_channel(db, 100)
        assert pending is None
        participant = get_combat_participant(
            db, pending_before["session_id"], target_id
        )
        assert participant["effect_uses"][str(effect_id)] == 1

    async def test_extra_defence_attempts_allow_a_second_defence(
        self, make_cog, interaction, db, monkeypatch
    ):
        cog = make_cog(Combat)
        attacker_id, target_id, mode_id = build_combatants(db)
        effect_id = insert_combat_effect(
            db,
            "Segunda Chance",
            "extra_defense_attempts",
            target=None,
            value=1,
            uses_per_turn=0,
            notes=None,
        )
        link_combat_effect(db, target_id, effect_id)
        effect_id = insert_combat_effect(
            db,
            "Reflexos",
            "extra_defense_uses",
            target="dodge",
            value=1,
            uses_per_turn=0,
            notes=None,
        )
        link_combat_effect(db, target_id, effect_id)
        db.commit()
        patch_rng(monkeypatch, combat_attack_module, [3, 3, 3], budget=20)
        patch_rng(monkeypatch, combat_resolution_module, [3, 3, 3], budget=20)
        patch_rng(monkeypatch, battle_module, [1], budget=20)

        await attack(cog, interaction, attacker_id, target_id, mode_id)
        pending = get_pending_attack_for_channel(db, 100)
        assert pending["max_defense_attempts"] == 2
        view = interaction.edited[0]["kwargs"]["view"]
        assert view.children[0].option["uses_remaining"] == 2

        first = FakeInteraction(
            user_id=2,
            message=FakeMessage(55),
            channel_id=100,
            guild_id=1,
        )
        patch_rng(monkeypatch, combat_attack_module, [4, 4, 4], budget=10)
        patch_rng(monkeypatch, combat_resolution_module, [4, 4, 4], budget=10)
        await view.handle_defense(first, view.children[0].option)

        pending = get_pending_attack_for_channel(db, 100)
        assert pending is not None
        assert pending["defense_attempts"] == 1
        assert pending["status"] == "pending"
        row = db.execute(
            "SELECT current_pv FROM characters WHERE character_id = ?",
            (target_id,),
        ).fetchone()
        assert row == (10,)
        assert first.edited[0]["kwargs"]["view"] is not None

        second_view = first.edited[0]["kwargs"]["view"]
        second = FakeInteraction(
            user_id=2,
            message=FakeMessage(55),
            channel_id=100,
            guild_id=1,
        )
        patch_rng(monkeypatch, combat_attack_module, [1, 1, 1], budget=10)
        patch_rng(monkeypatch, combat_resolution_module, [1, 1, 1], budget=10)
        await second_view.handle_defense(
            second, second_view.children[0].option
        )

        assert get_pending_attack_for_channel(db, 100) is None
        row = db.execute(
            "SELECT current_pv FROM characters WHERE character_id = ?",
            (target_id,),
        ).fetchone()
        assert row == (10,)

    async def test_advancing_turn_resets_next_participant_uses(
        self, make_cog, interaction, db, monkeypatch
    ):
        cog = make_cog(Combat)
        attacker_id, target_id, mode_id = build_combatants(db)
        effect_id = insert_combat_effect(
            db,
            "Postura",
            "defense",
            target=None,
            value=2,
            uses_per_turn=1,
            notes=None,
        )
        link_combat_effect(db, target_id, effect_id)
        db.commit()
        patch_rng(monkeypatch, combat_attack_module, [3, 3, 3], budget=10)
        patch_rng(monkeypatch, combat_resolution_module, [3, 3, 3], budget=10)
        patch_rng(monkeypatch, battle_module, [1], budget=10)
        await attack(cog, interaction, attacker_id, target_id, mode_id)

        target_interaction = FakeInteraction(
            user_id=2,
            message=FakeMessage(55),
            channel_id=100,
            guild_id=1,
        )
        # The target has no parry skill, so use the dodge option.
        view = interaction.edited[0]["kwargs"]["view"]
        patch_rng(monkeypatch, combat_attack_module, [1, 1, 1], budget=10)
        patch_rng(monkeypatch, combat_resolution_module, [1, 1, 1], budget=10)
        await view.handle_defense(
            target_interaction, view.children[0].option
        )

        session_row = db.execute(
            "SELECT session_id FROM combat_sessions WHERE channel_id = 100"
        ).fetchone()
        participant = get_combat_participant(db, session_row[0], target_id)
        assert participant["defense_uses"]
        assert participant["effect_uses"][str(effect_id)] == 1

        next_turn = FakeInteraction(
            user_id=999, channel_id=100, guild_id=1
        )
        await Combat.combat_next_turn.callback(cog, next_turn)

        participant = get_combat_participant(db, session_row[0], target_id)
        assert participant["defense_uses"] == {}
        assert participant["effect_uses"] == {}
        assert (
            get_active_combat_session(db, 100)["active_character_id"]
            == target_id
        )


class TestCombatEffectCommands:
    async def test_add_and_remove_catalog_effect(self, make_cog, db):
        cog = make_cog(Combat)
        character_id = insert_character(db, owner_id=1, name="Atacante")
        effect_id = insert_combat_effect(
            db,
            "Fúria",
            "attack",
            value=2,
            uses_per_turn=1,
        )
        gm_interaction = FakeInteraction(
            user_id=999, channel_id=100, guild_id=1
        )

        await Combat.combat_effect.callback(
            cog,
            gm_interaction,
            acao=SimpleNamespace(value="add"),
            efeito_id=effect_id,
            personagem=str(character_id),
        )

        effects = get_character_combat_effects(db, character_id)
        assert len(effects) == 1
        assert effects[0]["name"] == "Fúria"
        assert "aplicado" in gm_interaction.followup.sent[0]["args"][0]

        duplicate = FakeInteraction(
            user_id=999, channel_id=100, guild_id=1
        )
        await Combat.combat_effect.callback(
            cog,
            duplicate,
            acao=SimpleNamespace(value="add"),
            efeito_id=effect_id,
            personagem=str(character_id),
        )
        assert "já está aplicado" in duplicate.followup.sent[0]["args"][0]

        remove_interaction = FakeInteraction(
            user_id=999, channel_id=100, guild_id=1
        )
        await Combat.combat_effect.callback(
            cog,
            remove_interaction,
            acao=SimpleNamespace(value="remove"),
            efeito_id=effect_id,
            personagem=str(character_id),
        )
        assert get_character_combat_effects(db, character_id) == []
        assert "removido" in remove_interaction.followup.sent[0]["args"][0]

    async def test_rejects_unknown_catalog_effect(self, make_cog, db):
        cog = make_cog(Combat)
        character_id = insert_character(db, owner_id=1, name="Atacante")
        interaction = FakeInteraction(
            user_id=1, channel_id=100, guild_id=1
        )

        await Combat.combat_effect.callback(
            cog,
            interaction,
            acao=SimpleNamespace(value="add"),
            efeito_id=999,
            personagem=None,
        )

        assert "não encontrado no catálogo" in interaction.followup.sent[0]["args"][0]
        assert get_character_combat_effects(db, character_id) == []

    async def test_rejects_removing_an_unlinked_effect(self, make_cog, db):
        cog = make_cog(Combat)
        character_id = insert_character(db, owner_id=1, name="Atacante")
        effect_id = insert_combat_effect(db, "Fúria", "attack")
        interaction = FakeInteraction(
            user_id=1, channel_id=100, guild_id=1
        )

        await Combat.combat_effect.callback(
            cog,
            interaction,
            acao=SimpleNamespace(value="remove"),
            efeito_id=effect_id,
            personagem=None,
        )

        assert "não está aplicado" in interaction.followup.sent[0]["args"][0]

    async def test_player_cannot_manage_another_character(self, make_cog, db):
        cog = make_cog(Combat)
        insert_character(db, owner_id=1, name="Atacante")
        other_id = insert_character(db, owner_id=2, name="Outro")
        effect_id = insert_combat_effect(
            db, "Fúria", "attack", value=2, uses_per_turn=1
        )
        interaction = FakeInteraction(
            user_id=1, channel_id=100, guild_id=1
        )

        await Combat.combat_effect.callback(
            cog,
            interaction,
            acao=SimpleNamespace(value="add"),
            efeito_id=effect_id,
            personagem=str(other_id),
        )

        assert "não pode gerenciar" in interaction.followup.sent[0]["args"][0]
        assert get_character_combat_effects(db, other_id) == []


class TestCombatManeuverStance:
    async def test_all_out_attack_marks_attacker_without_defense(
        self, make_cog, interaction, db, monkeypatch
    ):
        cog = make_cog(Combat)
        attacker_id, target_id, mode_id = build_combatants(db)
        join_combat(db, [attacker_id, target_id], attacker_id)
        patch_rng(monkeypatch, combat_attack_module, [3, 3, 3], budget=10)
        patch_rng(monkeypatch, combat_resolution_module, [3, 3, 3], budget=10)
        patch_rng(monkeypatch, battle_module, [1], budget=10)

        await Combat.combat_attack.callback(
            cog,
            interaction,
            alvo=str(target_id),
            arma=f"{attacker_id}:{mode_id}",
            personagem=None,
            local=SimpleNamespace(value=0),
            manobra=SimpleNamespace(value="all_out_determined"),
            modificador=None,
            nh_manual=None,
        )

        row = db.execute(
            "SELECT no_defense, defense_bonus FROM next_turn_conditions WHERE character_id = ?",
            (attacker_id,),
        ).fetchone()
        assert row == (1, 0)

    def test_wounded_target_has_halved_dodge(self):
        data = {
            "profile": {
                "st": 10,
                "dx": 10,
                "ht": 10,
                "additional_max_pv": 0,
                "additional_basic_speed": 0,
                "current_pv": 3,
            },
            "encumbrance_penalty": 0,
            "skill_by_id": {},
            "melee_modes": [],
            "conditions": {
                "no_defense": 0,
                "defense_bonus": 0,
            },
        }

        options = _defense_options(data)

        assert options[0]["kind"] == "dodge"
        assert options[0]["value"] == 4

    def test_shock_does_not_reduce_dodge(self):
        data = {
            "profile": {
                "st": 10,
                "dx": 10,
                "ht": 10,
                "additional_max_pv": 0,
                "additional_basic_speed": 0,
                "current_pv": 10,
            },
            "encumbrance_penalty": 0,
            "skill_by_id": {},
            "melee_modes": [],
            "conditions": {
                "no_defense": 0,
                "defense_bonus": 0,
                "shock": 3,
            },
        }

        options = _defense_options(data)

        assert options[0]["value"] == 8

    def test_defense_bonus_and_no_defense_are_reflected_in_options(self, db):
        data = {
            "profile": {
                "dx": 10,
                "ht": 10,
                "additional_basic_speed": 0,
            },
            "encumbrance_penalty": 0,
            "skill_by_id": {},
            "melee_modes": [],
            "conditions": {
                "no_defense": 1,
                "defense_bonus": 0,
            },
        }

        assert _defense_options(data) == []

        data["conditions"] = {"no_defense": 0, "defense_bonus": 2}
        data["skill_by_id"] = {1: {"nh": 14}}
        data["melee_modes"] = [
            {
                "skill_id": 1,
                "skill_name": "Espadas Curtas",
                "weapon_name": "Espada",
                "parry": "0",
            }
        ]
        options = _defense_options(data)
        assert options[0]["value"] == 8
        assert options[1]["value"] == 12

    async def test_defensive_attack_stores_a_defense_bonus(
        self, make_cog, interaction, db, monkeypatch
    ):
        cog = make_cog(Combat)
        attacker_id, target_id, mode_id = build_combatants(db)
        join_combat(db, [attacker_id, target_id], attacker_id)
        patch_rng(monkeypatch, combat_attack_module, [3, 3, 3], budget=10)
        patch_rng(monkeypatch, combat_resolution_module, [3, 3, 3], budget=10)
        patch_rng(monkeypatch, battle_module, [1], budget=10)

        await Combat.combat_attack.callback(
            cog,
            interaction,
            alvo=str(target_id),
            arma=f"{attacker_id}:{mode_id}",
            personagem=None,
            local=SimpleNamespace(value=0),
            manobra=SimpleNamespace(value="defensive"),
            modificador=None,
            nh_manual=None,
        )

        row = db.execute(
            "SELECT no_defense, defense_bonus FROM next_turn_conditions WHERE character_id = ?",
            (attacker_id,),
        ).fetchone()
        assert row == (0, 1)


class TestCombatDefense:
    async def test_target_can_resolve_the_pending_attack(
        self, make_cog, interaction, db, monkeypatch
    ):
        cog = make_cog(Combat)
        attacker_id, target_id, mode_id = build_combatants(db)
        patch_rng(monkeypatch, combat_attack_module, [3, 3, 3], budget=10)
        patch_rng(monkeypatch, combat_resolution_module, [3, 3, 3], budget=10)
        patch_rng(monkeypatch, battle_module, [1], budget=10)

        await attack(cog, interaction, attacker_id, target_id, mode_id)
        view = interaction.edited[0]["kwargs"]["view"]

        target_interaction = FakeInteraction(
            user_id=2,
            message=FakeMessage(55),
            channel_id=100,
            guild_id=1,
        )
        patch_rng(monkeypatch, combat_attack_module, [4, 4, 4], budget=10)
        patch_rng(monkeypatch, combat_resolution_module, [4, 4, 4], budget=10)

        await view.handle_defense(
            target_interaction, view.children[0].option
        )

        assert get_pending_attack_for_channel(db, 100) is None
        row = db.execute(
            "SELECT current_pv FROM characters WHERE character_id = ?",
            (target_id,),
        ).fetchone()
        assert row == (6,)
        assert get_character_conditions_by_id(db, target_id)["shock"] == 4
        defense_embed = target_interaction.edited[0]["kwargs"]["embed"]
        assert defense_embed.title == "Defesa fracassou: Alvo"
        assert "[4, 4, 4] = 12" in defense_embed.fields[0].value
        assert "|" not in defense_embed.fields[0].value
        assert target_interaction.edited[0]["kwargs"]["view"] is not None

    async def test_defence_embed_reports_wounds_and_ht_check(
        self, make_cog, interaction, db, monkeypatch
    ):
        cog = make_cog(Combat)
        attacker_id, target_id, mode_id = build_combatants(db)
        db.execute(
            "UPDATE characters SET current_pv = 1 WHERE character_id = ?",
            (target_id,),
        )
        db.commit()
        patch_rng(monkeypatch, combat_attack_module, [3, 3, 3], budget=10)
        patch_rng(monkeypatch, combat_resolution_module, [3, 3, 3], budget=10)
        patch_rng(monkeypatch, battle_module, [1], budget=10)
        patch_rng(monkeypatch, combat_health_module, [3, 3, 3], budget=10)

        await attack(cog, interaction, attacker_id, target_id, mode_id)
        view = interaction.edited[0]["kwargs"]["view"]
        target_interaction = FakeInteraction(
            user_id=2,
            message=FakeMessage(55),
            channel_id=100,
            guild_id=1,
        )
        patch_rng(monkeypatch, combat_resolution_module, [4, 4, 4], budget=10)
        await view.handle_defense(
            target_interaction, view.children[0].option
        )

        embed = target_interaction.edited[0]["kwargs"]["embed"]
        field_names = [field.name for field in embed.fields]
        assert "Ferimento" in field_names
        assert "Testes de HT" in field_names
        assert "consciente" in next(
            field.value for field in embed.fields if field.name == "Testes de HT"
        )

    async def test_shock_is_accumulated_up_to_four(
        self, make_cog, interaction, db, monkeypatch
    ):
        cog = make_cog(Combat)
        attacker_id, target_id, mode_id = build_combatants(db)
        db.execute(
            "UPDATE melee_weapon_modes SET damage_modifier = 2 WHERE mode_id = ?",
            (mode_id,),
        )
        db.commit()
        set_player_condition(db, 2, "shock", 2)
        patch_rng(monkeypatch, combat_attack_module, [3, 3, 3], budget=10)
        patch_rng(monkeypatch, battle_module, [1], budget=10)

        await attack(cog, interaction, attacker_id, target_id, mode_id)
        view = interaction.edited[0]["kwargs"]["view"]
        target_interaction = FakeInteraction(
            user_id=2,
            message=FakeMessage(55),
            channel_id=100,
            guild_id=1,
        )
        patch_rng(monkeypatch, combat_resolution_module, [4, 4, 4], budget=10)
        await view.handle_defense(
            target_interaction, view.children[0].option
        )

        assert get_character_conditions_by_id(db, target_id)["shock"] == 3

    async def test_feint_penalty_reduces_the_defence_value(
        self, make_cog, interaction, db, monkeypatch
    ):
        from utils.db_functions import set_player_condition

        cog = make_cog(Combat)
        attacker_id, target_id, mode_id = build_combatants(db)
        set_player_condition(db, 1, "feint", 3)
        patch_rng(monkeypatch, combat_attack_module, [3, 3, 3], budget=10)
        patch_rng(monkeypatch, combat_resolution_module, [3, 3, 3], budget=10)
        patch_rng(monkeypatch, battle_module, [1], budget=10)

        await attack(cog, interaction, attacker_id, target_id, mode_id)
        view = interaction.edited[0]["kwargs"]["view"]
        assert view.children[0].option["value"] == 8

        target_interaction = FakeInteraction(
            user_id=2,
            message=FakeMessage(55),
            channel_id=100,
            guild_id=1,
        )
        patch_rng(monkeypatch, combat_attack_module, [4, 4, 4], budget=10)
        patch_rng(monkeypatch, combat_resolution_module, [4, 4, 4], budget=10)
        await view.handle_defense(
            target_interaction, view.children[0].option
        )

        defense_embed = target_interaction.edited[0]["kwargs"]["embed"]
        assert "NH efetivo: `5`" in defense_embed.fields[0].value

    async def test_wrong_user_cannot_defend(
        self, make_cog, interaction, db, monkeypatch
    ):
        cog = make_cog(Combat)
        attacker_id, target_id, mode_id = build_combatants(db)
        patch_rng(monkeypatch, combat_attack_module, [3, 3, 3], budget=10)
        patch_rng(monkeypatch, combat_resolution_module, [3, 3, 3], budget=10)
        patch_rng(monkeypatch, battle_module, [1], budget=10)

        await attack(cog, interaction, attacker_id, target_id, mode_id)
        view = interaction.edited[0]["kwargs"]["view"]

        stranger = FakeInteraction(
            user_id=77,
            message=FakeMessage(55),
            channel_id=100,
            guild_id=1,
        )
        allowed = await view.interaction_check(stranger)

        assert allowed is False
        assert "apenas o alvo" in stranger.response.messages[0]["args"][0]

    async def test_second_defence_is_rejected_without_extra_damage(
        self, make_cog, interaction, db, monkeypatch
    ):
        cog = make_cog(Combat)
        attacker_id, target_id, mode_id = build_combatants(db)
        patch_rng(monkeypatch, combat_attack_module, [3, 3, 3], budget=10)
        patch_rng(monkeypatch, combat_resolution_module, [3, 3, 3], budget=10)
        patch_rng(monkeypatch, battle_module, [1], budget=10)

        await attack(cog, interaction, attacker_id, target_id, mode_id)
        view = interaction.edited[0]["kwargs"]["view"]

        target_interaction = FakeInteraction(
            user_id=2,
            message=FakeMessage(55),
            channel_id=100,
            guild_id=1,
        )
        patch_rng(monkeypatch, combat_attack_module, [4, 4, 4], budget=10)
        patch_rng(monkeypatch, combat_resolution_module, [4, 4, 4], budget=10)
        await view.handle_defense(
            target_interaction, view.children[0].option
        )

        second_interaction = FakeInteraction(
            user_id=2,
            message=FakeMessage(55),
            channel_id=100,
            guild_id=1,
        )
        await view.handle_defense(
            second_interaction, view.children[0].option
        )

        row = db.execute(
            "SELECT current_pv FROM characters WHERE character_id = ?",
            (target_id,),
        ).fetchone()
        assert row == (6,)
        assert "já foi resolvido" in second_interaction.followup.sent[0]["args"][0]

    async def test_next_action_evaluate_sets_the_condition(
        self, make_cog, interaction, db, monkeypatch
    ):
        cog = make_cog(Combat)
        attacker_id, target_id, mode_id = build_combatants(db)
        patch_rng(monkeypatch, combat_attack_module, [3, 3, 3], budget=10)
        patch_rng(monkeypatch, combat_resolution_module, [3, 3, 3], budget=10)
        patch_rng(monkeypatch, battle_module, [1], budget=10)
        await attack(cog, interaction, attacker_id, target_id, mode_id)
        defense_view = interaction.edited[0]["kwargs"]["view"]

        target_interaction = FakeInteraction(
            user_id=2,
            message=FakeMessage(55),
            channel_id=100,
            guild_id=1,
        )
        patch_rng(monkeypatch, combat_attack_module, [1, 1, 1], budget=10)
        patch_rng(monkeypatch, combat_resolution_module, [1, 1, 1], budget=10)
        await defense_view.handle_defense(
            target_interaction, defense_view.children[0].option
        )
        next_view = target_interaction.edited[0]["kwargs"]["view"]

        attacker_interaction = FakeInteraction(
            user_id=1,
            message=FakeMessage(56),
            channel_id=100,
            guild_id=1,
        )
        await next_view.evaluate(attacker_interaction)

        row = db.execute(
            "SELECT aim, evaluate, no_defense, defense_bonus FROM next_turn_conditions WHERE character_id = ?",
            (attacker_id,),
        ).fetchone()
        assert row == (0, 1, 0, 0)
        assert attacker_interaction.edited[0]["kwargs"]["view"] is None

    async def test_next_action_repeat_creates_a_new_attack(
        self, make_cog, interaction, db, monkeypatch
    ):
        cog = make_cog(Combat)
        attacker_id, target_id, mode_id = build_combatants(db)
        patch_rng(monkeypatch, combat_attack_module, [3, 3, 3], budget=20)
        patch_rng(monkeypatch, combat_resolution_module, [3, 3, 3], budget=20)
        patch_rng(monkeypatch, battle_module, [1], budget=20)
        await attack(cog, interaction, attacker_id, target_id, mode_id)
        defense_view = interaction.edited[0]["kwargs"]["view"]

        target_interaction = FakeInteraction(
            user_id=2,
            message=FakeMessage(55),
            channel_id=100,
            guild_id=1,
        )
        await defense_view.handle_defense(
            target_interaction, defense_view.children[0].option
        )
        next_view = target_interaction.edited[0]["kwargs"]["view"]
        repeat_button = next_view.children[0]

        attacker_interaction = FakeInteraction(
            user_id=1,
            message=FakeMessage(57),
            channel_id=100,
            guild_id=1,
        )
        await repeat_button.callback(attacker_interaction)

        pending = get_pending_attack_for_channel(db, 100)
        assert pending is not None
        assert pending["attacker_character_id"] == attacker_id
        assert pending["target_character_id"] == target_id

    async def test_new_attack_supersedes_the_previous_one(
        self, make_cog, interaction, db, monkeypatch
    ):
        cog = make_cog(Combat)
        attacker_id, target_id, mode_id = build_combatants(db)
        patch_rng(monkeypatch, combat_attack_module, [3, 3, 3], budget=20)
        patch_rng(monkeypatch, combat_resolution_module, [3, 3, 3], budget=20)
        patch_rng(monkeypatch, battle_module, [1], budget=20)

        await attack(cog, interaction, attacker_id, target_id, mode_id)
        first = get_pending_attack_for_channel(db, 100)

        second_interaction = FakeInteraction(
            user_id=1,
            channel_id=100,
            guild_id=1,
        )
        await attack(
            cog, second_interaction, attacker_id, target_id, mode_id
        )

        assert get_pending_attack(db, first["attack_id"])["status"] == "superseded"
        pending = get_pending_attack_for_channel(db, 100)
        assert pending is not None
        assert pending["attack_id"] != first["attack_id"]


class TestCombatInitiativeAndLog:
    async def test_enter_defaults_to_basic_speed_not_basic_move(
        self, make_cog, db
    ):
        cog = make_cog(Combat)
        character_id = insert_character(
            db,
            owner_id=1,
            name="Veloz",
            dx=11,
            ht=10,
            additional_basic_speed=0,
            additional_basic_move=5,
        )
        interaction = FakeInteraction(
            user_id=1, channel_id=100, guild_id=1
        )

        await Combat.combat_enter.callback(
            cog,
            interaction,
            personagem=str(character_id),
            iniciativa=None,
        )

        session = get_active_combat_session(db, 100)
        participant = get_combat_participant(
            db, int(session["session_id"]), character_id
        )
        assert participant["initiative"] == 5.25
        assert isinstance(participant["initiative"], float)

    async def test_enter_accepts_a_fractional_initiative(
        self, make_cog, db
    ):
        cog = make_cog(Combat)
        character_id = insert_character(
            db, owner_id=1, name="Decimal"
        )
        interaction = FakeInteraction(
            user_id=1, channel_id=100, guild_id=1
        )

        await Combat.combat_enter.callback(
            cog,
            interaction,
            personagem=str(character_id),
            iniciativa=7.5,
        )

        session = get_active_combat_session(db, 100)
        participant = get_combat_participant(
            db, int(session["session_id"]), character_id
        )
        assert participant["initiative"] == 7.5

    async def test_enter_and_advance(self, make_cog, db):
        cog = make_cog(Combat)
        first = insert_character(db, owner_id=1, name="Alice")
        second = insert_character(db, owner_id=2, name="Bob")
        session = get_or_create_combat_session(db, 1, 100)
        db.commit()

        enter_one = FakeInteraction(
            user_id=999, channel_id=100, guild_id=1
        )
        await Combat.combat_enter.callback(
            cog,
            enter_one,
            personagem=str(first),
            iniciativa=10.5,
        )
        enter_two = FakeInteraction(
            user_id=999, channel_id=100, guild_id=1
        )
        await Combat.combat_enter.callback(
            cog,
            enter_two,
            personagem=str(second),
            iniciativa=20.25,
        )

        session = get_active_combat_session(db, 100)
        assert session["active_character_id"] == first
        participants = {
            participant["character_id"]: participant
            for participant in get_combat_participants(
                db, session["session_id"]
            )
        }
        assert participants[first]["initiative"] == 10.5
        assert participants[second]["initiative"] == 20.25

        next_turn = FakeInteraction(
            user_id=999, channel_id=100, guild_id=1
        )
        await Combat.combat_next_turn.callback(cog, next_turn)
        session = get_active_combat_session(db, 100)
        assert session["active_character_id"] == second
        assert session["round_number"] == 2

        entries = get_recent_combat_log(db, session["session_id"])
        descriptions = " ".join(
            entry["description"] or "" for entry in entries
        )
        assert "entrou no combate" in descriptions
        assert "Turno de Bob" in descriptions

    async def test_shock_survives_until_the_target_turn_ends(
        self, make_cog, db
    ):
        cog = make_cog(Combat)
        first = insert_character(db, owner_id=1, name="Alice")
        second = insert_character(db, owner_id=2, name="Bob")
        join_combat(db, [first, second], first)
        set_character_shock(db, second, 2)
        db.commit()

        first_advance = FakeInteraction(
            user_id=999, channel_id=100, guild_id=1
        )
        await Combat.combat_next_turn.callback(cog, first_advance)
        assert get_active_combat_session(db, 100)["active_character_id"] == second
        assert get_character_conditions_by_id(db, second)["shock"] == 2

        second_advance = FakeInteraction(
            user_id=999, channel_id=100, guild_id=1
        )
        await Combat.combat_next_turn.callback(cog, second_advance)
        assert get_active_combat_session(db, 100)["active_character_id"] == first
        assert get_character_conditions_by_id(db, second)["shock"] == 0

    async def test_gm_can_undo_the_last_damage(self, make_cog, db):
        cog = make_cog(Combat)
        target = insert_character(
            db, owner_id=1, name="Alvo", current_pv=5
        )
        session = get_or_create_combat_session(db, 1, 100)
        add_combat_log(
            db,
            session_id=session["session_id"],
            channel_id=100,
            event_type="damage",
            target_character_id=target,
            value=3,
            hp_before=8,
            hp_after=5,
            description="Dano de teste.",
        )
        db.commit()

        undo = FakeInteraction(user_id=999, channel_id=100, guild_id=1)
        await Combat.combat_undo.callback(cog, undo)

        row = db.execute(
            "SELECT current_pv FROM characters WHERE character_id = ?",
            (target,),
        ).fetchone()
        assert row == (8,)
        entries = get_recent_combat_log(db, session["session_id"])
        assert any(entry["event_type"] == "undo" for entry in entries)
        assert any(entry["reverted"] for entry in entries)


class FakePanelChannel:
    def __init__(self):
        self.sent = []
        self.messages = {}
        self._next_id = 500

    async def send(self, **kwargs):
        message = FakeMessage(self._next_id)
        self._next_id += 1
        self.sent.append({"kwargs": kwargs, "message": message})
        self.messages[message.id] = message
        return message

    async def fetch_message(self, message_id):
        return self.messages[message_id]


class FakeDiscordHTTPException(discord.HTTPException):
    def __init__(self):
        pass


class TestCombatPanel:
    async def test_start_creates_a_session_and_panel(
        self, make_cog, interaction, db
    ):
        cog = make_cog(Combat)

        await Combat.combat_start.callback(cog, interaction)

        sent = interaction.response.messages[0]
        assert sent["kwargs"]["embed"].title == "Painel de Combate"
        assert "ativa desde" not in sent["kwargs"]["embed"].fields[0].value
        row = db.execute(
            "SELECT status FROM combat_sessions WHERE channel_id = ?",
            (100,),
        ).fetchone()
        assert row == ("active",)

    async def test_panel_lists_participants_by_initiative(
        self, make_cog, db
    ):
        cog = make_cog(Combat)
        attacker_id, target_id, _ = build_combatants(db)
        join_combat(db, [attacker_id, target_id], attacker_id)
        with db:
            db.execute(
                "UPDATE combat_participants SET initiative = ? "
                "WHERE character_id = ?",
                (5.0, attacker_id),
            )
            db.execute(
                "UPDATE combat_participants SET initiative = ? "
                "WHERE character_id = ?",
                (10.0, target_id),
            )
        session = get_active_combat_session(db, 100)

        embed, _ = cog._build_panel_payload(session)
        participants_field = next(
            field for field in embed.fields if field.name == "Participantes"
        )
        lines = participants_field.value.splitlines()

        assert "Alvo" in lines[0]
        assert "Atacante" in lines[1]

    async def test_refresh_reposts_and_deletes_the_old_panel(
        self, make_cog, db
    ):
        cog = make_cog(Combat)
        session = get_or_create_combat_session(db, 1, 100)
        set_combat_session_panel(db, session["session_id"], 111)
        db.commit()
        old_panel = FakeMessage(111)
        channel = FakePanelChannel()
        interaction = FakeInteraction(
            user_id=999,
            channel_id=100,
            guild_id=1,
            message=old_panel,
        )
        interaction.channel = channel
        view = CombatPanelView(
            connection=db,
            channel_id=100,
            guild_id=1,
            dm_id=999,
        )

        await view.refresh(interaction)

        assert len(channel.sent) == 1
        assert isinstance(
            channel.sent[0]["kwargs"]["view"], CombatPanelView
        )
        assert old_panel.deleted is True
        assert get_active_combat_session(db, 100)["panel_message_id"] == 500
        assert interaction.response.deferred[0]["kwargs"]["ephemeral"] is True

    async def test_advance_turn_button_requires_the_gm(
        self, make_cog, db
    ):
        cog = make_cog(Combat)
        attacker_id, target_id, _ = build_combatants(db)
        join_combat(db, [attacker_id, target_id], attacker_id)
        view = CombatPanelView(
            connection=db,
            channel_id=100,
            guild_id=1,
            dm_id=999,
        )
        player_interaction = FakeInteraction(
            user_id=1, channel_id=100, guild_id=1
        )

        await view.advance_turn(player_interaction)

        assert "apenas o mestre" in player_interaction.response.messages[0]["args"][0]
        assert (
            get_active_combat_session(db, 100)["active_character_id"]
            == attacker_id
        )

    async def test_advance_turn_button_reposts_panel_to_bottom(
        self, make_cog, db
    ):
        cog = make_cog(Combat)
        attacker_id, target_id, _ = build_combatants(db)
        session = join_combat(db, [attacker_id, target_id], attacker_id)
        with db:
            set_combat_session_panel(db, session["session_id"], 111)
        old_panel = FakeMessage(111)
        channel = FakePanelChannel()
        channel.messages[111] = old_panel
        view = CombatPanelView(
            connection=db,
            channel_id=100,
            guild_id=1,
            dm_id=999,
        )
        gm_interaction = FakeInteraction(
            user_id=999,
            channel_id=100,
            guild_id=1,
            message=old_panel,
        )
        gm_interaction.channel = channel

        await view.advance_turn(gm_interaction)

        assert (
            get_active_combat_session(db, 100)["active_character_id"]
            == target_id
        )
        assert len(channel.sent) == 1
        assert channel.sent[0]["message"].id == 500
        assert isinstance(
            channel.sent[0]["kwargs"]["view"], CombatPanelView
        )
        assert old_panel.deleted is True
        assert get_active_combat_session(db, 100)["panel_message_id"] == 500
        assert "Turno de" in gm_interaction.followup.sent[0]["args"][0]
        assert gm_interaction.response.deferred[0]["kwargs"]["ephemeral"] is True

    async def test_next_turn_command_reposts_panel_to_bottom(
        self, make_cog, db
    ):
        cog = make_cog(Combat)
        attacker_id, target_id, _ = build_combatants(db)
        session = join_combat(db, [attacker_id, target_id], attacker_id)
        with db:
            set_combat_session_panel(db, session["session_id"], 111)
        old_panel = FakeMessage(111)
        channel = FakePanelChannel()
        channel.messages[111] = old_panel
        interaction = FakeInteraction(
            user_id=999, channel_id=100, guild_id=1
        )
        interaction.channel = channel

        await Combat.combat_next_turn.callback(cog, interaction)

        assert (
            get_active_combat_session(db, 100)["active_character_id"]
            == target_id
        )
        assert len(channel.sent) == 1
        assert channel.sent[0]["message"].id == 500
        assert old_panel.deleted is True
        assert get_active_combat_session(db, 100)["panel_message_id"] == 500
        assert "Turno de" in interaction.followup.sent[0]["args"][0]

    async def test_consecutive_next_turn_reposts_do_not_leave_old_panels(
        self, make_cog, db
    ):
        cog = make_cog(Combat)
        attacker_id, target_id, _ = build_combatants(db)
        session = join_combat(db, [attacker_id, target_id], attacker_id)
        with db:
            set_combat_session_panel(db, session["session_id"], 111)
        old_panel = FakeMessage(111)
        channel = FakePanelChannel()
        channel.messages[111] = old_panel

        first_interaction = FakeInteraction(
            user_id=999, channel_id=100, guild_id=1
        )
        first_interaction.channel = channel
        await Combat.combat_next_turn.callback(cog, first_interaction)
        first_new_panel = channel.sent[0]["message"]

        second_interaction = FakeInteraction(
            user_id=999, channel_id=100, guild_id=1
        )
        second_interaction.channel = channel
        await Combat.combat_next_turn.callback(cog, second_interaction)

        assert len(channel.sent) == 2
        assert old_panel.deleted is True
        assert first_new_panel.deleted is True
        assert get_active_combat_session(db, 100)["panel_message_id"] == 501

    async def test_advance_turn_button_falls_back_when_repost_fails(
        self, make_cog, db
    ):
        cog = make_cog(Combat)
        attacker_id, target_id, _ = build_combatants(db)
        session = join_combat(db, [attacker_id, target_id], attacker_id)
        with db:
            set_combat_session_panel(db, session["session_id"], 111)
        old_panel = FakeMessage(111)
        channel = FakePanelChannel()
        channel.messages[111] = old_panel

        async def fail_send(**kwargs):
            raise FakeDiscordHTTPException()

        channel.send = fail_send
        view = CombatPanelView(
            connection=db,
            channel_id=100,
            guild_id=1,
            dm_id=999,
        )
        gm_interaction = FakeInteraction(
            user_id=999,
            channel_id=100,
            guild_id=1,
            message=old_panel,
        )
        gm_interaction.channel = channel

        await view.advance_turn(gm_interaction)

        assert channel.sent == []
        assert old_panel.deleted is False
        assert get_active_combat_session(db, 100)["panel_message_id"] == 111
        assert gm_interaction.edited[0]["kwargs"]["embed"].title == "Painel de Combate"
        assert "Turno de" in gm_interaction.followup.sent[0]["args"][0]

    async def test_next_turn_command_falls_back_when_repost_fails(
        self, make_cog, db
    ):
        cog = make_cog(Combat)
        attacker_id, target_id, _ = build_combatants(db)
        session = join_combat(db, [attacker_id, target_id], attacker_id)
        with db:
            set_combat_session_panel(db, session["session_id"], 111)
        old_panel = FakeMessage(111)
        channel = FakePanelChannel()
        channel.messages[111] = old_panel

        async def fail_send(**kwargs):
            raise FakeDiscordHTTPException()

        channel.send = fail_send
        interaction = FakeInteraction(
            user_id=999, channel_id=100, guild_id=1
        )
        interaction.channel = channel

        await Combat.combat_next_turn.callback(cog, interaction)

        assert channel.sent == []
        assert old_panel.deleted is False
        assert get_active_combat_session(db, 100)["panel_message_id"] == 111
        assert old_panel.embeds[0].title == "Painel de Combate"
        assert "Turno de" in interaction.followup.sent[0]["args"][0]

    async def test_advance_turn_button_disables_old_panel_when_delete_fails(
        self, make_cog, db
    ):
        cog = make_cog(Combat)
        attacker_id, target_id, _ = build_combatants(db)
        session = join_combat(db, [attacker_id, target_id], attacker_id)
        with db:
            set_combat_session_panel(db, session["session_id"], 111)
        old_panel = FakeMessage(111)
        channel = FakePanelChannel()
        channel.messages[111] = old_panel

        async def fail_delete():
            raise FakeDiscordHTTPException()

        old_panel.delete = fail_delete
        view = CombatPanelView(
            connection=db,
            channel_id=100,
            guild_id=1,
            dm_id=999,
        )
        gm_interaction = FakeInteraction(
            user_id=999,
            channel_id=100,
            guild_id=1,
            message=old_panel,
        )
        gm_interaction.channel = channel

        await view.advance_turn(gm_interaction)

        assert len(channel.sent) == 1
        assert old_panel.deleted is False
        assert old_panel.views[-1] is None
        assert get_active_combat_session(db, 100)["panel_message_id"] == 500
        assert "não foi possível apagar" in (
            gm_interaction.followup.sent[0]["args"][0]
        )
        assert "Turno de" in gm_interaction.followup.sent[1]["args"][0]

    def test_combat_commands_are_flat_and_english(self):
        expected = {
            Combat.combat_start.name,
            Combat.combat_end.name,
            Combat.combat_effect.name,
            Combat.combat_enter.name,
            Combat.combat_next_turn.name,
            Combat.combat_undo.name,
            Combat.combat_feint.name,
            Combat.combat_attack.name,
        }
        assert expected == {
            "combat_start",
            "combat_end",
            "combat_manage_effect",
            "combat_enter",
            "combat_next_turn",
            "combat_undo",
            "combat_feint",
            "combat_attack",
        }
        assert not hasattr(Combat, "combat")

    async def test_panel_command_was_removed(self):
        assert not hasattr(Combat, "combat_panel")


class TestCombatMembership:
    async def test_attack_requires_an_active_session(
        self, make_cog, interaction, db
    ):
        cog = make_cog(Combat)
        attacker_id, target_id, mode_id = build_combatants(db)

        await invoke_attack_raw(
            cog, interaction, attacker_id, target_id, mode_id
        )

        assert "não existe combate ativo" in interaction.edited[0]["kwargs"]["content"]
        assert get_active_combat_session(db, 100) is None
        assert get_combat_participants(db, 1) == []

    async def test_attack_requires_the_attacker_to_be_in_combat(
        self, make_cog, interaction, db
    ):
        cog = make_cog(Combat)
        attacker_id, target_id, mode_id = build_combatants(db)
        join_combat(db, [target_id], target_id)

        await invoke_attack_raw(
            cog, interaction, attacker_id, target_id, mode_id
        )

        assert "atacante e alvo precisam estar no combate" in interaction.edited[0]["kwargs"]["content"]
        participants = get_combat_participants(
            db, int(get_active_combat_session(db, 100)["session_id"])
        )
        assert [p["character_id"] for p in participants] == [target_id]

    async def test_attack_requires_the_target_to_be_in_combat(
        self, make_cog, interaction, db
    ):
        cog = make_cog(Combat)
        attacker_id, target_id, mode_id = build_combatants(db)
        join_combat(db, [attacker_id], attacker_id)

        await invoke_attack_raw(
            cog, interaction, attacker_id, target_id, mode_id
        )

        assert "atacante e alvo precisam estar no combate" in interaction.edited[0]["kwargs"]["content"]
        participants = get_combat_participants(
            db, int(get_active_combat_session(db, 100)["session_id"])
        )
        assert [p["character_id"] for p in participants] == [attacker_id]
        assert get_pending_attack_for_channel(db, 100) is None

    async def test_participant_autocomplete_only_lists_joined_characters(
        self, make_cog, interaction, db
    ):
        cog = make_cog(Combat)
        attacker_id, target_id, _ = build_combatants(db)
        outsider_id = insert_character(db, owner_id=3, name="Forasteiro")
        join_combat(db, [attacker_id, target_id], attacker_id)

        choices = await Combat.participant_autocomplete(
            cog, interaction, ""
        )

        assert {choice.value for choice in choices} == {
            str(attacker_id),
            str(target_id),
        }
        assert str(outsider_id) not in {choice.value for choice in choices}

    async def test_removed_commands_are_absent(self):
        assert not hasattr(Combat, "combat_defender")
        assert not hasattr(Combat, "combat_turn")


def install_quick_dispute(monkeypatch, actor_dice, target_dice):
    """Install a deterministic quick-dispute payload and record its call."""
    calls = []

    def fake(player_id, actor_nh, target_nh, connection=None):
        calls.append(
            {
                "player_id": player_id,
                "actor_nh": actor_nh,
                "target_nh": target_nh,
                "connection": connection,
            }
        )
        actor_roll = sum(actor_dice)
        target_roll = sum(target_dice)
        return {
            "result1": {
                "dice_pool1": actor_roll,
                "success_roll1": actor_roll <= actor_nh,
                "margin1": actor_nh - actor_roll,
                "dices1": list(actor_dice),
            },
            "result2": {
                "dice_pool2": target_roll,
                "success_roll2": target_roll <= target_nh,
                "margin2": target_nh - target_roll,
                "dices2": list(target_dice),
            },
        }

    monkeypatch.setattr(combat_feint_module, "quick_dispute", fake)
    return calls


def start_feint_session(
    db, active_character_id: int, participant_ids: list[int]
) -> None:
    """Create an active session with the requested active participant."""
    join_combat(db, participant_ids, active_character_id)


class TestCombatFeint:
    async def test_successful_feint_stores_penalty_and_logs(
        self, make_cog, interaction, db, monkeypatch
    ):
        cog = make_cog(Combat)
        attacker_id, target_id, _ = build_combatants(db)
        start_feint_session(db, attacker_id, [attacker_id, target_id])
        calls = install_quick_dispute(
            monkeypatch, [3, 3, 3], [4, 4, 4]
        )

        await Combat.combat_feint.callback(
            cog,
            interaction,
            alvo=str(target_id),
            personagem=None,
            pericia=None,
            nh_manual=None,
            defesa=None,
            modificador=None,
        )

        assert calls[0]["actor_nh"] == 14
        assert calls[0]["target_nh"] == 10
        assert calls[0]["connection"] is db
        embed = interaction.followup.sent[0]["kwargs"]["embed"]
        assert "enganou" in embed.title
        assert get_character_conditions_by_id(db, attacker_id)["feint"] == 5
        log = get_recent_combat_log(
            db, int(get_active_combat_session(db, 100)["session_id"])
        )[0]
        assert log["event_type"] == "feint"
        assert log["value"] == 5

    async def test_feint_displays_and_applies_shock(
        self, make_cog, interaction, db, monkeypatch
    ):
        cog = make_cog(Combat)
        attacker_id, target_id, _ = build_combatants(db)
        set_player_condition(db, 1, "shock", 2)
        start_feint_session(db, attacker_id, [attacker_id, target_id])
        calls = install_quick_dispute(
            monkeypatch, [3, 3, 3], [4, 4, 4]
        )

        await Combat.combat_feint.callback(
            cog,
            interaction,
            alvo=str(target_id),
            personagem=None,
            pericia=None,
            nh_manual=None,
            defesa=None,
            modificador=None,
        )

        assert calls[0]["actor_nh"] == 12
        embed = interaction.followup.sent[0]["kwargs"]["embed"]
        assert "Choque: -2" in embed.fields[0].value

    async def test_feint_applies_encumbrance_to_actor_nh(
        self, make_cog, interaction, db, monkeypatch
    ):
        cog = make_cog(Combat)
        attacker_id, target_id, _ = build_combatants(db)
        apply_heavy_load(db, attacker_id)
        start_feint_session(db, attacker_id, [attacker_id, target_id])
        calls = install_quick_dispute(
            monkeypatch, [3, 3, 3], [4, 4, 4]
        )

        await Combat.combat_feint.callback(
            cog,
            interaction,
            alvo=str(target_id),
            personagem=None,
            pericia=None,
            nh_manual=None,
            defesa=None,
            modificador=None,
        )

        assert calls[0]["actor_nh"] == 12
        embed = interaction.followup.sent[0]["kwargs"]["embed"]
        assert "NH efetivo: `12`" in embed.fields[0].value

    async def test_feint_caps_evaluate_bonus_at_three(
        self, make_cog, interaction, db, monkeypatch
    ):
        cog = make_cog(Combat)
        attacker_id, target_id, _ = build_combatants(db)
        set_player_condition(db, attacker_id, "evaluate", 5)
        start_feint_session(db, attacker_id, [attacker_id, target_id])
        calls = install_quick_dispute(
            monkeypatch, [3, 3, 3], [4, 4, 4]
        )

        await Combat.combat_feint.callback(
            cog,
            interaction,
            alvo=str(target_id),
            personagem=None,
            pericia=None,
            nh_manual=None,
            defesa=None,
            modificador=None,
        )

        assert calls[0]["actor_nh"] == 17

    async def test_failed_feint_clears_previous_conditions(
        self, make_cog, interaction, db, monkeypatch
    ):
        cog = make_cog(Combat)
        attacker_id, target_id, _ = build_combatants(db)
        start_feint_session(db, attacker_id, [attacker_id, target_id])
        with db:
            db.execute(
                "INSERT INTO next_turn_conditions (character_id, feint) VALUES (?, ?)",
                (attacker_id, 3),
            )
        install_quick_dispute(monkeypatch, [6, 6, 6], [3, 3, 3])

        await Combat.combat_feint.callback(
            cog,
            interaction,
            alvo=str(target_id),
            personagem=None,
            pericia=None,
            nh_manual=None,
            defesa=None,
            modificador=None,
        )

        embed = interaction.followup.sent[0]["kwargs"]["embed"]
        assert "falhou" in embed.title
        assert get_character_conditions_by_id(db, attacker_id)["feint"] == 0

    async def test_feint_requires_the_active_turn(
        self, make_cog, interaction, db, monkeypatch
    ):
        cog = make_cog(Combat)
        attacker_id, target_id, _ = build_combatants(db)
        start_feint_session(db, target_id, [attacker_id, target_id])
        calls = install_quick_dispute(
            monkeypatch, [3, 3, 3], [3, 3, 3]
        )

        await Combat.combat_feint.callback(
            cog,
            interaction,
            alvo=str(target_id),
            personagem=None,
            pericia=None,
            nh_manual=None,
            defesa=None,
            modificador=None,
        )

        assert calls == []
        assert "turno" in interaction.followup.sent[0]["args"][0]

    async def test_attack_consumes_the_stored_feint_penalty(
        self, make_cog, interaction, db, monkeypatch
    ):
        cog = make_cog(Combat)
        attacker_id, target_id, mode_id = build_combatants(db)
        with db:
            db.execute(
                "INSERT INTO next_turn_conditions (character_id, feint) VALUES (?, ?)",
                (attacker_id, 3),
            )
        patch_rng(monkeypatch, combat_attack_module, [3, 3, 3], budget=10)
        patch_rng(monkeypatch, battle_module, [1], budget=10)

        await attack(cog, interaction, attacker_id, target_id, mode_id)

        pending = get_pending_attack_for_channel(db, 100)
        assert pending is not None
        assert pending["feint"] == 3
        assert get_character_conditions_by_id(db, attacker_id)["feint"] == 0

    async def test_feint_requires_both_characters_in_combat(
        self, make_cog, interaction, db, monkeypatch
    ):
        cog = make_cog(Combat)
        attacker_id, target_id, _ = build_combatants(db)
        join_combat(db, [attacker_id], attacker_id)
        calls = install_quick_dispute(monkeypatch, [3, 3, 3], [3, 3, 3])

        await Combat.combat_feint.callback(
            cog,
            interaction,
            alvo=str(target_id),
            personagem=None,
            pericia=None,
            nh_manual=None,
            defesa=None,
            modificador=None,
        )

        assert calls == []
        assert "precisam estar no combate" in interaction.followup.sent[0]["args"][0]
        participants = get_combat_participants(
            db, int(get_active_combat_session(db, 100)["session_id"])
        )
        assert [p["character_id"] for p in participants] == [attacker_id]


class TestGMShieldCombatDirectives:
    async def test_attack_directive_forces_success_and_minimum_damage(
        self, make_cog, interaction, db, monkeypatch
    ):
        from utils.gm_directives import gm_shield_store

        cog = make_cog(Combat)
        attacker_id, target_id, mode_id = build_combatants(db)
        gm_shield_store.set(
            character_id=attacker_id,
            player_id=1,
            roll_kind="attack",
            outcome="success",
            payload={"damage_preset": "min"},
        )
        join_combat(db, [attacker_id, target_id], attacker_id)

        await invoke_attack_raw(
            cog, interaction, attacker_id, target_id, mode_id
        )

        pending = get_pending_attack_for_channel(db, 100)
        assert pending is not None
        assert pending["attack_margin"] == 0
        assert pending["raw_damage"] == 5
        descriptions = " ".join(
            entry["description"] or ""
            for entry in get_recent_combat_log(
                db, int(get_active_combat_session(db, 100)["session_id"])
            )
        )
        assert "GM" not in descriptions
        assert "forced" not in descriptions.lower()
        assert db.execute("SELECT COUNT(*) FROM hdm").fetchone() == (0,)

    async def test_defense_directive_forces_a_failed_defense(
        self, make_cog, interaction, db, monkeypatch
    ):
        from utils.gm_directives import gm_shield_store

        cog = make_cog(Combat)
        attacker_id, target_id, mode_id = build_combatants(db)
        gm_shield_store.set(
            character_id=attacker_id,
            player_id=1,
            roll_kind="attack",
            outcome="success",
            payload={"damage_preset": "min"},
        )
        gm_shield_store.set(
            character_id=target_id,
            player_id=2,
            roll_kind="defense",
            outcome="failure",
        )
        join_combat(db, [attacker_id, target_id], attacker_id)

        await invoke_attack_raw(
            cog, interaction, attacker_id, target_id, mode_id
        )
        view = interaction.edited[0]["kwargs"]["view"]
        target_interaction = FakeInteraction(user_id=2)
        await view.handle_defense(
            target_interaction, view.children[0].option
        )

        hp = db.execute(
            "SELECT current_pv FROM characters WHERE character_id = ?",
            (target_id,),
        ).fetchone()[0]
        assert hp < 10
        assert gm_shield_store.consume(
            character_id=target_id,
            player_id=2,
            roll_kind="defense",
        ) is None
