"""Pure GURPS 4e combat calculations shared by command and persistence layers."""

from __future__ import annotations

import re
from typing import Any, Iterable


HIT_LOCATIONS: dict[int, dict[str, Any]] = {
    0: {"name": "Tronco", "key": "torso", "penalty": 0, "armor_body_part": "Tronco"},
    1: {"name": "Órgãos Vitais", "key": "vitals", "penalty": -3, "armor_body_part": "Tórax"},
    2: {"name": "Crânio", "key": "skull", "penalty": -7, "armor_body_part": "Crânio"},
    3: {"name": "Olho", "key": "eye", "penalty": -9, "armor_body_part": "Crânio"},
    4: {"name": "Rosto", "key": "face", "penalty": -5, "armor_body_part": "Rosto"},
    5: {"name": "Pescoço", "key": "neck", "penalty": -5, "armor_body_part": "Pescoço"},
    6: {"name": "Virilha", "key": "groin", "penalty": -3, "armor_body_part": "Virilha"},
    7: {"name": "Braço", "key": "arm", "penalty": -2, "armor_body_part": "Braços"},
    8: {"name": "Perna", "key": "leg", "penalty": -2, "armor_body_part": "Pernas"},
    9: {"name": "Mão", "key": "hand", "penalty": -4, "armor_body_part": "Mãos"},
    10: {"name": "Pé", "key": "foot", "penalty": -4, "armor_body_part": "Pés"},
}

MANEUVERS: dict[str, dict[str, Any]] = {
    "normal": {
        "label": "Ataque Normal",
        "attack_modifier": 0,
        "defense_modifier": 0,
        "allows_defense": True,
        "strong": False,
    },
    "all_out_determined": {
        "label": "Ataque Total (Determinado)",
        "attack_modifier": 4,
        "defense_modifier": 0,
        "allows_defense": False,
        "strong": False,
    },
    "all_out_strong": {
        "label": "Ataque Total (Forte)",
        "attack_modifier": 0,
        "defense_modifier": 0,
        "allows_defense": False,
        "strong": True,
    },
    "defensive": {
        "label": "Ataque Defensivo",
        "attack_modifier": -2,
        "defense_modifier": 1,
        "allows_defense": True,
        "strong": False,
    },
}

DAMAGE_TYPE_CODES: dict[str, int] = {
    "atribulação": 1,
    "atribulacao": 1,
    "queimadura": 2,
    "corrosão": 3,
    "corrosao": 3,
    "contusão": 4,
    "contusao": 4,
    "corte": 5,
    "cut": 5,
    "fadiga": 6,
    "fat": 6,
    "burn": 2,
    "corr": 3,
    "perfuração": 7,
    "perfuracao": 7,
    "imp": 7,
    "pi-": 8,
    "pi": 9,
    "pi+": 10,
    "pi++": 11,
    "especial": 12,
    "spec": 12,
    "toxina": 13,
    "tox": 13,
}

_DAMAGE_EXPRESSION = re.compile(
    r"^\s*(?P<dice>\d+)d(?:(?P<sign>[+-])(?P<modifier>\d+))?\s*(?P<damage_type>.*)$",
    re.IGNORECASE,
)

DAMAGE_TYPE_KEYS: dict[int, str] = {
    1: "affliction",
    2: "burning",
    3: "corrosion",
    4: "crushing",
    5: "cutting",
    6: "fatigue",
    7: "impaling",
    8: "piercing_small",
    9: "piercing",
    10: "piercing_large",
    11: "piercing_huge",
    12: "special",
    13: "toxic",
}

DAMAGE_TYPE_LABELS: dict[int, str] = {
    1: "Atribulação",
    2: "Queimadura",
    3: "Corrosão",
    4: "Contusão",
    5: "Corte",
    6: "Fadiga",
    7: "Perfuração",
    8: "Perfurante (Pi-)",
    9: "Perfurante (Pi)",
    10: "Muito Perfurante (Pi+)",
    11: "Extremamente Perfurante (Pi++)",
    12: "Especial",
    13: "Toxina",
}

BODY_PART_PARENTS: dict[str, tuple[str, ...]] = {
    "Crânio": ("Cabeça",),
    "Rosto": ("Cabeça",),
    "Tórax": ("Tronco",),
    "Abdômen": ("Tronco",),
    "Virilha": ("Abdômen",),
    "Ombros": ("Braços",),
    "Parte superior dos braços": ("Braços",),
    "Cotovelos": ("Braços",),
    "Antebraços": ("Braços",),
    "Coxas": ("Pernas",),
    "Joelhos": ("Pernas",),
    "Canelas": ("Pernas",),
}

ARMOR_SUBLOCATIONS: dict[int, tuple[dict[str, Any], ...]] = {
    0: (
        {
            "key": "vitals",
            "body_part": "Tórax",
            "label_kind": "hit_locations",
            "min": 1,
            "max": 1,
            "hit_location_id": 1,
        },
        {"key": "thorax", "body_part": "Tórax", "min": 2, "max": 4},
        {"key": "abdomen", "body_part": "Abdômen", "min": 5, "max": 6},
    ),
    7: (
        {"key": "forearms", "body_part": "Antebraços", "min": 1, "max": 3},
        {"key": "elbows", "body_part": "Cotovelos", "min": 4, "max": 4},
        {
            "key": "upper_arms",
            "body_part": "Parte superior dos braços",
            "min": 5,
            "max": 5,
        },
        {"key": "shoulders", "body_part": "Ombros", "min": 6, "max": 6},
    ),
    8: (
        {"key": "shins", "body_part": "Canelas", "min": 1, "max": 3},
        {"key": "knees", "body_part": "Joelhos", "min": 4, "max": 4},
        {"key": "thighs", "body_part": "Coxas", "min": 5, "max": 6},
    ),
}

ARMOR_SUBLOCATION_BY_KEY: dict[str, dict[str, Any]] = {
    entry["key"]: entry
    for entries in ARMOR_SUBLOCATIONS.values()
    for entry in entries
}

FLEXIBLE_UNDER_RIGID_PENALTY = 1

_BASE_DAMAGE_MULTIPLIERS: dict[int, float] = {
    1: 1.0,
    2: 1.0,
    3: 1.0,
    4: 1.0,
    5: 1.5,
    6: 1.0,
    7: 2.0,
    8: 0.5,
    9: 1.0,
    10: 1.5,
    11: 2.0,
    12: 1.0,
    13: 1.0,
}


def hit_location(hit_location_id: int) -> dict[str, Any]:
    """Return the canonical hit location definition for one numeric id."""
    return HIT_LOCATIONS.get(hit_location_id, HIT_LOCATIONS[0])


def resolve_armor_sublocation(
    hit_location_id: int, roll: int
) -> dict[str, Any] | None:
    """Resolve one d6 roll into the armor sublocation that was hit."""
    entries = ARMOR_SUBLOCATIONS.get(int(hit_location_id))
    if entries is None:
        return None

    rolled = int(roll)
    for entry in entries:
        if entry["min"] <= rolled <= entry["max"]:
            resolved = dict(entry)
            resolved["roll"] = rolled
            resolved["hit_location_id"] = int(
                entry.get("hit_location_id", hit_location_id)
            )
            return resolved
    return None


def armor_sublocation_by_key(key: str | None) -> dict[str, Any] | None:
    """Return the canonical sublocation definition for one persisted key."""
    if key is None:
        return None
    entry = ARMOR_SUBLOCATION_BY_KEY.get(str(key))
    return dict(entry) if entry is not None else None


def resolved_hit_location_id(
    hit_location_id: int, sublocation: dict[str, Any] | None
) -> int:
    """Return the hit location used by injury calculations after resolution."""
    if sublocation is None:
        return int(hit_location_id)
    return int(sublocation.get("hit_location_id", hit_location_id))


def normalize_damage_type(raw_value: Any) -> int:
    """Map a textual or numeric damage type to the internal numeric code."""
    if isinstance(raw_value, int) and raw_value in DAMAGE_TYPE_LABELS:
        return raw_value

    normalized = str(raw_value or "").strip().lower()
    if normalized in DAMAGE_TYPE_CODES:
        return DAMAGE_TYPE_CODES[normalized]

    return 4


def parse_parry_modifier(raw_value: Any) -> int | None:
    """Extract the numeric parry modifier from strings such as '0', '0U' or 'Não'."""
    if raw_value is None:
        return None

    text = str(raw_value).strip()
    if not text or text.lower().startswith("não") or text.lower().startswith("nao"):
        return None

    sign = -1 if text.startswith("-") else 1
    digits = "".join(character for character in text if character.isdigit())
    if not digits:
        return None

    return sign * int(digits)


def build_modifier_breakdown(
    base_value: int, modifiers: Iterable[tuple[str, int]]
) -> dict[str, Any]:
    """Build an auditable modifier stack and its clamped effective value."""
    entries = [
        {"label": label, "value": int(value)}
        for label, value in modifiers
        if int(value) != 0
    ]
    total = sum(entry["value"] for entry in entries)
    effective = max(0, int(base_value) + total)

    return {
        "base": int(base_value),
        "modifiers": entries,
        "total": total,
        "effective": effective,
    }


def compute_encumbrance_penalty(total_weight: float, strength: int) -> int:
    """Return the GURPS encumbrance penalty for the carried weight."""
    if int(strength) <= 0:
        return 0

    basic_lift = (int(strength) * int(strength)) / 10.0
    thresholds = (
        (basic_lift, 0),
        (basic_lift * 2, -1),
        (basic_lift * 3, -2),
        (basic_lift * 6, -3),
        (basic_lift * 10, -4),
    )

    for limit, penalty in thresholds:
        if float(total_weight) <= limit:
            return penalty

    return -4


def compute_dodge(
    dexterity: int,
    health: int,
    additional_basic_speed: int = 0,
    encumbrance_penalty: int = 0,
) -> int:
    """Compute the GURPS Dodge defense from attributes and encumbrance."""
    basic_speed = (int(dexterity) + int(health)) // 4
    return max(
        0,
        basic_speed + int(additional_basic_speed) + 3 - int(encumbrance_penalty),
    )


def compute_parry(skill_level: int, parry_modifier: int = 0) -> int:
    """Compute the GURPS Parry defense for one weapon mode."""
    return max(0, 3 + int(skill_level) // 2 + int(parry_modifier))


def compute_shock_penalty(injury: int, max_pv: int) -> int:
    """Return the GURPS shock penalty from one injury event."""
    injury = max(0, int(injury))
    maximum = max(1, int(max_pv))
    divisor = max(1, maximum // 10)
    return min(4, injury // divisor)


def is_wounded(current_pv: int, max_pv: int) -> bool:
    """Return True when injury halves Basic Move and Dodge."""
    maximum = max(0, int(max_pv))
    if maximum <= 0:
        return False
    return int(current_pv) <= maximum // 3


def halve_for_wounds(value: int, wounded: bool) -> int:
    """Halve a movement or defence value when the character is wounded."""
    value = max(0, int(value))
    return value // 2 if wounded else value


def compute_basic_move(
    dexterity: int,
    health: int,
    additional_basic_speed: int = 0,
    additional_basic_move: int = 0,
    wounded: bool = False,
) -> int:
    """Compute Basic Move from attributes and injury state."""
    basic_speed = (int(dexterity) + int(health)) // 4
    move = max(
        0,
        basic_speed + int(additional_basic_speed) + int(additional_basic_move),
    )
    return halve_for_wounds(move, wounded)


def _body_part_coverage(
    body_part: str, *, include_descendants: bool = True
) -> set[str]:
    """Return a body part, its ancestors and optionally its own descendants."""
    coverage = {body_part}
    current = body_part

    while current in BODY_PART_PARENTS:
        parents = BODY_PART_PARENTS[current]
        coverage.update(parents)
        current = parents[0]

    if not include_descendants:
        return coverage

    descendants = {body_part}
    changed = True
    while changed:
        changed = False
        for child, parents in BODY_PART_PARENTS.items():
            if any(parent in descendants for parent in parents) and child not in coverage:
                coverage.add(child)
                descendants.add(child)
                changed = True

    return coverage


def compute_armor_dr(
    layers: Iterable[dict[str, Any]],
    hit_location_id: int,
    *,
    sublocation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute layered DR; each flexible layer under any rigid layer loses one DR.

    When a sublocation is supplied, only that segment and its full-location
    ancestors protect the hit. The caller decides whether to accept multiple
    rigid layers; this function reports that condition as a warning instead of
    silently dropping a layer.
    """
    location = hit_location(hit_location_id)
    target_body_part = (
        str(sublocation["body_part"])
        if sublocation is not None
        else location["armor_body_part"]
    )
    applicable_parts = _body_part_coverage(
        target_body_part, include_descendants=sublocation is None
    )

    selected = [
        dict(layer)
        for layer in layers
        if str(layer.get("body_part") or "") in applicable_parts
    ]
    selected.sort(
        key=lambda layer: (
            int(layer.get("layer_order") or 0),
            0 if bool(layer.get("is_flexible")) else 1,
            int(layer.get("character_armor_id") or 0),
        )
    )

    warnings: list[str] = []
    warning_keys: list[str] = []
    rigid_positions = [
        index
        for index, layer in enumerate(selected)
        if not bool(layer.get("is_flexible"))
    ]
    if len(rigid_positions) > 1:
        warnings.append(
            "Mais de uma camada rígida equipada no mesmo local; "
            "o mestre deve confirmar a composição."
        )
        warning_keys.append("multiple_rigid_layers")

    total = 0
    breakdown: list[dict[str, Any]] = []

    for index, layer in enumerate(selected):
        base_dr = max(0, int(layer.get("dr") or 0))
        penalty = 0

        if bool(layer.get("is_flexible")):
            has_outer_rigid = any(position > index for position in rigid_positions)
            if has_outer_rigid:
                penalty = FLEXIBLE_UNDER_RIGID_PENALTY

        effective_dr = max(0, base_dr - penalty)
        total += effective_dr
        breakdown.append(
            {
                "name": layer.get("name") or layer.get("body_part") or "Armadura",
                "body_part": layer.get("body_part"),
                "base_dr": base_dr,
                "penalty": penalty,
                "effective_dr": effective_dr,
                "is_flexible": bool(layer.get("is_flexible")),
                "layer_order": int(layer.get("layer_order") or 0),
            }
        )

    return {
        "total": total,
        "layers": breakdown,
        "warnings": warnings,
        "warning_keys": warning_keys,
        "target_body_part": target_body_part,
    }


def classify_roll(dice_pool: int, effective_skill: int) -> dict[str, Any]:
    """Classify a 3d6 roll against an effective skill level."""
    dice_pool = int(dice_pool)
    effective_skill = int(effective_skill)

    critical_success = False
    success = False
    critical_failure = False

    if dice_pool == 18:
        critical_failure = True
    elif dice_pool == 17 and effective_skill <= 15:
        critical_failure = True
    elif dice_pool <= 4:
        success = True
        critical_success = True
    elif dice_pool <= effective_skill:
        success = True
        critical_success = (effective_skill - dice_pool) >= 10
    elif (dice_pool - effective_skill) >= 10:
        critical_failure = True

    return {
        "critical_success": critical_success,
        "success": success,
        "critical_failure": critical_failure,
        "margin": effective_skill - dice_pool,
    }


def compute_injury(
    penetrating_damage: int,
    damage_type: int,
    hit_location_id: int,
    body_type: int,
    strength: int,
    additional_max_pv: int,
    current_pv: int,
) -> dict[str, Any]:
    """Apply GURPS wound multipliers, caps, crippling and amputation rules."""
    penetrating_damage = max(0, int(penetrating_damage))
    damage_type = int(damage_type)
    hit_location_id = int(hit_location_id)
    body_type = int(body_type)

    multiplier = _BASE_DAMAGE_MULTIPLIERS.get(damage_type, 1.0)

    if body_type in (0, 3):
        if hit_location_id == 1 and damage_type in (7, 8, 9, 10, 11):
            multiplier = 3.0
        elif hit_location_id in (2, 3):
            multiplier = 4.0

    if hit_location_id == 4 and damage_type == 3:
        multiplier = 1.5
    elif hit_location_id == 5:
        if damage_type in (3, 4):
            multiplier = 1.5
        elif damage_type == 5:
            multiplier = 2.0

    if hit_location_id not in (2, 3):
        if body_type == 3:
            if damage_type in (7, 11):
                multiplier = 1.0
            elif damage_type == 10:
                multiplier = 0.5
            elif damage_type == 9:
                multiplier = 1.0 / 3.0
            elif damage_type == 8:
                multiplier = 0.2
        elif body_type == 2:
            if damage_type in (7, 11):
                multiplier = 0.5
            elif damage_type == 10:
                multiplier = 1.0 / 3.0
            elif damage_type == 9:
                multiplier = 0.2
            elif damage_type == 8:
                multiplier = 0.1
    elif body_type == 2:
        if damage_type in (7, 11):
            multiplier = 0.5
        elif damage_type == 10:
            multiplier = 1.0 / 3.0
        elif damage_type == 9:
            multiplier = 0.2
        elif damage_type == 8:
            multiplier = 0.1
        else:
            multiplier = _BASE_DAMAGE_MULTIPLIERS.get(damage_type, 1.0)

    raw_injury = penetrating_damage * multiplier

    if body_type == 1 and penetrating_damage > 0:
        if damage_type in (7, 8, 9, 10, 11):
            raw_injury = min(raw_injury, 1.0)
        else:
            raw_injury = min(raw_injury, 2.0)

    if penetrating_damage > 0 and 0 < raw_injury < 1.0:
        raw_injury = 1.0

    raw_injury = int(raw_injury)
    final_injury = raw_injury

    appendage_hp: float | None = None
    amputation = False
    incapacitation = False

    if hit_location_id in (7, 8):
        appendage_hp = (int(strength) + int(additional_max_pv)) / 2
    elif hit_location_id in (9, 10):
        appendage_hp = (int(strength) + int(additional_max_pv)) / 3

    if appendage_hp is not None and body_type in (0, 3):
        if raw_injury >= appendage_hp * 2:
            amputation = True
            final_injury = int(appendage_hp)
        elif raw_injury >= appendage_hp:
            incapacitation = True
            final_injury = int(appendage_hp)

    return {
        "penetrating_damage": penetrating_damage,
        "multiplier": multiplier,
        "raw_injury": raw_injury,
        "final_injury": final_injury,
        "new_pv": int(current_pv) - final_injury,
        "amputation": amputation,
        "incapacitation": incapacitation,
        "appendage_hp": appendage_hp,
        "location_name": hit_location(hit_location_id)["name"],
        "location_key": hit_location(hit_location_id)["key"],
    }


DEFENSE_EFFECT_TARGETS = ("dodge", "parry", "block")

CONTINUOUS_EFFECT_TYPES = frozenset(
    {
        "st",
        "dx",
        "iq",
        "ht",
        "max_pv",
        "max_pf",
        "will",
        "per",
        "basic_speed",
        "basic_move",
        "ht_check",
        "rd",
    }
)


def continuous_effect_total(
    effects: Iterable[dict], applies_to: str
) -> int:
    """Sum passive effects of one family that have no target filter."""
    if applies_to not in CONTINUOUS_EFFECT_TYPES:
        return 0
    return sum(
        int(effect.get("value") or 0)
        for effect in effects
        if effect.get("applies_to") == applies_to
        and effect.get("target") is None
    )


def apply_continuous_effects(
    profile: dict, effects: Iterable[dict]
) -> dict:
    """Return a combat profile adjusted by linked passive effects."""
    effect_list = list(effects)
    st = int(profile["st"]) + continuous_effect_total(effect_list, "st")
    dx = int(profile["dx"]) + continuous_effect_total(effect_list, "dx")
    iq = int(profile["iq"]) + continuous_effect_total(effect_list, "iq")
    ht = int(profile["ht"]) + continuous_effect_total(effect_list, "ht")

    additional_max_pv = int(
        profile.get("additional_max_pv") or 0
    ) + continuous_effect_total(effect_list, "max_pv")
    additional_max_pf = int(
        profile.get("additional_max_pf") or 0
    ) + continuous_effect_total(effect_list, "max_pf")
    additional_basic_speed = int(
        profile.get("additional_basic_speed") or 0
    ) + continuous_effect_total(effect_list, "basic_speed")
    additional_basic_move = int(
        profile.get("additional_basic_move") or 0
    ) + continuous_effect_total(effect_list, "basic_move")

    effective = dict(profile)
    effective.update(
        {
            "st": st,
            "dx": dx,
            "iq": iq,
            "ht": ht,
            "additional_max_pv_effective": additional_max_pv,
            "additional_max_pf_effective": additional_max_pf,
            "max_pv": max(1, st + additional_max_pv),
            "max_pf": max(1, ht + additional_max_pf),
            "will": (
                iq
                + int(profile.get("additional_vont") or 0)
                + continuous_effect_total(effect_list, "will")
            ),
            "per": (
                iq
                + int(profile.get("additional_per") or 0)
                + continuous_effect_total(effect_list, "per")
            ),
            "additional_basic_speed_effective": additional_basic_speed,
            "additional_basic_move_effective": additional_basic_move,
            "basic_speed": (
                (dx + ht) / 4.0 + additional_basic_speed
            ),
            "basic_move": max(
                0,
                (dx + ht) // 4
                + additional_basic_speed
                + additional_basic_move,
            ),
            "ht_check_bonus": continuous_effect_total(
                effect_list, "ht_check"
            ),
            "rd_bonus": continuous_effect_total(effect_list, "rd"),
        }
    )
    return effective


def effect_is_available(effect: dict, participant: dict | None) -> bool:
    """Return True when a per-turn effect still has an available use."""
    uses_per_turn = int(effect.get("uses_per_turn") or 0)
    if uses_per_turn <= 0:
        return True
    if participant is None:
        return True

    used = int(
        participant.get("effect_uses", {}).get(
            str(effect.get("effect_id")), 0
        )
    )
    return used < uses_per_turn


def active_effect_bonus(
    effects: Iterable[dict],
    applies_to: str,
    participant: dict | None = None,
    *,
    target: str | None = None,
) -> int:
    """Sum available effects of one family, optionally filtered by target."""
    total = 0
    for effect in effects:
        if effect.get("applies_to") != applies_to:
            continue
        if target is not None and effect.get("target") not in (None, target):
            continue
        if not effect_is_available(effect, participant):
            continue
        total += int(effect.get("value") or 0)
    return total


def max_defense_attempts(effects: Iterable[dict]) -> int:
    """Return the number of defence attempts allowed against one attack."""
    extra = sum(
        int(effect.get("value") or 0)
        for effect in effects
        if effect.get("applies_to") == "extra_defense_attempts"
    )
    return max(1, 1 + extra)


def defense_remaining_uses(
    effects: Iterable[dict],
    participant: dict | None,
    defense_key: str,
    defense_kind: str,
) -> int:
    """Return remaining uses for one defence option in the current turn."""
    extra_uses = sum(
        int(effect.get("value") or 0)
        for effect in effects
        if effect.get("applies_to") == "extra_defense_uses"
        and effect.get("target") in (None, defense_kind)
    )
    max_uses = max(0, 1 + extra_uses)
    used = 0
    if participant is not None:
        used = int(participant.get("defense_uses", {}).get(defense_key, 0))
    return max(0, max_uses - used)


def parse_damage_expression(expression: str | None) -> dict[str, Any] | None:
    """Parse a GURPS damage expression such as '2d+1 pi+'."""
    if expression is None:
        return None

    match = _DAMAGE_EXPRESSION.match(str(expression).strip())
    if match is None:
        return None

    dice_count = int(match.group("dice"))
    if dice_count <= 0:
        return None

    modifier = 0
    if match.group("modifier") is not None:
        modifier = int(match.group("modifier"))
        if match.group("sign") == "-":
            modifier = -modifier

    raw_type = match.group("damage_type").strip()
    return {
        "dice_count": dice_count,
        "modifier": modifier,
        "damage_type": normalize_damage_type(raw_type or "cr"),
        "damage_type_raw": raw_type,
        "expression": str(expression).strip(),
    }
