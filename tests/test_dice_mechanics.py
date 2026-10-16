"""Tests for the deterministic dice engine in utils/dice_mechanics.py."""

from __future__ import annotations

import sqlite3

import pytest

from helpers import BudgetRng, dice_sequence, insert_hdm
from utils import dice_mechanics
from utils.dice_mechanics import consume_deterministic_fate, hdm_dices


def roll_once(monkeypatch, values):
    """Run a single hdm_dices call with a deterministic RNG stream."""
    rng = BudgetRng(values)
    monkeypatch.setattr(dice_mechanics, "randint", rng)
    return rng


class TestHdmDicesNormalSuccess:
    def test_discards_rolls_of_three_and_four(self, monkeypatch):
        roll_once(monkeypatch, dice_sequence([1, 1, 1], [1, 1, 2], [2, 2, 2]))

        assert hdm_dices(nh=10, fate=0) == [2, 2, 2]

    def test_accepts_lowest_regular_success(self, monkeypatch):
        roll_once(monkeypatch, dice_sequence([1, 2, 2]))

        assert hdm_dices(nh=10, fate=0) == [1, 2, 2]

    def test_rejects_roll_above_effective_nh(self, monkeypatch):
        roll_once(monkeypatch, dice_sequence([4, 4, 3], [4, 3, 3]))

        assert hdm_dices(nh=10, fate=0) == [4, 3, 3]

    def test_nh_15_requires_margin_below_ten(self, monkeypatch):
        roll_once(monkeypatch, dice_sequence([2, 1, 2], [3, 1, 2]))

        assert hdm_dices(nh=15, fate=0) == [3, 1, 2]

    def test_high_nh_rejects_critical_margin(self, monkeypatch):
        roll_once(monkeypatch, dice_sequence([4, 5, 6], [5, 5, 6]))

        assert hdm_dices(nh=25, fate=0) == [5, 5, 6]


class TestHdmDicesForcedFates:
    def test_nh_up_to_four_forces_critical_success(self, monkeypatch):
        roll_once(monkeypatch, dice_sequence([1, 2, 2], [1, 1, 2]))

        assert hdm_dices(nh=3, fate=0) == [1, 1, 2]

    def test_nh_26_or_more_forces_critical_success(self, monkeypatch):
        roll_once(monkeypatch, dice_sequence([6, 6, 6]))

        assert hdm_dices(nh=30, fate=0) == [6, 6, 6]


class TestHdmDicesNormalFailure:
    def test_accepts_failure_below_seventeen(self, monkeypatch):
        roll_once(monkeypatch, dice_sequence([1, 2, 2], [4, 4, 3]))

        assert hdm_dices(nh=10, fate=1) == [4, 4, 3]

    def test_nh_16_requires_exactly_seventeen(self, monkeypatch):
        roll_once(monkeypatch, dice_sequence([6, 6, 6], [6, 5, 6]))

        assert hdm_dices(nh=16, fate=1) == [6, 5, 6]


class TestHdmDicesCriticalSuccess:
    def test_low_nh_accepts_roll_up_to_four(self, monkeypatch):
        roll_once(monkeypatch, dice_sequence([2, 2, 2], [1, 1, 2]))

        assert hdm_dices(nh=10, fate=2) == [1, 1, 2]

    def test_nh_15_requires_margin_of_ten(self, monkeypatch):
        roll_once(monkeypatch, dice_sequence([2, 2, 2], [2, 1, 2]))

        assert hdm_dices(nh=15, fate=2) == [2, 1, 2]


class TestHdmDicesCriticalFailure:
    def test_low_nh_accepts_margin_of_ten(self, monkeypatch):
        roll_once(monkeypatch, dice_sequence([5, 5, 5]))

        assert hdm_dices(nh=5, fate=3) == [5, 5, 5]

    def test_mid_nh_accepts_seventeen(self, monkeypatch):
        roll_once(monkeypatch, dice_sequence([6, 5, 5], [6, 6, 5]))

        assert hdm_dices(nh=10, fate=3) == [6, 6, 5]

    def test_nh_15_accepts_seventeen_but_not_sixteen(self, monkeypatch):
        roll_once(monkeypatch, dice_sequence([6, 5, 5], [6, 6, 5]))

        assert hdm_dices(nh=15, fate=3) == [6, 6, 5]

    def test_nh_16_requires_eighteen(self, monkeypatch):
        roll_once(monkeypatch, dice_sequence([6, 6, 5], [6, 6, 6]))

        assert hdm_dices(nh=16, fate=3) == [6, 6, 6]

    def test_unknown_fate_falls_back_to_critical_failure(self, monkeypatch):
        roll_once(monkeypatch, dice_sequence([6, 6, 6]))

        assert hdm_dices(nh=20, fate=7) == [6, 6, 6]


class TestHdmDicesLoopGuard:
    def test_impossible_predicate_exhausts_the_budget(self, monkeypatch):
        rng = BudgetRng([1, 1, 1], budget=6)
        monkeypatch.setattr(dice_mechanics, "randint", rng)

        with pytest.raises(AssertionError, match="RNG budget exhausted"):
            hdm_dices(nh=10, fate=0)


class TestConsumeDeterministicFate:
    def test_returns_and_purges_the_stored_fate(self, db_path, monkeypatch):
        monkeypatch.setattr(dice_mechanics, "DATABASE_FILE_PATH", db_path)
        connection = sqlite3.connect(db_path)
        insert_hdm(connection, player_id=42, fate=3)
        connection.close()

        assert consume_deterministic_fate(42) == 3
        assert consume_deterministic_fate(42) is None

        connection = sqlite3.connect(db_path)
        remaining = connection.execute(
            "SELECT COUNT(*) FROM hdm WHERE id_player = ?", (42,)
        ).fetchone()[0]
        connection.close()
        assert remaining == 0

    def test_unknown_player_returns_none(self, db_path, monkeypatch):
        monkeypatch.setattr(dice_mechanics, "DATABASE_FILE_PATH", db_path)

        assert consume_deterministic_fate(999) is None

    def test_database_error_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(dice_mechanics, "DATABASE_FILE_PATH", tmp_path)

        assert consume_deterministic_fate(1) is None
