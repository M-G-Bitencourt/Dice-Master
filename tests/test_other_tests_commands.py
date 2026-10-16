"""Command-level tests for cogs/other_tests.py.

Commands are invoked through the raw ``discord.app_commands`` callback against
an isolated in-memory database (``patched_sqlite``). Every randint consumer is
replaced by a deterministic BudgetRng stream, so no real randomness or network
access is involved.
"""

from __future__ import annotations

import discord
import pytest

import cogs.other_tests as other_tests_module
from cogs.other_tests import Other_tests
from helpers import dice_sequence, insert_hdm, patch_rng
from utils import dice_mechanics


@pytest.fixture
def cog(make_cog):
    return make_cog(Other_tests)


def followup_embed(interaction, index: int = 0):
    return interaction.followup.sent[index]["kwargs"]["embed"]


def field_value(embed, name: str) -> str:
    for field in embed.fields:
        if field.name == name:
            return field.value
    raise AssertionError(f"embed field {name!r} not found")


def assert_deferred(interaction) -> None:
    assert interaction.response.deferred, "response.defer was not awaited"
    assert interaction.response.deferred[0]["kwargs"]["ephemeral"] is False


def hdm_row_count(connection, player_id: int = 1) -> int:
    return connection.execute(
        "SELECT COUNT(*) FROM hdm WHERE id_player = ?", (player_id,)
    ).fetchone()[0]


class TestRollCommand:
    async def test_sums_dice_and_adds_the_modifier(
        self, cog, interaction, character, monkeypatch
    ):
        patch_rng(monkeypatch, other_tests_module, [1, 2, 3, 4])

        await Other_tests.roll.callback(cog, interaction, 4, 2)

        # /roll performs no database I/O and intentionally replies immediately,
        # so the interaction is never deferred (unlike /react and /panic).
        assert interaction.response.deferred == []
        embed = interaction.response.messages[0]["kwargs"]["embed"]
        assert embed.title == "ROLAGEM"
        assert embed.color == discord.Color.green()
        assert [field.name for field in embed.fields] == ["Rolagem"]
        assert field_value(embed, "Rolagem") == (
            "`Dados: [1, 2, 3, 4] = 10`\nModificador: 2\n\n**Total:** 12"
        )

    async def test_zero_dice_rolls_an_empty_list_and_total_zero(
        self, cog, interaction, character, monkeypatch
    ):
        rng = patch_rng(monkeypatch, other_tests_module, [1])

        await Other_tests.roll.callback(cog, interaction, 0, 4)

        assert rng.calls == 0
        embed = interaction.response.messages[0]["kwargs"]["embed"]
        assert field_value(embed, "Rolagem") == (
            "`Dados: [] = 0`\nModificador: 4\n\n**Total:** 4"
        )

    async def test_negative_modifier_subtracts_from_the_total(
        self, cog, interaction, character, monkeypatch
    ):
        patch_rng(monkeypatch, other_tests_module, [6, 6, 6])

        await Other_tests.roll.callback(cog, interaction, 3, -5)

        embed = interaction.response.messages[0]["kwargs"]["embed"]
        assert field_value(embed, "Rolagem") == (
            "`Dados: [6, 6, 6] = 18`\nModificador: -5\n\n**Total:** 13"
        )


# (modifier, total, expected title, expected color); dice are always [1, 1, 1].
REACTION_BOUNDARIES = [
    (-5, -2, "REAÇÃO DESASTROSA", discord.Color.red()),
    (-3, 0, "REAÇÃO DESASTROSA", discord.Color.red()),
    (-2, 1, "REAÇÃO MUITO RUIM", discord.Color.red()),
    (0, 3, "REAÇÃO MUITO RUIM", discord.Color.red()),
    (3, 6, "REAÇÃO RUIM", discord.Color.orange()),
    (6, 9, "REAÇÃO FRACA", discord.Color.yellow()),
    (9, 12, "REAÇÃO NEUTRA", discord.Color.greyple()),
    (12, 15, "REAÇÃO BOA", discord.Color.green()),
    (15, 18, "REAÇÃO MUITO BOA", discord.Color.green()),
    (16, 19, "REAÇÃO EXCELENTE", discord.Color.blue()),
]

# (fate, modifier, expected dice, total, title, color)
REACTION_SHORTCUTS = [
    (0, -10, [6, 6, 6], 8, "REAÇÃO FRACA", discord.Color.yellow()),
    (0, 13, [1, 1, 1], 16, "REAÇÃO MUITO BOA", discord.Color.green()),
    (1, -15, [6, 6, 6], 3, "REAÇÃO MUITO RUIM", discord.Color.red()),
    (1, 7, [1, 1, 1], 10, "REAÇÃO NEUTRA", discord.Color.greyple()),
    (2, -5, [6, 6, 6], 13, "REAÇÃO BOA", discord.Color.green()),
    (3, 1, [1, 1, 1], 4, "REAÇÃO RUIM", discord.Color.orange()),
]

# (fate, modifier, rng stream, expected dice, total, title, color, expected calls)
REACTION_LOOPS = [
    (
        0,
        0,
        dice_sequence([1, 1, 1], [4, 4, 4]),
        [4, 4, 4],
        12,
        "REAÇÃO NEUTRA",
        discord.Color.greyple(),
        6,
    ),
    (
        1,
        0,
        [2, 2, 2],
        [2, 2, 2],
        6,
        "REAÇÃO RUIM",
        discord.Color.orange(),
        3,
    ),
    (
        2,
        0,
        [6, 6, 6],
        [6, 6, 6],
        18,
        "REAÇÃO MUITO BOA",
        discord.Color.green(),
        3,
    ),
    (
        3,
        0,
        [1, 1, 1],
        [1, 1, 1],
        3,
        "REAÇÃO MUITO RUIM",
        discord.Color.red(),
        3,
    ),
]


def assert_react_field(embed, dices, pool, modifier, total) -> None:
    """Assert the exact metrics field rendering of /react."""
    value = field_value(embed, "Métricas da Rolagem")
    assert value == (
        f"`Dados: {dices} = {pool}`\n"
        f"Modificador: `{modifier:+d}`\n\n"
        f"**Resultado Final: {total}**"
    )


async def invoke_react(cog, interaction, modifier: int) -> None:
    await Other_tests.react.callback(cog, interaction, modifier)


class TestReactCommand:
    """/react defers the interaction before consuming fate, rolling, and replying."""

    @pytest.mark.parametrize(
        "modifier, total, title, color",
        REACTION_BOUNDARIES,
        ids=[
            "total-negative",
            "total-0-disaster",
            "total-1-muito-ruim",
            "total-3-muito-ruim",
            "total-6-ruim",
            "total-9-fraca",
            "total-12-neutra",
            "total-15-boa",
            "total-18-muito-boa",
            "total-19-excelente",
        ],
    )
    async def test_exact_table_boundaries_with_rng_fallback(
        self, cog, interaction, character, patched_sqlite, monkeypatch, modifier, total, title, color
    ):
        # No hdm row exists: the command falls back to its module randint.
        rng = patch_rng(monkeypatch, other_tests_module, [1, 1, 1])

        await invoke_react(cog, interaction, modifier)

        assert_deferred(interaction)
        assert rng.calls == 3
        embed = followup_embed(interaction)
        assert embed.title == title
        assert embed.color == color
        assert_react_field(embed, [1, 1, 1], 3, modifier, total)

    @pytest.mark.parametrize(
        "fate, modifier, expected_dice, total, title, color",
        REACTION_SHORTCUTS,
        ids=[
            "fate-0-max-below-10",
            "fate-0-min-above-15",
            "fate-1-max-below-4",
            "fate-1-min-above-9",
            "fate-2-max-below-16",
            "fate-3-min-above-3",
        ],
    )
    async def test_fate_shortcuts_skip_rng_for_extreme_modifiers(
        self,
        cog,
        interaction,
        character,
        patched_sqlite,
        monkeypatch,
        fate,
        modifier,
        expected_dice,
        total,
        title,
        color,
    ):
        insert_hdm(patched_sqlite, player_id=1, fate=fate)
        # Any accidental randint call would consume this stub and fail the assert.
        rng = patch_rng(monkeypatch, other_tests_module, [1])

        await invoke_react(cog, interaction, modifier)

        assert rng.calls == 0
        embed = followup_embed(interaction)
        assert embed.title == title
        assert embed.color == color
        assert_react_field(embed, expected_dice, sum(expected_dice), modifier, total)
        assert hdm_row_count(patched_sqlite) == 0

    @pytest.mark.parametrize(
        "fate, modifier, stream, expected_dice, total, title, color, expected_calls",
        REACTION_LOOPS,
        ids=["fate-0-loop", "fate-1-loop", "fate-2-loop", "fate-3-loop"],
    )
    async def test_fate_loops_accept_the_first_matching_roll(
        self,
        cog,
        interaction,
        character,
        patched_sqlite,
        monkeypatch,
        fate,
        modifier,
        stream,
        expected_dice,
        total,
        title,
        color,
        expected_calls,
    ):
        insert_hdm(patched_sqlite, player_id=1, fate=fate)
        rng = patch_rng(monkeypatch, other_tests_module, stream)

        await invoke_react(cog, interaction, modifier)

        assert rng.calls == expected_calls
        embed = followup_embed(interaction)
        assert embed.title == title
        assert embed.color == color
        assert_react_field(embed, expected_dice, sum(expected_dice), modifier, total)
        assert hdm_row_count(patched_sqlite) == 0

    async def test_rng_fallback_uses_three_dice(
        self, cog, interaction, character, patched_sqlite, monkeypatch
    ):
        rng = patch_rng(monkeypatch, other_tests_module, [2, 3, 4])

        await invoke_react(cog, interaction, 0)

        assert rng.calls == 3
        embed = followup_embed(interaction)
        assert embed.title == "REAÇÃO FRACA"
        assert_react_field(embed, [2, 3, 4], 9, 0, 9)



class TestPanicCommand:
    async def test_success_embed_metrics(
        self, cog, interaction, character, patched_sqlite, monkeypatch
    ):
        patch_rng(monkeypatch, other_tests_module, [1, 2, 2])

        await Other_tests.panic.callback(cog, interaction, 10, 0)

        assert_deferred(interaction)
        embed = followup_embed(interaction)
        assert embed.title == "RESISTIU AO PÂNICO"
        assert embed.color == discord.Color.green()
        assert [field.name for field in embed.fields] == [
            "Parada de Dados",
            "Nível de Vontade",
            "Margem de Vitória",
        ]
        assert field_value(embed, "Parada de Dados") == "`[1, 2, 2] = 5`"
        assert field_value(embed, "Nível de Vontade") == (
            "NH Básico: 10\nModificador: 0\n`NH Efetivo: 10` -> 10 + 0"
        )
        assert field_value(embed, "Margem de Vitória") == "`10 - 5 = 5`"

    async def test_critical_success_paints_the_embed_gold(
        self, cog, interaction, character, patched_sqlite, monkeypatch
    ):
        rng = patch_rng(monkeypatch, other_tests_module, [1, 1, 2])

        await Other_tests.panic.callback(cog, interaction, 10, 0)

        assert rng.calls == 3
        embed = followup_embed(interaction)
        assert embed.title == "RESISTIU AO PÂNICO"
        assert embed.color == discord.Color.gold()
        assert field_value(embed, "Margem de Vitória") == "`10 - 4 = 6`"

    async def test_normal_failure_rolls_the_panic_table_without_bonus(
        self, cog, interaction, character, patched_sqlite, monkeypatch
    ):
        patch_rng(monkeypatch, other_tests_module, dice_sequence([4, 4, 3], [2, 3, 4]))

        await Other_tests.panic.callback(cog, interaction, 10, 0)

        embed = followup_embed(interaction)
        assert embed.title == "SUCUMBIU AO PÂNICO"
        assert embed.color == discord.Color.red()
        assert embed.description == (
            "A tabela de consequências de pânico encontra-se no Módulo Básico, pág. 361."
        )
        assert field_value(embed, "Métricas de Fracasso") == (
            "Dados do Teste: `[4, 4, 3] = 11`\nMargem de Fracasso: `1`"
        )
        assert field_value(embed, "Rolagem na Tabela de Pânicos") == (
            "Dados: `[2, 3, 4] = 9`\n**Valor Final do Pânico:** `10`"
        )

    async def test_critical_failure_adds_the_flat_ten_badge(
        self, cog, interaction, character, patched_sqlite, monkeypatch
    ):
        patch_rng(monkeypatch, other_tests_module, dice_sequence([6, 6, 6], [1, 2, 3]))

        await Other_tests.panic.callback(cog, interaction, 10, 0)

        embed = followup_embed(interaction)
        assert embed.title == "SUCUMBIU AO PÂNICO"
        assert embed.color == discord.Color.brand_red()
        # Badge text is pinned exactly, so any decorative glyph would break it.
        assert embed.description == (
            "A tabela de consequências de pânico encontra-se no Módulo Básico, pág. 361."
            "\n**[FALHA CRÍTICA: +10 adicionado ao resultado final!]**"
        )
        assert field_value(embed, "Métricas de Fracasso") == (
            "Dados do Teste: `[6, 6, 6] = 18`\nMargem de Fracasso: `8`"
        )
        assert field_value(embed, "Rolagem na Tabela de Pânicos") == (
            "Dados: `[1, 2, 3] = 6`\n**Valor Final do Pânico:** `24`"
        )

    async def test_critical_failure_by_ten_margin_also_gets_the_badge(
        self, cog, interaction, character, patched_sqlite, monkeypatch
    ):
        patch_rng(monkeypatch, other_tests_module, dice_sequence([4, 4, 3], [1, 1, 1]))

        await Other_tests.panic.callback(cog, interaction, 1, 0)

        embed = followup_embed(interaction)
        assert embed.title == "SUCUMBIU AO PÂNICO"
        assert embed.color == discord.Color.brand_red()
        assert "[FALHA CRÍTICA: +10 adicionado ao resultado final!]" in embed.description
        assert field_value(embed, "Métricas de Fracasso") == (
            "Dados do Teste: `[4, 4, 3] = 11`\nMargem de Fracasso: `10`"
        )
        assert field_value(embed, "Rolagem na Tabela de Pânicos") == (
            "Dados: `[1, 1, 1] = 3`\n**Valor Final do Pânico:** `23`"
        )

    async def test_negative_effective_will_is_clamped_to_zero(
        self, cog, interaction, character, patched_sqlite, monkeypatch
    ):
        # Raw effective will would be 5 - 20 = -15; clamped to 0 the failure
        # margin is 3, while the unclamped value would yield 18 >= 10 and turn
        # the result into a critical failure with the flat +10 badge.
        patch_rng(monkeypatch, other_tests_module, dice_sequence([1, 1, 1], [2, 2, 2]))

        await Other_tests.panic.callback(cog, interaction, 5, -20)

        embed = followup_embed(interaction)
        assert embed.title == "SUCUMBIU AO PÂNICO"
        assert embed.color == discord.Color.red()
        assert embed.description == (
            "A tabela de consequências de pânico encontra-se no Módulo Básico, pág. 361."
        )
        assert field_value(embed, "Métricas de Fracasso") == (
            "Dados do Teste: `[1, 1, 1] = 3`\nMargem de Fracasso: `3`"
        )
        assert field_value(embed, "Rolagem na Tabela de Pânicos") == (
            "Dados: `[2, 2, 2] = 6`\n**Valor Final do Pânico:** `9`"
        )

    async def test_negative_modifier_success_math(
        self, cog, interaction, character, patched_sqlite, monkeypatch
    ):
        patch_rng(monkeypatch, other_tests_module, [1, 2, 2])

        await Other_tests.panic.callback(cog, interaction, 15, -5)

        embed = followup_embed(interaction)
        assert embed.title == "RESISTIU AO PÂNICO"
        assert embed.color == discord.Color.green()
        assert field_value(embed, "Nível de Vontade") == (
            "NH Básico: 15\nModificador: -5\n`NH Efetivo: 10` -> 15 - 5"
        )
        assert field_value(embed, "Margem de Vitória") == "`10 - 5 = 5`"

    async def test_deterministic_fate_routes_through_hdm_dices(
        self, cog, interaction, character, patched_sqlite, monkeypatch
    ):
        insert_hdm(patched_sqlite, player_id=1, fate=0)
        patch_rng(monkeypatch, dice_mechanics, [1, 2, 2])

        await Other_tests.panic.callback(cog, interaction, 10, 0)

        embed = followup_embed(interaction)
        assert embed.title == "RESISTIU AO PÂNICO"
        assert field_value(embed, "Parada de Dados") == "`[1, 2, 2] = 5`"
        assert field_value(embed, "Margem de Vitória") == "`10 - 5 = 5`"
        assert hdm_row_count(patched_sqlite) == 0
