"""Automatic HT checks triggered by injury."""

from __future__ import annotations

from collections.abc import Callable
from random import randint

from utils.combat import (
    compute_basic_move,
    compute_dodge,
    halve_for_wounds,
    is_wounded,
)
from utils.gm_dice import select_health_dice


def _max_pv(profile: dict) -> int:
    """Return the effective maximum PV used by injury thresholds."""
    if "max_pv" in profile:
        return max(1, int(profile["max_pv"]))
    return max(1, int(profile["st"]) + int(profile["additional_max_pv"] or 0))


def _additional_basic_speed(profile: dict) -> int:
    """Return the Basic Speed bonus applied to Dodge and Move."""
    if "additional_basic_speed_effective" in profile:
        return int(profile["additional_basic_speed_effective"])
    return int(profile.get("additional_basic_speed") or 0)


def _additional_basic_move(profile: dict) -> int:
    """Return the Basic Move bonus applied to Move."""
    if "additional_basic_move_effective" in profile:
        return int(profile["additional_basic_move_effective"])
    return int(profile.get("additional_basic_move") or 0)


def _death_multiplier(pv: int, max_pv: int) -> int:
    """Return how many negative PV multiples the value has reached."""
    if int(pv) >= 0:
        return 0
    return abs(int(pv)) // max(1, int(max_pv))


def _roll_ht_check(
    label: str,
    ht: int,
    forced_outcome: str | None = None,
) -> dict:
    """Roll 3d6 against HT and report the check, optionally forced."""
    if forced_outcome is not None:
        dices, total, success, margin = select_health_dice(
            int(ht), forced_outcome
        )
    else:
        dices = [randint(1, 6) for _ in range(3)]
        total = sum(dices)
        margin = int(ht) - total
        success = total <= int(ht)

    return {
        "label": label,
        "target": int(ht),
        "dices": dices,
        "total": total,
        "success": success,
        "margin": margin,
    }


def resolve_damage_health(
    profile: dict,
    old_pv: int,
    new_pv: int,
    encumbrance_penalty: int = 0,
    directive_resolver: Callable[[str], str | None] | None = None,
    flags: dict[str, bool] | None = None,
) -> dict:
    """Resolve consciousness and death checks for one injury event."""
    old_pv = int(old_pv)
    new_pv = int(new_pv)
    max_pv = _max_pv(profile)
    ht = int(profile["ht"])
    check_ht = ht + int(profile.get("ht_check_bonus") or 0)
    wounded = is_wounded(new_pv, max_pv)
    move = compute_basic_move(
        int(profile["dx"]),
        ht,
        _additional_basic_speed(profile),
        _additional_basic_move(profile),
        wounded,
    )
    dodge = compute_dodge(
        int(profile["dx"]),
        ht,
        _additional_basic_speed(profile),
        int(encumbrance_penalty),
    )
    dodge = halve_for_wounds(dodge, wounded)

    checks: list[dict] = []
    conscious = True
    life_state = "alive"

    active_flags = flags or {}
    if old_pv > 0 >= new_pv:
        forced = "success" if active_flags.get("no_faint") else None
        if forced is None and directive_resolver is not None:
            forced = directive_resolver("consciousness")
        check = _roll_ht_check("0 PV", check_ht, forced_outcome=forced)
        check["label_key"] = "zero_hp"
        check["effect"] = "consciente" if check["success"] else "inconsciente"
        check["effect_key"] = "conscious" if check["success"] else "unconscious"
        conscious = check["success"]
        checks.append(check)

    if new_pv <= -10 * max_pv:
        life_state = "obliterated"
        conscious = False
    elif new_pv <= -5 * max_pv:
        life_state = "dead"
        conscious = False
    else:
        old_multiplier = _death_multiplier(old_pv, max_pv)
        new_multiplier = _death_multiplier(new_pv, max_pv)
        for multiplier in range(old_multiplier + 1, new_multiplier + 1):
            forced = (
                directive_resolver("death")
                if directive_resolver is not None
                else None
            )
            if active_flags.get("no_death") and forced == "dead":
                forced = "dying"
            check = _roll_ht_check(
                f"Morte -{multiplier}xPV", check_ht, forced_outcome=forced
            )
            if (
                active_flags.get("no_death")
                and not check["success"]
                and -check["margin"] >= 3
            ):
                check = _roll_ht_check(
                    f"Morte -{multiplier}xPV", check_ht, forced_outcome="dying"
                )
            check["label_key"] = "death_check"
            check["label_params"] = {"multiplier": multiplier}
            checks.append(check)
            if check["success"]:
                check["effect"] = "sobrevive"
                check["effect_key"] = "survives"
                conscious = True
                continue
            failure_margin = -check["margin"]
            if failure_margin <= 2:
                check["effect"] = "morrendo"
                check["effect_key"] = "dying"
                life_state = "dying"
            else:
                check["effect"] = "morto"
                check["effect_key"] = "dead"
                life_state = "dead"
            conscious = False
            break

    if life_state == "obliterated":
        status = "obliterado"
        status_key = "obliterated"
    elif life_state == "dead":
        status = "morto"
        status_key = "dead"
    elif life_state == "dying":
        status = "morrendo"
        status_key = "dying"
    elif checks and not conscious:
        status = "inconsciente"
        status_key = "unconscious"
    elif checks:
        status = "consciente"
        status_key = "conscious"
    else:
        status = None
        status_key = None

    return {
        "current_pv": new_pv,
        "max_pv": max_pv,
        "wounded": wounded,
        "move": move,
        "dodge": dodge,
        "checks": checks,
        "conscious": conscious,
        "life_state": life_state,
        "status": status,
        "status_key": status_key,
    }
