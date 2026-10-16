"""Tests for the character sheet helpers in utils/db_functions.py."""

from __future__ import annotations

import discord
import pytest

from helpers import insert_character
from utils import db_functions
from utils.db_functions import (
    get_character_profile,
    get_character_profile_by_id,
    get_character_strength,
    get_character_thumbnail_by_id,
    get_character_thumbnail_payload,
    modify_character_points,
    set_character_resource,
)

PROFILE_KEYS = {
    "character_id",
    "owner_id",
    "is_npc",
    "name",
    "st",
    "dx",
    "iq",
    "ht",
    "additional_max_pv",
    "additional_vont",
    "additional_per",
    "additional_max_pf",
    "additional_basic_speed",
    "additional_basic_move",
    "energy_reserve",
    "normal_diffuse_homogeneous_unded",
    "money",
    "current_pv",
    "current_pf",
    "current_er",
    "current_points",
}


@pytest.fixture
def image_directory(monkeypatch, tmp_path):
    """Redirect the thumbnail pipeline to a throwaway image tree under tmp_path."""
    monkeypatch.setattr(db_functions, "Path", lambda _: tmp_path / "utils" / "db_functions.py")
    directory = tmp_path / "data" / "images" / "characters"
    directory.mkdir(parents=True)
    return directory


class TestGetCharacterStrength:
    def test_returns_strength_for_the_owner(self, db):
        insert_character(db, owner_id=7, st=15)

        assert get_character_strength(db, 7) == 15

    def test_raises_for_unknown_owner(self, db):
        with pytest.raises(ValueError, match="character non-existent"):
            get_character_strength(db, 999)


class TestGetCharacterProfile:
    def test_returns_all_21_columns_by_owner(self, db):
        character_id = insert_character(
            db,
            owner_id=4242,
            is_npc=0,
            name="Ficha Completa",
            st=11,
            dx=12,
            iq=13,
            ht=14,
            additional_max_pv=1,
            additional_vont=2,
            additional_per=3,
            additional_max_pf=4,
            additional_basic_speed=5,
            additional_basic_move=6,
            energy_reserve=7,
            normal_diffuse_homogeneous_unded=8,
            money=9,
            current_pv=10,
            current_pf=11,
            current_er=12,
            current_points=13,
        )

        profile = get_character_profile(db, 4242)

        assert set(profile) == PROFILE_KEYS
        assert len(profile) == 21
        assert profile == {
            "character_id": character_id,
            "owner_id": 4242,
            "is_npc": False,
            "name": "Ficha Completa",
            "st": 11,
            "dx": 12,
            "iq": 13,
            "ht": 14,
            "additional_max_pv": 1,
            "additional_vont": 2,
            "additional_per": 3,
            "additional_max_pf": 4,
            "additional_basic_speed": 5,
            "additional_basic_move": 6,
            "energy_reserve": 7,
            "normal_diffuse_homogeneous_unded": 8,
            "money": 9,
            "current_pv": 10,
            "current_pf": 11,
            "current_er": 12,
            "current_points": 13,
        }

    def test_is_npc_is_coerced_to_bool(self, db):
        insert_character(db, owner_id=1, is_npc=1)

        assert get_character_profile(db, 1)["is_npc"] is True

    def test_raises_for_unknown_owner(self, db):
        with pytest.raises(ValueError, match="No character sheet linked"):
            get_character_profile(db, 999)

    def test_by_id_returns_the_requested_character(self, db):
        first_id = insert_character(db, owner_id=1, name="Primeira")
        second_id = insert_character(db, owner_id=2, name="Segunda")

        profile = get_character_profile_by_id(db, second_id)

        assert set(profile) == PROFILE_KEYS
        assert profile["character_id"] == second_id
        assert profile["owner_id"] == 2
        assert profile["name"] == "Segunda"
        assert first_id != second_id

    def test_by_id_raises_for_unknown_character(self, db):
        with pytest.raises(ValueError, match="No character sheet linked"):
            get_character_profile_by_id(db, 999)


class TestSetCharacterResource:
    @pytest.mark.parametrize(
        ("alias", "column"),
        [
            ("hp", "current_pv"),
            ("pv", "current_pv"),
            ("current_pv", "current_pv"),
            ("fp", "current_pf"),
            ("pf", "current_pf"),
            ("current_pf", "current_pf"),
            ("er", "current_er"),
            ("re", "current_er"),
            ("current_er", "current_er"),
        ],
    )
    def test_aliases_target_the_expected_column(self, db, alias, column):
        character_id = insert_character(db, owner_id=1)

        set_character_resource(db, 1, alias, 7)

        stored = db.execute(
            f"SELECT {column} FROM characters WHERE character_id = ?", (character_id,)
        ).fetchone()[0]
        assert stored == 7

    def test_alias_is_case_insensitive(self, db):
        insert_character(db, owner_id=1)

        set_character_resource(db, 1, "HP", 9)

        assert db.execute("SELECT current_pv FROM characters WHERE owner_id = 1").fetchone()[0] == 9

    def test_hp_and_pv_share_the_same_column(self, db):
        insert_character(db, owner_id=1)

        set_character_resource(db, 1, "hp", 5)
        set_character_resource(db, 1, "pv", 6)

        assert db.execute("SELECT current_pv FROM characters WHERE owner_id = 1").fetchone()[0] == 6

    def test_fp_and_pf_share_the_same_column(self, db):
        insert_character(db, owner_id=1)

        set_character_resource(db, 1, "fp", 5)
        set_character_resource(db, 1, "pf", 6)

        assert db.execute("SELECT current_pf FROM characters WHERE owner_id = 1").fetchone()[0] == 6

    def test_er_and_re_share_the_same_column(self, db):
        insert_character(db, owner_id=1)

        set_character_resource(db, 1, "er", 5)
        set_character_resource(db, 1, "re", 6)

        assert db.execute("SELECT current_er FROM characters WHERE owner_id = 1").fetchone()[0] == 6

    def test_accepts_negative_values(self, db):
        # The helper performs no clamping; the caller is responsible for bounds.
        insert_character(db, owner_id=1)

        set_character_resource(db, 1, "hp", -3)

        assert db.execute("SELECT current_pv FROM characters WHERE owner_id = 1").fetchone()[0] == -3

    def test_rejects_unknown_resource(self, db):
        insert_character(db, owner_id=1)

        with pytest.raises(ValueError, match="does not map to any known volatile column"):
            set_character_resource(db, 1, "mana", 1)

    def test_raises_for_unknown_owner(self, db):
        with pytest.raises(ValueError, match="No character found assigned"):
            set_character_resource(db, 999, "hp", 1)

    def test_raises_when_resolution_bypasses_the_character_table(self, db, monkeypatch):
        # Defensive rowcount branch: an id returned by a tampered resolver matches no row.
        monkeypatch.setattr(db_functions, "_resolve_character_id", lambda connection, player_id: 9999)

        with pytest.raises(ValueError, match="absent from the foundational matrix"):
            set_character_resource(db, 1, "hp", 1)


class TestModifyCharacterPoints:
    def test_positive_delta_increases_current_points(self, db):
        insert_character(db, owner_id=1, name="Ganhadora", current_points=10)

        result = modify_character_points(db, 1, 5)

        assert result == ("Ganhadora", 10, 15)
        assert db.execute("SELECT current_points FROM characters").fetchone()[0] == 15

    def test_negative_delta_decreases_current_points(self, db):
        insert_character(db, owner_id=1, current_points=10)

        result = modify_character_points(db, 1, -4)

        assert result == ("Cobaia", 10, 6)

    def test_null_current_points_is_treated_as_zero(self, db):
        character_id = insert_character(db, owner_id=1, current_points=None)

        result = modify_character_points(db, character_id, 3)

        assert result == ("Cobaia", 0, 3)
        stored = db.execute(
            "SELECT current_points FROM characters WHERE character_id = ?", (character_id,)
        ).fetchone()[0]
        assert stored == 3

    def test_raises_for_unknown_character(self, db):
        with pytest.raises(ValueError, match="No character entity found"):
            modify_character_points(db, 999, 5)

    def test_touches_only_current_points(self, db):
        character_id = insert_character(
            db,
            owner_id=1,
            current_points=10,
            current_pv=7,
            current_pf=8,
            current_er=9,
            money=100,
        )

        modify_character_points(db, character_id, -4)

        row = db.execute(
            """
            SELECT current_points, current_pv, current_pf, current_er, money
            FROM characters WHERE character_id = ?
            """,
            (character_id,),
        ).fetchone()
        assert row == (6, 7, 8, 9, 100)


class TestCharacterThumbnails:
    def test_prefers_the_character_image(self, db, image_directory):
        character_id = insert_character(db, owner_id=1, character_id=5)
        (image_directory / "5.png").write_bytes(b"character-image")

        file, url = get_character_thumbnail_by_id(db, character_id)

        try:
            assert isinstance(file, discord.File)
            assert file.filename == "char_5.png"
            assert url == "attachment://char_5.png"
            assert file.fp.read() == b"character-image"
        finally:
            file.close()

    def test_falls_back_to_default_character_image(self, db, image_directory):
        character_id = insert_character(db, owner_id=1, character_id=7)
        (image_directory / "default_character.png").write_bytes(b"default-image")

        file, url = get_character_thumbnail_by_id(db, character_id)

        try:
            # The sealed filename keeps the requested character_id even on the fallback path.
            assert file.filename == "char_7.png"
            assert url == "attachment://char_7.png"
            assert file.fp.read() == b"default-image"
        finally:
            file.close()

    def test_returns_none_pair_when_no_image_exists(self, db, image_directory):
        character_id = insert_character(db, owner_id=1, character_id=8)

        assert get_character_thumbnail_by_id(db, character_id) == (None, None)

    def test_returns_none_pair_when_image_directory_is_missing(self, db, monkeypatch, tmp_path):
        monkeypatch.setattr(db_functions, "Path", lambda _: tmp_path / "utils" / "db_functions.py")
        character_id = insert_character(db, owner_id=1)

        assert get_character_thumbnail_by_id(db, character_id) == (None, None)

    def test_payload_resolves_the_owner_to_a_thumbnail(self, db, image_directory):
        character_id = insert_character(db, owner_id=55, character_id=5)
        (image_directory / "5.png").write_bytes(b"character-image")

        file, url = get_character_thumbnail_payload(db, 55)

        try:
            assert file.filename == f"char_{character_id}.png"
            assert url == f"attachment://char_{character_id}.png"
        finally:
            file.close()

    def test_payload_returns_none_pair_for_unknown_owner(self, db, image_directory):
        assert get_character_thumbnail_payload(db, 999) == (None, None)
