"""View and command tests for cogs/sheet.py.

The sheet embed and the hub view are exercised with hand-built profile dicts,
while the slash commands run through the raw callbacks against the shared
in-memory database. Thumbnail helpers are monkeypatched so the binary asset
pipeline never touches the real portraits directory.
"""

from __future__ import annotations

from types import SimpleNamespace

import discord
import pytest

import cogs.sheet as sheet_module
from cogs.inventory import InventoryView
from cogs.sheet import Sheet, SheetHubView, _attachment_kwargs, build_sheet_embed
from cogs.skills import SkillListView
from cogs.spells import SpellListView
from cogs.traits import TraitListView
from helpers import (
    FakeInteraction,
    insert_advantage,
    insert_skill,
    insert_spell,
    insert_spell_class,
    link_advantage,
    link_skill,
    link_spell,
)


def profile(**overrides) -> dict:
    data = {
        "character_id": 1,
        "owner_id": 1,
        "is_npc": False,
        "name": "Heroína",
        "st": 12,
        "dx": 11,
        "iq": 13,
        "ht": 10,
        "additional_max_pv": 2,
        "additional_vont": 3,
        "additional_per": -1,
        "additional_max_pf": 1,
        "additional_basic_speed": 0,
        "additional_basic_move": 0,
        "energy_reserve": 5,
        "normal_diffuse_homogeneous_unded": 0,
        "money": 42,
        "current_pv": 10,
        "current_pf": 9,
        "current_er": 3,
        "current_points": 7,
    }
    data.update(overrides)
    return data


def field_value(embed: discord.Embed, name: str) -> str:
    for field in embed.fields:
        if field.name == name:
            return field.value
    raise AssertionError(f"embed field {name!r} not found")


def followup_embed(interaction, index: int = 0) -> discord.Embed:
    return interaction.followup.sent[index]["kwargs"]["embed"]


@pytest.fixture
def cog(make_cog):
    return make_cog(Sheet)


@pytest.fixture
def no_thumbnail(monkeypatch):
    monkeypatch.setattr(
        sheet_module,
        "get_character_thumbnail_by_id",
        lambda *args, **kwargs: (None, None),
    )
    monkeypatch.setattr(
        sheet_module,
        "get_character_thumbnail_payload",
        lambda *args, **kwargs: (None, None),
    )


class TestBuildSheetEmbed:
    def test_derives_secondary_characteristics(self):
        embed = build_sheet_embed(profile())

        assert embed.title == "**Heroína**"
        assert "**Pontos não Gastos:** `7`" in embed.description
        assert "**Dinheiro:** `42`" in embed.description
        attributes = field_value(embed, "Atributos Básicos")
        assert "**ST:** `12`" in attributes
        assert "**DX:** `11`" in attributes
        assert "**IQ:** `13`" in attributes
        assert "**HT:** `10`" in attributes
        assert "**ER:** `5`" in attributes

        secondary = field_value(embed, "Características Secundárias")
        assert "PV Máximo: `14`" in secondary
        assert "PF Máximo: `11`" in secondary
        assert "Vontade: `16`" in secondary
        assert "Percepção: `12`" in secondary

    def test_resource_bars_use_current_and_maximum_values(self):
        embed = build_sheet_embed(profile())

        resources = field_value(embed, "Recursos Atuais (PV - PF - ER)")
        assert "10/14" in resources
        assert "9/11" in resources
        assert "3/5" in resources

    def test_zero_energy_reserve_does_not_divide_by_zero(self):
        embed = build_sheet_embed(profile(energy_reserve=0, current_er=0))

        resources = field_value(embed, "Recursos Atuais (PV - PF - ER)")
        assert "0/0" in resources

    def test_uses_the_gold_color_and_exactly_three_fields(self):
        embed = build_sheet_embed(profile())

        assert embed.color == discord.Color.gold()
        assert [field.name for field in embed.fields] == [
            "Atributos Básicos",
            "Características Secundárias",
            "Recursos Atuais (PV - PF - ER)",
        ]

    def test_negative_additional_stats_reduce_the_secondary_values(self):
        embed = build_sheet_embed(
            profile(additional_max_pv=-2, additional_max_pf=-1, additional_vont=-3, additional_per=-1)
        )

        secondary = field_value(embed, "Características Secundárias")
        assert "PV Máximo: `10`" in secondary
        assert "PF Máximo: `9`" in secondary
        assert "Vontade: `10`" in secondary
        assert "Percepção: `12`" in secondary


class TestAttachmentKwargs:
    def test_missing_file_returns_an_empty_attachment_list(self, interaction):
        assert _attachment_kwargs(interaction, None) == {"attachments": []}

    def test_new_file_is_returned_as_attachment(self, interaction):
        character_file = SimpleNamespace(filename="char_1.png")

        result = _attachment_kwargs(interaction, character_file)

        assert result == {"attachments": [character_file]}

    def test_already_attached_file_returns_no_kwargs(self):
        interaction = FakeInteraction(
            message=SimpleNamespace(
                attachments=[SimpleNamespace(filename="char_1.png")]
            )
        )
        character_file = SimpleNamespace(filename="char_1.png")

        assert _attachment_kwargs(interaction, character_file) == {}

    def test_different_attachment_filename_is_reuploaded(self):
        interaction = FakeInteraction(
            message=SimpleNamespace(
                attachments=[SimpleNamespace(filename="char_2.png")]
            )
        )
        character_file = SimpleNamespace(filename="char_1.png")

        result = _attachment_kwargs(interaction, character_file)

        assert result == {"attachments": [character_file]}


class TestSheetHubView:
    def test_exposes_the_four_inspection_buttons(self, db):
        view = SheetHubView(
            db_connection=db,
            character_id=1,
            author_id=1,
            sheet_embed=build_sheet_embed(profile()),
        )

        assert [item.label for item in view.children] == [
            "Inventário",
            "Perícias",
            "Vantagens/Desvantagens",
            "Magias",
        ]

    async def test_owner_is_allowed(self, db, interaction):
        view = SheetHubView(
            db_connection=db,
            character_id=1,
            author_id=1,
            sheet_embed=build_sheet_embed(profile()),
        )

        assert await view.interaction_check(interaction) is True

    async def test_other_user_is_rejected(self, db):
        view = SheetHubView(
            db_connection=db,
            character_id=1,
            author_id=1,
            sheet_embed=build_sheet_embed(profile()),
        )
        interaction = FakeInteraction(user_id=2)

        assert await view.interaction_check(interaction) is False
        assert interaction.response.messages[0]["args"][0] == (
            "Erro: Apenas o usuário que invocou o comando pode interagir com este menu."
        )
        assert interaction.response.messages[0]["kwargs"]["ephemeral"] is True

    async def test_restore_hub_replaces_the_child_view(self, db, interaction, no_thumbnail):
        embed = build_sheet_embed(profile())
        view = SheetHubView(
            db_connection=db, character_id=1, author_id=1, sheet_embed=embed
        )

        await view.restore_hub(interaction)

        assert interaction.response.deferred
        edit = interaction.edited[0]["kwargs"]
        assert edit["content"] is None
        assert edit["embed"] is embed
        assert isinstance(edit["view"], SheetHubView)
        assert edit["attachments"] == []

    async def test_open_inventory_without_character_sends_an_error(self, db, interaction, no_thumbnail):
        view = SheetHubView(
            db_connection=db,
            character_id=999,
            author_id=1,
            sheet_embed=build_sheet_embed(profile()),
        )

        await view.open_inventory(interaction)

        assert interaction.edited == []
        sent = interaction.followup.sent[0]
        assert sent["args"][0] == (
            "Erro de consistência: nenhum inventário associado ao personagem."
        )
        assert sent["kwargs"]["ephemeral"] is True

    async def test_open_inventory_renders_with_attachment_cleanup(
        self, db, interaction, character, no_thumbnail
    ):
        view = SheetHubView(
            db_connection=db,
            character_id=1,
            author_id=1,
            sheet_embed=build_sheet_embed(profile()),
        )

        await view.open_inventory(interaction)

        assert interaction.followup.sent == []
        edit = interaction.edited[0]["kwargs"]
        assert edit["content"] is None
        assert edit["embed"].title == "Inventário: Cobaia"
        assert isinstance(edit["view"], InventoryView)
        assert edit["attachments"] == []

    async def test_open_skills_without_skills_sends_an_error(self, db, interaction, character):
        view = SheetHubView(
            db_connection=db,
            character_id=1,
            author_id=1,
            sheet_embed=build_sheet_embed(profile()),
        )

        await view.open_skills(interaction)

        assert interaction.edited == []
        sent = interaction.followup.sent[0]
        assert sent["args"][0] == (
            "O personagem Cobaia não possui nenhuma perícia cadastrada."
        )
        assert sent["kwargs"]["ephemeral"] is True

    async def test_open_skills_without_character_sends_a_consistency_error(
        self, db, interaction
    ):
        view = SheetHubView(
            db_connection=db,
            character_id=999,
            author_id=1,
            sheet_embed=build_sheet_embed(profile()),
        )

        await view.open_skills(interaction)

        sent = interaction.followup.sent[0]
        assert sent["args"][0] == (
            "Erro de consistência: Personagem com ID `999` não foi localizado."
        )

    async def test_open_skills_renders_the_skill_list(self, db, interaction, character):
        skill_id = insert_skill(db, name="Espada Curta", attribute="DX")
        link_skill(db, 1, skill_id, 2)
        view = SheetHubView(
            db_connection=db,
            character_id=1,
            author_id=1,
            sheet_embed=build_sheet_embed(profile()),
        )

        await view.open_skills(interaction)

        assert interaction.followup.sent == []
        edit = interaction.edited[0]["kwargs"]
        assert edit["embed"] is None
        assert edit["attachments"] == []
        assert isinstance(edit["view"], SkillListView)
        assert edit["content"] == edit["view"].build_content()
        assert "Perícias" in edit["content"]

    async def test_open_traits_without_traits_sends_an_error(self, db, interaction, character):
        view = SheetHubView(
            db_connection=db,
            character_id=1,
            author_id=1,
            sheet_embed=build_sheet_embed(profile()),
        )

        await view.open_traits(interaction)

        assert interaction.edited == []
        assert interaction.followup.sent[0]["args"][0] == (
            "O personagem Cobaia não possui nenhuma vantagem ou desvantagem cadastrada."
        )

    async def test_open_traits_renders_the_trait_list(self, db, interaction, character):
        advantage_id = insert_advantage(db)
        link_advantage(db, 1, advantage_id)
        view = SheetHubView(
            db_connection=db,
            character_id=1,
            author_id=1,
            sheet_embed=build_sheet_embed(profile()),
        )

        await view.open_traits(interaction)

        edit = interaction.edited[0]["kwargs"]
        assert isinstance(edit["view"], TraitListView)
        assert edit["content"] == edit["view"].build_content()
        assert "Vantagens e Desvantagens" in edit["content"]

    async def test_open_spells_without_spells_sends_an_error(self, db, interaction, character):
        view = SheetHubView(
            db_connection=db,
            character_id=1,
            author_id=1,
            sheet_embed=build_sheet_embed(profile()),
        )

        await view.open_spells(interaction)

        assert interaction.edited == []
        assert interaction.followup.sent[0]["args"][0] == (
            "O personagem Cobaia não possui nenhuma magia cadastrada."
        )

    async def test_open_spells_renders_the_spell_list(self, db, interaction, character):
        class_id = insert_spell_class(db, "Fogo")
        spell_id = insert_spell(db, name="Bola de Fogo", class_id=class_id)
        link_spell(db, 1, spell_id, 2)
        view = SheetHubView(
            db_connection=db,
            character_id=1,
            author_id=1,
            sheet_embed=build_sheet_embed(profile()),
        )

        await view.open_spells(interaction)

        edit = interaction.edited[0]["kwargs"]
        assert isinstance(edit["view"], SpellListView)
        assert edit["content"] == edit["view"].build_content()
        assert "Magias" in edit["content"]


class TestSheetCommands:
    async def test_sheet_without_character_reports_the_database_anomaly(
        self, cog, interaction, no_thumbnail
    ):
        await Sheet.sheet.callback(cog, interaction)

        assert interaction.response.deferred[0]["kwargs"]["ephemeral"] is True
        sent = interaction.followup.sent[0]
        assert sent["args"][0].startswith("Erro de processamento: Database Anomaly")
        assert sent["kwargs"]["ephemeral"] is True

    async def test_sheet_renders_the_hub_for_the_active_character(
        self, cog, interaction, character, no_thumbnail
    ):
        await Sheet.sheet.callback(cog, interaction)

        sent = interaction.followup.sent[0]["kwargs"]
        assert sent["embed"].title == "**Cobaia**"
        assert isinstance(sent["view"], SheetHubView)
        assert sent["ephemeral"] is True
        assert "file" not in sent

    async def test_sheet_attaches_the_portrait_when_available(
        self, cog, interaction, character, monkeypatch
    ):
        portrait = SimpleNamespace(filename="char_1.png")
        monkeypatch.setattr(
            sheet_module,
            "get_character_thumbnail_payload",
            lambda *args, **kwargs: (portrait, "attachment://char_1.png"),
        )

        await Sheet.sheet.callback(cog, interaction)

        sent = interaction.followup.sent[0]["kwargs"]
        assert sent["file"] is portrait

    async def test_sheet_view_renders_an_arbitrary_character(
        self, cog, interaction, character, no_thumbnail
    ):
        await Sheet.sheet_view.callback(cog, interaction, "1")

        sent = interaction.followup.sent[0]["kwargs"]
        assert sent["embed"].title == "**Cobaia**"
        assert isinstance(sent["view"], SheetHubView)
        assert sent["view"].character_id == 1

    async def test_sheet_view_rejects_a_non_numeric_identifier(
        self, cog, interaction, no_thumbnail
    ):
        await Sheet.sheet_view.callback(cog, interaction, "abc")

        assert interaction.followup.sent[0]["args"][0] == (
            "Erro de processamento: O identificador do personagem fornecido é estruturalmente inválido."
        )

    async def test_sheet_view_reports_a_missing_character(
        self, cog, interaction, no_thumbnail
    ):
        await Sheet.sheet_view.callback(cog, interaction, "999")

        assert interaction.followup.sent[0]["args"][0].startswith(
            "Erro de processamento:"
        )
