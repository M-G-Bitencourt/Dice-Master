"""Integration tests for GM shield directives in non-combat rolls."""

from __future__ import annotations

from cogs.other_tests import Other_tests
from cogs.skill_test import Skill_tests
from helpers import FakeInteraction
from utils.gm_directives import gm_shield_store


def field_value(embed, name: str) -> str:
    for field in embed.fields:
        if field.name == name:
            return field.value
    raise AssertionError(name)


class TestGMShieldSkillTest:
    async def test_forced_failure_changes_the_skill_result(
        self, make_cog, interaction, character, monkeypatch
    ):
        cog = make_cog(Skill_tests)
        gm_shield_store.set(
            character_id=character,
            player_id=1,
            roll_kind="skill_test",
            outcome="failure",
        )

        await Skill_tests.test.callback(cog, interaction, 10)

        embed = interaction.followup.sent[0]["kwargs"]["embed"]
        assert embed.title == "FALHA"
        assert field_value(embed, "Margem de Derrota") == "`11 - 10 = 1`"


class TestGMShieldGenericRoll:
    async def test_preset_controls_the_total_and_dice(
        self, make_cog, interaction, character, monkeypatch
    ):
        cog = make_cog(Other_tests)
        gm_shield_store.set(
            character_id=character,
            player_id=1,
            roll_kind="generic_roll",
            outcome="random",
            payload={"preset": "min"},
        )

        await Other_tests.roll.callback(cog, interaction, 4, 2)

        embed = interaction.response.messages[0]["kwargs"]["embed"]
        assert field_value(embed, "Rolagem") == (
            "`Dados: [1, 1, 1, 1] = 4`\nModificador: 2\n\n**Total:** 6"
        )
