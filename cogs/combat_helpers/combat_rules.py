"""Combat effect selection and defence options."""

from __future__ import annotations

import sqlite3

from utils.combat import (
    active_effect_bonus,
    compute_dodge,
    compute_parry,
    defense_remaining_uses,
    effect_is_available,
    halve_for_wounds,
    is_wounded,
    parse_parry_modifier,
)
from utils.db_functions import record_participant_use


def _consume_effects(
    connection: sqlite3.Connection,
    participant: dict | None,
    effects: list[dict],
) -> list[dict]:
    """Consume per-turn uses for the effects actually applied."""
    if participant is None:
        return []

    applied: list[dict] = []
    for effect in effects:
        if not effect_is_available(effect, participant):
            continue

        record_participant_use(
            connection,
            session_id=int(participant["session_id"]),
            character_id=int(participant["character_id"]),
            field="effect_uses",
            key=str(effect["effect_id"]),
        )
        applied.append(effect)

    return applied


def _available_effects(
    effects: list[dict],
    participant: dict | None,
    applies_to: str,
    *,
    target: str | None = None,
) -> list[dict]:
    """Filter active effects by family and per-turn availability."""
    result = []
    for effect in effects:
        if effect.get("applies_to") != applies_to:
            continue
        if target is not None and effect.get("target") not in (None, target):
            continue
        if not effect_is_available(effect, participant):
            continue
        result.append(effect)
    return result


def _select_available_effects(
    effects: list[dict],
    participant: dict | None,
    applies_to: set[str],
) -> list[dict]:
    """Select available effects from several families."""
    return [
        effect
        for effect in effects
        if effect.get("applies_to") in applies_to
        and effect_is_available(effect, participant)
    ]


def _defense_options(
    target_data: dict,
    effects: list[dict] | None = None,
    participant: dict | None = None,
    *,
    allow_parry: bool = True,
) -> list[dict]:
    """Build available Dodge and Parry options with per-turn use limits."""
    effects = effects or []
    conditions = target_data["conditions"]
    if int(conditions["no_defense"]):
        return []

    stance_parry_bonus = int(conditions["defense_bonus"] or 0)
    profile = target_data["profile"]
    generic_defense_effects = [
        effect
        for effect in effects
        if effect.get("applies_to") == "defense"
        and effect.get("target") is None
        and effect_is_available(effect, participant)
    ]
    generic_defense_bonus = sum(
        int(effect["value"]) for effect in generic_defense_effects
    )
    defense_effect_ids = [
        int(effect["effect_id"]) for effect in generic_defense_effects
    ]

    dodge_effects = [
        effect
        for effect in effects
        if effect.get("applies_to") == "dodge"
        and effect.get("target") in (None, "dodge")
        and effect_is_available(effect, participant)
    ]
    max_pv = int(profile.get("st") or 0) + int(
        profile.get("additional_max_pv") or 0
    )
    wounded = is_wounded(int(profile.get("current_pv") or 0), max_pv)
    dodge = max(
        0,
        compute_dodge(
            int(profile["dx"]),
            int(profile["ht"]),
            int(profile["additional_basic_speed"] or 0),
            int(target_data["encumbrance_penalty"]),
        )
        + generic_defense_bonus
        + active_effect_bonus(dodge_effects, "dodge", participant),
    )
    dodge = halve_for_wounds(dodge, wounded)

    options: list[dict] = []
    dodge_uses = defense_remaining_uses(effects, participant, "dodge", "dodge")
    if dodge_uses > 0:
        options.append(
            {
                "kind": "dodge",
                "key": "dodge",
                "label": f"Esquivar {dodge}"
                + (f" ({dodge_uses} usos)" if dodge_uses > 1 else ""),
                "value": dodge,
                "uses_remaining": dodge_uses,
                "effect_ids": defense_effect_ids
                + [int(effect["effect_id"]) for effect in dodge_effects],
            }
        )

    seen: set[tuple[str, int]] = {("dodge", dodge)}
    if not allow_parry:
        return options[:4]

    for mode in target_data["melee_modes"]:
        skill_id = mode.get("skill_id")
        if skill_id is None:
            continue
        skill = target_data["skill_by_id"].get(int(skill_id))
        if skill is None:
            continue

        parry_modifier = parse_parry_modifier(mode["parry"])
        if parry_modifier is None:
            continue

        parry_effects = [
            effect
            for effect in effects
            if effect.get("applies_to") == "parry"
            and effect.get("target") in (None, "parry")
            and effect_is_available(effect, participant)
        ]
        value = max(
            0,
            compute_parry(int(skill["nh"]), parry_modifier)
            + stance_parry_bonus
            + generic_defense_bonus
            + active_effect_bonus(parry_effects, "parry", participant),
        )
        key = f"parry:{mode.get('mode_id') or mode.get('weapon_name')}"
        uses = defense_remaining_uses(effects, participant, key, "parry")
        if uses <= 0:
            continue

        label = f"Aparar {mode['weapon_name']} {value}"
        if uses > 1:
            label += f" ({uses} usos)"
        dedupe_key = (label.casefold(), value)
        if dedupe_key in seen:
            continue

        seen.add(dedupe_key)
        options.append(
            {
                "kind": "parry",
                "key": key,
                "label": label,
                "value": value,
                "uses_remaining": uses,
                "effect_ids": defense_effect_ids
                + [int(effect["effect_id"]) for effect in parry_effects],
            }
        )

    return options[:4]


def best_melee_skill(data: dict) -> dict | None:
    """Return the highest-NH skill used by an equipped melee mode."""
    best = None
    for mode in data.get("melee_modes", []):
        skill_id = mode.get("skill_id")
        if skill_id is None:
            continue
        skill = data.get("skill_by_id", {}).get(int(skill_id))
        if skill is None:
            continue
        if best is None or int(skill["nh"]) > int(best["nh"]):
            best = skill
    return best
