"""Add or remove catalog combat effects for one character."""

from __future__ import annotations

import discord

from cogs.combat_helpers.combat_support import _friendly_character_error
from utils.i18n import t as tr
from utils.db_functions import (
    get_character_effect_link,
    get_character_profile_by_id,
    get_combat_effect,
    link_character_effect,
    unlink_character_effect,
)


async def perform_effect_change(
    cog,
    interaction: discord.Interaction,
    acao: str,
    *,
    efeito_id: int,
    personagem: str | None = None,
):
    """Link or unlink a catalog effect for one managed character."""
    await interaction.response.defer(ephemeral=True)

    if efeito_id <= 0:
        await interaction.followup.send(
            tr("Error: effect ID must be greater than zero."),
            ephemeral=True,
        )
        return

    try:
        character_id = cog._resolve_managed_character(
            interaction, personagem
        )
        profile = get_character_profile_by_id(
            cog.db_connection, character_id
        )
    except (ValueError, TypeError) as error:
        await interaction.followup.send(
            tr("Error: {detail}", detail=_friendly_character_error(error)),
            ephemeral=True,
        )
        return

    effect = get_combat_effect(cog.db_connection, int(efeito_id))
    if effect is None:
        await interaction.followup.send(
            tr("Error: effect not found in the external catalog."),
            ephemeral=True,
        )
        return

    if acao == "add":
        with cog.db_connection:
            linked = link_character_effect(
                cog.db_connection, character_id, int(efeito_id)
            )
        if not linked:
            await interaction.followup.send(
                tr(
                    "Effect **{effect}** is already applied to **{character}**.",
                    effect=effect["name"],
                    character=profile["name"],
                ),
                ephemeral=True,
            )
            return
        message = tr(
            "Effect **{effect}** applied to **{character}**.",
            effect=effect["name"],
            character=profile["name"],
        )
    elif acao == "remove":
        if not get_character_effect_link(
            cog.db_connection, character_id, int(efeito_id)
        ):
            await interaction.followup.send(
                tr(
                    "Effect **{effect}** is not applied to **{character}**.",
                    effect=effect["name"],
                    character=profile["name"],
                ),
                ephemeral=True,
            )
            return
        with cog.db_connection:
            unlink_character_effect(
                cog.db_connection, character_id, int(efeito_id)
            )
        message = tr(
            "Effect **{effect}** removed from **{character}**.",
            effect=effect["name"],
            character=profile["name"],
        )
    else:
        await interaction.followup.send(
            tr("Error: invalid effect action."),
            ephemeral=True,
        )
        return

    await interaction.followup.send(message, ephemeral=True)
