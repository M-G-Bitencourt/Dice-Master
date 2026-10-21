"""Command-level tests for cogs/admin.py.

Commands are driven through the raw ``discord.app_commands`` callbacks against
the shared in-memory database injected by the ``patched_sqlite`` fixture. The
production ``data/database.db`` is never opened and no Discord gateway or
network connection is involved.
"""

from __future__ import annotations

import discord
import pytest
from discord import app_commands

from cogs.admin import Admin
from helpers import FakeBot, FakeInteraction, FakeUser, insert_character
from utils.gm_directives import gm_shield_store

HP = app_commands.Choice(name="pv", value="hp")
FP = app_commands.Choice(name="pf", value="fp")
ER = app_commands.Choice(name="er", value="er")

AIM = app_commands.Choice(name="Apontar", value="aim")
EVALUATE = app_commands.Choice(name="Avaliar", value="evaluate")
SHOCK = app_commands.Choice(name="Choque", value="shock")
FEINT = app_commands.Choice(name="Finta", value="feint")


class BareBot:
    """Minimal bot stub that deliberately lacks the ``config`` attribute."""


class NoneConfigBot:
    """Bot stub whose ``config`` attribute exists but is None."""


NoneConfigBot.config = None


@pytest.fixture
def cog(make_cog):
    return make_cog(Admin)


@pytest.fixture
def player():
    """Discord member stub bound to the default character owner id 1."""
    return FakeUser(user_id=1)


def followup_embed(interaction, index: int = 0):
    return interaction.followup.sent[index]["kwargs"]["embed"]


def response_embed(interaction, index: int = 0):
    return interaction.response.messages[index]["kwargs"]["embed"]


def field_value(embed, name: str) -> str:
    for field in embed.fields:
        if field.name == name:
            return field.value
    raise AssertionError(f"embed field {name!r} not found")


def assert_deferred(interaction, ephemeral: bool) -> None:
    assert interaction.response.deferred, "response.defer was not awaited"
    assert interaction.response.deferred[0]["kwargs"]["ephemeral"] is ephemeral


def assert_not_deferred(interaction) -> None:
    assert interaction.response.deferred == []


class TestAdminInit:
    def test_bot_without_config_raises_runtime_error(self, patched_sqlite):
        with pytest.raises(RuntimeError, match="bot.config"):
            Admin(BareBot())

    def test_missing_bot_section_raises_value_error(self, patched_sqlite):
        with pytest.raises(ValueError, match="Configuration Malformation"):
            Admin(FakeBot({}))

    def test_missing_dm_id_raises_value_error(self, patched_sqlite):
        with pytest.raises(ValueError, match="Configuration Malformation"):
            Admin(FakeBot({"BOT": {}}))

    def test_non_numeric_dm_id_raises_value_error(self, patched_sqlite):
        with pytest.raises(ValueError, match="Configuration Malformation"):
            Admin(FakeBot({"BOT": {"DM_ID": "not-a-number"}}))

    def test_none_config_is_not_translated_to_value_error(self, patched_sqlite):
        # Pinned current behavior: only AttributeError/KeyError/ValueError are
        # translated; a None config surfaces as a raw TypeError.
        with pytest.raises(TypeError):
            Admin(NoneConfigBot())

    def test_valid_dm_id_is_coerced_to_integer(self, patched_sqlite):
        cog = Admin(FakeBot({"BOT": {"DM_ID": "123"}}))
        assert cog.designated_dm_id == 123


class TestHdmCommand:
    async def test_non_dm_gets_denial_and_no_pending_directive(
        self, cog, patched_sqlite
    ):
        interaction = FakeInteraction(user_id=1)

        await Admin.deterministic_mock_command.callback(
            cog,
            interaction,
            FakeUser(user_id=42),
            app_commands.Choice(name="Sucesso", value=0),
        )

        assert_not_deferred(interaction)
        message = interaction.response.messages[0]
        assert message["args"][0] == (
            "Erro. Você não tem permissão para usar os comandos de Debug"
        )
        assert message["kwargs"]["ephemeral"] is True
        assert gm_shield_store.active_for(character_id=None, player_id=42) == []
        assert patched_sqlite.execute("SELECT COUNT(*) FROM hdm").fetchone() == (0,)

    async def test_dm_sets_pending_directive_and_replies_ephemerally(
        self, cog, patched_sqlite
    ):
        interaction = FakeInteraction(user_id=999)

        await Admin.deterministic_mock_command.callback(
            cog,
            interaction,
            FakeUser(user_id=42),
            app_commands.Choice(name="Falha Crítica", value=3),
        )

        directive = gm_shield_store.consume(
            character_id=None,
            player_id=42,
            roll_kind="generic",
        )
        assert directive is not None
        assert directive.outcome == "critical_failure"
        assert patched_sqlite.execute("SELECT COUNT(*) FROM hdm").fetchone() == (0,)
        message = interaction.response.messages[0]
        assert message["kwargs"]["content"] == (
            "A próxima rolagem de <@42> será Falha Crítica"
        )
        assert message["kwargs"]["ephemeral"] is True

    async def test_dm_directive_overwrites_the_previous_one(
        self, cog, patched_sqlite
    ):
        gm_shield_store.set(
            player_id=42, roll_kind="generic", outcome="success"
        )
        interaction = FakeInteraction(user_id=999)

        await Admin.deterministic_mock_command.callback(
            cog,
            interaction,
            FakeUser(user_id=42),
            app_commands.Choice(name="Sucesso Decisivo", value=2),
        )

        directive = gm_shield_store.consume(
            character_id=None,
            player_id=42,
            roll_kind="generic",
        )
        assert directive is not None
        assert directive.outcome == "critical_success"

    async def test_pending_directive_is_consumed_exactly_once(
        self, cog, patched_sqlite
    ):
        interaction = FakeInteraction(user_id=999)

        await Admin.deterministic_mock_command.callback(
            cog,
            interaction,
            FakeUser(user_id=42),
            app_commands.Choice(name="Falha Crítica", value=3),
        )

        assert gm_shield_store.consume(
            character_id=None,
            player_id=42,
            roll_kind="generic",
        ) is not None
        assert gm_shield_store.consume(
            character_id=None,
            player_id=42,
            roll_kind="generic",
        ) is None


class TestManageCharacterResourcePool:
    @pytest.mark.parametrize(
        "resource_choice, column, label, initial",
        [
            (HP, "current_pv", "PV", 10),
            (FP, "current_pf", "PF", 8),
            (ER, "current_er", "ER", 1),
        ],
        ids=["pv", "pf", "er"],
    )
    async def test_positive_delta_updates_target_resource(
        self, cog, interaction, player, db, resource_choice, column, label, initial
    ):
        insert_character(
            db,
            owner_id=1,
            current_pv=10,
            current_pf=8,
            current_er=1,
            energy_reserve=4,
        )

        await Admin.manage_character_resource_pool.callback(
            cog, interaction, player, resource_choice, 2
        )

        assert_deferred(interaction, ephemeral=False)
        stored = db.execute(
            f"SELECT {column} FROM characters WHERE character_id = 1"
        ).fetchone()
        assert stored == (initial + 2,)

        balance = field_value(followup_embed(interaction), "Balanço da Mutação")
        assert f"Recurso Afetado: `{label}`" in balance
        assert "Modificador Aplicado: `+2`" in balance
        assert f"Transição de Estado: `{initial}` -> `{initial + 2}`" in balance

    async def test_negative_delta_reports_signed_modifier_and_state(
        self, cog, interaction, player, db
    ):
        insert_character(db, owner_id=1, name="Alvo", current_pf=10)

        await Admin.manage_character_resource_pool.callback(
            cog, interaction, player, FP, -4
        )

        assert_deferred(interaction, ephemeral=False)
        stored = db.execute(
            "SELECT current_pf FROM characters WHERE owner_id = 1"
        ).fetchone()
        assert stored == (6,)

        embed = followup_embed(interaction)
        balance = field_value(embed, "Balanço da Mutação")
        assert "Modificador Aplicado: `-4`" in balance
        assert "Transição de Estado: `10` -> `6`" in balance
        assert "6/10" in field_value(embed, "Estado Atual")

    async def test_state_bar_reports_structural_ceilings(
        self, cog, interaction, player, db
    ):
        insert_character(
            db,
            owner_id=1,
            st=15,
            additional_max_pv=5,
            ht=12,
            additional_max_pf=3,
            energy_reserve=6,
            current_pv=10,
            current_pf=8,
            current_er=2,
        )

        await Admin.manage_character_resource_pool.callback(
            cog, interaction, player, HP, 2
        )

        state = field_value(followup_embed(interaction), "Estado Atual")
        assert "12/20" in state  # PV: (10 + 2) over st + additional_max_pv
        assert "8/15" in state  # PF: ht + additional_max_pf
        assert "2/6" in state  # ER: energy_reserve

    async def test_value_above_ceiling_is_not_clamped(
        self, cog, interaction, player, db
    ):
        # Pinned current behavior: set_character_resource receives the raw sum,
        # so the ceiling is only a display reference.
        insert_character(db, owner_id=1, current_pv=10)

        await Admin.manage_character_resource_pool.callback(
            cog, interaction, player, HP, 100
        )

        stored = db.execute("SELECT current_pv FROM characters").fetchone()
        assert stored == (110,)
        assert "110/10" in field_value(followup_embed(interaction), "Estado Atual")

    async def test_value_below_zero_is_not_clamped(self, cog, interaction, player, db):
        # Pinned current behavior: there is no floor at zero for subtractive deltas.
        insert_character(db, owner_id=1, current_er=0, energy_reserve=0)

        await Admin.manage_character_resource_pool.callback(
            cog, interaction, player, ER, -3
        )

        stored = db.execute("SELECT current_er FROM characters").fetchone()
        assert stored == (-3,)
        assert "-3/0" in field_value(followup_embed(interaction), "Estado Atual")

    async def test_missing_character_reports_followup_error(
        self, cog, interaction, player
    ):
        await Admin.manage_character_resource_pool.callback(
            cog, interaction, player, HP, 5
        )

        assert_deferred(interaction, ephemeral=False)
        sent = interaction.followup.sent[0]
        assert "embed" not in sent["kwargs"]
        assert "ephemeral" not in sent["kwargs"]
        assert "Erro de processamento" in sent["args"][0]
        assert "owner_id 1" in sent["args"][0]


class TestRestoreCharacterResources:
    async def test_restores_all_resources_to_structural_ceilings(
        self, cog, interaction, player, db
    ):
        insert_character(
            db,
            owner_id=1,
            name="Ferido",
            st=12,
            additional_max_pv=3,
            ht=11,
            additional_max_pf=2,
            energy_reserve=6,
            current_pv=1,
            current_pf=2,
            current_er=0,
        )

        await Admin.restore_character_resources.callback(cog, interaction, player)

        assert_deferred(interaction, ephemeral=False)
        stored = db.execute(
            "SELECT current_pv, current_pf, current_er FROM characters "
            "WHERE owner_id = 1"
        ).fetchone()
        assert stored == (15, 13, 6)

        embed = followup_embed(interaction)
        assert embed.title == "Restauração Estrutural Absoluta"
        assert "<@1>" in embed.description

        balance = field_value(embed, "Balanço da Mutação")
        assert "**PV (Hit Points):** `1` -> `15`" in balance
        assert "**PF (Fatigue Points):** `2` -> `13`" in balance
        assert "**ER (Energy Reserve):** `0` -> `6`" in balance

        state = field_value(embed, "Estado Restaurado")
        assert "15/15" in state
        assert "13/13" in state
        assert "6/6" in state

    async def test_missing_character_reports_followup_error(
        self, cog, interaction, player
    ):
        await Admin.restore_character_resources.callback(cog, interaction, player)

        assert_deferred(interaction, ephemeral=False)
        sent = interaction.followup.sent[0]
        assert "Erro de processamento" in sent["args"][0]
        assert "owner_id 1" in sent["args"][0]
        assert "embed" not in sent["kwargs"]


class TestSwitchCharacter:
    async def test_transfers_ownership_and_nulls_the_previous_owner(
        self, cog, interaction, db
    ):
        previous = insert_character(db, owner_id=1, name="Antigo")
        target = insert_character(db, owner_id=None, name="Novo")

        await Admin.switch_character.callback(cog, interaction, str(target))

        assert_not_deferred(interaction)
        owners = dict(
            db.execute("SELECT character_id, owner_id FROM characters").fetchall()
        )
        assert owners[previous] is None
        assert owners[target] == 1

        embed = response_embed(interaction)
        assert embed.title == "Sincronização de Avatar Concluída"
        assert embed.description == "<@1> agora está jogando com **Novo**."

    async def test_unknown_target_reports_entity_but_still_clears_owner(
        self, cog, interaction, db
    ):
        # Pinned current behavior: the previous owner is nullified before the
        # target existence check, so a bogus id leaves the player unassigned.
        previous = insert_character(db, owner_id=1, name="Antigo")

        await Admin.switch_character.callback(cog, interaction, "999")

        owner = db.execute(
            "SELECT owner_id FROM characters WHERE character_id = ?", (previous,)
        ).fetchone()
        assert owner == (None,)
        assert "**Entidade Desconhecida**" in response_embed(interaction).description

    async def test_invalid_identifier_is_rejected_without_mutation(
        self, cog, interaction, db
    ):
        character_id = insert_character(db, owner_id=1, name="Antigo")

        await Admin.switch_character.callback(cog, interaction, "not-a-number")

        message = interaction.response.messages[0]
        assert message["args"][0] == (
            "Erro de processamento: O identificador do personagem é inválido."
        )
        assert message["kwargs"]["ephemeral"] is True
        owner = db.execute(
            "SELECT owner_id FROM characters WHERE character_id = ?", (character_id,)
        ).fetchone()
        assert owner == (1,)


class TestManageXp:
    async def test_adds_points_and_touches_only_current_points(
        self, cog, interaction, db
    ):
        insert_character(
            db,
            owner_id=1,
            name="Alvo XP",
            current_points=10,
            current_pv=7,
            current_pf=6,
            current_er=2,
        )

        await Admin.manage_xp.callback(cog, interaction, "1", 5)

        assert_deferred(interaction, ephemeral=True)
        stored = db.execute(
            "SELECT current_points, current_pv, current_pf, current_er "
            "FROM characters WHERE character_id = 1"
        ).fetchone()
        assert stored == (15, 7, 6, 2)

        embed = followup_embed(interaction)
        assert embed.title == "AJUSTE DE PONTOS (XP): Alvo XP"
        assert embed.color == discord.Color.green()
        operation = field_value(embed, "Operação Homologada")
        assert "Tipo: `Concessão (+XP)`" in operation
        assert "Ajuste: `+5 pts`" in operation
        assert field_value(embed, "Demonstrativo de Pontos") == (
            "Anterior: `10 pts`\nAtual: `15 pts`"
        )

    async def test_subtracts_points_and_uses_red_embed(self, cog, interaction, db):
        insert_character(db, owner_id=1, name="Alvo XP", current_points=10)

        await Admin.manage_xp.callback(cog, interaction, "1", -3)

        assert_deferred(interaction, ephemeral=True)
        stored = db.execute(
            "SELECT current_points FROM characters WHERE character_id = 1"
        ).fetchone()
        assert stored == (7,)

        embed = followup_embed(interaction)
        assert embed.color == discord.Color.red()
        operation = field_value(embed, "Operação Homologada")
        assert "Tipo: `Dedução (-XP)`" in operation
        assert "Ajuste: `-3 pts`" in operation
        assert field_value(embed, "Demonstrativo de Pontos") == (
            "Anterior: `10 pts`\nAtual: `7 pts`"
        )

    async def test_null_current_points_is_treated_as_zero(self, cog, interaction, db):
        insert_character(db, owner_id=1, name="Sem Pontos", current_points=None)

        await Admin.manage_xp.callback(cog, interaction, "1", 4)

        stored = db.execute("SELECT current_points FROM characters").fetchone()
        assert stored == (4,)
        assert field_value(followup_embed(interaction), "Demonstrativo de Pontos") == (
            "Anterior: `0 pts`\nAtual: `4 pts`"
        )

    async def test_missing_character_reports_consistency_error(
        self, cog, interaction
    ):
        await Admin.manage_xp.callback(cog, interaction, "77", 5)

        assert_deferred(interaction, ephemeral=True)
        sent = interaction.followup.sent[0]
        assert sent["kwargs"]["ephemeral"] is True
        assert sent["args"][0] == (
            "[ERRO] **Erro de consistência:** Nenhuma entidade foi localizada "
            "sob o ID `77`."
        )

    async def test_invalid_identifier_reports_processing_error(self, cog, interaction):
        await Admin.manage_xp.callback(cog, interaction, "abc", 5)

        assert_deferred(interaction, ephemeral=True)
        sent = interaction.followup.sent[0]
        assert sent["kwargs"]["ephemeral"] is True
        assert sent["args"][0] == (
            "[ERRO] **Erro de processamento:** O identificador do personagem "
            "fornecido é inválido."
        )

    async def test_attaches_thumbnail_asset_when_available(
        self, cog, interaction, db
    ):
        insert_character(db, owner_id=1, name="Com Imagem", current_points=1)

        await Admin.manage_xp.callback(cog, interaction, "1", 1)

        sent = interaction.followup.sent[0]
        assert sent["kwargs"]["file"] is not None
        assert sent["kwargs"]["embed"].thumbnail.url == "attachment://char_1.png"


class TestManageNextTurnConditions:
    @pytest.mark.parametrize(
        "condition_choice, column",
        [(AIM, "aim"), (EVALUATE, "evaluate"), (SHOCK, "shock"), (FEINT, "feint")],
        ids=["aim", "evaluate", "shock", "feint"],
    )
    async def test_inserts_each_condition_column(
        self, cog, interaction, character, db, condition_choice, column
    ):
        await Admin.manage_next_turn_conditions.callback(
            cog, interaction, "1", condition_choice, 4
        )

        assert_not_deferred(interaction)
        stored = db.execute(
            f"SELECT {column} FROM next_turn_conditions WHERE character_id = 1"
        ).fetchone()
        assert stored == (4,)

        embed = response_embed(interaction)
        assert embed.title == "Mudança do Mestre Nas Condições de Próximo Turno"
        assert "**Cobaia**" in embed.description
        assert field_value(embed, "Parâmetro Afetado") == (
            f"`{condition_choice.name.upper()}`"
        )
        assert field_value(embed, "Novo Valor Alocado") == "`4`"

    async def test_updates_existing_row_without_touching_other_columns(
        self, cog, interaction, character, db
    ):
        db.execute(
            "INSERT INTO next_turn_conditions "
            "(character_id, aim, evaluate, shock, feint) VALUES (1, 1, 2, 3, 4)"
        )
        db.commit()

        await Admin.manage_next_turn_conditions.callback(
            cog, interaction, "1", AIM, 7
        )

        stored = db.execute(
            "SELECT aim, evaluate, shock, feint FROM next_turn_conditions "
            "WHERE character_id = 1"
        ).fetchone()
        assert stored == (7, 2, 3, 4)

    async def test_missing_character_is_rejected_before_upsert(
        self, cog, interaction, db
    ):
        await Admin.manage_next_turn_conditions.callback(cog, interaction, "99", AIM, 1)

        message = interaction.response.messages[0]
        assert message["args"][0] == (
            "Erro de processamento: Personagem não encontrado."
        )
        assert message["kwargs"]["ephemeral"] is True
        # The existence guard prevented a foreign key violation and no row exists.
        assert db.execute("SELECT COUNT(*) FROM next_turn_conditions").fetchone() == (0,)

    async def test_invalid_identifier_is_rejected(self, cog, interaction, character):
        await Admin.manage_next_turn_conditions.callback(cog, interaction, "abc", AIM, 1)

        message = interaction.response.messages[0]
        assert message["args"][0] == (
            "Erro de processamento: O identificador do personagem fornecido "
            "é inválido."
        )
        assert message["kwargs"]["ephemeral"] is True


class TestClearNextTurnConditions:
    async def test_creates_zeroed_row_when_absent(self, cog, interaction, character, db):
        await Admin.clear_next_turn_conditions.callback(cog, interaction, "1")

        assert_not_deferred(interaction)
        stored = db.execute(
            "SELECT aim, evaluate, shock, feint FROM next_turn_conditions "
            "WHERE character_id = 1"
        ).fetchone()
        assert stored == (0, 0, 0, 0)

        embed = response_embed(interaction)
        assert embed.title == "Purgação de Estado Tático"
        assert "**Cobaia**" in embed.description

    async def test_zeroes_every_existing_value(self, cog, interaction, character, db):
        db.execute(
            "INSERT INTO next_turn_conditions "
            "(character_id, aim, evaluate, shock, feint) VALUES (1, 5, 4, 3, 2)"
        )
        db.commit()

        await Admin.clear_next_turn_conditions.callback(cog, interaction, "1")

        stored = db.execute(
            "SELECT aim, evaluate, shock, feint FROM next_turn_conditions "
            "WHERE character_id = 1"
        ).fetchone()
        assert stored == (0, 0, 0, 0)

    async def test_invalid_identifier_is_rejected(self, cog, interaction, character):
        await Admin.clear_next_turn_conditions.callback(cog, interaction, "abc")

        message = interaction.response.messages[0]
        assert message["args"][0] == (
            "Erro de processamento: O identificador do personagem fornecido "
            "é inválido."
        )
        assert message["kwargs"]["ephemeral"] is True

    async def test_missing_character_is_rejected_before_upsert(
        self, cog, interaction, db
    ):
        # The command validates character existence before the upsert, returning
        # a friendly pt-BR error instead of leaking the foreign key failure.
        await Admin.clear_next_turn_conditions.callback(cog, interaction, "99")

        message = interaction.response.messages[0]
        assert message["args"][0] == "Erro de processamento: Personagem não encontrado."
        assert message["kwargs"]["ephemeral"] is True
        assert db.execute("SELECT COUNT(*) FROM next_turn_conditions").fetchone() == (0,)


class TestViewNextTurnConditions:
    async def test_character_without_conditions_row_defaults_to_zero(
        self, cog, interaction, character
    ):
        await Admin.view_next_turn_conditions.callback(cog, interaction, "1")

        assert_not_deferred(interaction)
        embed = response_embed(interaction)
        assert embed.title == "Diagnóstico de Estado Tático — Cobaia"
        values = {field.name: field.value for field in embed.fields}
        assert values == {
            "Apontar (Aim)": "`0`",
            "Avaliar (Evaluate)": "`0`",
            "Choque (Shock)": "`0`",
            "Finta (Feint)": "`0`",
        }

    async def test_character_with_conditions_reports_stored_values(
        self, cog, interaction, character, db
    ):
        db.execute(
            "INSERT INTO next_turn_conditions "
            "(character_id, aim, evaluate, shock, feint) VALUES (1, 2, 3, 1, 4)"
        )
        db.commit()

        await Admin.view_next_turn_conditions.callback(cog, interaction, "1")

        values = {field.name: field.value for field in response_embed(interaction).fields}
        assert values == {
            "Apontar (Aim)": "`2`",
            "Avaliar (Evaluate)": "`3`",
            "Choque (Shock)": "`1`",
            "Finta (Feint)": "`4`",
        }

    async def test_missing_character_reports_localization_error(
        self, cog, interaction
    ):
        await Admin.view_next_turn_conditions.callback(cog, interaction, "99")

        message = interaction.response.messages[0]
        assert message["args"][0] == (
            "Erro de processamento: A entidade especificada não foi localizada "
            "na matriz fundacional."
        )
        assert message["kwargs"]["ephemeral"] is True

    async def test_invalid_identifier_is_rejected(self, cog, interaction):
        await Admin.view_next_turn_conditions.callback(cog, interaction, "abc")

        message = interaction.response.messages[0]
        assert message["args"][0] == (
            "Erro de processamento: O identificador do personagem fornecido "
            "é inválido."
        )
        assert message["kwargs"]["ephemeral"] is True


class TestCharacterAutocomplete:
    async def test_matches_substring_and_returns_string_ids(self, cog, interaction, db):
        alice = insert_character(db, owner_id=None, name="Alice")
        super_alice = insert_character(db, owner_id=None, name="Super Alice")
        insert_character(db, owner_id=None, name="Bob")

        result = await Admin.character_autocomplete(cog, interaction, "Ali")

        # The SQL wildcard wraps both sides (%current%), so the match is a
        # substring match rather than a strict prefix match.
        assert {choice.name for choice in result} == {"Alice", "Super Alice"}
        assert {choice.value for choice in result} == {str(alice), str(super_alice)}

    async def test_limits_results_to_twenty_five(self, cog, interaction, db):
        for index in range(30):
            insert_character(db, owner_id=None, name=f"Heroi {index:02d}")

        result = await Admin.character_autocomplete(cog, interaction, "Heroi")

        assert len(result) == 25
        assert all(choice.name.startswith("Heroi") for choice in result)

    async def test_returns_empty_list_when_nothing_matches(self, cog, interaction, db):
        insert_character(db, owner_id=None, name="Alice")

        result = await Admin.character_autocomplete(cog, interaction, "Zzz")

        assert result == []
