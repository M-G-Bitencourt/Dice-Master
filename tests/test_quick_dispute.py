"""Tests for utils/test_mechanics.py::quick_dispute."""

from __future__ import annotations

import pytest

from helpers import patch_rng
from utils import test_mechanics
from utils.test_mechanics import quick_dispute


class HdmStub:
    """Deterministic replacement for hdm_dices that records every call.

    Dice can be pinned per 1-based call index through ``responses`` or per
    requested fate through ``by_fate``; any remaining call falls back to
    ``default``. No real RNG is involved, so the retry loop inside
    quick_dispute can never hang the suite.
    """

    def __init__(self, responses=None, by_fate=None, default=(1, 1, 1)):
        self.responses = {
            index: list(dice) for index, dice in (responses or {}).items()
        }
        self.by_fate = {fate: list(dice) for fate, dice in (by_fate or {}).items()}
        self.default = list(default)
        self.calls: list[tuple[int, int]] = []

    def __call__(self, nh: int, fate: int) -> list[int]:
        self.calls.append((nh, fate))
        if len(self.calls) in self.responses:
            return list(self.responses[len(self.calls)])
        if fate in self.by_fate:
            return list(self.by_fate[fate])
        return list(self.default)


def install_stubs(monkeypatch, fate, hdm_stub):
    """Patch fate consumption and dice rolling, recording the queried player id."""
    consumed: list[int] = []

    def fake_consume(player_id):
        consumed.append(player_id)
        return fate

    monkeypatch.setattr(test_mechanics, "consume_deterministic_fate", fake_consume)
    monkeypatch.setattr(test_mechanics, "hdm_dices", hdm_stub)
    return consumed


def assert_result_structure(result):
    """Assert the exact public shape of a quick_dispute result."""
    assert set(result) == {"result1", "result2"}
    assert set(result["result1"]) == {"dice_pool1", "success_roll1", "margin1", "dices1"}
    assert set(result["result2"]) == {"dice_pool2", "success_roll2", "margin2", "dices2"}


def assert_pool_consistency(result, nh1, nh2):
    """Assert pools, success flags and margins match the rolled dice."""
    for index, nh in ((1, nh1), (2, nh2)):
        side = result[f"result{index}"]
        pool = sum(side[f"dices{index}"])
        assert side[f"dice_pool{index}"] == pool
        assert side[f"success_roll{index}"] is (pool <= nh)
        assert side[f"margin{index}"] == nh - pool


class TestQuickDisputeFateZero:
    def test_first_comparison_wins(self, monkeypatch):
        stub = HdmStub(responses={1: [1, 1, 1], 2: [3, 3, 3]})
        consumed = install_stubs(monkeypatch, fate=0, hdm_stub=stub)

        result = quick_dispute(player_id=77, effective_nh1=12, effective_nh2=10)

        assert consumed == [77]
        assert stub.calls == [(12, 0), (10, 0)]
        assert_result_structure(result)
        assert result["result1"]["dices1"] == [1, 1, 1]
        assert result["result2"]["dices2"] == [3, 3, 3]
        assert result["result1"]["margin1"] == 9
        assert result["result2"]["margin2"] == 1
        assert result["result1"]["success_roll1"] is True
        assert result["result2"]["success_roll2"] is True
        assert_pool_consistency(result, 12, 10)

    def test_second_comparison_wins_after_tie(self, monkeypatch):
        stub = HdmStub(
            responses={1: [3, 3, 3], 2: [1, 1, 1], 3: [1, 1, 1], 4: [3, 3, 3]}
        )
        install_stubs(monkeypatch, fate=0, hdm_stub=stub)

        result = quick_dispute(player_id=1, effective_nh1=10, effective_nh2=10)

        assert stub.calls == [(10, 0), (10, 0), (10, 0), (10, 0)]
        assert result["result1"]["dices1"] == [1, 1, 1]
        assert result["result2"]["dices2"] == [3, 3, 3]
        assert result["result1"]["margin1"] == 7
        assert result["result2"]["margin2"] == 1
        assert_pool_consistency(result, 10, 10)

    def test_escapes_loop_with_failure_roll_for_the_enemy(self, monkeypatch):
        stub = HdmStub(by_fate={1: [2, 2, 2]})
        install_stubs(monkeypatch, fate=0, hdm_stub=stub)

        result = quick_dispute(player_id=1, effective_nh1=8, effective_nh2=10)

        assert stub.calls.count((8, 0)) == 101
        assert stub.calls.count((10, 0)) == 101
        assert stub.calls.count((10, 1)) == 1
        assert len(stub.calls) == 203
        assert stub.calls[-1] == (10, 1)
        assert result["result1"]["dices1"] == [1, 1, 1]
        assert result["result2"]["dices2"] == [2, 2, 2]
        assert result["result1"]["margin1"] == 5
        assert result["result2"]["margin2"] == 4
        assert result["result1"]["success_roll1"] is True
        assert result["result2"]["success_roll2"] is True
        assert_pool_consistency(result, 8, 10)


class TestQuickDisputeFateOne:
    def test_first_comparison_loses(self, monkeypatch):
        stub = HdmStub(responses={1: [3, 3, 3], 2: [1, 1, 1]})
        consumed = install_stubs(monkeypatch, fate=1, hdm_stub=stub)

        result = quick_dispute(player_id=42, effective_nh1=10, effective_nh2=12)

        assert consumed == [42]
        assert stub.calls == [(10, 0), (12, 0)]
        assert_result_structure(result)
        assert result["result1"]["margin1"] == 1
        assert result["result2"]["margin2"] == 9
        assert result["result1"]["success_roll1"] is True
        assert result["result2"]["success_roll2"] is True
        assert_pool_consistency(result, 10, 12)

    def test_second_comparison_loses_after_tie(self, monkeypatch):
        stub = HdmStub(
            responses={1: [1, 1, 1], 2: [3, 3, 3], 3: [3, 3, 3], 4: [1, 1, 1]}
        )
        install_stubs(monkeypatch, fate=1, hdm_stub=stub)

        result = quick_dispute(player_id=1, effective_nh1=10, effective_nh2=10)

        assert stub.calls == [(10, 0), (10, 0), (10, 0), (10, 0)]
        assert result["result1"]["dices1"] == [3, 3, 3]
        assert result["result2"]["dices2"] == [1, 1, 1]
        assert result["result1"]["margin1"] == 1
        assert result["result2"]["margin2"] == 7
        assert_pool_consistency(result, 10, 10)

    def test_escapes_loop_with_failure_roll_for_the_player(self, monkeypatch):
        stub = HdmStub(by_fate={1: [2, 2, 2]})
        install_stubs(monkeypatch, fate=1, hdm_stub=stub)

        result = quick_dispute(player_id=1, effective_nh1=10, effective_nh2=8)

        assert stub.calls.count((10, 0)) == 101
        assert stub.calls.count((8, 0)) == 101
        assert stub.calls.count((10, 1)) == 1
        assert len(stub.calls) == 203
        assert stub.calls[-1] == (10, 1)
        assert result["result1"]["dices1"] == [2, 2, 2]
        assert result["result2"]["dices2"] == [1, 1, 1]
        assert result["result1"]["margin1"] == 4
        assert result["result2"]["margin2"] == 5
        assert result["result1"]["success_roll1"] is True
        assert result["result2"]["success_roll2"] is True
        assert_pool_consistency(result, 10, 8)


class TestQuickDisputeFateTwo:
    def test_player_passes_and_enemy_fails(self, monkeypatch):
        stub = HdmStub(responses={1: [1, 1, 1], 2: [4, 4, 4]})
        install_stubs(monkeypatch, fate=2, hdm_stub=stub)

        result = quick_dispute(player_id=1, effective_nh1=12, effective_nh2=8)

        assert stub.calls == [(12, 0), (8, 1)]
        assert result["result1"]["dices1"] == [1, 1, 1]
        assert result["result2"]["dices2"] == [4, 4, 4]
        assert result["result1"]["success_roll1"] is True
        assert result["result2"]["success_roll2"] is False
        assert result["result1"]["margin1"] == 9
        assert result["result2"]["margin2"] == -4
        assert_pool_consistency(result, 12, 8)


class TestQuickDisputeFateThree:
    def test_player_fails_and_enemy_passes(self, monkeypatch):
        stub = HdmStub(responses={1: [5, 5, 5], 2: [1, 1, 1]})
        install_stubs(monkeypatch, fate=3, hdm_stub=stub)

        result = quick_dispute(player_id=1, effective_nh1=12, effective_nh2=8)

        assert stub.calls == [(12, 1), (8, 0)]
        assert result["result1"]["dices1"] == [5, 5, 5]
        assert result["result2"]["dices2"] == [1, 1, 1]
        assert result["result1"]["success_roll1"] is False
        assert result["result2"]["success_roll2"] is True
        assert result["result1"]["margin1"] == -3
        assert result["result2"]["margin2"] == 5
        assert_pool_consistency(result, 12, 8)


class TestQuickDisputeFateNone:
    def test_random_fallback_rolls_two_three_dice_pools(self, monkeypatch):
        stub = HdmStub()
        install_stubs(monkeypatch, fate=None, hdm_stub=stub)
        rng = patch_rng(monkeypatch, test_mechanics, [1, 2, 3, 4, 5, 6])

        result = quick_dispute(player_id=1, effective_nh1=10, effective_nh2=12)

        assert stub.calls == []
        assert rng.calls == 6
        assert_result_structure(result)
        assert result["result1"]["dices1"] == [1, 2, 3]
        assert result["result2"]["dices2"] == [4, 5, 6]
        assert result["result1"]["success_roll1"] is True
        assert result["result2"]["success_roll2"] is False
        assert result["result1"]["margin1"] == 4
        assert result["result2"]["margin2"] == -3
        assert_pool_consistency(result, 10, 12)

    def test_pools_equal_to_nh_are_successes_with_zero_margin(self, monkeypatch):
        stub = HdmStub()
        install_stubs(monkeypatch, fate=None, hdm_stub=stub)
        rng = patch_rng(monkeypatch, test_mechanics, [1, 2, 3, 6, 6, 6])

        result = quick_dispute(player_id=1, effective_nh1=6, effective_nh2=18)

        assert rng.calls == 6
        assert result["result1"]["dice_pool1"] == 6
        assert result["result2"]["dice_pool2"] == 18
        assert result["result1"]["success_roll1"] is True
        assert result["result2"]["success_roll2"] is True
        assert result["result1"]["margin1"] == 0
        assert result["result2"]["margin2"] == 0
        assert_pool_consistency(result, 6, 18)


class TestQuickDisputeUnknownFate:
    def test_unknown_fate_raises_unbound_local_error(self, monkeypatch):
        # Current behavior (suspicious): fate values outside 0-3 match no branch,
        # so dices1/dices2 stay unbound and the first sum() raises
        # UnboundLocalError. Pinned here to characterize the defect; reported
        # separately since production must not be fixed by this suite.
        stub = HdmStub()
        install_stubs(monkeypatch, fate=4, hdm_stub=stub)

        with pytest.raises(UnboundLocalError):
            quick_dispute(player_id=1, effective_nh1=10, effective_nh2=10)

        assert stub.calls == []
