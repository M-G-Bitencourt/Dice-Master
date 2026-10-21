"""Tests for automatic injury HT checks and wound thresholds."""

from __future__ import annotations

import pytest

import cogs.combat_helpers.combat_health as combat_health
from cogs.combat_helpers.combat_health import resolve_damage_health
from utils.combat import compute_basic_move, is_wounded


def profile(**overrides) -> dict:
    data = {
        "st": 10,
        "dx": 10,
        "ht": 10,
        "additional_max_pv": 0,
        "additional_basic_speed": 0,
        "additional_basic_move": 0,
    }
    data.update(overrides)
    return data


def patch_rolls(monkeypatch, values: list[int]) -> None:
    rolls = iter(values)
    monkeypatch.setattr(combat_health, "randint", lambda *_: next(rolls))


class TestWoundThreshold:
    @pytest.mark.parametrize(
        "current_pv, max_pv, expected",
        [(3, 10, True), (4, 10, False), (0, 10, True), (0, 0, False)],
    )
    def test_is_wounded(self, current_pv, max_pv, expected):
        assert is_wounded(current_pv, max_pv) is expected

    def test_basic_move_is_halved_when_wounded(self):
        assert compute_basic_move(10, 10) == 5
        assert compute_basic_move(10, 10, wounded=True) == 2
        assert compute_basic_move(12, 10, 1, 2) == 8
        assert compute_basic_move(12, 10, 1, 2, wounded=True) == 4


class TestHTEffectBonuses:
    def test_ht_check_bonus_applies_to_consciousness_and_death(self, monkeypatch):
        patch_rolls(monkeypatch, [3, 3, 3, 1, 1, 1])

        result = resolve_damage_health(
            profile(ht_check_bonus=2), 10, -11
        )

        assert [check["target"] for check in result["checks"]] == [12, 12]

    def test_effective_max_pv_and_basic_speed_are_used(self):
        result = resolve_damage_health(
            profile(
                max_pv=13,
                additional_basic_speed_effective=1,
            ),
            10,
            3,
        )

        assert result["max_pv"] == 13
        assert result["move"] == 3
        assert result["dodge"] == 4


class TestConsciousnessCheck:
    def test_crossing_zero_with_success_stays_conscious(self, monkeypatch):
        patch_rolls(monkeypatch, [3, 3, 3])

        result = resolve_damage_health(profile(), 5, 0)

        assert result["status"] == "consciente"
        assert result["checks"][0]["label"] == "0 PV"
        assert result["checks"][0]["effect"] == "consciente"

    def test_crossing_zero_with_failure_is_unconscious(self, monkeypatch):
        patch_rolls(monkeypatch, [4, 4, 4])

        result = resolve_damage_health(profile(), 5, 0)

        assert result["status"] == "inconsciente"
        assert result["checks"][0]["effect"] == "inconsciente"

    def test_damage_while_already_at_zero_does_not_repeat_check(self):
        result = resolve_damage_health(profile(), 0, -2)

        assert result["checks"] == []
        assert result["status"] is None


class TestDeathChecks:
    def test_death_check_success_keeps_character_alive(self, monkeypatch):
        patch_rolls(monkeypatch, [3, 3, 3, 1, 1, 1])

        result = resolve_damage_health(profile(), 10, -11)

        assert [check["label"] for check in result["checks"]] == [
            "0 PV",
            "Morte -1xPV",
        ]
        assert result["checks"][1]["effect"] == "sobrevive"
        assert result["status"] == "consciente"

    def test_failure_by_one_or_two_is_dying(self, monkeypatch):
        patch_rolls(monkeypatch, [3, 3, 3, 3, 4, 4])

        result = resolve_damage_health(profile(), 10, -11)

        assert result["checks"][1]["effect"] == "morrendo"
        assert result["status"] == "morrendo"
        assert result["conscious"] is False

    def test_failure_by_three_or_more_is_dead(self, monkeypatch):
        patch_rolls(monkeypatch, [3, 3, 3, 4, 4, 5])

        result = resolve_damage_health(profile(), 10, -11)

        assert result["checks"][1]["effect"] == "morto"
        assert result["status"] == "morto"

    def test_multiple_thresholds_are_checked_in_order(self, monkeypatch):
        patch_rolls(
            monkeypatch,
            [3, 3, 3, 1, 1, 1, 2, 2, 2],
        )

        result = resolve_damage_health(profile(), 10, -22)

        assert [check["label"] for check in result["checks"]] == [
            "0 PV",
            "Morte -1xPV",
            "Morte -2xPV",
        ]
        assert result["status"] == "consciente"

    def test_same_threshold_is_not_checked_again(self):
        result = resolve_damage_health(profile(), -11, -12)

        assert result["checks"] == []
        assert result["status"] is None

    def test_minus_five_times_is_automatic_death(self):
        result = resolve_damage_health(profile(), -40, -50)

        assert result["checks"] == []
        assert result["status"] == "morto"

    def test_minus_ten_times_is_obliteration(self):
        result = resolve_damage_health(profile(), -90, -100)

        assert result["checks"] == []
        assert result["status"] == "obliterado"

    def test_death_check_success_restores_consciousness(self, monkeypatch):
        patch_rolls(monkeypatch, [4, 4, 4, 1, 1, 1])

        result = resolve_damage_health(profile(), 5, -11)

        assert result["checks"][0]["effect"] == "inconsciente"
        assert result["checks"][1]["effect"] == "sobrevive"
        assert result["status"] == "consciente"


class TestWoundedEmbedValues:
    def test_wounded_move_and_dodge_are_halved(self):
        result = resolve_damage_health(profile(), 10, 3)

        assert result["wounded"] is True
        assert result["move"] == 2
        assert result["dodge"] == 4


class TestGMShieldHealthDirectives:
    def test_forced_consciousness_failure(self):
        result = resolve_damage_health(
            profile(),
            5,
            0,
            directive_resolver=lambda check_type: "failure",
        )

        assert result["checks"][0]["success"] is False
        assert result["status"] == "inconsciente"

    def test_no_faint_forces_consciousness_success(self):
        result = resolve_damage_health(
            profile(),
            5,
            0,
            flags={"no_faint": True},
        )

        assert result["checks"][0]["success"] is True
        assert result["status"] == "consciente"

    def test_forced_death_check_can_kill(self):
        result = resolve_damage_health(
            profile(),
            10,
            -11,
            directive_resolver=lambda check_type: (
                "dead" if check_type == "death" else None
            ),
        )

        assert result["checks"][1]["success"] is False
        assert -result["checks"][1]["margin"] >= 3
        assert result["status"] == "morto"

    def test_no_death_caps_failed_death_check_at_dying(self):
        result = resolve_damage_health(
            profile(),
            10,
            -11,
            directive_resolver=lambda check_type: (
                "dead" if check_type == "death" else None
            ),
            flags={"no_death": True},
        )

        assert result["checks"][1]["success"] is False
        assert -result["checks"][1]["margin"] <= 2
        assert result["status"] == "morrendo"

    def test_no_death_does_not_prevent_automatic_death(self):
        result = resolve_damage_health(
            profile(),
            -40,
            -50,
            flags={"no_death": True},
        )

        assert result["checks"] == []
        assert result["status"] == "morto"
