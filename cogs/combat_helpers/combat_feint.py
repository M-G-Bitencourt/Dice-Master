"""Feint command flow extracted from the primary combat cog."""

from __future__ import annotations

import discord

from cogs.combat_helpers.combat_embeds import _build_feint_embed
from cogs.combat_helpers.combat_rules import best_melee_skill
from cogs.combat_helpers.combat_support import _friendly_character_error
from utils.db_functions import (
    add_combat_log,
    clear_character_conditions,
    get_active_combat_session,
    get_character_combat_data,
    get_character_profile_by_id,
    get_combat_participant,
    get_pending_attack_for_channel,
    set_character_feint,
)
from utils.test_mechanics import quick_dispute


async def perform_feint(
    cog,
    interaction: discord.Interaction,
    alvo: str,
    personagem: str | None = None,
    pericia: str | None = None,
    nh_manual: int | None = None,
    defesa: int | None = None,
    modificador: int | None = None,
):
    """Resolve a feint contest and persist the resulting defence penalty."""
    await interaction.response.defer(ephemeral=True)

    if nh_manual is not None and not 0 <= nh_manual <= 60:
        await interaction.followup.send(
            "Erro: o NH da finta deve estar entre 0 e 60.",
            ephemeral=True,
        )
        return
    if defesa is not None and not 0 <= defesa <= 60:
        await interaction.followup.send(
            "Erro: o NH de resistência deve estar entre 0 e 60.",
            ephemeral=True,
        )
        return
    if modificador is not None and not -20 <= modificador <= 20:
        await interaction.followup.send(
            "Erro: o modificador de finta deve estar entre -20 e +20.",
            ephemeral=True,
        )
        return

    try:
        actor_id = cog._resolve_managed_character(
            interaction, personagem
        )
        target_id = int(alvo)
        if target_id == actor_id:
            raise ValueError("O personagem não pode fintar a si mesmo.")
        actor_profile = get_character_profile_by_id(
            cog.db_connection, actor_id
        )
        target_profile = get_character_profile_by_id(
            cog.db_connection, target_id
        )
        actor_data = get_character_combat_data(
            cog.db_connection, actor_id
        )
    except (ValueError, TypeError) as error:
        await interaction.followup.send(
            f"Erro: {_friendly_character_error(error)}",
            ephemeral=True,
        )
        return

    if actor_data is None:
        await interaction.followup.send(
            "Erro: o personagem não possui perícias de combate.",
            ephemeral=True,
        )
        return

    session = get_active_combat_session(
        cog.db_connection, interaction.channel_id
    )
    if session is None:
        await interaction.followup.send(
            "Erro: não existe combate ativo neste canal. "
            "Use `/combat_enter` para participar.",
            ephemeral=True,
        )
        return

    if (
        get_combat_participant(
            cog.db_connection, int(session["session_id"]), actor_id
        )
        is None
        or get_combat_participant(
            cog.db_connection, int(session["session_id"]), target_id
        )
        is None
    ):
        await interaction.followup.send(
            "Erro: atacante e alvo precisam estar no combate. "
            "Use `/combat_enter` para participar.",
            ephemeral=True,
        )
        return

    if get_pending_attack_for_channel(
        cog.db_connection, interaction.channel_id
    ) is not None:
        await interaction.followup.send(
            "Erro: resolva o ataque pendente antes de fintar.",
            ephemeral=True,
        )
        return

    active_id = session.get("active_character_id")
    if not cog._is_gm(interaction) and (
        active_id is None or int(active_id) != actor_id
    ):
        await interaction.followup.send(
            "Erro: não é o turno deste personagem. "
            "Use `/combat_next_turn` para avançar o turno.",
            ephemeral=True,
        )
        return

    skill = cog._find_skill_by_id(actor_data, pericia)
    if pericia is not None and skill is None:
        await interaction.followup.send(
            "Erro: a perícia selecionada não pertence ao personagem.",
            ephemeral=True,
        )
        return
    actor_shock = 0
    if nh_manual is None:
        if skill is None:
            skill = best_melee_skill(actor_data)
        if skill is None:
            await interaction.followup.send(
                "Erro: informe uma perícia ou um NH manual para a finta.",
                ephemeral=True,
            )
            return
        conditions = actor_data["conditions"]
        actor_shock = int(conditions["shock"])
        actor_nh = (
            int(skill["nh"])
            + min(int(conditions["evaluate"]), 3)
            + int(actor_data["encumbrance_penalty"])
            - int(conditions["shock"])
            + int(modificador or 0)
        )
    else:
        actor_nh = int(nh_manual) + int(modificador or 0)
    actor_nh = max(0, min(60, actor_nh))

    target_data = get_character_combat_data(
        cog.db_connection, target_id
    )
    if defesa is not None:
        target_nh = int(defesa)
    else:
        target_skill = (
            best_melee_skill(target_data)
            if target_data is not None
            else None
        )
        target_nh = (
            int(target_skill["nh"])
            if target_skill is not None
            else int(target_profile["dx"])
        )
    target_nh = max(0, min(60, target_nh))

    dispute = quick_dispute(
        int(actor_profile.get("owner_id") or 0),
        actor_nh,
        target_nh,
        connection=cog.db_connection,
    )
    actor_result = dispute["result1"]
    target_result = dispute["result2"]
    actor_success = bool(actor_result["success_roll1"])
    target_success = bool(target_result["success_roll2"])
    actor_margin = int(actor_result["margin1"])
    target_margin = int(target_result["margin2"])

    success = False
    feint_value = 0
    if actor_success and not target_success:
        success = True
        feint_value = max(0, actor_margin)
    elif (
        actor_success
        and target_success
        and actor_margin > target_margin
    ):
        success = True
        feint_value = max(0, actor_margin - target_margin)

    with cog.db_connection:
        clear_character_conditions(cog.db_connection, actor_id)
        if success:
            set_character_feint(
                cog.db_connection, actor_id, feint_value
            )
        add_combat_log(
            cog.db_connection,
            session_id=int(session["session_id"]),
            channel_id=interaction.channel_id,
            event_type="feint",
            actor_character_id=actor_id,
            target_character_id=target_id,
            value=feint_value,
            description=(
                f"{actor_profile['name']} fintou "
                f"{target_profile['name']} (penalidade {feint_value})."
                if success
                else (
                    f"{actor_profile['name']} tentou fintar "
                    f"{target_profile['name']} sem sucesso."
                )
            ),
        )

    await cog._edit_stored_panel(session)

    embed = _build_feint_embed(
        actor_name=actor_profile["name"],
        target_name=target_profile["name"],
        actor_nh=actor_nh,
        target_nh=target_nh,
        actor_roll=sum(actor_result["dices1"]),
        actor_dices=actor_result["dices1"],
        target_roll=sum(target_result["dices2"]),
        target_dices=target_result["dices2"],
        actor_success=actor_success,
        target_success=target_success,
        actor_margin=actor_margin,
        target_margin=target_margin,
        feint_value=feint_value,
        success=success,
        shock=actor_shock,
    )
    await interaction.followup.send(embed=embed, ephemeral=False)
