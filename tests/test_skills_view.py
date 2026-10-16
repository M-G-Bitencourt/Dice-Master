"""View and command tests for cogs/skills.py.

Rows, headers, pagination and the detail dropdown are exercised with
hand-built skill dicts shaped like utils.db_functions.get_character_skills_data.
Slash commands run through the raw callbacks against the shared in-memory
database.
"""

from __future__ import annotations

import discord
import pytest

import cogs.skills as skills_module
from cogs.skills import (
    Skills,
    SkillListView,
    SkillSelect,
    build_skill_header,
    build_skill_row,
)
from helpers import FakeInteraction, insert_skill, link_skill


def skill(
    skill_id: int = 1,
    name: str = "Espada Curta",
    attribute: str = "DX",
    difficulty: str = "Medium",
    relative_display: str = "DX+2",
    nh: int = 12,
    description: str = "Perícia de teste",
) -> dict:
    return {
        "skill_id": skill_id,
        "name": name,
        "attribute": attribute,
        "difficulty": difficulty,
        "relative_level": 2,
        "relative_display": relative_display,
        "nh": nh,
        "description": description,
    }


def many_skills(count: int = 40) -> list[dict]:
    return [
        skill(skill_id=index + 1, name=f"Perícia {index + 1:02d}")
        for index in range(count)
    ]


def select_of(view: SkillListView) -> SkillSelect:
    for item in view.children:
        if isinstance(item, SkillSelect):
            return item
    raise AssertionError("SkillSelect not found in the view")


def button_labels(view: SkillListView) -> list[str]:
    return [
        item.label for item in view.children if isinstance(item, discord.ui.Button)
    ]


def button_by_label(view: SkillListView, label: str) -> discord.ui.Button:
    for item in view.children:
        if isinstance(item, discord.ui.Button) and item.label == label:
            return item
    raise AssertionError(f"button {label!r} not found")


def followup_content(interaction, index: int = 0) -> str:
    sent = interaction.followup.sent[index]
    if "content" in sent["kwargs"]:
        return sent["kwargs"]["content"]
    return sent["args"][0]


@pytest.fixture
def cog(make_cog):
    return make_cog(Skills)


class TestBuildSkillRow:
    def test_contains_name_relative_level_and_nh(self):
        row = build_skill_row(skill())

        assert "Espada Curta" in row
        assert "DX+2" in row
        assert "NH" in row
        assert "12" in row

    def test_truncates_long_names_to_thirty_visible_characters(self):
        row = build_skill_row(skill(name="A" * 40))

        assert "A" * 27 + "..." in row
        assert "A" * 40 not in row

    def test_names_at_the_exact_width_are_untouched(self):
        row = build_skill_row(skill(name="B" * 30))

        assert "B" * 30 in row
        assert "..." not in row

    def test_backticks_are_sanitized(self):
        row = build_skill_row(skill(name="Es`pada"))

        assert "`" not in row
        assert "Es'pada" in row

    def test_negative_nh_is_rendered_verbatim(self):
        row = build_skill_row(skill(relative_display="DX-3", nh=-1))

        assert "-1" in row
        assert "DX-3" in row


class TestBuildSkillHeader:
    def test_contains_nh_relative_level_and_difficulty(self):
        header = build_skill_header(skill())

        assert header.startswith("```ansi")
        assert "NH" in header
        assert "12" in header
        assert "Nível Relativo" in header
        assert "DX+2" in header
        assert "Dificuldade" in header
        assert "DX / Medium" in header
        assert header.endswith("\n**Descrição e Regras:**\n")


class TestSkillListPagination:
    def test_many_skills_split_into_multiple_pages(self):
        view = SkillListView("Cobaia", many_skills(40), author_id=1)

        assert view.total_pages > 1
        assert sum(len(page) for page in view.pages) == 40

    def test_pagination_uses_the_300_character_base_length(self, monkeypatch):
        captured = {}

        def fake_paginate(rows, base_length):
            captured["base_length"] = base_length
            captured["rows"] = rows
            return [[(None, "linha")]]

        monkeypatch.setattr(skills_module, "paginate_rows", fake_paginate)

        SkillListView("Cobaia", many_skills(2), author_id=1)

        assert captured["base_length"] == 300
        assert len(captured["rows"]) == 2

    def test_every_page_respects_the_row_budget(self):
        view = SkillListView("Cobaia", many_skills(40), author_id=1)

        for page in view.pages:
            assert len(page) <= 25

    def test_every_rendered_page_respects_the_1900_clamp(self):
        view = SkillListView("Cobaia", many_skills(40), author_id=1)

        for index in range(view.total_pages):
            view.current_page = index
            content = view.build_content()
            assert len(content) <= 1900
            assert "Página {0} de {1}".format(index + 1, view.total_pages) in content

    def test_single_page_hides_the_page_counter(self):
        view = SkillListView("Cobaia", many_skills(3), author_id=1)

        content = view.build_content()

        assert "*Página 1 de 1*" not in content
        assert content.startswith("# Perícias: **Cobaia**")
        assert "---" in content

    def test_empty_skill_list_still_builds_a_view(self):
        view = SkillListView("Cobaia", [], author_id=1)

        assert view.total_pages == 1
        assert select_of(view).options == []
        assert len(view.build_content()) <= 1900


class TestSkillSelect:
    def test_options_cover_the_current_page_skills(self):
        skills = many_skills(40)
        view = SkillListView("Cobaia", skills, author_id=1)
        view.current_page = 0
        view.update_components()

        options = select_of(view).options

        assert len(options) == len(view.pages[0])
        assert [option.value for option in options] == [
            str(entry["skill_id"]) for entry, _ in view.pages[0]
        ]

    def test_options_per_page_never_exceed_twenty_five(self):
        view = SkillListView("Cobaia", many_skills(60), author_id=1)

        for index in range(view.total_pages):
            view.current_page = index
            view.update_components()
            assert len(select_of(view).options) <= 25

    def test_labels_and_descriptions_are_clamped_to_100_characters(self):
        skills = [
            skill(skill_id=1, name="N" * 150, description="x"),
            skill(skill_id=2, name="Curta", description="x"),
        ]
        view = SkillListView("Cobaia", skills, author_id=1)

        for option in select_of(view).options:
            assert len(option.label) <= 100
            assert len(option.description) <= 100

    async def test_callback_edits_the_message_with_the_detail_embed(self):
        view = SkillListView("Cobaia", [skill()], author_id=1)
        select = select_of(view)
        interaction = FakeInteraction()

        select._values = ["1"]
        await select.callback(interaction)

        edit = interaction.response.edits[0]["kwargs"]
        assert edit["embed"].title == "Perícia: Espada Curta"
        assert edit["embed"].description.startswith("```ansi")
        assert "Perícia de teste" in edit["embed"].description
        assert edit["content"] == view.build_content()
        assert edit["view"] is view

    async def test_callback_clamps_the_embed_description_to_4000(self):
        view = SkillListView(
            "Cobaia", [skill(description="d" * 5000)], author_id=1
        )
        select = select_of(view)
        interaction = FakeInteraction()

        select._values = ["1"]
        await select.callback(interaction)

        embed = interaction.response.edits[0]["kwargs"]["embed"]
        assert len(embed.description) == 4000
        assert embed.description.endswith("...")

    async def test_unknown_skill_id_reports_an_error(self):
        view = SkillListView("Cobaia", [skill()], author_id=1)
        select = select_of(view)
        interaction = FakeInteraction()

        select._values = ["999"]
        await select.callback(interaction)

        assert interaction.response.messages[0]["args"][0] == (
            "Erro: Perícia não localizada no registro atual."
        )
        assert interaction.response.messages[0]["kwargs"]["ephemeral"] is True
        assert interaction.response.edits == []


class TestSkillListNavigation:
    def test_first_page_disables_previous_and_enables_next(self):
        view = SkillListView("Cobaia", many_skills(40), author_id=1)

        labels = button_labels(view)
        assert labels[0] == "< Anterior"
        assert labels[1].endswith("/ {0}".format(view.total_pages))
        assert labels[2] == "Próxima >"
        previous = button_by_label(view, "< Anterior")
        next_button = button_by_label(view, "Próxima >")
        assert previous.disabled is True
        assert next_button.disabled is False

    def test_back_button_only_exists_with_a_callback(self):
        plain = SkillListView("Cobaia", many_skills(3), author_id=1)
        with_back = SkillListView(
            "Cobaia", many_skills(3), author_id=1, back_callback=lambda interaction: None
        )

        assert "Voltar" not in button_labels(plain)
        assert "Voltar" in button_labels(with_back)

    async def test_next_button_advances_the_page(self, interaction):
        view = SkillListView("Cobaia", many_skills(40), author_id=1)
        next_button = next(
            item for item in view.children if getattr(item, "label", None) == "Próxima >"
        )

        await next_button.callback(interaction)

        assert view.current_page == 1
        edit = interaction.response.edits[0]["kwargs"]
        assert edit["embed"] is None
        assert edit["view"] is view
        assert "Página 2 de {0}".format(view.total_pages) in edit["content"]

    async def test_previous_page_at_the_first_page_does_nothing(self, interaction):
        view = SkillListView("Cobaia", many_skills(40), author_id=1)

        await view.previous_page(interaction)

        assert view.current_page == 0
        assert interaction.response.edits == []

    async def test_go_back_delegates_to_the_parent_callback(self):
        calls = []

        async def back(interaction):
            calls.append(interaction)

        view = SkillListView(
            "Cobaia", many_skills(3), author_id=1, back_callback=back
        )
        interaction = FakeInteraction()

        await view.go_back(interaction)

        assert calls == [interaction]

    async def test_other_user_is_rejected(self, interaction):
        view = SkillListView("Cobaia", many_skills(3), author_id=1)
        interaction.user.id = 2

        assert await view.interaction_check(interaction) is False
        assert interaction.response.messages[0]["args"][0] == (
            "Erro: Apenas o usuário que invocou o comando pode interagir com este menu."
        )


class TestListSkillsCommand:
    async def test_without_character_reports_the_missing_binding(self, cog, interaction):
        await Skills.list_skills.callback(cog, interaction)

        assert interaction.response.deferred[0]["kwargs"]["ephemeral"] is True
        assert followup_content(interaction) == (
            "Erro: Você não possui um personagem ativo atribuído à sua conta."
        )

    async def test_without_skills_reports_the_empty_registry(self, cog, interaction, character):
        await Skills.list_skills.callback(cog, interaction)

        assert followup_content(interaction) == (
            "O personagem Cobaia não possui nenhuma perícia cadastrada."
        )

    async def test_with_skills_sends_the_paginated_view(self, cog, interaction, character, db):
        skill_id = insert_skill(db, name="Espada Curta", attribute="DX")
        link_skill(db, 1, skill_id, 2)

        await Skills.list_skills.callback(cog, interaction)

        sent = interaction.followup.sent[0]["kwargs"]
        assert sent["ephemeral"] is True
        assert sent["content"] == sent["view"].build_content()
        assert "Perícias" in sent["content"]
        assert "DX+2" in sent["content"]

    async def test_master_command_accepts_an_explicit_character(self, cog, interaction, character, db):
        skill_id = insert_skill(db, name="Furtividade", attribute="IQ")
        link_skill(db, 1, skill_id, 1)

        await Skills.master_list_skills.callback(cog, interaction, "1")

        sent = interaction.followup.sent[0]["kwargs"]
        assert "Furtividade" in sent["content"]
        assert sent["view"].skills[0]["nh"] == 11

    async def test_master_command_rejects_an_invalid_identifier(self, cog, interaction):
        await Skills.master_list_skills.callback(cog, interaction, "abc")

        assert followup_content(interaction) == (
            "Erro de processamento: O identificador do personagem fornecido é inválido."
        )

    async def test_master_command_reports_a_missing_character(self, cog, interaction):
        await Skills.master_list_skills.callback(cog, interaction, "999")

        assert followup_content(interaction) == (
            "Erro de consistência: Personagem com ID `999` não foi localizado."
        )

    async def test_master_command_without_argument_falls_back_to_the_caller(
        self, cog, interaction, character, db
    ):
        skill_id = insert_skill(db, name="Escalada", attribute="DX")
        link_skill(db, 1, skill_id, 0)

        await Skills.master_list_skills.callback(cog, interaction, None)

        sent = interaction.followup.sent[0]["kwargs"]
        assert "Escalada" in sent["content"]
