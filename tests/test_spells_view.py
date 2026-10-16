"""View and command tests for cogs/spells.py.

Rows, headers, school grouping, pagination and the detail dropdown are
exercised with hand-built spell dicts shaped like
utils.db_functions.get_character_spells_data. Slash commands run through the raw
callbacks against the shared in-memory database.
"""

from __future__ import annotations

import pytest

import cogs.spells as spells_module
from cogs.spells import (
    Spells,
    SpellListView,
    SpellSelect,
    build_spell_header,
    build_spell_row,
)
from helpers import FakeInteraction, insert_spell, insert_spell_class, link_spell


def spell(
    spell_id: int = 1,
    name: str = "Bola de Fogo",
    school: str = "Fogo",
    attribute: str = "IQ",
    difficulty: str = "Hard",
    cost: int = 2,
    resource: str = "PF",
    relative_display: str = "IQ+2",
    nh: int = 12,
    description: str = "Magia de teste",
) -> dict:
    return {
        "spell_id": spell_id,
        "name": name,
        "school": school,
        "attribute": attribute,
        "difficulty": difficulty,
        "cost": cost,
        "resource": resource,
        "relative_level": 2,
        "relative_display": relative_display,
        "nh": nh,
        "description": description,
    }


def select_of(view: SpellListView) -> SpellSelect:
    for item in view.children:
        if isinstance(item, SpellSelect):
            return item
    raise AssertionError("SpellSelect not found in the view")


def followup_content(interaction, index: int = 0) -> str:
    sent = interaction.followup.sent[index]
    if "content" in sent["kwargs"]:
        return sent["kwargs"]["content"]
    return sent["args"][0]


@pytest.fixture
def cog(make_cog):
    return make_cog(Spells)


class TestBuildSpellRow:
    def test_contains_name_nh_and_cost(self):
        row = build_spell_row(spell())

        assert "Bola de Fogo" in row
        assert "NH" in row
        assert "12" in row
        assert "2 PF" in row

    def test_truncates_long_names_to_twenty_six_visible_characters(self):
        row = build_spell_row(spell(name="A" * 40))

        assert "A" * 23 + "..." in row
        assert "A" * 40 not in row

    def test_backticks_are_sanitized(self):
        row = build_spell_row(spell(name="Bola `Fogo`"))

        assert "`" not in row
        assert "Bola 'Fogo'" in row

    def test_cost_display_keeps_the_resource_suffix(self):
        row = build_spell_row(spell(cost=5, resource="ER"))

        assert "5 ER" in row


class TestBuildSpellHeader:
    def test_contains_nh_cost_relative_level_and_difficulty(self):
        header = build_spell_header(spell())

        assert header.startswith("```ansi")
        assert "NH" in header
        assert "12" in header
        assert "Custo" in header
        assert "2 PF" in header
        assert "Nível Relativo" in header
        assert "IQ+2" in header
        assert "Dificuldade" in header
        assert "IQ / Hard" in header
        assert header.endswith("\n**Descrição e Regras:**\n")


class TestSpellListGrouping:
    def test_pagination_uses_the_300_character_base_length(self, monkeypatch):
        captured = {}

        def fake_paginate(rows, base_length):
            captured["base_length"] = base_length
            captured["rows"] = rows
            return [[(None, "linha")]]

        monkeypatch.setattr(spells_module, "paginate_rows", fake_paginate)

        SpellListView(
            "Cobaia",
            [spell(spell_id=1, school="Fogo"), spell(spell_id=2, school="Fogo")],
            author_id=1,
        )

        assert captured["base_length"] == 300
        # One school heading plus the two spell rows.
        assert len(captured["rows"]) == 3

    def test_schools_are_grouped_with_a_heading_row(self):
        spells = [
            spell(spell_id=1, name="Bola de Fogo", school="Fogo"),
            spell(spell_id=2, name="Muralha de Fogo", school="Fogo"),
            spell(spell_id=3, name="Cura", school="Água"),
        ]

        view = SpellListView("Cobaia", spells, author_id=1)

        assert [payload for payload, _ in view.pages[0]] == [
            None,
            spells[0],
            spells[1],
            None,
            spells[2],
        ]

    def test_content_renders_every_school_heading(self):
        spells = [
            spell(spell_id=1, name="Bola de Fogo", school="Fogo"),
            spell(spell_id=2, name="Cura", school="Água"),
        ]
        view = SpellListView("Cobaia", spells, author_id=1)

        content = view.build_content()

        assert "Fogo" in content
        assert "Água" in content
        assert "Magias: **Cobaia**" in content

    def test_options_exclude_the_heading_rows(self):
        spells = [
            spell(spell_id=1, name="Bola de Fogo", school="Fogo"),
            spell(spell_id=2, name="Cura", school="Água"),
        ]
        view = SpellListView("Cobaia", spells, author_id=1)

        options = select_of(view).options

        assert [option.value for option in options] == ["1", "2"]

    def test_continuation_pages_reinsert_the_running_school(self):
        spells = [
            spell(spell_id=index + 1, name=f"Magia {index + 1:02d}", school="Fogo")
            for index in range(30)
        ]

        view = SpellListView("Cobaia", spells, author_id=1)

        assert view.total_pages > 1
        for index in range(1, view.total_pages):
            view.current_page = index
            content = view.build_content()
            assert "Fogo" in content
            first_payload = next(
                payload for payload, _ in view.pages[index] if payload is not None
            )
            assert "Magia {0:02d}".format(first_payload["spell_id"]) in content

    def test_every_rendered_page_respects_the_1900_clamp(self):
        spells = [
            spell(spell_id=index + 1, name=f"Magia {index + 1:02d}", school="Fogo")
            for index in range(30)
        ]
        view = SpellListView("Cobaia", spells, author_id=1)

        for index in range(view.total_pages):
            view.current_page = index
            assert len(view.build_content()) <= 1900

    def test_options_per_page_never_exceed_twenty_five(self):
        spells = [
            spell(spell_id=index + 1, name=f"Magia {index + 1:02d}", school="Fogo")
            for index in range(30)
        ]
        view = SpellListView("Cobaia", spells, author_id=1)

        for index in range(view.total_pages):
            view.current_page = index
            view.update_components()
            assert len(select_of(view).options) <= 25


class TestSpellSelect:
    def test_labels_are_clamped_to_100_characters(self):
        view = SpellListView(
            "Cobaia",
            [spell(spell_id=1, name="M" * 150), spell(spell_id=2, name="Curta")],
            author_id=1,
        )

        for option in select_of(view).options:
            assert len(option.label) <= 100

    async def test_callback_edits_the_message_with_the_detail_embed(self):
        view = SpellListView("Cobaia", [spell()], author_id=1)
        select = select_of(view)
        interaction = FakeInteraction()

        select._values = ["1"]
        await select.callback(interaction)

        edit = interaction.response.edits[0]["kwargs"]
        assert edit["embed"].title == "Magia: Bola de Fogo"
        assert "Magia de teste" in edit["embed"].description
        assert edit["content"] == view.build_content()
        assert edit["view"] is view

    async def test_callback_clamps_the_embed_description_to_4000(self):
        view = SpellListView(
            "Cobaia", [spell(description="d" * 5000)], author_id=1
        )
        select = select_of(view)
        interaction = FakeInteraction()

        select._values = ["1"]
        await select.callback(interaction)

        embed = interaction.response.edits[0]["kwargs"]["embed"]
        assert len(embed.description) == 4000
        assert embed.description.endswith("...")

    async def test_unknown_spell_id_reports_an_error(self):
        view = SpellListView("Cobaia", [spell()], author_id=1)
        select = select_of(view)
        interaction = FakeInteraction()

        select._values = ["999"]
        await select.callback(interaction)

        assert interaction.response.messages[0]["args"][0] == (
            "Erro: Magia não localizada no registro atual."
        )
        assert interaction.response.messages[0]["kwargs"]["ephemeral"] is True


class TestSpellListNavigationAndOwnership:
    async def test_next_page_advances_and_previous_returns(self):
        spells = [
            spell(spell_id=index + 1, name=f"Magia {index + 1:02d}")
            for index in range(30)
        ]
        view = SpellListView("Cobaia", spells, author_id=1)
        first = FakeInteraction()
        second = FakeInteraction()

        await view.next_page(first)
        await view.previous_page(second)

        assert view.current_page == 0
        assert first.response.edits[0]["kwargs"]["embed"] is None
        assert second.response.edits[0]["kwargs"]["content"] == view.build_content()

    async def test_other_user_is_rejected(self):
        view = SpellListView("Cobaia", [spell()], author_id=1)
        interaction = FakeInteraction(user_id=7)

        assert await view.interaction_check(interaction) is False
        assert interaction.response.messages[0]["args"][0] == (
            "Erro: Apenas o usuário que invocou o comando pode interagir com este menu."
        )


class TestListSpellsCommand:
    async def test_without_character_reports_the_missing_binding(self, cog, interaction):
        await Spells.list_spells.callback(cog, interaction)

        assert interaction.response.deferred[0]["kwargs"]["ephemeral"] is True
        assert followup_content(interaction) == (
            "Erro: Você não possui um personagem ativo atribuído à sua conta."
        )

    async def test_without_spells_reports_the_empty_registry(self, cog, interaction, character):
        await Spells.list_spells.callback(cog, interaction)

        assert followup_content(interaction) == (
            "O personagem Cobaia não possui nenhuma magia cadastrada."
        )

    async def test_with_spells_sends_the_paginated_view(self, cog, interaction, character, db):
        class_id = insert_spell_class(db, "Fogo")
        spell_id = insert_spell(db, name="Bola de Fogo", class_id=class_id)
        link_spell(db, 1, spell_id, 2)

        await Spells.list_spells.callback(cog, interaction)

        sent = interaction.followup.sent[0]["kwargs"]
        assert sent["ephemeral"] is True
        assert sent["content"] == sent["view"].build_content()
        assert "Magias" in sent["content"]
        assert "Bola de Fogo" in sent["content"]

    async def test_master_command_accepts_an_explicit_character(self, cog, interaction, character, db):
        class_id = insert_spell_class(db, "Água")
        spell_id = insert_spell(db, name="Cura", class_id=class_id)
        link_spell(db, 1, spell_id, 1)

        await Spells.master_list_spells.callback(cog, interaction, "1")

        sent = interaction.followup.sent[0]["kwargs"]
        assert "Cura" in sent["content"]
        assert sent["view"].spells[0]["nh"] == 11

    async def test_master_command_rejects_an_invalid_identifier(self, cog, interaction):
        await Spells.master_list_spells.callback(cog, interaction, "abc")

        assert followup_content(interaction) == (
            "Erro de processamento: O identificador do personagem fornecido é inválido."
        )

    async def test_master_command_reports_a_missing_character(self, cog, interaction):
        await Spells.master_list_spells.callback(cog, interaction, "999")

        assert followup_content(interaction) == (
            "Erro de consistência: Personagem com ID `999` não foi localizado."
        )

    async def test_master_command_without_argument_falls_back_to_the_caller(
        self, cog, interaction, character, db
    ):
        class_id = insert_spell_class(db, "Fogo")
        spell_id = insert_spell(db, name="Fogo Fátuo", class_id=class_id)
        link_spell(db, 1, spell_id, 0)

        await Spells.master_list_spells.callback(cog, interaction, None)

        assert "Fogo Fátuo" in followup_content(interaction)
