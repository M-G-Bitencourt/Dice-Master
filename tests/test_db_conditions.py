"""Tests for the transient condition and current attack state helpers in utils/db_functions.py."""

from __future__ import annotations

import pytest

from helpers import insert_attack, insert_character
from utils import db_functions
from utils.db_functions import (
    _resolve_character_id,
    clear_current_attack,
    clear_player_conditions,
    get_current_attack,
    get_player_condition,
    save_current_attack,
    set_player_condition,
)

CONDITION_COLUMNS = ("aim", "evaluate", "shock", "feint")


def seed_conditions(
    connection, character_id: int, aim: int = 0, evaluate: int = 0, shock: int = 0, feint: int = 0
) -> None:
    connection.execute(
        """
        INSERT INTO next_turn_conditions (character_id, aim, evaluate, shock, feint)
        VALUES (?, ?, ?, ?, ?)
        """,
        (character_id, aim, evaluate, shock, feint),
    )
    connection.commit()


class TestResolveCharacterId:
    def test_returns_character_id_for_the_given_owner(self, db):
        character_id = insert_character(db, owner_id=321)

        assert _resolve_character_id(db, 321) == character_id

    def test_raises_when_no_character_is_assigned(self, db):
        with pytest.raises(ValueError, match="No character found assigned"):
            _resolve_character_id(db, 999)


class TestPlayerConditions:
    def test_set_then_get_roundtrip(self, db):
        insert_character(db, owner_id=1)

        set_player_condition(db, 1, "aim", 3)

        assert get_player_condition(db, 1, "aim") == 3

    def test_get_defaults_to_zero_without_a_condition_row(self, db):
        insert_character(db, owner_id=1)

        assert get_player_condition(db, 1, "aim") == 0

    def test_get_returns_zero_for_unknown_player(self, db):
        assert get_player_condition(db, 999, "aim") == 0

    def test_get_returns_zero_for_unset_column_inside_existing_row(self, db):
        character_id = insert_character(db, owner_id=1)
        seed_conditions(db, character_id, aim=2)

        assert get_player_condition(db, 1, "shock") == 0

    def test_set_upserts_instead_of_duplicating_rows(self, db):
        character_id = insert_character(db, owner_id=1)

        set_player_condition(db, 1, "aim", 1)
        set_player_condition(db, 1, "aim", 4)

        rows = db.execute(
            "SELECT COUNT(*) FROM next_turn_conditions WHERE character_id = ?", (character_id,)
        ).fetchone()[0]
        assert rows == 1
        assert get_player_condition(db, 1, "aim") == 4

    def test_set_multiple_columns_keeps_a_single_row(self, db):
        character_id = insert_character(db, owner_id=1)

        set_player_condition(db, 1, "aim", 1)
        set_player_condition(db, 1, "evaluate", 2)
        set_player_condition(db, 1, "shock", 3)
        set_player_condition(db, 1, "feint", 4)

        rows = db.execute(
            "SELECT COUNT(*) FROM next_turn_conditions WHERE character_id = ?", (character_id,)
        ).fetchone()[0]
        assert rows == 1
        assert get_player_condition(db, 1, "aim") == 1
        assert get_player_condition(db, 1, "evaluate") == 2
        assert get_player_condition(db, 1, "shock") == 3
        assert get_player_condition(db, 1, "feint") == 4

    @pytest.mark.parametrize("column", ["mana", "aim; DROP TABLE characters", ""])
    def test_set_rejects_invalid_column(self, db, column):
        insert_character(db, owner_id=1)

        with pytest.raises(ValueError, match="not a valid condition column"):
            set_player_condition(db, 1, column, 1)

    @pytest.mark.parametrize("column", ["mana", "aim; DROP TABLE characters", ""])
    def test_get_rejects_invalid_column(self, db, column):
        insert_character(db, owner_id=1)

        with pytest.raises(ValueError, match="not a valid condition column"):
            get_player_condition(db, 1, column)

    def test_set_validates_column_before_resolving_the_character(self, db):
        # Column validation runs first, so the invalid column error wins over the missing character.
        with pytest.raises(ValueError, match="not a valid condition column"):
            set_player_condition(db, 999, "mana", 1)

    def test_set_requires_an_owned_character(self, db):
        with pytest.raises(ValueError, match="No character found assigned"):
            set_player_condition(db, 999, "aim", 1)

    def test_column_name_is_accepted_case_insensitively(self, db):
        insert_character(db, owner_id=1)

        set_player_condition(db, 1, "AIM", 5)

        assert get_player_condition(db, 1, "Aim") == 5

    def test_clear_zeroes_all_four_columns(self, db):
        character_id = insert_character(db, owner_id=1)
        seed_conditions(db, character_id, aim=1, evaluate=2, shock=3, feint=4)

        clear_player_conditions(db, 1)

        row = db.execute(
            "SELECT aim, evaluate, shock, feint FROM next_turn_conditions WHERE character_id = ?",
            (character_id,),
        ).fetchone()
        assert row == (0, 0, 0, 0)

    def test_clear_without_a_condition_row_is_a_noop(self, db):
        insert_character(db, owner_id=1)

        clear_player_conditions(db, 1)

        assert get_player_condition(db, 1, "aim") == 0

    def test_clear_requires_an_owned_character(self, db):
        with pytest.raises(ValueError, match="No character found assigned"):
            clear_player_conditions(db, 999)


class TestCurrentAttack:
    def test_save_enforces_single_row_invariant(self, db):
        insert_attack(db, raw_damage=11)

        save_current_attack(db, raw_damage=7, dmg_type=2, hit_location=5, feint=1, critical_damage=0)
        save_current_attack(db, raw_damage=9, dmg_type=3, hit_location=8, feint=0, critical_damage=1)

        count = db.execute("SELECT COUNT(*) FROM current_attacks").fetchone()[0]
        assert count == 1
        assert get_current_attack(db) == {
            "raw_damage": 9,
            "dmg_type": 3,
            "hit_location": 8,
            "feint": 0,
            "critical_damage": 1,
        }

    def test_get_returns_the_complete_state_dict(self, db):
        save_current_attack(db, raw_damage=12, dmg_type=1, hit_location=9, feint=4, critical_damage=5)

        attack = get_current_attack(db)

        assert set(attack) == {
            "raw_damage",
            "dmg_type",
            "hit_location",
            "feint",
            "critical_damage",
        }
        assert attack == {
            "raw_damage": 12,
            "dmg_type": 1,
            "hit_location": 9,
            "feint": 4,
            "critical_damage": 5,
        }

    def test_get_returns_empty_dict_when_table_is_empty(self, db):
        assert get_current_attack(db) == {}

    def test_clear_removes_every_row(self, db):
        insert_attack(db, raw_damage=3)
        insert_attack(db, raw_damage=4)

        clear_current_attack(db)

        assert db.execute("SELECT COUNT(*) FROM current_attacks").fetchone()[0] == 0
        assert get_current_attack(db) == {}
