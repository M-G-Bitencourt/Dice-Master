"""Command-level tests for cogs/skill_test.py.

Commands are invoked through the raw ``discord.app_commands`` callback against
an isolated in-memory database (``patched_sqlite``). Every randint consumer is
replaced by a deterministic BudgetRng stream, so no real randomness or network
access is involved.
"""

from __future__ import annotations

import discord
import pytest

import cogs.skill_test as skill_test_module
from cogs.skill_test import Skill_tests
from helpers import insert_hdm, patch_rng
from utils import dice_mechanics


@pytest.fixture
def cog(make_cog):
    return make_cog(Skill_tests)


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


async def invoke_test(cog, interaction, nh: int) -> None:
    await Skill_tests.test.callback(cog, interaction, nh)


async def invoke_qkd(cog, interaction, nh1: int, nh2: int) -> None:
    await Skill_tests.qkd.callback(cog, interaction, nh1, nh2)


# (fate, nh, rolls, title, color, margin field, margin value)
FATE_CASES = [
    (
        0,
        10,
        [1, 2, 2],
        "SUCESSO!",
        discord.Color.green(),
        "Margem de Vitória",
        "`10 - 5 = 5`",
    ),
    (
        1,
        10,
        [4, 4, 3],
        "FALHA",
        discord.Color.red(),
        "Margem de Derrota",
        "`11 - 10 = 1`",
    ),
    (
        2,
        10,
        [1, 1, 2],
        "SUCESSO DECISIVO!",
        discord.Color.gold(),
        "Margem de Vitória",
        "`10 - 4 = 6`",
    ),
    (
        3,
        10,
        [6, 5, 6],
        "FALHA CRÍTICA!",
        discord.Color.brand_red(),
        "Margem de Derrota",
        "`17 - 10 = 7`",
    ),
]

# (nh, rolls, title, color, margin field, margin value)
RESOLUTION_CASES = [
    (
        10,
        [6, 6, 6],
        "FALHA CRÍTICA!",
        discord.Color.brand_red(),
        "Margem de Derrota",
        "`18 - 10 = 8`",
    ),
    (
        15,
        [6, 5, 6],
        "FALHA CRÍTICA!",
        discord.Color.brand_red(),
        "Margem de Derrota",
        "`17 - 15 = 2`",
    ),
    (
        16,
        [6, 5, 6],
        "FALHA",
        discord.Color.red(),
        "Margem de Derrota",
        "`17 - 16 = 1`",
    ),
    (
        4,
        [1, 1, 2],
        "SUCESSO DECISIVO!",
        discord.Color.gold(),
        "Margem de Vitória",
        "`4 - 4 = 0`",
    ),
    (
        15,
        [1, 1, 3],
        "SUCESSO DECISIVO!",
        discord.Color.gold(),
        "Margem de Vitória",
        "`15 - 5 = 10`",
    ),
    (
        1,
        [4, 4, 3],
        "FALHA CRÍTICA!",
        discord.Color.brand_red(),
        "Margem de Derrota",
        "`11 - 1 = 10`",
    ),
    (
        14,
        [1, 1, 3],
        "SUCESSO!",
        discord.Color.green(),
        "Margem de Vitória",
        "`14 - 5 = 9`",
    ),
    (
        0,
        [1, 1, 1],
        "FALHA",
        discord.Color.red(),
        "Margem de Derrota",
        "`3 - 0 = 3`",
    ),
]


class TestTestCommandFates:
    @pytest.mark.parametrize(
        "fate, nh, rolls, title, color, margin_name, margin_value",
        FATE_CASES,
        ids=[
            "fate-0-normal-success",
            "fate-1-normal-failure",
            "fate-2-critical-success",
            "fate-3-critical-failure",
        ],
    )
    async def test_deterministic_fate_drives_the_expected_embed(
        self,
        cog,
        interaction,
        character,
        patched_sqlite,
        monkeypatch,
        fate,
        nh,
        rolls,
        title,
        color,
        margin_name,
        margin_value,
    ):
        insert_hdm(patched_sqlite, player_id=1, fate=fate)
        patch_rng(monkeypatch, dice_mechanics, rolls)

        await invoke_test(cog, interaction, nh)

        assert_deferred(interaction)
        embed = followup_embed(interaction)
        assert embed.title == title
        assert embed.color == color
        assert field_value(embed, "Parada de Dados") == f"`{rolls} = {sum(rolls)}`"
        assert field_value(embed, "Nível de Habilidade") == f"`NH Efetivo: {nh}`"
        assert field_value(embed, margin_name) == margin_value
        # The fate is consumed once and purged from the persistence layer.
        assert hdm_row_count(patched_sqlite) == 0


class TestTestCommandResolutionMatrix:
    @pytest.mark.parametrize(
        "nh, rolls, title, color, margin_name, margin_value",
        RESOLUTION_CASES,
        ids=[
            "roll-18-critical-failure",
            "roll-17-nh-15-critical-failure",
            "roll-17-nh-16-plain-failure",
            "pool-4-critical-success",
            "margin-10-critical-success",
            "margin-10-critical-failure",
            "margin-9-normal-success",
            "nh-0-cannot-succeed",
        ],
    )
    async def test_resolution_state_machine(
        self,
        cog,
        interaction,
        character,
        patched_sqlite,
        monkeypatch,
        nh,
        rolls,
        title,
        color,
        margin_name,
        margin_value,
    ):
        # No hdm row exists, so the command falls back to its module randint.
        patch_rng(monkeypatch, skill_test_module, rolls)

        await invoke_test(cog, interaction, nh)

        assert_deferred(interaction)
        embed = followup_embed(interaction)
        assert embed.title == title
        assert embed.color == color
        assert field_value(embed, "Parada de Dados") == f"`{rolls} = {sum(rolls)}`"
        assert field_value(embed, "Nível de Habilidade") == f"`NH Efetivo: {nh}`"
        assert field_value(embed, margin_name) == margin_value


class TestTestCommandNegativeNh:
    async def test_hdm_dices_receives_clamped_zero(
        self, cog, interaction, character, patched_sqlite, monkeypatch
    ):
        insert_hdm(patched_sqlite, player_id=1, fate=0)
        captured: list[dict] = []

        def fake_hdm_dices(**kwargs):
            captured.append(kwargs)
            return [1, 2, 2]

        monkeypatch.setattr(skill_test_module, "hdm_dices", fake_hdm_dices)

        await invoke_test(cog, interaction, -5)

        assert captured == [{"nh": 0, "fate": 0}]
        embed = followup_embed(interaction)
        assert embed.title == "FALHA"
        assert field_value(embed, "Nível de Habilidade") == "`NH Efetivo: 0`"
        assert field_value(embed, "Margem de Derrota") == "`5 - 0 = 5`"

    async def test_rng_path_also_resolves_with_effective_sl_zero(
        self, cog, interaction, character, patched_sqlite, monkeypatch
    ):
        patch_rng(monkeypatch, skill_test_module, [1, 1, 1])

        await invoke_test(cog, interaction, -5)

        assert_deferred(interaction)
        embed = followup_embed(interaction)
        assert embed.title == "FALHA"
        assert field_value(embed, "Nível de Habilidade") == "`NH Efetivo: 0`"
        assert field_value(embed, "Margem de Derrota") == "`3 - 0 = 3`"

    async def test_embed_field_names_are_exact_for_critical_failure(
        self, cog, interaction, character, patched_sqlite, monkeypatch
    ):
        patch_rng(monkeypatch, skill_test_module, [6, 6, 6])

        await invoke_test(cog, interaction, -1)

        embed = followup_embed(interaction)
        assert embed.title == "FALHA CRÍTICA!"
        assert [field.name for field in embed.fields] == [
            "Parada de Dados",
            "Nível de Habilidade",
            "Margem de Derrota",
        ]


def dispute_payload(nh1, dices1, nh2, dices2):
    """Build a quick_dispute-shaped payload with pools and margins derived from dice."""
    pool1, pool2 = sum(dices1), sum(dices2)
    return {
        "result1": {
            "dice_pool1": pool1,
            "success_roll1": pool1 <= nh1,
            "margin1": nh1 - pool1,
            "dices1": list(dices1),
        },
        "result2": {
            "dice_pool2": pool2,
            "success_roll2": pool2 <= nh2,
            "margin2": nh2 - pool2,
            "dices2": list(dices2),
        },
    }


def install_quick_dispute(monkeypatch, payload):
    """Replace cogs.skill_test.quick_dispute with a recording stub."""
    calls: list[tuple[int, int, int]] = []

    def fake_quick_dispute(player_id, effective_nh1, effective_nh2):
        calls.append((player_id, effective_nh1, effective_nh2))
        return payload

    monkeypatch.setattr(skill_test_module, "quick_dispute", fake_quick_dispute)
    return calls


class TestQkdCommand:
    async def test_roll_victory_branch(
        self, cog, interaction, character, monkeypatch
    ):
        payload = dispute_payload(nh1=10, dices1=[1, 1, 1], nh2=8, dices2=[3, 3, 3])
        calls = install_quick_dispute(monkeypatch, payload)

        await invoke_qkd(cog, interaction, 10, 8)

        assert_deferred(interaction)
        assert calls == [(1, 10, 8)]
        embed = followup_embed(interaction)
        assert embed.title == "SUCESSO POR ROLAGEM!"
        assert embed.description == (
            "Você obteve um sucesso no teste e seu oponente um fracasso."
        )
        assert embed.color == discord.Color.green()
        assert field_value(embed, "Você") == (
            "`Dados: [1, 1, 1] = 3`\n"
            "`NH Efetivo: 10`\n"
            "Sucesso: Sim\n"
            "`Margem: 7`"
        )
        assert field_value(embed, "Oponente") == (
            "`Dados: [3, 3, 3] = 9`\n"
            "`NH Efetivo: 8`\n"
            "Sucesso: Não\n"
            "`Margem: -1`"
        )
        assert field_value(embed, "Diferença das Margens de Sucesso") == "`7 - (-1) = 8`"

    async def test_roll_defeat_branch(
        self, cog, interaction, character, monkeypatch
    ):
        payload = dispute_payload(nh1=8, dices1=[3, 3, 3], nh2=10, dices2=[1, 1, 1])
        install_quick_dispute(monkeypatch, payload)

        await invoke_qkd(cog, interaction, 8, 10)

        embed = followup_embed(interaction)
        assert embed.title == "FRACASSO POR ROLAGEM!"
        assert embed.description == (
            "Você obteve um fracasso no teste e seu oponente um sucesso."
        )
        assert embed.color == discord.Color.red()
        assert field_value(embed, "Diferença das Margens de Sucesso") == "`-1 - (7) = -8`"

    async def test_margin_victory_branch(
        self, cog, interaction, character, monkeypatch
    ):
        payload = dispute_payload(nh1=10, dices1=[1, 2, 2], nh2=10, dices2=[3, 3, 2])
        install_quick_dispute(monkeypatch, payload)

        await invoke_qkd(cog, interaction, 10, 10)

        embed = followup_embed(interaction)
        assert embed.title == "SUCESSO POR MARGEM DE TESTE!"
        assert embed.description == "Resultado decidido pela margem do teste."
        assert embed.color == discord.Color.green()
        assert field_value(embed, "Você") == (
            "`Dados: [1, 2, 2] = 5`\n"
            "`NH Efetivo: 10`\n"
            "Sucesso: Sim\n"
            "`Margem: 5`"
        )
        assert field_value(embed, "Oponente") == (
            "`Dados: [3, 3, 2] = 8`\n"
            "`NH Efetivo: 10`\n"
            "Sucesso: Sim\n"
            "`Margem: 2`"
        )
        assert field_value(embed, "Diferença das Margens de Sucesso") == "`5 - (2) = 3`"

    async def test_tie_branch(self, cog, interaction, character, monkeypatch):
        payload = dispute_payload(nh1=10, dices1=[2, 2, 2], nh2=10, dices2=[1, 2, 3])
        install_quick_dispute(monkeypatch, payload)

        await invoke_qkd(cog, interaction, 10, 10)

        embed = followup_embed(interaction)
        assert embed.title == "EMPATE!"
        assert embed.description == (
            "A disputa terminou em um equilíbrio absoluto de margens."
        )
        assert embed.color == discord.Color.dark_gray()
        assert field_value(embed, "Diferença das Margens de Sucesso") == "`4 - (4) = 0`"

    async def test_margin_defeat_branch(
        self, cog, interaction, character, monkeypatch
    ):
        payload = dispute_payload(nh1=10, dices1=[3, 3, 3], nh2=10, dices2=[1, 1, 1])
        install_quick_dispute(monkeypatch, payload)

        await invoke_qkd(cog, interaction, 10, 10)

        embed = followup_embed(interaction)
        assert embed.title == "FRACASSO POR MARGEM DE TESTE!"
        assert embed.description == "Resultado decidido pela margem do teste."
        assert embed.color == discord.Color.red()
        assert field_value(embed, "Diferença das Margens de Sucesso") == "`1 - (7) = -6`"
