"""Tests for combat persistence helpers in utils/db_functions.py."""

from __future__ import annotations

import json

from helpers import (
    insert_body_part,
    insert_character,
    insert_combat_effect,
    insert_melee_mode,
    insert_melee_weapon,
    insert_ranged_weapon,
    insert_skill,
    link_armor,
    link_melee_weapon,
    link_ranged_weapon,
    insert_armor_material,
)
from utils.db_functions import (
    apply_character_injury,
    claim_pending_attack,
    clear_character_conditions,
    clear_character_shock,
    close_combat_session,
    create_pending_attack,
    ensure_combat_participant,
    finish_pending_attack,
    get_active_combat_session,
    add_combat_log,
    get_character_combat_data,
    get_character_combat_effects,
    get_character_effect_link,
    get_character_inventory_data_by_id,
    get_combat_effect,
    get_combat_participant,
    get_equipped_melee_modes,
    get_equipped_ranged_weapons,
    get_last_damage_log,
    get_recent_combat_log,
    mark_combat_log_reverted,
    set_character_current_pv,
    set_character_shock,
    set_combat_session_active,
    set_combat_session_panel,
    set_participant_initiative,
    get_or_create_combat_session,
    get_pending_attack,
    get_pending_attack_for_channel,
    record_participant_use,
    reset_combat_participant_turn,
    set_character_aim_evaluate,
    link_character_effect,
    unlink_character_effect,
    spend_character_resource,
    supersede_pending_attacks,
)
from utils.db_functions import (
    get_character_conditions_by_id,
    set_character_combat_stance,
    set_player_condition,
)


def make_attacker(db, owner_id: int = 1) -> tuple[int, dict]:
    character_id = insert_character(db, owner_id=owner_id, name="Atacante")
    skill_id = insert_skill(db, name="Espadas Curtas", attribute="DX")
    db.execute(
        "INSERT INTO character_skills (character_id, skill_id, relative_level) VALUES (?, ?, 4)",
        (character_id, skill_id),
    )
    weapon_id = insert_melee_weapon(db, name="Espada Curta")
    insert_melee_mode(
        db,
        weapon_id,
        skill_id,
        mode_name="Corte",
        damage_base="GeB",
        damage_modifier=1,
        damage_type="corte",
        parry="0",
    )
    link_melee_weapon(db, character_id, weapon_id, is_equipped=1)
    db.commit()
    return character_id, {"skill_id": skill_id, "weapon_id": weapon_id}


def make_target(db, owner_id: int = 2) -> int:
    character_id = insert_character(db, owner_id=owner_id, name="Alvo")
    torso = insert_body_part(db, name="Tronco", factor=1.0)
    material_id = insert_armor_material(
        db, name="Cota", dr=4, is_flexible=1
    )
    link_armor(
        db,
        character_id,
        material_id,
        torso,
        is_equipped=1,
    )
    db.commit()
    return character_id


def pending_payload(character_id: int, target_id: int, **overrides) -> dict:
    payload = {
        "session_id": None,
        "guild_id": 1,
        "channel_id": 100,
        "attacker_id": 1,
        "attacker_character_id": character_id,
        "target_character_id": target_id,
        "target_owner_id": 2,
        "weapon_name": "Espada Curta",
        "mode_name": "Corte",
        "skill_name": "Espadas Curtas",
        "mode_id": 1,
        "attack_kind": "melee",
        "ranged_weapon_id": None,
        "damage_expression": None,
        "maneuver": "normal",
        "custom_modifier": 0,
        "nh_base": 14,
        "nh_effective": 14,
        "attack_roll": 9,
        "attack_margin": 5,
        "raw_damage": 10,
        "critical_damage": 20,
        "max_defense_attempts": 1,
        "defense_attempts": 0,
        "rd": 4,
        "damage_type": 5,
        "hit_location": 0,
        "feint": 0,
        "is_critical": 0,
        "modifiers_json": json.dumps({"effective": 14}),
    }
    payload.update(overrides)
    return payload


class TestCombatData:
    def test_assembles_profile_skills_weapons_armor_and_conditions(self, db):
        attacker_id, ids = make_attacker(db)
        target_id = make_target(db)
        set_player_condition(db, 1, "evaluate", 2)

        data = get_character_combat_data(db, attacker_id)

        assert data["profile"]["name"] == "Atacante"
        assert data["skill_by_id"][ids["skill_id"]]["nh"] == 14
        assert data["melee_modes"][0]["weapon_name"] == "Espada Curta"
        assert data["conditions"]["evaluate"] == 2
        assert data["armor_layers"] == []
        assert data["encumbrance_penalty"] == 0

    def test_passive_effects_apply_to_profile_and_skills(self, db):
        character_id = insert_character(db, owner_id=1, name="Efeitos")
        skill_ids = {
            "Espadas": insert_skill(db, name="Espadas", attribute="DX"),
            "História": insert_skill(db, name="História", attribute="IQ"),
            "Percepção": insert_skill(db, name="Percepção", attribute="Per"),
            "Vontade": insert_skill(db, name="Vontade", attribute="Will"),
        }
        for skill_id in skill_ids.values():
            db.execute(
                "INSERT INTO character_skills "
                "(character_id, skill_id, relative_level) VALUES (?, ?, 0)",
                (character_id, skill_id),
            )
        effects = [
            ("ST", "st", 2),
            ("DX", "dx", 1),
            ("IQ", "iq", 2),
            ("PV", "max_pv", 3),
            ("Per", "per", 1),
            ("Vontade", "will", 1),
            ("HT checks", "ht_check", 2),
            ("RD", "rd", 3),
        ]
        for name, applies_to, value in effects:
            effect_id = insert_combat_effect(
                db, name, applies_to, value=value
            )
            link_character_effect(db, character_id, effect_id)
        db.commit()

        data = get_character_combat_data(db, character_id)

        assert data is not None
        assert data["profile"]["st"] == 12
        assert data["profile"]["max_pv"] == 15
        assert data["profile"]["ht_check_bonus"] == 2
        assert data["profile"]["rd_bonus"] == 3
        assert len(data["effects"]) == len(effects)
        nh = {
            skill["name"]: skill["nh"] for skill in data["skills"]
        }
        assert nh["Espadas"] == 11
        assert nh["História"] == 12
        assert nh["Percepção"] == 13
        assert nh["Vontade"] == 13

    def test_target_armor_layers_are_returned(self, db):
        target_id = make_target(db)

        data = get_character_combat_data(db, target_id)

        assert len(data["armor_layers"]) == 1
        assert data["armor_layers"][0]["dr"] == 4
        assert data["armor_layers"][0]["body_part"] == "Tronco"

    def test_missing_character_raises(self, db):
        try:
            get_character_combat_data(db, 999)
        except ValueError as error:
            assert "character_id 999" in str(error)
        else:
            raise AssertionError("Expected ValueError")


class TestCombatSessions:
    def test_get_or_create_is_idempotent(self, db):
        first = get_or_create_combat_session(db, 1, 100)
        db.commit()
        second = get_or_create_combat_session(db, 1, 100)
        db.commit()

        assert first["session_id"] == second["session_id"]
        assert get_active_combat_session(db, 100)["status"] == "active"

    def test_close_marks_the_session_closed(self, db):
        session = get_or_create_combat_session(db, 1, 100)
        db.commit()

        close_combat_session(db, 100)
        db.commit()

        assert get_active_combat_session(db, 100) is None
        row = db.execute(
            "SELECT status FROM combat_sessions WHERE session_id = ?",
            (session["session_id"],),
        ).fetchone()
        assert row == ("closed",)


class TestPendingAttacks:
    def test_create_claim_and_finish(self, db):
        attacker_id, _ = make_attacker(db)
        target_id = make_target(db)

        attack_id = create_pending_attack(
            db, **pending_payload(attacker_id, target_id)
        )
        db.commit()

        pending = get_pending_attack(db, attack_id)
        assert pending["status"] == "pending"
        assert pending["raw_damage"] == 10

        claimed = claim_pending_attack(db, attack_id)
        assert claimed["status"] == "resolving"

        finish_pending_attack(db, attack_id)
        db.commit()
        assert get_pending_attack(db, attack_id)["status"] == "resolved"

    def test_persists_armor_sublocation(self, db):
        attacker_id, _ = make_attacker(db)
        target_id = make_target(db)

        attack_id = create_pending_attack(
            db,
            **pending_payload(
                attacker_id,
                target_id,
                hit_location=7,
                hit_sublocation="forearms",
                hit_sublocation_roll=2,
            ),
        )
        db.commit()

        pending = get_pending_attack(db, attack_id)
        assert pending["hit_location"] == 7
        assert pending["hit_sublocation"] == "forearms"
        assert pending["hit_sublocation_roll"] == 2

    def test_second_claim_returns_none(self, db):
        attacker_id, _ = make_attacker(db)
        target_id = make_target(db)
        attack_id = create_pending_attack(
            db, **pending_payload(attacker_id, target_id)
        )
        db.commit()

        assert claim_pending_attack(db, attack_id) is not None
        assert claim_pending_attack(db, attack_id) is None

    def test_supersede_discards_the_current_attack(self, db):
        attacker_id, _ = make_attacker(db)
        target_id = make_target(db)
        attack_id = create_pending_attack(
            db, **pending_payload(attacker_id, target_id)
        )
        db.commit()

        supersede_pending_attacks(db, 100)
        db.commit()

        assert get_pending_attack_for_channel(db, 100) is None
        assert get_pending_attack(db, attack_id)["status"] == "superseded"

    def test_second_pending_in_same_channel_violates_the_unique_index(self, db):
        attacker_id, _ = make_attacker(db)
        target_id = make_target(db)
        create_pending_attack(db, **pending_payload(attacker_id, target_id))
        db.commit()

        try:
            create_pending_attack(
                db,
                **pending_payload(
                    attacker_id,
                    target_id,
                    weapon_name="Outra",
                ),
            )
        except Exception as error:
            assert "UNIQUE" in str(error)
        else:
            raise AssertionError("Expected a UNIQUE constraint failure")


class TestCombatStance:
    def test_stance_upserts_without_losing_existing_conditions(self, db):
        character_id = insert_character(db, owner_id=1)
        set_player_condition(db, 1, "evaluate", 2)

        set_character_combat_stance(
            db, character_id, no_defense=1, defense_bonus=0
        )
        db.commit()

        conditions = get_character_conditions_by_id(db, character_id)
        assert conditions["evaluate"] == 2
        assert conditions["no_defense"] == 1
        assert conditions["defense_bonus"] == 0

    def test_stance_can_be_replaced(self, db):
        character_id = insert_character(db, owner_id=1)

        set_character_combat_stance(
            db, character_id, no_defense=1, defense_bonus=0
        )
        set_character_combat_stance(
            db, character_id, no_defense=0, defense_bonus=1
        )
        db.commit()

        conditions = get_character_conditions_by_id(db, character_id)
        assert conditions["no_defense"] == 0
        assert conditions["defense_bonus"] == 1


class TestInternalUnarmedWeapons:
    def test_unarmed_modes_are_always_available_without_inventory(
        self, db
    ):
        character_id = insert_character(db, owner_id=1, name="Desarmado")

        modes = get_equipped_melee_modes(db, character_id)
        by_name = {mode["mode_name"]: mode for mode in modes}

        assert set(by_name) == {"Soco", "Chute"}
        assert by_name["Soco"]["is_unarmed"] is True
        assert by_name["Soco"]["is_fallback"] is True
        assert by_name["Soco"]["skill_id"] is None
        assert by_name["Soco"]["skill_name"] is None
        assert by_name["Chute"]["attack_modifier"] == -2
        assert get_character_inventory_data_by_id(
            db, character_id
        )["melee_weapons"] == []


    def test_specific_unarmed_skill_hides_generic_modes(self, db):
        character_id = insert_character(db, owner_id=1, name="Briguento")
        skill_id = db.execute(
            "SELECT skill_id FROM skills WHERE name = 'Briga'"
        ).fetchone()[0]
        db.execute(
            "INSERT INTO character_skills (character_id, skill_id, relative_level) "
            "VALUES (?, ?, 0)",
            (character_id, skill_id),
        )
        db.commit()

        modes = get_equipped_melee_modes(db, character_id)
        by_name = {mode["mode_name"]: mode for mode in modes}

        assert set(by_name) == {"Soco", "Chute"}
        assert by_name["Soco"]["weapon_name"] == "Briga"
        assert by_name["Soco"]["skill_name"] == "Briga"
        assert by_name["Soco"]["is_fallback"] is False


class TestRangedWeapons:
    def test_returns_only_equipped_ranged_weapons(self, db):
        character_id = insert_character(db, owner_id=1)
        equipped_id = insert_ranged_weapon(
            db, name="Arco", damage="2d+1 imp"
        )
        stored_id = insert_ranged_weapon(db, name="Besta")
        link_ranged_weapon(db, character_id, equipped_id, is_equipped=1)
        link_ranged_weapon(db, character_id, stored_id, is_equipped=0)
        db.commit()

        weapons = get_equipped_ranged_weapons(db, character_id)

        assert [weapon["ranged_weapon_id"] for weapon in weapons] == [
            equipped_id
        ]
        assert weapons[0]["damage"] == "2d+1 imp"


class TestCombatLog:
    def test_log_roundtrip_and_damage_revert_tracking(self, db):
        character_id = insert_character(db, owner_id=1, current_pv=5)
        session = get_or_create_combat_session(db, 1, 100)
        db.commit()

        log_id = add_combat_log(
            db,
            session_id=session["session_id"],
            channel_id=100,
            event_type="damage",
            target_character_id=character_id,
            value=3,
            hp_before=8,
            hp_after=5,
            description="Dano de teste.",
        )
        db.commit()

        entries = get_recent_combat_log(db, session["session_id"])
        assert entries[0]["log_id"] == log_id
        damage = get_last_damage_log(db, 100)
        assert damage["hp_before"] == 8
        assert damage["hp_after"] == 5

        old, new = set_character_current_pv(db, character_id, 8)
        mark_combat_log_reverted(db, log_id)
        db.commit()
        assert (old, new) == (5, 8)
        assert get_last_damage_log(db, 100) is None

    def test_session_active_panel_and_initiative(self, db):
        character_id = insert_character(db, owner_id=1)
        session = get_or_create_combat_session(db, 1, 100)
        ensure_combat_participant(
            db,
            session_id=session["session_id"],
            character_id=character_id,
            owner_id=1,
            is_npc=0,
            initiative=7,
        )
        set_participant_initiative(
            db, session["session_id"], character_id, 9.5
        )
        set_combat_session_active(
            db, session["session_id"], character_id, 2
        )
        set_combat_session_panel(db, session["session_id"], 12345)
        db.commit()

        active = get_active_combat_session(db, 100)
        participant = get_combat_participant(
            db, session["session_id"], character_id
        )
        assert active["active_character_id"] == character_id
        assert active["round_number"] == 2
        assert active["panel_message_id"] == 12345
        assert participant["initiative"] == 9.5


class TestCombatEffectsPersistence:
    def test_catalog_link_list_and_unlink(self, db):
        character_id = insert_character(db, owner_id=1)
        effect_id = insert_combat_effect(
            db,
            "Fúria",
            "attack",
            value=2,
            uses_per_turn=1,
        )

        catalog_effect = get_combat_effect(db, effect_id)
        assert catalog_effect["name"] == "Fúria"
        assert catalog_effect["value"] == 2

        assert link_character_effect(db, character_id, effect_id) is True
        assert link_character_effect(db, character_id, effect_id) is False
        db.commit()

        effects = get_character_combat_effects(db, character_id)
        assert effects[0]["effect_id"] == effect_id
        assert effects[0]["name"] == "Fúria"
        assert get_character_effect_link(db, character_id, effect_id) is True

        assert unlink_character_effect(db, character_id, effect_id) is True
        assert unlink_character_effect(db, character_id, effect_id) is False
        db.commit()
        assert get_character_combat_effects(db, character_id) == []


class TestCombatParticipants:
    def test_use_counters_and_turn_reset(self, db):
        character_id = insert_character(db, owner_id=1)
        session = get_or_create_combat_session(db, 1, 100)
        db.commit()

        participant = ensure_combat_participant(
            db,
            session_id=session["session_id"],
            character_id=character_id,
            owner_id=1,
            is_npc=0,
        )
        assert participant["defense_uses"] == {}

        record_participant_use(
            db,
            session_id=session["session_id"],
            character_id=character_id,
            field="defense_uses",
            key="dodge",
        )
        record_participant_use(
            db,
            session_id=session["session_id"],
            character_id=character_id,
            field="effect_uses",
            key="7",
        )
        db.commit()

        participant = get_combat_participant(
            db, session["session_id"], character_id
        )
        assert participant["defense_uses"] == {"dodge": 1}
        assert participant["effect_uses"] == {"7": 1}

        reset_combat_participant_turn(
            db, session["session_id"], character_id
        )
        db.commit()
        participant = get_combat_participant(
            db, session["session_id"], character_id
        )
        assert participant["defense_uses"] == {}
        assert participant["effect_uses"] == {}


class TestAimEvaluateAndResources:
    def test_aim_evaluate_sets_conditions_and_clears_stance(self, db):
        character_id = insert_character(db, owner_id=1)
        set_character_combat_stance(
            db, character_id, no_defense=1, defense_bonus=0
        )
        set_character_aim_evaluate(
            db, character_id, aim=2, evaluate=0
        )
        db.commit()

        conditions = get_character_conditions_by_id(db, character_id)
        assert conditions["aim"] == 2
        assert conditions["evaluate"] == 0
        assert conditions["no_defense"] == 0
        assert conditions["defense_bonus"] == 0

    def test_spending_resources_clamps_at_zero(self, db):
        character_id = insert_character(
            db, owner_id=1, current_pf=3, current_er=2
        )
        db.commit()

        assert spend_character_resource(db, character_id, "pf", 2) == (3, 1)
        assert spend_character_resource(db, character_id, "pf", 5) == (1, 0)
        assert spend_character_resource(db, character_id, "er", 2) == (2, 0)
        db.commit()


class TestInjuryApplication:
    def test_apply_character_injury_updates_pv(self, db):
        character_id = insert_character(db, owner_id=1, current_pv=10)
        db.commit()

        old_pv, new_pv = apply_character_injury(db, character_id, 4)
        db.commit()

        assert (old_pv, new_pv) == (10, 6)
        row = db.execute(
            "SELECT current_pv FROM characters WHERE character_id = ?",
            (character_id,),
        ).fetchone()
        assert row == (6,)

    def test_set_and_clear_character_shock_caps_at_four(self, db):
        character_id = insert_character(db, owner_id=1)
        db.commit()

        set_character_shock(db, character_id, 7)
        db.commit()
        row = db.execute(
            "SELECT shock FROM next_turn_conditions WHERE character_id = ?",
            (character_id,),
        ).fetchone()
        assert row == (4,)

        clear_character_shock(db, character_id)
        db.commit()
        row = db.execute(
            "SELECT shock FROM next_turn_conditions WHERE character_id = ?",
            (character_id,),
        ).fetchone()
        assert row == (0,)

    def test_clear_conditions_resets_all_columns(self, db):
        character_id = insert_character(db, owner_id=1)
        set_player_condition(db, 1, "aim", 3)
        set_player_condition(db, 1, "shock", 2)

        clear_character_conditions(db, character_id)
        db.commit()

        row = db.execute(
            "SELECT aim, evaluate, shock, feint FROM next_turn_conditions WHERE character_id = ?",
            (character_id,),
        ).fetchone()
        assert row == (0, 0, 0, 0)
