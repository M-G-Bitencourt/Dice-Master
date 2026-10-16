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
from helpers import (
    FakeInteraction,
    dice_sequence,
    insert_attack,
    insert_hdm,
    patch_rng,
)
from utils import dice_mechanics, test_mechanics
from utils.db_functions import get_player_condition, set_player_condition


def choice(name: str, value: int) -> app_commands.Choice:
    return app_commands.Choice(name=name, value=value)


TRUNK = choice("Tronco (0)", 0)
SKULL = choice("Crânio (-7)", 2)
GDP = choice("GdP", 11)
CRUSHING = choice("Contusão", 4)
PIERCING = choice("Perfurante", 7)
GDP_THRUST = choice("Golpe de Ponta", 0)
GEB_SWING = choice("Golpe em Balanço", 1)
STRONG_YES = choice("Sim", 1)
WAIVED = choice("Desistir da Defesa", 1)
OPPONENT_CRITICAL = choice("Crítico do Oponente", 2)


@pytest.fixture
def cog(make_cog):
    return make_cog(Battle)


def attack_row(connection):
    return connection.execute(
        "SELECT raw_damage, dmg_type, hit_location, feint, critical_damage "
        "FROM current_attacks"
    ).fetchone()


def character_pv(connection, character_id: int = 1) -> int:
    return connection.execute(
        "SELECT current_pv FROM characters WHERE character_id = ?", (character_id,)
    ).fetchone()[0]


def set_body_type(connection, body_type: int, character_id: int = 1) -> None:
    connection.execute(
        "UPDATE characters SET normal_diffuse_homogeneous_unded = ? "
        "WHERE character_id = ?",
        (body_type, character_id),
    )
    connection.commit()


def followup_embed(interaction, index: int = 0):
    return interaction.followup.sent[index]["kwargs"]["embed"]


def field_value(embed, name: str) -> str:
    for field in embed.fields:
        if field.name == name:
            return field.value
    raise AssertionError(f"embed field {name!r} not found")


def assert_deferred(interaction) -> None:
    """Commands performing I/O must defer the interaction before any work."""
    assert interaction.response.deferred, "response.defer was not awaited"
    assert interaction.response.deferred[0]["kwargs"]["ephemeral"] is False


async def invoke_atk(
    cog,
    interaction,
    nh: int = 10,
    local=TRUNK,
    attack_column=GDP,
    weapon_dmg: int = 0,
    damage_type=CRUSHING,
    strong=None,
):
    await Battle.atk_melee.callback(
        cog, interaction, nh, local, attack_column, weapon_dmg, damage_type, strong
    )


async def invoke_ranged(
    cog, interaction, nh: int = 10, local=TRUNK, weapon_dmg: int = 0, damage_type=PIERCING
):
    await Battle.ranged_atk.callback(
        cog, interaction, nh, local, weapon_dmg, damage_type
    )


async def invoke_def(cog, interaction, nh: int = 10, rd: int = 0, receive_atk=None):
    await Battle.defense.callback(cog, interaction, nh, rd, receive_atk)


class TestDmgCommand:
    async def test_builds_expected_embed_without_deferring(
        self, cog, interaction, character, monkeypatch
    ):
        patch_rng(monkeypatch, battle_module, [3])

        await Battle.dmg.callback(cog, interaction, 10, 2, GDP_THRUST)

        # /dmg performs no I/O and intentionally replies immediately.
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

        await Battle.dmg.callback(cog, interaction, 10, 0, GEB_SWING)

        embed = interaction.response.messages[0]["kwargs"]["embed"]
        fields = {field.name: field.value for field in embed.fields}
        assert fields["Tipo de Ataque"] == "Golpe em Balanço\n1d + 0"
        assert "**Total:** 4" in fields["Resultado da Rolagem"]

    async def test_embed_fields_respect_discord_clamp(
        self, cog, interaction, character, monkeypatch
    ):
        patch_rng(monkeypatch, battle_module, [1, 1, 1])

        await Battle.dmg.callback(cog, interaction, 30, 5, GDP_THRUST)

        embed = interaction.response.messages[0]["kwargs"]["embed"]
        assert all(len(field.value) <= 1000 for field in embed.fields)


class TestAtkCommand:
    async def test_success_saves_attack_with_local_mode_and_feint(
        self, cog, interaction, character, db, monkeypatch
    ):
        set_player_condition(db, 1, "feint", 3)
        patch_rng(monkeypatch, battle_module, dice_sequence([3, 3, 3], [4]))

        await invoke_atk(
            cog, interaction, nh=10, local=TRUNK, weapon_dmg=2, damage_type=CRUSHING
        )

        assert_deferred(interaction)
        embed = followup_embed(interaction)
        assert embed.title == "SUCESSO!"
        # raw = 4 - 2 (ST) + 2 (weapon); critical = 6 - 2 + 2.
        assert attack_row(db) == (4, 4, 0, 3, 6)
        # Transient conditions were purged after the roll.
        assert get_player_condition(db, 1, "feint") == 0

    async def test_failure_does_not_save_and_purges_stale_attack(
        self, cog, interaction, character, db, monkeypatch
    ):
        insert_attack(
            db, raw_damage=99, dmg_type=4, hit_location=0, feint=9, critical_damage=99
        )
        patch_rng(monkeypatch, battle_module, [5, 5, 5])

        await invoke_atk(cog, interaction, nh=10)

        assert_deferred(interaction)
        assert followup_embed(interaction).title == "FALHA"
        assert attack_row(db) is None

    async def test_critical_success_uses_critical_damage(
        self, cog, interaction, character, db, monkeypatch
    ):
        patch_rng(monkeypatch, battle_module, dice_sequence([1, 1, 1], [5]))

        await invoke_atk(cog, interaction, nh=10)

        assert followup_embed(interaction).title == "GOLPE FULMINANTE!"
        # raw = 5 - 2; critical = 6 - 2.
        assert attack_row(db) == (3, 4, 0, 0, 4)

    async def test_critical_failure_rolls_critical_failure_table(
        self, cog, interaction, character, db, monkeypatch
    ):
        patch_rng(monkeypatch, battle_module, dice_sequence([6, 6, 6], [2, 3, 4]))

        await invoke_atk(cog, interaction, nh=10)

        embed = followup_embed(interaction)
        assert embed.title == "FALHA CRÍTICA!"
        assert (
            field_value(embed, "Tabela de Falhas Críticas (Combate Corpo a Corpo)")
            == "Dados: `[2, 3, 4] = 9`"
        )
        assert attack_row(db) is None

    async def test_roll_of_seventeen_is_critical_failure_at_nh_15(
        self, cog, interaction, character, db, monkeypatch
    ):
        patch_rng(monkeypatch, battle_module, dice_sequence([6, 5, 6], [1, 1, 1]))

        await invoke_atk(cog, interaction, nh=15)

        assert followup_embed(interaction).title == "FALHA CRÍTICA!"
        assert attack_row(db) is None

    async def test_roll_of_seventeen_is_plain_failure_at_nh_16(
        self, cog, interaction, character, db, monkeypatch
    ):
        patch_rng(monkeypatch, battle_module, [6, 5, 6])

        await invoke_atk(cog, interaction, nh=16)

        embed = followup_embed(interaction)
        assert embed.title == "FALHA"
        assert "Tabela de Falhas Críticas (Combate Corpo a Corpo)" not in [
            field.name for field in embed.fields
        ]
        assert attack_row(db) is None

    async def test_failure_margin_of_ten_is_critical(
        self, cog, interaction, character, db, monkeypatch
    ):
        patch_rng(monkeypatch, battle_module, dice_sequence([4, 4, 4], [1, 2, 3]))

        await invoke_atk(cog, interaction, nh=1)

        embed = followup_embed(interaction)
        assert embed.title == "FALHA CRÍTICA!"
        assert (
            field_value(embed, "Tabela de Falhas Críticas (Combate Corpo a Corpo)")
            == "Dados: `[1, 2, 3] = 6`"
        )

    async def test_evaluate_bonus_is_capped_at_three(
        self, cog, interaction, character, db, monkeypatch
    ):
        set_player_condition(db, 1, "evaluate", 5)
        patch_rng(monkeypatch, battle_module, [1, 2, 3])

        await invoke_atk(cog, interaction, nh=1)

        embed = followup_embed(interaction)
        assert embed.title == "FALHA"
        # Effective NH 4 (1 + capped 3), not 6 as the raw evaluate value would give.
        assert "NH Efetivo: `4` -> 1 + 3" in field_value(embed, "Dados Técnicos")

    async def test_shock_is_subtracted_from_effective_nh(
        self, cog, interaction, character, db, monkeypatch
    ):
        set_player_condition(db, 1, "shock", 4)
        patch_rng(monkeypatch, battle_module, [1, 2, 3])

        await invoke_atk(cog, interaction, nh=6)

        embed = followup_embed(interaction)
        assert embed.title == "FALHA"
        assert "NH Efetivo: `2` -> 6 - 4" in field_value(embed, "Dados Técnicos")

    async def test_effective_nh_never_drops_below_zero(
        self, cog, interaction, character, db, monkeypatch
    ):
        set_player_condition(db, 1, "shock", 10)
        patch_rng(monkeypatch, battle_module, [1, 1, 1])

        await invoke_atk(cog, interaction, nh=1)

        embed = followup_embed(interaction)
        assert embed.title == "FALHA"
        assert "NH Efetivo: `0` -> 1 - 10" in field_value(embed, "Dados Técnicos")

    async def test_hit_location_penalty_can_turn_hit_into_failure(
        self, cog, interaction, character, db, monkeypatch
    ):
        patch_rng(monkeypatch, battle_module, [3, 3, 3])

        await invoke_atk(cog, interaction, nh=10, local=SKULL)

        embed = followup_embed(interaction)
        assert embed.title == "FALHA"
        assert (
            "TOTAL: (-7) + (0) - (0) = `-7`"
            in field_value(embed, "Modificadores")
        )

    async def test_same_roll_succeeds_when_hitting_the_torso(
        self, cog, interaction, character, db, monkeypatch
    ):
        patch_rng(monkeypatch, battle_module, dice_sequence([3, 3, 3], [4]))

        await invoke_atk(cog, interaction, nh=10, local=TRUNK)

        assert followup_embed(interaction).title == "SUCESSO!"

    async def test_strong_attack_bonus_is_saved(
        self, cog, interaction, character, db, monkeypatch
    ):
        patch_rng(monkeypatch, battle_module, dice_sequence([3, 3, 3], [2]))

        await invoke_atk(cog, interaction, nh=10, strong=STRONG_YES)

        assert "Ataque Forte: Sim" in field_value(
            followup_embed(interaction), "Dados Técnicos"
        )
        # raw = 2 - 2 + 0 + 2; critical = 6 - 2 + 0 + 2.
        assert attack_row(db) == (2, 4, 0, 0, 6)

    async def test_missing_character_sends_error_message(
        self, cog, interaction, monkeypatch
    ):
        # atk_melee guards get_character_strength with a ValueError handler, sending
        # a pt-BR error message through the followup after the defer (same as /def).
        patch_rng(monkeypatch, battle_module, [1, 1, 1])

        await invoke_atk(cog, interaction, nh=10)

        assert interaction.response.deferred
        message = interaction.followup.sent[0]["args"][0]
        assert "Erro de processamento" in message
        assert "owner_id 1" in message


class TestRangedAttackCommand:
    async def test_success_saves_gdp_damage_and_zero_feint(
        self, cog, interaction, character, db, monkeypatch
    ):
        set_player_condition(db, 1, "feint", 4)
        patch_rng(monkeypatch, battle_module, dice_sequence([3, 3, 3], [4]))

        await invoke_ranged(cog, interaction, nh=10, weapon_dmg=0)

        assert_deferred(interaction)
        assert followup_embed(interaction).title == "SUCESSO!"
        # GdP for ST 10: raw = 4 - 2; critical = 6 - 2; ranged always saves feint 0.
        assert attack_row(db) == (2, 7, 0, 0, 4)

    async def test_aim_bonus_is_capped_at_three(
        self, cog, interaction, character, db, monkeypatch
    ):
        set_player_condition(db, 1, "aim", 5)
        patch_rng(monkeypatch, battle_module, [1, 2, 3])

        await invoke_ranged(cog, interaction, nh=1)

        embed = followup_embed(interaction)
        assert embed.title == "FALHA"
        assert "NH Efetivo: `4` -> 1 + 3" in field_value(embed, "Resultados Balísticos")

    async def test_critical_success_uses_critical_damage(
        self, cog, interaction, character, db, monkeypatch
    ):
        patch_rng(monkeypatch, battle_module, dice_sequence([1, 1, 1], [5]))

        await invoke_ranged(cog, interaction, nh=10)

        assert followup_embed(interaction).title == "SUCESSO DECISIVO!"
        assert attack_row(db) == (3, 7, 0, 0, 4)

    async def test_critical_failure_reports_table_and_saves_nothing(
        self, cog, interaction, character, db, monkeypatch
    ):
        patch_rng(monkeypatch, battle_module, dice_sequence([6, 6, 6], [2, 2, 2]))

        await invoke_ranged(cog, interaction, nh=10)

        embed = followup_embed(interaction)
        assert embed.title == "FALHA CRÍTICA!"
        assert (
            field_value(embed, "Tabela de Falhas Críticas (Armas à Distância)")
            == "Dados: `[2, 2, 2] = 6`"
        )
        assert attack_row(db) is None

    async def test_missing_character_sends_error_message(
        self, cog, interaction, monkeypatch
    ):
        # ranged_atk guards get_character_strength with a ValueError handler,
        # sending a pt-BR error message through the followup after the defer.
        patch_rng(monkeypatch, battle_module, [1, 1, 1])

        await invoke_ranged(cog, interaction, nh=10)

        assert interaction.response.deferred
        message = interaction.followup.sent[0]["args"][0]
        assert "Erro de processamento" in message
        assert "owner_id 1" in message


class TestDefenseCommand:
    async def test_without_saved_attack_reports_and_returns(
        self, cog, interaction, character, monkeypatch
    ):
        patch_rng(monkeypatch, battle_module, [1])

        await invoke_def(cog, interaction, nh=10, rd=0, receive_atk=WAIVED)

        assert_deferred(interaction)
        sent = interaction.followup.sent[0]
        assert sent["args"][0] == (
            "Nenhum ataque registrado para defender. "
            "Realize um ataque antes de usar este comando."
        )
        assert "embed" not in sent["kwargs"]

    async def test_waived_applies_raw_damage(
        self, cog, interaction, character, db, monkeypatch
    ):
        insert_attack(db, raw_damage=10, dmg_type=4, hit_location=0, critical_damage=99)
        patch_rng(monkeypatch, battle_module, [1])

        await invoke_def(cog, interaction, nh=10, rd=0, receive_atk=WAIVED)

        embed = followup_embed(interaction)
        assert embed.title == "DEFESA ABANDONADA"
        assert embed.description == "Você optou por não esboçar qualquer reação defensiva."
        impact = field_value(embed, "Resolução de Impacto")
        assert "Dano Base Oponente: `10`" in impact
        assert "10 x 1.0 = 10 PV" in impact
        assert character_pv(db) == 0

    async def test_opponent_critical_applies_critical_damage(
        self, cog, interaction, character, db, monkeypatch
    ):
        insert_attack(db, raw_damage=10, dmg_type=4, hit_location=0, critical_damage=99)
        patch_rng(monkeypatch, battle_module, [1])

        await invoke_def(cog, interaction, nh=10, rd=0, receive_atk=OPPONENT_CRITICAL)

        embed = followup_embed(interaction)
        assert embed.title == "ATAQUE CRÍTICO RECEBIDO"
        assert "A defesa é matematicamente impossível" in embed.description
        assert "Dano Base Oponente: `99`" in field_value(embed, "Resolução de Impacto")
        assert character_pv(db) == -89

    async def test_successful_defense_preserves_hp(
        self, cog, interaction, character, db, monkeypatch
    ):
        insert_attack(db, raw_damage=30, dmg_type=4, hit_location=0)
        patch_rng(monkeypatch, battle_module, [1, 2, 2])

        await invoke_def(cog, interaction, nh=10, rd=0)

        embed = followup_embed(interaction)
        assert embed.title == "SUCESSO!"
        vitals = field_value(embed, "Métricas Vitais do Personagem")
        assert "Integridade totalmente preservada" in vitals
        assert "PV permanece estável em `10`" in vitals
        assert character_pv(db) == 10

    async def test_decisive_success_rolls_opponent_critical_table(
        self, cog, interaction, character, db, monkeypatch
    ):
        insert_attack(db, raw_damage=30, dmg_type=4, hit_location=0)
        patch_rng(monkeypatch, battle_module, dice_sequence([1, 1, 1], [2, 2, 2]))

        await invoke_def(cog, interaction, nh=10, rd=0)

        embed = followup_embed(interaction)
        assert embed.title == "SUCESSO DECISIVO!"
        assert (
            field_value(embed, "Tabela de Falhas Críticas (Oponente)")
            == "Dados: `[2, 2, 2] = 6`"
        )
        assert character_pv(db) == 10

    async def test_normal_failure_applies_raw_damage(
        self, cog, interaction, character, db, monkeypatch
    ):
        insert_attack(db, raw_damage=4, dmg_type=4, hit_location=0, critical_damage=50)
        patch_rng(monkeypatch, battle_module, [5, 5, 5])

        await invoke_def(cog, interaction, nh=10, rd=0)

        embed = followup_embed(interaction)
        assert embed.title == "FALHA!"
        assert "Dano Base Oponente: `4`" in field_value(embed, "Resolução de Impacto")
        assert character_pv(db) == 6

    async def test_critical_failure_applies_critical_damage(
        self, cog, interaction, character, db, monkeypatch
    ):
        insert_attack(db, raw_damage=4, dmg_type=4, hit_location=0, critical_damage=50)
        patch_rng(monkeypatch, battle_module, [6, 6, 6])

        await invoke_def(cog, interaction, nh=10, rd=0)

        embed = followup_embed(interaction)
        assert embed.title == "FALHA CRÍTICA!"
        assert "Dano Base Oponente: `50`" in field_value(embed, "Resolução de Impacto")
        assert character_pv(db) == -40

    async def test_failure_by_ten_margin_is_critical(
        self, cog, interaction, character, db, monkeypatch
    ):
        insert_attack(db, raw_damage=4, dmg_type=4, hit_location=0, critical_damage=50)
        patch_rng(monkeypatch, battle_module, [4, 4, 4])

        await invoke_def(cog, interaction, nh=1, rd=0)

        embed = followup_embed(interaction)
        assert embed.title == "FALHA CRÍTICA!"
        assert "Dano Base Oponente: `50`" in field_value(embed, "Resolução de Impacto")

    async def test_feint_penalty_reduces_effective_nh(
        self, cog, interaction, character, db, monkeypatch
    ):
        insert_attack(db, raw_damage=30, dmg_type=4, hit_location=0, feint=5)
        patch_rng(monkeypatch, battle_module, [2, 2, 2])

        await invoke_def(cog, interaction, nh=10, rd=0)

        embed = followup_embed(interaction)
        assert embed.title == "FALHA!"
        assert (
            "NH Efetivo: `10 - 5(finta) = 5`"
            in field_value(embed, "Rolagem de Defesa")
        )
        assert character_pv(db) == -20

    async def test_rd_absorbs_all_damage(
        self, cog, interaction, character, db, monkeypatch
    ):
        insert_attack(db, raw_damage=5, dmg_type=4, hit_location=0)
        patch_rng(monkeypatch, battle_module, [1])

        await invoke_def(cog, interaction, nh=10, rd=8, receive_atk=WAIVED)

        impact = field_value(followup_embed(interaction), "Resolução de Impacto")
        assert "Dano Penetrante: `5 - 8(RD) = 0`" in impact
        assert character_pv(db) == 10

    async def test_negative_rd_increases_penetrating_damage(
        self, cog, interaction, character, db, monkeypatch
    ):
        insert_attack(db, raw_damage=5, dmg_type=4, hit_location=0)
        patch_rng(monkeypatch, battle_module, [1])

        await invoke_def(cog, interaction, nh=10, rd=-3, receive_atk=WAIVED)

        impact = field_value(followup_embed(interaction), "Resolução de Impacto")
        assert "Dano Penetrante: `5 - -3(RD) = 8`" in impact
        assert character_pv(db) == 2

    async def test_skull_grants_two_extra_rd(
        self, cog, interaction, character, db, monkeypatch
    ):
        insert_attack(db, raw_damage=10, dmg_type=4, hit_location=2)
        patch_rng(monkeypatch, battle_module, [1])

        await invoke_def(cog, interaction, nh=10, rd=3, receive_atk=WAIVED)

        impact = field_value(followup_embed(interaction), "Resolução de Impacto")
        assert "Dano Penetrante: `10 - 5(RD) = 5`" in impact
        # 5 penetrating x 4.0 (skull) = 20 injury.
        assert character_pv(db) == -10

    @pytest.mark.parametrize(
        "dmg_type, hit_location, raw_damage, penetrating, multiplier, injury",
        [
            (5, 0, 10, 10, 1.5, 15),  # torso cutting
            (7, 1, 4, 4, 3.0, 12),  # vitals piercing
            (4, 3, 2, 2, 4.0, 8),  # eye
            (5, 5, 3, 3, 2.0, 6),  # neck cutting
            (4, 0, 7, 7, 1.0, 7),  # torso crushing
            (3, 4, 4, 4, 1.5, 6),  # face corrosion
            (3, 5, 4, 4, 1.5, 6),  # neck corrosion
            (4, 5, 4, 4, 1.5, 6),  # neck crushing
            (4, 2, 4, 2, 4.0, 8),  # skull crushing (native +2 RD)
            (7, 2, 4, 2, 4.0, 8),  # skull piercing at a normal target
        ],
        ids=[
            "torso-cutting",
            "vitals-piercing",
            "eye",
            "neck-cutting",
            "torso-crushing",
            "face-corrosion",
            "neck-corrosion",
            "neck-crushing",
            "skull-crushing",
            "skull-piercing",
        ],
    )
    async def test_normal_morphology_multipliers(
        self,
        cog,
        interaction,
        character,
        db,
        monkeypatch,
        dmg_type,
        hit_location,
        raw_damage,
        penetrating,
        multiplier,
        injury,
    ):
        insert_attack(
            db, raw_damage=raw_damage, dmg_type=dmg_type, hit_location=hit_location
        )
        patch_rng(monkeypatch, battle_module, [1])

        await invoke_def(cog, interaction, nh=10, rd=0, receive_atk=WAIVED)

        impact = field_value(followup_embed(interaction), "Resolução de Impacto")
        assert f"{penetrating} x {multiplier:.1f} = {injury} PV" in impact
        assert character_pv(db) == 10 - injury

    @pytest.mark.parametrize(
        "dmg_type, raw_damage, multiplier, injury",
        [
            (7, 6, 1.0, 6),  # Unliving: impaling downgraded to 1.0
            (11, 6, 1.0, 6),  # Unliving: Pi++ downgraded to 1.0
            (10, 6, 0.5, 3),  # Unliving: Pi+ downgraded to 0.5
            (9, 6, 1.0 / 3.0, 2),  # Unliving: Pi downgraded to 1/3
            (8, 6, 0.2, 1),  # Unliving: Pi- downgraded to 0.2
        ],
        ids=["unliving-impaling", "unliving-pi-plus-plus", "unliving-pi-plus", "unliving-pi", "unliving-pi-minus"],
    )
    async def test_unliving_morphology_multipliers(
        self,
        cog,
        interaction,
        character,
        db,
        monkeypatch,
        dmg_type,
        raw_damage,
        multiplier,
        injury,
    ):
        set_body_type(db, 3)
        insert_attack(db, raw_damage=raw_damage, dmg_type=dmg_type, hit_location=0)
        patch_rng(monkeypatch, battle_module, [1])

        await invoke_def(cog, interaction, nh=10, rd=0, receive_atk=WAIVED)

        impact = field_value(followup_embed(interaction), "Resolução de Impacto")
        assert f"{raw_damage} x {multiplier:.1f} = {injury} PV" in impact
        assert character_pv(db) == 10 - injury

    @pytest.mark.parametrize(
        "dmg_type, hit_location, raw_damage, penetrating, multiplier, injury",
        [
            (7, 0, 6, 6, 0.5, 3),  # homogeneous torso impaling
            (10, 0, 6, 6, 1.0 / 3.0, 2),  # homogeneous PI+
            (9, 0, 6, 6, 0.2, 1),  # homogeneous PI
            (8, 0, 4, 4, 0.1, 1),  # homogeneous PI- hits the minimum injury floor
            (5, 2, 4, 2, 1.5, 3),  # homogeneous skull cutting keeps the base table
            (7, 2, 6, 4, 0.5, 2),  # homogeneous skull piercing override
        ],
        ids=[
            "homogeneous-impaling",
            "homogeneous-pi-plus",
            "homogeneous-pi",
            "homogeneous-pi-minus-floor",
            "homogeneous-skull-cutting",
            "homogeneous-skull-piercing",
        ],
    )
    async def test_homogeneous_morphology_multipliers(
        self,
        cog,
        interaction,
        character,
        db,
        monkeypatch,
        dmg_type,
        hit_location,
        raw_damage,
        penetrating,
        multiplier,
        injury,
    ):
        set_body_type(db, 2)
        insert_attack(
            db, raw_damage=raw_damage, dmg_type=dmg_type, hit_location=hit_location
        )
        patch_rng(monkeypatch, battle_module, [1])

        await invoke_def(cog, interaction, nh=10, rd=0, receive_atk=WAIVED)

        impact = field_value(followup_embed(interaction), "Resolução de Impacto")
        assert f"{penetrating} x {multiplier:.1f} = {injury} PV" in impact
        assert character_pv(db) == 10 - injury

    @pytest.mark.parametrize(
        "dmg_type, raw_damage, multiplier, injury",
        [
            (7, 10, 2.0, 1),  # Diffuse caps piercing at 1
            (8, 4, 0.5, 1),  # Diffuse caps Pi- at 1
            (4, 10, 1.0, 2),  # Diffuse caps non-piercing at 2
        ],
        ids=["diffuse-impaling-cap", "diffuse-pi-minus-cap", "diffuse-crushing-cap"],
    )
    async def test_diffuse_morphology_injury_caps(
        self,
        cog,
        interaction,
        character,
        db,
        monkeypatch,
        dmg_type,
        raw_damage,
        multiplier,
        injury,
    ):
        set_body_type(db, 1)
        insert_attack(db, raw_damage=raw_damage, dmg_type=dmg_type, hit_location=0)
        patch_rng(monkeypatch, battle_module, [1])

        await invoke_def(cog, interaction, nh=10, rd=0, receive_atk=WAIVED)

        impact = field_value(followup_embed(interaction), "Resolução de Impacto")
        assert f"{raw_damage} x {multiplier:.1f} = {injury} PV" in impact
        assert character_pv(db) == 10 - injury

    async def test_minimum_injury_is_one_when_penetration_is_positive(
        self, cog, interaction, character, db, monkeypatch
    ):
        set_body_type(db, 2)
        insert_attack(db, raw_damage=4, dmg_type=8, hit_location=0)
        patch_rng(monkeypatch, battle_module, [1])

        await invoke_def(cog, interaction, nh=10, rd=3, receive_atk=WAIVED)

        impact = field_value(followup_embed(interaction), "Resolução de Impacto")
        assert "Dano Penetrante: `4 - 3(RD) = 1`" in impact
        # 1 penetrating x 0.1 = 0.1 injury, raised to the 1 PV floor.
        assert "1 x 0.1 = 1 PV" in impact
        assert character_pv(db) == 9

    async def test_character_with_negative_hp_is_accepted(
        self, cog, interaction, character, db, monkeypatch
    ):
        db.execute("UPDATE characters SET current_pv = -5 WHERE character_id = 1")
        db.commit()
        insert_attack(db, raw_damage=3, dmg_type=4, hit_location=0)
        patch_rng(monkeypatch, battle_module, [1])

        await invoke_def(cog, interaction, nh=10, rd=0, receive_atk=WAIVED)

        embed = followup_embed(interaction)
        assert "PV Anterior: `-5` -> PV Atual: `-8`" in field_value(
            embed, "Métricas Vitais do Personagem"
        )
        assert character_pv(db) == -8

    @pytest.mark.parametrize(
        "hit_location, raw_damage, final_injury, label",
        [
            (7, 10, 5, "BRAÇO AMPUTADO"),  # limb threshold: 2 x (ST/2) = 10
            (7, 5, 5, "BRAÇO INCAPACITADO"),  # limb threshold: ST/2 = 5
            (8, 12, 5, "PERNA AMPUTADO"),
            (9, 4, 3, "MÃO INCAPACITADO"),  # hand threshold: ST/3 = 3.33
            (9, 7, 3, "MÃO AMPUTADO"),
            (10, 4, 3, "PÉ INCAPACITADO"),
        ],
        ids=[
            "arm-amputation",
            "arm-incapacitation",
            "leg-amputation",
            "hand-incapacitation",
            "hand-amputation",
            "foot-incapacitation",
        ],
    )
    async def test_amputation_and_incapacitation(
        self,
        cog,
        interaction,
        character,
        db,
        monkeypatch,
        hit_location,
        raw_damage,
        final_injury,
        label,
    ):
        insert_attack(db, raw_damage=raw_damage, dmg_type=4, hit_location=hit_location)
        patch_rng(monkeypatch, battle_module, [1])

        await invoke_def(cog, interaction, nh=10, rd=0, receive_atk=WAIVED)

        impact = field_value(followup_embed(interaction), "Resolução de Impacto")
        assert f"[AVISO] **{label}!**" in impact
        assert character_pv(db) == 10 - final_injury

    async def test_homogeneous_targets_skip_crippling_rules(
        self, cog, interaction, character, db, monkeypatch
    ):
        set_body_type(db, 2)
        insert_attack(db, raw_damage=50, dmg_type=4, hit_location=8)
        patch_rng(monkeypatch, battle_module, [1])

        await invoke_def(cog, interaction, nh=10, rd=0, receive_atk=WAIVED)

        impact = field_value(followup_embed(interaction), "Resolução de Impacto")
        assert "[AVISO]" not in impact
        assert character_pv(db) == -40


class TestFeintCommand:
    async def test_win_by_margin_stores_margin_difference(
        self, cog, interaction, character, patched_sqlite, monkeypatch
    ):
        insert_hdm(patched_sqlite, 1, 0)
        # Player rolls 5 (margin 5), opponent rolls 6 (margin 4): wins by 1.
        patch_rng(monkeypatch, dice_mechanics, dice_sequence([1, 2, 2], [2, 2, 2]))

        await Battle.fnt.callback(cog, interaction, 10, 10)

        assert_deferred(interaction)
        embed = followup_embed(interaction)
        assert embed.title == "A FINTA FOI UM SUCESSO!"
        assert (
            field_value(embed, "Margem de Vitória") == "`5 - 4 = 1`"
        )
        assert get_player_condition(cog.db_connection, 1, "feint") == 1
        stored = patched_sqlite.execute(
            "SELECT feint FROM next_turn_conditions WHERE character_id = 1"
        ).fetchone()
        assert stored == (1,)

    async def test_loss_by_margin_stores_nothing(
        self, cog, interaction, character, patched_sqlite, monkeypatch
    ):
        insert_hdm(patched_sqlite, 1, 1)
        # Player rolls 6 (margin 4), opponent rolls 5 (margin 5): loses by 1.
        patch_rng(monkeypatch, dice_mechanics, dice_sequence([2, 2, 2], [1, 2, 2]))

        await Battle.fnt.callback(cog, interaction, 10, 10)

        embed = followup_embed(interaction)
        assert embed.title == "A FINTA FOI UM FRACASSO"
        assert embed.description == (
            "O oponente previu seus movimentos e superou sua margem."
        )
        assert get_player_condition(cog.db_connection, 1, "feint") == 0

    async def test_tie_stores_nothing(
        self, cog, interaction, character, monkeypatch
    ):
        # No deterministic fate: quick_dispute falls back to its own randint.
        patch_rng(monkeypatch, test_mechanics, dice_sequence([2, 2, 2], [2, 2, 2]))

        await Battle.fnt.callback(cog, interaction, 10, 10)

        embed = followup_embed(interaction)
        assert embed.title == "EMPATE!"
        assert embed.description == (
            "A finta não surtiu efeito devido ao equilíbrio de margens."
        )
        assert get_player_condition(cog.db_connection, 1, "feint") == 0

    async def test_fate_two_pass_fail_stores_player_margin(
        self, cog, interaction, character, patched_sqlite, monkeypatch
    ):
        insert_hdm(patched_sqlite, 1, 2)
        # Player rolls 5 (success, margin 5); opponent rolls 11 (failure).
        patch_rng(monkeypatch, dice_mechanics, dice_sequence([1, 2, 2], [4, 4, 3]))

        await Battle.fnt.callback(cog, interaction, 10, 10)

        embed = followup_embed(interaction)
        assert embed.title == "A FINTA FOI UM SUCESSO"
        assert "Sua margem de sucesso será usada como penalidade" in embed.description
        assert get_player_condition(cog.db_connection, 1, "feint") == 5

    async def test_fate_three_player_failure_stores_nothing(
        self, cog, interaction, character, patched_sqlite, monkeypatch
    ):
        insert_hdm(patched_sqlite, 1, 3)
        # Player rolls 11 (failure); opponent rolls 5 (success).
        patch_rng(monkeypatch, dice_mechanics, dice_sequence([4, 4, 3], [1, 2, 2]))

        await Battle.fnt.callback(cog, interaction, 10, 10)

        embed = followup_embed(interaction)
        assert embed.title == "A FINTA FOI UM FRACASSO"
        assert embed.description == "Você fracassou no teste de finta."
        assert get_player_condition(cog.db_connection, 1, "feint") == 0


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
