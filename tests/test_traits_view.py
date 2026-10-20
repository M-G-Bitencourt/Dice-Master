"""View tests for cogs/traits.py.

Rows, headers, category grouping, notes clamping and the detail dropdown are
exercised with hand-built trait dicts shaped like
utils.db_functions.get_character_traits_data. Slash commands run through the raw
callbacks against the shared in-memory database.
"""

from __future__ import annotations

import discord

import cogs.traits as traits_module
from cogs.traits import (
    TraitListView,
    TraitSelect,
    build_trait_header,
    build_trait_row,
)
from helpers import FakeInteraction


def trait(
    trait_key: str = "adv_1",
    trait_id: int = 1,
    category: str = "Vantagem",
    name: str = "Reflexos de Combate",
    cost: int = 15,
    description: str = "Vantagem de teste",
    notes: str = "",
) -> dict:
    return {
        "trait_key": trait_key,
        "trait_id": trait_id,
        "category": category,
        "name": name,
        "cost": cost,
        "description": description,
        "notes": notes,
    }


def select_of(view: TraitListView) -> TraitSelect:
    for item in view.children:
        if isinstance(item, TraitSelect):
            return item
    raise AssertionError("TraitSelect not found in the view")


class TestBuildTraitRow:
    def test_positive_cost_uses_the_plus_sign(self):
        row = build_trait_row(trait(cost=15))

        assert "Reflexos de Combate" in row
        assert "+15 pts" in row

    def test_negative_cost_keeps_the_minus_sign(self):
        row = build_trait_row(trait(category="Desvantagem", cost=-10))

        assert "-10 pts" in row

    def test_zero_cost_is_rendered_as_plus_zero(self):
        row = build_trait_row(trait(cost=0))

        assert "+0 pts" in row

    def test_truncates_long_names_to_thirty_visible_characters(self):
        row = build_trait_row(trait(name="A" * 40))

        assert "A" * 27 + "..." in row
        assert "A" * 40 not in row

    def test_backticks_are_sanitized(self):
        row = build_trait_row(trait(name="Visão `Noturna`"))

        assert "`" not in row
        assert "Visão 'Noturna'" in row


class TestBuildTraitHeader:
    def test_contains_the_cost_badge(self):
        header = build_trait_header(trait(cost=15))

        assert header.startswith("```ansi")
        assert "Custo" in header
        assert "+15 pts" in header

    def test_negative_cost_header_keeps_the_minus_sign(self):
        header = build_trait_header(trait(cost=-10))

        assert "-10 pts" in header


class TestTraitListGrouping:
    def test_pagination_uses_the_300_character_base_length(self, monkeypatch):
        captured = {}

        def fake_paginate(rows, base_length):
            captured["base_length"] = base_length
            captured["rows"] = rows
            return [[(None, "linha")]]

        monkeypatch.setattr(traits_module, "paginate_rows", fake_paginate)

        TraitListView(
            "Cobaia",
            [
                trait(trait_key="adv_1", category="Vantagem"),
                trait(trait_key="dis_1", category="Desvantagem", cost=-10),
            ],
            author_id=1,
        )

        assert captured["base_length"] == 300
        # Two category headings plus the two trait rows.
        assert len(captured["rows"]) == 4

    def test_categories_are_grouped_with_a_heading_row(self):
        advantage = trait(trait_key="adv_1", category="Vantagem", cost=15)
        disadvantage = trait(
            trait_key="dis_1", trait_id=1, category="Desvantagem", cost=-10
        )

        view = TraitListView("Cobaia", [advantage, disadvantage], author_id=1)

        assert [payload for payload, _ in view.pages[0]] == [
            None,
            advantage,
            None,
            disadvantage,
        ]

    def test_content_renders_uppercase_category_headings(self):
        view = TraitListView(
            "Cobaia",
            [
                trait(trait_key="adv_1", category="Vantagem"),
                trait(trait_key="dis_1", category="Desvantagem", cost=-10),
            ],
            author_id=1,
        )

        content = view.build_content()

        assert "VANTAGEM" in content
        assert "DESVANTAGEM" in content
        assert "Vantagens e Desvantagens: **Cobaia**" in content

    def test_options_exclude_the_heading_rows_and_use_trait_keys(self):
        view = TraitListView(
            "Cobaia",
            [
                trait(trait_key="adv_1", category="Vantagem"),
                trait(trait_key="dis_1", category="Desvantagem", cost=-10),
            ],
            author_id=1,
        )

        assert [option.value for option in select_of(view).options] == [
            "adv_1",
            "dis_1",
        ]

    def test_continuation_pages_reinsert_the_running_category(self):
        traits = [
            trait(trait_key=f"adv_{index}", trait_id=index, name=f"Vantagem {index:02d}")
            for index in range(30)
        ]

        view = TraitListView("Cobaia", traits, author_id=1)

        assert view.total_pages > 1
        for index in range(1, view.total_pages):
            view.current_page = index
            content = view.build_content()
            assert "VANTAGEM" in content

    def test_every_rendered_page_respects_the_1900_clamp(self):
        traits = [
            trait(trait_key=f"adv_{index}", trait_id=index, name=f"Vantagem {index:02d}")
            for index in range(30)
        ]
        view = TraitListView("Cobaia", traits, author_id=1)

        for index in range(view.total_pages):
            view.current_page = index
            assert len(view.build_content()) <= 1900

    def test_options_per_page_never_exceed_twenty_five(self):
        traits = [
            trait(trait_key=f"adv_{index}", trait_id=index, name=f"Vantagem {index:02d}")
            for index in range(30)
        ]
        view = TraitListView("Cobaia", traits, author_id=1)

        for index in range(view.total_pages):
            view.current_page = index
            view.update_components()
            assert len(select_of(view).options) <= 25


class TestTraitSelect:
    def test_labels_and_descriptions_are_clamped_to_100_characters(self):
        view = TraitListView(
            "Cobaia",
            [
                trait(trait_key="adv_1", name="N" * 150),
                trait(trait_key="adv_2", name="Curta"),
            ],
            author_id=1,
        )

        for option in select_of(view).options:
            assert len(option.label) <= 100
            assert len(option.description) <= 100

    async def test_callback_shows_cost_notes_and_description(self):
        view = TraitListView(
            "Cobaia",
            [trait(notes="Anotação pessoal", description="Texto de regra")],
            author_id=1,
        )
        select = select_of(view)
        interaction = FakeInteraction()

        select._values = ["adv_1"]
        await select.callback(interaction)

        edit = interaction.response.edits[0]["kwargs"]
        embed = edit["embed"]
        assert embed.title == "Vantagem: Reflexos de Combate"
        assert embed.color == discord.Color.gold()
        assert "+15 pts" in embed.description
        assert "Anotação pessoal" in embed.description
        assert "Texto de regra" in embed.description
        assert edit["content"] == view.build_content()
        assert edit["view"] is view

    async def test_disadvantage_uses_the_dark_red_color(self):
        view = TraitListView(
            "Cobaia",
            [trait(category="Desvantagem", cost=-10)],
            author_id=1,
        )
        select = select_of(view)
        interaction = FakeInteraction()

        select._values = ["adv_1"]
        await select.callback(interaction)

        embed = interaction.response.edits[0]["kwargs"]["embed"]
        assert embed.title == "Desvantagem: Reflexos de Combate"
        assert embed.color == discord.Color.dark_red()

    async def test_empty_notes_use_the_fallback_message(self):
        view = TraitListView("Cobaia", [trait(notes="")], author_id=1)
        select = select_of(view)
        interaction = FakeInteraction()

        select._values = ["adv_1"]
        await select.callback(interaction)

        embed = interaction.response.edits[0]["kwargs"]["embed"]
        assert "Nenhuma observação registrada." in embed.description

    async def test_notes_are_truncated_to_1000_characters(self):
        view = TraitListView(
            "Cobaia", [trait(notes="n" * 1500, description="d" * 10)], author_id=1
        )
        select = select_of(view)
        interaction = FakeInteraction()

        select._values = ["adv_1"]
        await select.callback(interaction)

        embed = interaction.response.edits[0]["kwargs"]["embed"]
        assert "n" * 1000 in embed.description
        assert "n" * 1001 not in embed.description
        assert len(embed.description) <= 4000

    async def test_unknown_trait_key_reports_an_error(self):
        view = TraitListView("Cobaia", [trait()], author_id=1)
        select = select_of(view)
        interaction = FakeInteraction()

        select._values = ["missing"]
        await select.callback(interaction)

        assert interaction.response.messages[0]["args"][0] == (
            "Erro: Característica não localizada no registro atual."
        )
        assert interaction.response.messages[0]["kwargs"]["ephemeral"] is True


class TestTraitListNavigationAndOwnership:
    async def test_next_page_advances_and_previous_returns(self):
        traits = [
            trait(trait_key=f"adv_{index}", trait_id=index, name=f"Vantagem {index:02d}")
            for index in range(30)
        ]
        view = TraitListView("Cobaia", traits, author_id=1)
        first = FakeInteraction()
        second = FakeInteraction()

        await view.next_page(first)
        await view.previous_page(second)

        assert view.current_page == 0
        assert first.response.edits[0]["kwargs"]["embed"] is None
        assert second.response.edits[0]["kwargs"]["content"] == view.build_content()

    async def test_other_user_is_rejected(self):
        view = TraitListView("Cobaia", [trait()], author_id=1)
        interaction = FakeInteraction(user_id=7)

        assert await view.interaction_check(interaction) is False
        assert interaction.response.messages[0]["args"][0] == (
            "Erro: Apenas o usuário que invocou o comando pode interagir com este menu."
        )
