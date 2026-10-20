"""Command-level tests for cogs/battle.py.

All commands run through the raw discord.app_commands callback against an
isolated in-memory SQLite database. Every randint consumer is replaced by a
deterministic BudgetRng stream, so no real randomness or network is involved.
"""

from __future__ import annotations

import pytest
from discord import app_commands

import cogs.battle as battle_module
from cogs.battle import Battle
from helpers import FakeInteraction, patch_rng
from utils.db_functions import get_player_condition, set_player_condition


GDP_THRUST = app_commands.Choice(name="Golpe de Ponta", value=0)
GEB_SWING = app_commands.Choice(name="Golpe em Balanço", value=1)


@pytest.fixture
def cog(make_cog):
    return make_cog(Battle)


def assert_deferred(interaction) -> None:
    """Commands performing I/O must defer the interaction before any work."""
    assert interaction.response.deferred, "response.defer was not awaited"
    assert interaction.response.deferred[0]["kwargs"]["ephemeral"] is False


class TestCommandNames:
    def test_aim_and_evaluate_use_flat_combat_names(self):
        assert Battle.aim.name == "combat_aim"
        assert Battle.evaluate.name == "combat_evaluate"

    def test_damage_replaces_legacy_dmg_and_removed_commands_are_absent(self):
        assert Battle.damage.name == "damage"
        for legacy in ("atk", "def", "fnt", "ranged_attack", "dmg"):
            assert not hasattr(Battle, legacy)


class TestDamageCommand:
    async def test_builds_expected_embed_without_deferring(
        self, cog, interaction, character, monkeypatch
    ):
        patch_rng(monkeypatch, battle_module, [3])

        await Battle.damage.callback(cog, interaction, 10, 2, GDP_THRUST)

        # /damage performs no I/O and intentionally replies immediately.
        assert interaction.response.deferred == []
        embed = interaction.response.messages[0]["kwargs"]["embed"]
        assert embed.title == "DANO"
        assert [field.name for field in embed.fields] == [
            "Força",
            "Tipo de Ataque",
            "Resultado da Rolagem",
        ]

        fields = {field.name: field.value for field in embed.fields}
        assert fields["Força"] == "10"
        assert fields["Tipo de Ataque"] == "Golpe de Ponta\n1d - 2"
        assert fields["Resultado da Rolagem"] == (
            "\n`Dados: [3] = 3`\n"
            "Modificador de Força: -2\n"
            "Modificador de Arma: 2\n\n"
            "**Total:** 3"
        )

    async def test_swing_choice_reads_geb_column(
        self, cog, interaction, character, monkeypatch
    ):
        patch_rng(monkeypatch, battle_module, [4])

        await Battle.damage.callback(cog, interaction, 10, 0, GEB_SWING)

        embed = interaction.response.messages[0]["kwargs"]["embed"]
        fields = {field.name: field.value for field in embed.fields}
        assert fields["Tipo de Ataque"] == "Golpe em Balanço\n1d + 0"
        assert "**Total:** 4" in fields["Resultado da Rolagem"]

    async def test_embed_fields_respect_discord_clamp(
        self, cog, interaction, character, monkeypatch
    ):
        patch_rng(monkeypatch, battle_module, [1, 1, 1])

        await Battle.damage.callback(cog, interaction, 30, 5, GDP_THRUST)

        embed = interaction.response.messages[0]["kwargs"]["embed"]
        assert all(len(field.value) <= 1000 for field in embed.fields)


class TestAimAndEvaluateCommands:
    async def test_aim_increments_and_resets_evaluate(
        self, cog, interaction, character, db
    ):
        set_player_condition(db, 1, "evaluate", 5)

        await Battle.aim.callback(cog, interaction)

        assert_deferred(interaction)
        assert interaction.followup.sent[0]["args"][0] == "1º Turno apontando."
        assert get_player_condition(db, 1, "aim") == 1
        assert get_player_condition(db, 1, "evaluate") == 0

    async def test_aim_increments_across_turns(self, cog, character, db):
        first = FakeInteraction()
        second = FakeInteraction()

        await Battle.aim.callback(cog, first)
        await Battle.aim.callback(cog, second)

        assert_deferred(first)
        assert_deferred(second)
        assert first.followup.sent[0]["args"][0] == "1º Turno apontando."
        assert second.followup.sent[0]["args"][0] == "2º Turno apontando."
        assert get_player_condition(db, 1, "aim") == 2

    async def test_evaluate_increments_and_resets_aim(
        self, cog, interaction, character, db
    ):
        set_player_condition(db, 1, "aim", 4)

        await Battle.evaluate.callback(cog, interaction)

        assert_deferred(interaction)
        assert interaction.followup.sent[0]["args"][0] == "1º Turno Avaliando."
        assert get_player_condition(db, 1, "evaluate") == 1
        assert get_player_condition(db, 1, "aim") == 0
