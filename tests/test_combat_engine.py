"""Tests for the pure combat engine in utils/combat.py."""

from __future__ import annotations

import pytest

from utils.combat import (
    active_effect_bonus,
    build_modifier_breakdown,
    classify_roll,
    compute_armor_dr,
    compute_dodge,
    compute_encumbrance_penalty,
    compute_injury,
    compute_parry,
    compute_shock_penalty,
    defense_remaining_uses,
    effect_is_available,
    max_defense_attempts,
    normalize_damage_type,
    parse_damage_expression,
    parse_parry_modifier,
)


class TestModifierBreakdown:
    def test_filters_zeroes_and_clamps_effective_value(self):
        breakdown = build_modifier_breakdown(
            10, [("Mira", 2), ("Choque", 0), ("Situacional", -15)]
        )

        assert breakdown["base"] == 10
        assert breakdown["modifiers"] == [
            {"label": "Mira", "value": 2},
            {"label": "Situacional", "value": -15},
        ]
        assert breakdown["total"] == -13
        assert breakdown["effective"] == 0

    def test_positive_stack_is_summed(self):
        breakdown = build_modifier_breakdown(
            14, [("Mira", 3), ("Ataque Total", 4)]
        )

        assert breakdown["effective"] == 21


class TestDefenseValues:
    @pytest.mark.parametrize(
        "dx, ht, bonus, encumbrance, expected",
        [
            (10, 10, 0, 0, 8),
            (12, 10, 0, 0, 8),
            (10, 10, 1, 0, 9),
            (10, 10, 0, 2, 6),
            (0, 0, 0, 0, 3),
        ],
    )
    def test_dodge(self, dx, ht, bonus, encumbrance, expected):
        assert compute_dodge(dx, ht, bonus, encumbrance) == expected

    @pytest.mark.parametrize(
        "skill, modifier, expected",
        [(10, 0, 8), (11, 0, 8), (10, 2, 10), (10, -5, 3), (0, 0, 3)],
    )
    def test_parry(self, skill, modifier, expected):
        assert compute_parry(skill, modifier) == expected

    @pytest.mark.parametrize(
        "raw, expected",
        [("0", 0), ("0U", 0), ("0D", 0), ("-2", -2), ("2", 2), ("Não", None), ("", None)],
    )
    def test_parse_parry_modifier(self, raw, expected):
        assert parse_parry_modifier(raw) == expected

    @pytest.mark.parametrize(
        "weight, strength, expected",
        [
            (0, 10, 0),
            (10, 10, 0),
            (10.1, 10, -1),
            (20, 10, -1),
            (20.1, 10, -2),
            (30, 10, -2),
            (30.1, 10, -3),
            (60, 10, -3),
            (60.1, 10, -4),
        ],
    )
    def test_encumbrance(self, weight, strength, expected):
        assert compute_encumbrance_penalty(weight, strength) == expected


class TestShockPenalty:
    @pytest.mark.parametrize(
        "injury, max_pv, expected",
        [
            (0, 10, 0),
            (1, 10, 1),
            (3, 10, 3),
            (7, 10, 4),
            (3, 20, 1),
            (4, 20, 2),
            (8, 20, 4),
            (5, 30, 1),
            (9, 30, 3),
            (12, 30, 4),
            (15, 40, 3),
        ],
    )
    def test_shock_scales_with_hp_and_caps_at_four(
        self, injury, max_pv, expected
    ):
        assert compute_shock_penalty(injury, max_pv) == expected


class TestArmorLayering:
    def test_flexible_layer_under_rigid_loses_one_dr(self):
        layers = [
            {
                "character_armor_id": 1,
                "name": "Tecido",
                "body_part": "Tronco",
                "dr": 2,
                "is_flexible": True,
                "layer_order": 1,
            },
            {
                "character_armor_id": 2,
                "name": "Placas",
                "body_part": "Tronco",
                "dr": 5,
                "is_flexible": False,
                "layer_order": 2,
            },
        ]

        result = compute_armor_dr(layers, 0)

        assert result["total"] == 6
        assert result["layers"][0]["penalty"] == 1
        assert result["layers"][1]["penalty"] == 0

    def test_two_flexible_layers_add_normally(self):
        layers = [
            {
                "character_armor_id": 1,
                "name": "Tecido",
                "body_part": "Tronco",
                "dr": 2,
                "is_flexible": True,
                "layer_order": 1,
            },
            {
                "character_armor_id": 2,
                "name": "Malha",
                "body_part": "Tronco",
                "dr": 4,
                "is_flexible": True,
                "layer_order": 2,
            },
        ]

        result = compute_armor_dr(layers, 0)

        assert result["total"] == 6
        assert all(layer["penalty"] == 0 for layer in result["layers"])

    def test_rigid_over_flexible_does_not_penalise_outer_layer(self):
        layers = [
            {
                "character_armor_id": 1,
                "name": "Placas",
                "body_part": "Tronco",
                "dr": 5,
                "is_flexible": False,
                "layer_order": 1,
            },
            {
                "character_armor_id": 2,
                "name": "Tecido",
                "body_part": "Tronco",
                "dr": 2,
                "is_flexible": True,
                "layer_order": 2,
            },
        ]

        result = compute_armor_dr(layers, 0)

        assert result["total"] == 7
        assert result["layers"][1]["penalty"] == 0

    def test_parent_body_part_covers_child_location(self):
        layers = [
            {
                "character_armor_id": 1,
                "name": "Cota",
                "body_part": "Tronco",
                "dr": 4,
                "is_flexible": True,
                "layer_order": 1,
            }
        ]

        result = compute_armor_dr(layers, 1)

        assert result["total"] == 4

    def test_generic_torso_includes_specific_chest_armor(self):
        layers = [
            {
                "character_armor_id": 1,
                "name": "Peitoral",
                "body_part": "Tórax",
                "dr": 5,
                "is_flexible": False,
                "layer_order": 1,
            }
        ]

        result = compute_armor_dr(layers, 0)

        assert result["total"] == 5

    def test_skull_does_not_include_face_armor(self):
        layers = [
            {
                "character_armor_id": 1,
                "name": "Máscara",
                "body_part": "Rosto",
                "dr": 3,
                "is_flexible": False,
                "layer_order": 1,
            }
        ]

        result = compute_armor_dr(layers, 2)

        assert result["total"] == 0

    def test_two_rigid_layers_produce_a_warning(self):
        layers = [
            {
                "character_armor_id": 1,
                "name": "Placas A",
                "body_part": "Tronco",
                "dr": 5,
                "is_flexible": False,
                "layer_order": 1,
            },
            {
                "character_armor_id": 2,
                "name": "Placas B",
                "body_part": "Tronco",
                "dr": 5,
                "is_flexible": False,
                "layer_order": 2,
            },
        ]

        result = compute_armor_dr(layers, 0)

        assert result["total"] == 10
        assert result["warnings"]


class TestRollClassification:
    @pytest.mark.parametrize(
        "roll, nh, success, critical_success, critical_failure",
        [
            (3, 10, True, True, False),
            (4, 10, True, True, False),
            (10, 10, True, False, False),
            (11, 10, False, False, False),
            (17, 10, False, False, True),
            (17, 16, False, False, False),
            (18, 16, False, False, True),
            (16, 5, False, False, True),
            (5, 16, True, True, False),
            (4, 0, True, True, False),
            (5, 0, False, False, False),
        ],
    )
    def test_classification(
        self, roll, nh, success, critical_success, critical_failure
    ):
        result = classify_roll(roll, nh)

        assert result["success"] is success
        assert result["critical_success"] is critical_success
        assert result["critical_failure"] is critical_failure
        assert result["margin"] == nh - roll


class TestDamageTypes:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("corte", 5),
            ("Corte", 5),
            ("perfuração", 7),
            ("perfuracao", 7),
            ("contusão", 4),
            ("pi+", 10),
            ("pi++", 11),
            ("desconhecido", 4),
            (3, 3),
            (99, 4),
        ],
    )
    def test_normalize_damage_type(self, raw, expected):
        assert normalize_damage_type(raw) == expected


class TestInjury:
    def test_torso_cutting_multiplier(self):
        result = compute_injury(10, 5, 0, 0, 10, 0, 10)

        assert result["penetrating_damage"] == 10
        assert result["multiplier"] == 1.5
        assert result["final_injury"] == 15
        assert result["new_pv"] == -5

    def test_vitals_impaling_multiplier(self):
        result = compute_injury(4, 7, 1, 0, 10, 0, 10)

        assert result["multiplier"] == 3.0
        assert result["final_injury"] == 12

    def test_minimum_injury_for_positive_penetration(self):
        result = compute_injury(1, 4, 0, 2, 10, 0, 10)

        assert result["final_injury"] == 1

    def test_limb_crippling_caps_injury(self):
        result = compute_injury(20, 4, 7, 0, 10, 0, 10)

        assert result["appendage_hp"] == 5
        assert result["amputation"] is True
        assert result["final_injury"] == 5


def effect(effect_id=1, applies_to="attack", value=2, uses=0, target=None):
    return {
        "effect_id": effect_id,
        "applies_to": applies_to,
        "value": value,
        "uses_per_turn": uses,
        "target": target,
    }


class TestCombatEffects:
    def test_effect_availability_respects_per_turn_uses(self):
        participant = {"effect_uses": {"1": 2}}

        assert effect_is_available(effect(uses=3), participant) is True
        assert effect_is_available(effect(uses=2), participant) is False
        assert effect_is_available(effect(uses=0), participant) is True

    def test_bonus_filters_family_and_target(self):
        effects = [
            effect(1, "defense", 2),
            effect(2, "dodge", 3, target="dodge"),
            effect(3, "defense", 5, target="parry"),
        ]

        assert active_effect_bonus(effects, "defense") == 7
        assert active_effect_bonus(effects, "dodge", target="dodge") == 3
        assert active_effect_bonus(effects, "defense", target="parry") == 7

    def test_extra_defense_attempts_are_added(self):
        effects = [effect(1, "extra_defense_attempts", 1)]

        assert max_defense_attempts(effects) == 2

    def test_defense_uses_include_extra_uses_and_used_counter(self):
        effects = [
            effect(1, "extra_defense_uses", 1, target="dodge"),
            effect(2, "extra_defense_uses", 2, target="parry"),
        ]
        participant = {"defense_uses": {"dodge": 1}}

        assert defense_remaining_uses(effects, participant, "dodge", "dodge") == 1
        assert defense_remaining_uses(effects, participant, "parry:1", "parry") == 3


class TestDamageExpression:
    @pytest.mark.parametrize(
        "expression, dice, modifier, damage_type",
        [
            ("2d+1 pi+", 2, 1, 10),
            ("3d-1 cut", 3, -1, 5),
            ("1d cr", 1, 0, 4),
            ("2d imp", 2, 0, 7),
            ("1d+2 burn", 1, 2, 2),
        ],
    )
    def test_parses_gurps_expressions(
        self, expression, dice, modifier, damage_type
    ):
        parsed = parse_damage_expression(expression)

        assert parsed is not None
        assert parsed["dice_count"] == dice
        assert parsed["modifier"] == modifier
        assert parsed["damage_type"] == damage_type

    @pytest.mark.parametrize("expression", [None, "", "dano", "0d", "2x+1"])
    def test_invalid_expressions_return_none(self, expression):
        assert parse_damage_expression(expression) is None
