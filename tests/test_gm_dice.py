"""Tests for deterministic selection of plausible forced results."""

from __future__ import annotations

from utils.combat import classify_roll
from utils.gm_dice import (
    apply_damage_preset,
    select_dice_for_outcome,
    select_health_dice,
    select_preset_dice,
    select_quick_contest_dice,
    select_reaction_dice,
)


def test_critical_failure_uses_a_critical_failure_total():
    dices = select_dice_for_outcome(10, "critical_failure")
    outcome = classify_roll(sum(dices), 10)

    assert outcome["critical_failure"] is True
    assert sum(dices) == 17


def test_impossible_failure_falls_back_to_success():
    dices = select_dice_for_outcome(17, "failure")
    outcome = classify_roll(sum(dices), 17)

    assert outcome["success"] is True
    assert outcome["critical_failure"] is False


def test_critical_success_uses_the_least_extreme_success():
    dices = select_dice_for_outcome(16, "critical_success")
    outcome = classify_roll(sum(dices), 16)

    assert outcome["critical_success"] is True
    assert sum(dices) == 6


def test_impossible_death_is_converted_to_dying():
    dices, total, success, margin = select_health_dice(17, "dead")

    assert dices
    assert total == 18
    assert success is False
    assert margin == -1


def test_death_at_low_health_uses_the_three_point_margin():
    dices, total, success, margin = select_health_dice(10, "dead")

    assert total == 13
    assert success is False
    assert margin == -3


def test_health_success_uses_the_closest_success_total():
    dices, total, success, margin = select_health_dice(10, "success")

    assert total == 10
    assert success is True
    assert margin == 0


def test_preset_damage_is_consistent_with_the_dice():
    dices, total = select_preset_dice(2, 1, "min")
    assert dices == [1, 1]
    assert total == 3

    dices, total = select_preset_dice(2, 1, "max")
    assert dices == [6, 6]
    assert total == 13

    dices, total = select_preset_dice(2, 1, "exact", 7)
    assert sum(dices) + 1 == 7


def test_apply_damage_preset_keeps_critical_damage_consistent():
    data = {
        "dice_count": 2,
        "total_modifier": 1,
        "dices": [5, 5],
        "critical_dices": [6, 6],
        "damage": 11,
        "critical_damage": 13,
    }

    apply_damage_preset(data, "min")

    assert data["dices"] == [1, 1]
    assert data["damage"] == 3
    assert data["critical_damage"] == 3


def test_reaction_selection_lands_in_the_requested_bracket():
    dices = select_reaction_dice(0, "good")

    assert 10 <= sum(dices) <= 15


def test_quick_contest_selection_satisfies_the_requested_result():
    dices1, dices2 = select_quick_contest_dice(10, 8, "win")
    result1 = classify_roll(sum(dices1), 10)
    result2 = classify_roll(sum(dices2), 8)

    assert result1["success"] is True
    assert result2["success"] is True
    assert result1["margin"] > result2["margin"]
