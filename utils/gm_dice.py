"""Deterministic dice selection for transient GM shield directives."""

from __future__ import annotations

from typing import Any

from utils.combat import classify_roll

DICE_TABLE: dict[int, tuple[int, int, int]] = {
    3: (1, 1, 1),
    4: (1, 1, 2),
    5: (1, 2, 2),
    6: (2, 2, 2),
    7: (2, 2, 3),
    8: (2, 3, 3),
    9: (3, 3, 3),
    10: (3, 3, 4),
    11: (3, 4, 4),
    12: (4, 4, 4),
    13: (4, 4, 5),
    14: (4, 5, 5),
    15: (5, 5, 5),
    16: (5, 5, 6),
    17: (5, 6, 6),
    18: (6, 6, 6),
}

_OUTCOME_PRIORITY: dict[str, tuple[str, ...]] = {
    "critical_failure": (
        "critical_failure",
        "failure",
        "success",
        "critical_success",
    ),
    "failure": ("failure", "success", "critical_failure", "critical_success"),
    "success": ("success", "critical_success", "failure", "critical_failure"),
    "critical_success": (
        "critical_success",
        "success",
        "failure",
        "critical_failure",
    ),
}

_LEAST_EXTREME = {
    "success": "highest",
    "failure": "lowest",
    "critical_success": "highest",
    "critical_failure": "lowest",
}


def _category(roll_total: int, target: int) -> str:
    outcome = classify_roll(roll_total, target)
    if outcome["critical_success"]:
        return "critical_success"
    if outcome["success"]:
        return "success"
    if outcome["critical_failure"]:
        return "critical_failure"
    return "failure"


def _outcome_rows(target: int) -> dict[str, list[int]]:
    rows: dict[str, list[int]] = {
        "critical_success": [],
        "success": [],
        "failure": [],
        "critical_failure": [],
    }
    for total in range(3, 19):
        rows[_category(total, target)].append(total)
    return rows


def select_dice_for_outcome(target: int, outcome: str) -> list[int]:
    """Return subtle 3d6 for the closest achievable requested outcome."""
    rows = _outcome_rows(int(target))
    requested = str(outcome)
    priorities = _OUTCOME_PRIORITY.get(
        requested, _OUTCOME_PRIORITY["failure"]
    )

    chosen_category = priorities[-1]
    for category in priorities:
        if rows.get(category):
            chosen_category = category
            break

    totals = rows[chosen_category]
    if not totals:
        return list(DICE_TABLE[10])

    if _LEAST_EXTREME[chosen_category] == "highest":
        total = max(totals)
    else:
        total = min(totals)
    return list(DICE_TABLE[total])


def dice_for_total(
    dice_count: int,
    modifier: int,
    target_total: int,
) -> tuple[list[int], int]:
    """Return balanced dice whose sum plus modifier is closest to a total."""
    count = max(1, int(dice_count))
    modifier = int(modifier)
    minimum = count + modifier
    maximum = count * 6 + modifier
    target = max(minimum, min(maximum, int(target_total)))
    dice_sum = max(count, min(count * 6, target - modifier))

    base = dice_sum // count
    remainder = dice_sum % count
    values = [base] * count
    for index in range(remainder):
        values[index] += 1
    return values, sum(values) + modifier


def select_preset_dice(
    dice_count: int,
    modifier: int,
    preset: str,
    exact_total: int | None = None,
) -> tuple[list[int], int]:
    """Return balanced dice for a damage or generic-roll preset."""
    count = max(1, int(dice_count))
    modifier = int(modifier)
    minimum = count + modifier
    maximum = count * 6 + modifier
    fractions = {
        "min": 0.0,
        "low": 0.25,
        "average": 0.5,
        "high": 0.75,
        "max": 1.0,
    }

    if preset == "exact" and exact_total is not None:
        target = int(exact_total)
    elif preset in fractions:
        target = round(minimum + (maximum - minimum) * fractions[preset])
    else:
        target = maximum

    return dice_for_total(count, modifier, target)


def apply_damage_preset(
    damage_data: dict[str, Any],
    preset: str | None,
    exact_total: int | None = None,
) -> dict[str, Any]:
    """Apply a damage preset to a mutable damage-data mapping."""
    if not preset:
        return damage_data

    dice_count = int(damage_data.get("dice_count") or 0)
    if dice_count <= 0:
        return damage_data

    modifier = int(damage_data.get("total_modifier") or 0)
    dices, total = select_preset_dice(
        dice_count, modifier, str(preset), exact_total
    )
    damage_data["dices"] = dices
    damage_data["dice_sum"] = sum(dices)
    damage_data["damage"] = total
    critical_dices = list(dices)
    damage_data["critical_dices"] = critical_dices
    damage_data["critical_damage"] = total
    return damage_data


def select_health_dice(
    health_target: int,
    outcome: str,
) -> tuple[list[int], int, bool, int]:
    """Return dice and margin for a requested health-check outcome."""
    target = int(health_target)
    requested = str(outcome)

    successes = [total for total in range(3, 19) if total <= target]
    failures = [total for total in range(3, 19) if total > target]

    if requested == "success":
        if successes:
            total = max(successes)
            return list(DICE_TABLE[total]), total, True, target - total
        total = min(failures) if failures else 18
        return list(DICE_TABLE[total]), total, False, target - total

    if requested in {"failure", "dying"}:
        margin_target = 1 if requested == "dying" else 1
        preferred = [
            total
            for total in failures
            if 1 <= total - target <= (2 if requested == "dying" else 18)
        ]
        if preferred:
            total = min(preferred, key=lambda value: abs((value - target) - margin_target))
            return list(DICE_TABLE[total]), total, False, target - total
        if failures:
            total = min(failures, key=lambda value: abs((value - target) - margin_target))
            return list(DICE_TABLE[total]), total, False, target - total
        total = max(successes)
        return list(DICE_TABLE[total]), total, True, target - total

    if requested == "dead":
        preferred = [total for total in failures if total - target >= 3]
        if preferred:
            total = min(preferred)
            return list(DICE_TABLE[total]), total, False, target - total
        if failures:
            total = max(failures)
            return list(DICE_TABLE[total]), total, False, target - total
        total = max(successes)
        return list(DICE_TABLE[total]), total, True, target - total

    return select_health_dice(health_target, "success")


def select_reaction_dice(modifier: int, outcome: str) -> list[int]:
    """Return 3d6 for the closest requested reaction bracket."""
    modifier = int(modifier)
    total_scores: list[tuple[float, int]] = []

    brackets = {
        "disastrous": lambda total: total <= 3,
        "bad": lambda total: 4 <= total <= 9,
        "good": lambda total: 10 <= total <= 15,
        "excellent": lambda total: total >= 16,
    }
    centers = {
        "disastrous": 3.0,
        "bad": 6.5,
        "good": 12.5,
        "excellent": 17.0,
    }
    requested = str(outcome) if str(outcome) in brackets else "good"

    for dice_total in range(3, 19):
        effective_total = dice_total + modifier
        score = abs(effective_total - centers[requested])
        if not brackets[requested](effective_total):
            score += 100.0
        total_scores.append((score, dice_total))

    _, chosen = min(total_scores, key=lambda item: item[0])
    return list(DICE_TABLE[chosen])


def _contest_score(
    pool1: int, nh1: int, pool2: int, nh2: int, outcome: str
) -> tuple[int, int]:
    success1 = pool1 <= nh1
    success2 = pool2 <= nh2
    margin1 = nh1 - pool1
    margin2 = nh2 - pool2
    difference = margin1 - margin2

    if outcome == "win":
        if success1 and success2 and difference > 0:
            return 0, abs(difference)
        if success1 and not success2:
            return 1, 0
        if success1 and success2:
            return 1, abs(difference)
        return 2, abs(difference)
    if outcome == "lose":
        if success1 and success2 and difference < 0:
            return 0, abs(difference)
        if not success1 and success2:
            return 1, 0
        if success1 and success2:
            return 1, abs(difference)
        return 2, abs(difference)
    if outcome == "critical_success":
        if success1 and not success2:
            return 0, 0
        if success1 and success2 and difference > 0:
            return 1, abs(difference)
        return 2, abs(difference)
    if outcome == "critical_failure":
        if not success1 and success2:
            return 0, 0
        if success1 and success2 and difference < 0:
            return 1, abs(difference)
        return 2, abs(difference)

    return _contest_score(pool1, nh1, pool2, nh2, "win")


def select_quick_contest_dice(
    nh1: int, nh2: int, outcome: str
) -> tuple[list[int], list[int]]:
    """Return two 3d6 sets that best satisfy a requested quick contest."""
    best: tuple[int, int, int, int] | None = None
    best_key: tuple[int, int, int] | None = None

    for pool1 in range(3, 19):
        for pool2 in range(3, 19):
            score, tie = _contest_score(pool1, int(nh1), pool2, int(nh2), outcome)
            key = (score, tie, abs(pool1 - 10) + abs(pool2 - 10))
            if best_key is None or key < best_key:
                best_key = key
                best = (pool1, nh1, pool2, nh2)

    if best is None:
        return list(DICE_TABLE[10]), list(DICE_TABLE[10])
    pool1, _, pool2, _ = best
    return list(DICE_TABLE[pool1]), list(DICE_TABLE[pool2])
