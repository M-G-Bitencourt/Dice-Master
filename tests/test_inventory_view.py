"""View and command tests for cogs/inventory.py.

InventoryView is exercised directly with hand-built page dicts; the slash
commands run through the raw discord.app_commands callbacks against the shared
in-memory database. Thumbnail resolution is monkeypatched so no real portrait
file is uploaded and no network client is ever involved.
"""

from __future__ import annotations

from types import SimpleNamespace

import discord
import pytest
from discord import app_commands

import cogs.inventory as inventory_module
from cogs.inventory import Inventory, InventoryView
from helpers import FakeInteraction, insert_character


def make_page(
    title: str = "Página de teste",
    description: str | None = "descrição",
    fields: list[tuple[str, str, bool]] | None = None,
    color: discord.Color | None = None,
) -> dict:
    return {
        "title": title,
        "color": color if color is not None else discord.Color.gold(),
        "description": description,
        "fields": fields if fields is not None else [("Campo", "valor", False)],
    }


def make_pages(count: int = 2) -> list[dict]:
    return [make_page(title=f"Página {index + 1}") for index in range(count)]


def button_by_label(view: discord.ui.View, label: str) -> discord.ui.Button:
    for item in view.children:
        if isinstance(item, discord.ui.Button) and item.label == label:
            return item
    raise AssertionError(f"button {label!r} not found")


def followup_embed(interaction, index: int = 0) -> discord.Embed:
    return interaction.followup.sent[index]["kwargs"]["embed"]


def field_value(embed: discord.Embed, name: str) -> str:
    for field in embed.fields:
        if field.name == name:
            return field.value
    raise AssertionError(f"embed field {name!r} not found")


@pytest.fixture
def cog(make_cog):
    return make_cog(Inventory)


@pytest.fixture
def no_thumbnail(monkeypatch):
    """Deterministic absence of the binary portrait pipeline."""
    monkeypatch.setattr(
        inventory_module, "get_character_thumbnail_by_id", lambda *args, **kwargs: (None, None)
    )


class TestInventoryViewEmbed:
    def test_clamps_title_description_field_name_and_field_value(self):
        view = InventoryView(
            pages=[
                make_page(
                    title="T" * 300,
                    description="d" * 4500,
                    fields=[("n" * 300, "v" * 2000, False)],
                )
            ],
            author_id=1,
        )

        embed = view.build_embed()

        assert len(embed.title) == 256
        assert len(embed.description) == 4000
        assert len(embed.fields[0].name) == 256
        assert len(embed.fields[0].value) == 1000

    def test_footer_reports_the_current_page(self):
        view = InventoryView(pages=make_pages(3), author_id=1)
        view.current_page = 1

        embed = view.build_embed()

        assert embed.footer.text == "Página 2 de 3"

    def test_missing_description_stays_none(self):
        view = InventoryView(
            pages=[make_page(description=None)], author_id=1
        )

        assert view.build_embed().description is None

    def test_thumbnail_is_applied_when_present(self):
        view = InventoryView(
            pages=make_pages(1),
            author_id=1,
            thumbnail_url="attachment://char_1.png",
        )

        assert view.build_embed().thumbnail.url == "attachment://char_1.png"

    def test_thumbnail_is_absent_when_not_provided(self):
        view = InventoryView(pages=make_pages(1), author_id=1)

        assert view.build_embed().thumbnail.url is None

    def test_fields_keep_their_inline_flags(self):
        view = InventoryView(
            pages=[make_page(fields=[("a", "1", True), ("b", "2", False)])],
            author_id=1,
        )

        embed = view.build_embed()

        assert embed.fields[0].inline is True
        assert embed.fields[1].inline is False


class TestInventoryViewButtons:
    def test_first_page_disables_previous_and_enables_next(self):
        view = InventoryView(pages=make_pages(2), author_id=1)

        assert button_by_label(view, "< Anterior").disabled is True
        assert button_by_label(view, "Próxima >").disabled is False

    def test_last_page_disables_next_and_enables_previous(self):
        view = InventoryView(pages=make_pages(2), author_id=1)
        view.current_page = 1
        view._sync_buttons()

        assert button_by_label(view, "< Anterior").disabled is False
        assert button_by_label(view, "Próxima >").disabled is True

    def test_single_page_disables_both_navigation_buttons(self):
        view = InventoryView(pages=make_pages(1), author_id=1)

        assert button_by_label(view, "< Anterior").disabled is True
        assert button_by_label(view, "Próxima >").disabled is True

    def test_back_button_only_exists_with_a_callback(self):
        plain = InventoryView(pages=make_pages(1), author_id=1)
        with_back = InventoryView(
            pages=make_pages(1), author_id=1, back_callback=lambda interaction: None
        )

        assert [item.label for item in plain.children] == [
            "< Anterior",
            "Próxima >",
        ]
        assert [item.label for item in with_back.children] == [
            "< Anterior",
            "Próxima >",
            "Voltar",
        ]

    async def test_next_button_advances_and_renders_the_new_page(self, interaction):
        view = InventoryView(pages=make_pages(2), author_id=1)
        interaction.user.id = 1

        await button_by_label(view, "Próxima >").callback(interaction)

        assert view.current_page == 1
        assert view.build_embed().footer.text == "Página 2 de 2"
        edit = interaction.response.edits[0]["kwargs"]
        assert edit["embed"].footer.text == "Página 2 de 2"
        assert edit["view"] is view

    async def test_previous_page_at_first_page_does_nothing(self, interaction):
        view = InventoryView(pages=make_pages(2), author_id=1)

        await view.previous_page(interaction)

        assert view.current_page == 0
        assert interaction.response.edits == []

    async def test_next_page_at_last_page_does_nothing(self, interaction):
        view = InventoryView(pages=make_pages(2), author_id=1)
        view.current_page = 1

        await view.next_page(interaction)

        assert view.current_page == 1
        assert interaction.response.edits == []

    async def test_go_back_delegates_to_the_parent_callback(self):
        calls = []

        async def back(interaction):
            calls.append(interaction)

        view = InventoryView(pages=make_pages(1), author_id=1, back_callback=back)
        interaction = FakeInteraction()

        await view.go_back(interaction)

        assert calls == [interaction]


class TestInventoryViewInteractionCheck:
    async def test_owner_is_allowed(self, interaction):
        view = InventoryView(pages=make_pages(1), author_id=1)

        assert await view.interaction_check(interaction) is True
        assert interaction.response.messages == []

    async def test_other_user_is_rejected_with_an_ephemeral_error(self):
        view = InventoryView(pages=make_pages(1), author_id=1)
        interaction = FakeInteraction(user_id=2)

        assert await view.interaction_check(interaction) is False
        message = interaction.response.messages[0]
        assert message["args"][0] == (
            "Erro: Apenas o usuário que invocou o comando pode interagir com este menu."
        )
        assert message["kwargs"]["ephemeral"] is True


class TestViewInventoryCommand:
    async def test_missing_character_replies_with_an_error(self, cog, interaction):
        assert interaction.user.id == 1

        await Inventory.view_inventory.callback(cog, interaction)

        assert interaction.response.deferred[0]["kwargs"]["ephemeral"] is True
        sent = interaction.followup.sent[0]
        assert sent["args"][0] == (
            "**Você não possui um personagem ativo atribuído à sua conta!**"
        )
        assert sent["kwargs"]["ephemeral"] is True

    async def test_renders_the_summary_embed_and_view(self, cog, interaction, character, no_thumbnail):
        await Inventory.view_inventory.callback(cog, interaction)

        assert interaction.response.deferred[0]["kwargs"]["ephemeral"] is True
        sent = interaction.followup.sent[0]["kwargs"]
        assert sent["embed"].title == "Inventário: Cobaia"
        assert sent["embed"].description == "*Nenhum equipamento ou item registrado.*"
        assert isinstance(sent["view"], InventoryView)
        assert sent["ephemeral"] is True
        assert "file" not in sent

    async def test_attaches_the_portrait_when_available(self, cog, interaction, character, monkeypatch):
        portrait = SimpleNamespace(filename="char_1.png")
        monkeypatch.setattr(
            inventory_module,
            "get_character_thumbnail_by_id",
            lambda *args, **kwargs: (portrait, "attachment://char_1.png"),
        )

        await Inventory.view_inventory.callback(cog, interaction)

        sent = interaction.followup.sent[0]["kwargs"]
        assert sent["file"] is portrait
        assert sent["embed"].thumbnail.url == "attachment://char_1.png"


class TestManageMoneyCommand:
    async def _invoke(self, cog, interaction, character_id: str, money: int):
        await Inventory.manage_money.callback(cog, interaction, character_id, money)

    async def test_positive_delta_reports_entry_and_updates_balance(
        self, cog, interaction, character, db, no_thumbnail
    ):
        await self._invoke(cog, interaction, "1", 50)

        assert interaction.response.deferred[0]["kwargs"]["ephemeral"] is True
        embed = followup_embed(interaction)
        assert embed.title == "MUTAÇÃO PATRIMONIAL: Cobaia"
        assert embed.color == discord.Color.green()
        assert field_value(embed, "Transação Homologada") == (
            "Tipo: `Entrada`\nFluxo: `+50 $`"
        )
        assert field_value(embed, "Demonstrativo de Saldos") == (
            "Anterior: `0 $`\nAtualizado: `50 $`"
        )
        assert db.execute(
            "SELECT money FROM characters WHERE character_id = 1"
        ).fetchone()[0] == 50

    async def test_negative_delta_reports_exit_and_updates_balance(
        self, cog, interaction, character, db, no_thumbnail
    ):
        db.execute("UPDATE characters SET money = 100 WHERE character_id = 1")
        db.commit()

        await self._invoke(cog, interaction, "1", -30)

        embed = followup_embed(interaction)
        assert embed.color == discord.Color.red()
        assert field_value(embed, "Transação Homologada") == (
            "Tipo: `Saída`\nFluxo: `-30 $`"
        )
        assert field_value(embed, "Demonstrativo de Saldos") == (
            "Anterior: `100 $`\nAtualizado: `70 $`"
        )
        assert db.execute(
            "SELECT money FROM characters WHERE character_id = 1"
        ).fetchone()[0] == 70

    async def test_zero_delta_is_reported_as_entry(self, cog, interaction, character, no_thumbnail):
        await self._invoke(cog, interaction, "1", 0)

        embed = followup_embed(interaction)
        assert "Tipo: `Entrada`" in field_value(embed, "Transação Homologada")
        assert "Fluxo: `+0 $`" in field_value(embed, "Transação Homologada")

    async def test_invalid_identifier_reports_a_processing_error(self, cog, interaction, no_thumbnail):
        await self._invoke(cog, interaction, "abc", 10)

        assert interaction.response.deferred
        sent = interaction.followup.sent[0]
        assert sent["args"][0] == (
            "**Erro de processamento:** O identificador do personagem fornecido é inválido."
        )
        assert sent["kwargs"]["ephemeral"] is True

    async def test_unknown_identifier_reports_a_consistency_error(self, cog, interaction, no_thumbnail):
        await self._invoke(cog, interaction, "999", 10)

        sent = interaction.followup.sent[0]
        assert "**Erro de consistência:**" in sent["args"][0]
        assert "`999`" in sent["args"][0]
        assert sent["kwargs"]["ephemeral"] is True

    async def test_portrait_file_is_forwarded_when_available(self, cog, interaction, character, monkeypatch):
        portrait = SimpleNamespace(filename="char_1.png")
        monkeypatch.setattr(
            inventory_module,
            "get_character_thumbnail_by_id",
            lambda *args, **kwargs: (portrait, "attachment://char_1.png"),
        )

        await self._invoke(cog, interaction, "1", 5)

        sent = interaction.followup.sent[0]["kwargs"]
        assert sent["file"] is portrait
        assert sent["embed"].thumbnail.url == "attachment://char_1.png"


class TestCharacterAutocomplete:
    async def test_returns_choices_with_stringified_character_ids(self, cog, interaction, db):
        for index in range(3):
            insert_character(db, owner_id=100 + index, name=f"Herói {index}")

        choices = await Inventory.character_autocomplete(cog, interaction, "")

        assert len(choices) == 3
        assert all(isinstance(choice, app_commands.Choice) for choice in choices)
        assert all(isinstance(choice.value, str) for choice in choices)
        assert {"Herói 0", "Herói 1", "Herói 2"} == {choice.name for choice in choices}

    async def test_filters_by_the_current_search_term(self, cog, interaction, db):
        insert_character(db, owner_id=100, name="Feiticeiro")
        insert_character(db, owner_id=101, name="Guerreiro")

        choices = await Inventory.character_autocomplete(cog, interaction, "Feit")

        assert [choice.name for choice in choices] == ["Feiticeiro"]

    async def test_limits_the_result_pool_to_twenty_five(self, cog, interaction, db):
        for index in range(30):
            insert_character(db, owner_id=200 + index, name=f"Cobaia {index}")

        choices = await Inventory.character_autocomplete(cog, interaction, "Cobaia")

        assert len(choices) == 25
