"""Automatic HT checks triggered by injury."""

from __future__ import annotations

from random import randint

from utils.combat import (
    compute_basic_move,
    compute_dodge,
    halve_for_wounds,
    is_wounded,
)


def _max_pv(profile: dict) -> int:
    """Return the effective maximum PV used by injury thresholds."""
    return max(1, int(profile["st"]) + int(profile["additional_max_pv"] or 0))


def _death_multiplier(pv: int, max_pv: int) -> int:
    """Return how many negative PV multiples the value has reached."""
    if int(pv) >= 0:
        return 0
    return abs(int(pv)) // max(1, int(max_pv))


def _roll_ht_check(label: str, ht: int) -> dict:
    """Roll 3d6 against HT and report the raw check."""
    dices = [randint(1, 6) for _ in range(3)]
    total = sum(dices)
    margin = int(ht) - total
    return {
        "label": label,
        "target": int(ht),
        "dices": dices,
        "total": total,
        "success": total <= int(ht),
        "margin": margin,
    }


def resolve_damage_health(
    profile: dict,
    old_pv: int,
    new_pv: int,
    encumbrance_penalty: int = 0,
) -> dict:
    """Resolve consciousness and death checks for one injury event."""
    old_pv = int(old_pv)
    new_pv = int(new_pv)
    max_pv = _max_pv(profile)
    ht = int(profile["ht"])
    wounded = is_wounded(new_pv, max_pv)
    move = compute_basic_move(
        int(profile["dx"]),
        ht,
        int(profile["additional_basic_speed"] or 0),
        int(profile["additional_basic_move"] or 0),
        wounded,
    )
    dodge = compute_dodge(
        int(profile["dx"]),
        ht,
        int(profile["additional_basic_speed"] or 0),
        int(encumbrance_penalty),
    )
    dodge = halve_for_wounds(dodge, wounded)

    checks: list[dict] = []
    conscious = True
    life_state = "alive"

    if old_pv > 0 >= new_pv:
        check = _roll_ht_check("0 PV", ht)
        check["effect"] = "consciente" if check["success"] else "inconsciente"
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
            check = _roll_ht_check(f"Morte -{multiplier}xPV", ht)
            checks.append(check)
            if check["success"]:
                check["effect"] = "sobrevive"
                conscious = True
                continue
            failure_margin = -check["margin"]
            if failure_margin <= 2:
                check["effect"] = "morrendo"
                life_state = "dying"
            else:
                check["effect"] = "morto"
                life_state = "dead"
            conscious = False
            break

    if life_state == "obliterated":
        status = "obliterado"
    elif life_state == "dead":
        status = "morto"
    elif life_state == "dying":
        status = "morrendo"
    elif checks and not conscious:
        status = "inconsciente"
    elif checks:
        status = "consciente"
    else:
        status = None

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
    }
