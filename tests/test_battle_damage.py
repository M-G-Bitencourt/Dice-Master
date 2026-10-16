"""Tests for the pure damage table engine in cogs/battle.py.

Every assertion is deterministic: randint is always replaced by a BudgetRng
stream, so the damage table, rounding and strong-attack rules are validated
without any real randomness.
"""

from __future__ import annotations

import pytest

import cogs.battle as battle_module
from cogs.battle import damage_func
from helpers import patch_rng

# (st, gdp_geb, expected_dice_count, expected_st_mod)
DAMAGE_TABLE_CASES = [
    # Thrust (GdP), column index 0
    (1, 0, 1, -6),
    (5, 0, 1, -4),
    (10, 0, 1, -2),
    (15, 0, 1, 1),
    (20, 0, 2, -1),
    (30, 0, 3, 0),
    (40, 0, 4, 1),
    (50, 0, 5, 2),
    (75, 0, 8, 2),
    (100, 0, 11, 0),
    # Swing (GeB), column index 1
    (1, 1, 1, -5),
    (5, 1, 1, -3),
    (10, 1, 1, 0),
    (15, 1, 2, 1),
    (20, 1, 3, 2),
    (30, 1, 5, 2),
    (40, 1, 7, -1),
    (50, 1, 8, -1),
    (75, 1, 10, 2),
    (100, 1, 13, 0),
]

# (st, gdp_geb, expected_dice_count, expected_st_mod) for non-tabulated ST
ROUNDING_CASES = [
    (41, 0, 4, 1),
    (42, 0, 4, 1),
    (44, 0, 4, 1),
    (45, 0, 5, 0),
    (46, 0, 5, 0),
    (49, 0, 5, 0),
    (99, 0, 10, 2),
    (100, 0, 11, 0),
    (41, 1, 7, -1),
    (46, 1, 7, 1),
    (99, 1, 12, 2),
    (100, 1, 13, 0),
]

# (st, expected_gdp_dice, expected_geb_dice)
ABOVE_100_CASES = [
    (100, 11, 13),
    (101, 11, 13),
    (105, 11, 13),
    (109, 11, 13),
    (110, 12, 14),
    (119, 12, 14),
    (120, 13, 15),
]


@pytest.mark.parametrize(
    "st, gdp_geb, expected_dice, expected_mod", DAMAGE_TABLE_CASES
)
def test_damage_table_matches_gurps_baseline(
    monkeypatch, st, gdp_geb, expected_dice, expected_mod
):
    """Exact dice count, ST modifier, damage and critical damage per table row."""
    patch_rng(monkeypatch, battle_module, [1] * expected_dice)

    data = damage_func(st, gdp_geb, 0)

    assert data["dice_count"] == expected_dice
    assert data["st_mod"] == expected_mod
    assert data["dices"] == [1] * expected_dice
    assert data["dice_sum"] == expected_dice
    assert data["damage"] == expected_dice + expected_mod
    assert data["critical_damage"] == 6 * expected_dice + expected_mod


def test_damage_adds_rolled_dice_and_weapon_modifier(monkeypatch):
    patch_rng(monkeypatch, battle_module, [2, 3])

    data = damage_func(20, 0, 4)

    assert data["dices"] == [2, 3]
    assert data["dice_sum"] == 5
    assert data["damage"] == 5 + (-1) + 4
    assert data["critical_damage"] == 12 + (-1) + 4


def test_critical_damage_ignores_rolled_dice(monkeypatch):
    """Critical damage always assumes all dice showing 6."""
    patch_rng(monkeypatch, battle_module, [1, 2, 3])

    data = damage_func(20, 0, 1)

    assert data["dices"] == [1, 2]
    assert data["damage"] == 1 + 2 + (-1) + 1
    assert data["critical_damage"] == 12 + (-1) + 1


@pytest.mark.parametrize("st, gdp_geb, expected_dice, expected_mod", ROUNDING_CASES)
def test_st_between_40_and_100_rounds_down_to_multiple_of_five(
    monkeypatch, st, gdp_geb, expected_dice, expected_mod
):
    patch_rng(monkeypatch, battle_module, [1] * expected_dice)

    data = damage_func(st, gdp_geb, 0)

    assert data["dice_count"] == expected_dice
    assert data["st_mod"] == expected_mod


@pytest.mark.parametrize("st, expected_gdp, expected_geb", ABOVE_100_CASES)
def test_st_above_100_adds_one_die_per_full_ten_points(
    monkeypatch, st, expected_gdp, expected_geb
):
    # One value cycling through a generous budget covers both columns.
    patch_rng(monkeypatch, battle_module, [1], budget=64)

    gdp = damage_func(st, 0, 0)
    geb = damage_func(st, 1, 0)

    assert gdp["dice_count"] == expected_gdp
    assert geb["dice_count"] == expected_geb
    assert gdp["st_mod"] == 0
    assert geb["st_mod"] == 0
    assert gdp["dice_sum"] == expected_gdp
    assert geb["dice_sum"] == expected_geb


@pytest.mark.parametrize("st", [0, -5])
@pytest.mark.parametrize("gdp_geb", [0, 1])
def test_st_at_or_below_zero_rolls_no_dice(monkeypatch, st, gdp_geb):
    patch_rng(monkeypatch, battle_module, [1])

    data = damage_func(st, gdp_geb, 7)

    assert data["dice_count"] == 0
    assert data["dices"] == []
    assert data["dice_sum"] == 0
    assert data["st_mod"] == 0
    assert data["damage"] == 7
    assert data["critical_damage"] == 7


def test_strong_none_and_zero_add_no_bonus(monkeypatch):
    patch_rng(monkeypatch, battle_module, [1, 2])

    without_strong = damage_func(20, 0, 3, None)
    with_zero = damage_func(20, 0, 3, 0)

    assert without_strong["damage"] == with_zero["damage"] == 3 + (-1) + 3
    assert (
        without_strong["critical_damage"]
        == with_zero["critical_damage"]
        == 12 + (-1) + 3
    )


def test_strong_with_single_die_adds_two(monkeypatch):
    patch_rng(monkeypatch, battle_module, [5])

    data = damage_func(10, 1, 3, 1)

    # Single die: the +2 flat bonus applies.
    assert data["damage"] == 5 + 0 + 3 + 2
    assert data["critical_damage"] == 6 + 0 + 3 + 2


def test_strong_with_multiple_dice_adds_dice_count(monkeypatch):
    patch_rng(monkeypatch, battle_module, [1, 2])

    data = damage_func(20, 0, 3, 1)

    # More than one die: the +dice_count bonus applies.
    assert data["damage"] == 3 + (-1) + 3 + 2
    assert data["critical_damage"] == 12 + (-1) + 3 + 2


def test_strong_with_zero_dice_still_adds_two(monkeypatch):
    """Edge case: the flat +2 branch is used whenever dice_count <= 1, including 0."""
    patch_rng(monkeypatch, battle_module, [1])

    data = damage_func(0, 0, 3, 1)

    assert data["dice_count"] == 0
    assert data["damage"] == 0 + 0 + 3 + 2
    assert data["critical_damage"] == 0 + 0 + 3 + 2


def test_values_other_than_one_are_treated_as_no_strong_attack(monkeypatch):
    patch_rng(monkeypatch, battle_module, [1, 2])

    data = damage_func(20, 0, 3, 2)

    assert data["damage"] == 3 + (-1) + 3
    assert data["critical_damage"] == 12 + (-1) + 3


def test_payload_exposes_exact_key_set(monkeypatch):
    patch_rng(monkeypatch, battle_module, [1])

    data = damage_func(10, 0, 0)

    assert set(data) == {
        "critical_damage",
        "damage",
        "dice_count",
        "dices",
        "st_mod",
        "dice_sum",
    }


@pytest.mark.parametrize("invalid_column", [2, 99])
def test_gdp_geb_above_one_raises_index_error(monkeypatch, invalid_column):
    # The column selector indexes a two-element tuple directly, so any value
    # other than 0 or 1 escapes the tuple and raises IndexError.
    patch_rng(monkeypatch, battle_module, [1])

    with pytest.raises(IndexError):
        damage_func(10, invalid_column, 0)


def test_negative_gdp_geb_silently_reads_swing_column(monkeypatch):
    # Latent validation gap documented as-is: gdp_geb=-1 is accepted and Python
    # negative indexing selects the swing (GeB) entry instead of being rejected.
    patch_rng(monkeypatch, battle_module, [1])

    data = damage_func(10, -1, 0)

    assert data["dice_count"] == 1
    assert data["st_mod"] == 0
