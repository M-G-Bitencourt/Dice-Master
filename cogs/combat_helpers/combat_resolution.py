"""Atomic attack defence resolution and damage application."""

from __future__ import annotations

import sqlite3
from random import randint

import discord

from cogs.combat_helpers.combat_embeds import _build_defense_embed, _build_interim_defense_embed
from cogs.combat_helpers.combat_health import resolve_damage_health
from cogs.combat_helpers.combat_rules import (
    _available_effects,
    _consume_effects,
    _defense_options,
)
from cogs.combat_helpers.combat_support import _can_defend, _roll_result_text
from cogs.combat_helpers.combat_views import DefenseView, NextActionView
from utils.i18n import get_locale, t as tr
from utils.combat import (
    classify_roll,
    compute_armor_dr,
    compute_injury,
    compute_shock_penalty,
    defense_remaining_uses,
    effect_is_available,
)
from utils.db_functions import (
    add_combat_log,
    apply_character_injury,
    claim_pending_attack,
    ensure_combat_participant,
    expire_pending_attack,
    finish_pending_attack,
    get_character_combat_data,
    get_character_combat_effects,
    get_combat_participant,
    get_pending_attack,
    record_participant_use,
    set_character_shock,
    update_pending_attack_attempts,
)
from utils.dice_mechanics import consume_deterministic_fate, hdm_dices


async def resolve_defense(
    interaction: discord.Interaction,
    connection: sqlite3.Connection,
    attack_id: int,
    *,
    defense_value: int | None,
    defense_label: str,
    dm_id: int,
    nh_override: int | None = None,
    rd_override: int | None = None,
    modifier: int = 0,
    waive: bool = False,
    defense_key: str | None = None,
    effect_ids: list[int] | None = None,
    repeat_callback=None,
):
    """Resolve one defence attempt atomically and edit the attack message."""
    pending = get_pending_attack(connection, attack_id)
    if pending is None:
        await interaction.response.send_message(
            tr("Error: this attack no longer exists."),
            ephemeral=True,
        )
        return

    if not _can_defend(interaction.user, pending, dm_id):
        await interaction.response.send_message(
            tr("Error: only the attack target or the GM can defend."),
            ephemeral=True,
        )
        return

    if not waive and nh_override is None and defense_value is None:
        await interaction.response.send_message(
            tr("Error: enter a defense skill."),
            ephemeral=True,
        )
        return

    await interaction.response.defer()

    claimed = claim_pending_attack(connection, attack_id)
    if claimed is None:
        connection.rollback()
        current = get_pending_attack(connection, attack_id)
        if current and current["status"] == "pending" and current["expires_at"]:
            expire_pending_attack(connection, attack_id)
            connection.commit()
        await interaction.followup.send(
            tr("This attack was already resolved, superseded, or expired."),
            ephemeral=True,
        )
        return

    target_data = None
    target_effects: list[dict] = []
    target_participant: dict | None = None
    dices: list[int] = []
    effective_nh = 0
    outcome = {
        "critical_success": False,
        "success": False,
        "critical_failure": False,
        "margin": 0,
    }
    injury_data = None
    health_outcome = None
    chosen_damage = 0
    old_pv = 0
    new_pv = 0
    attempt_number = 1
    max_attempts = 1
    can_try_again = False
    remaining_options: list[dict] = []
    rd = 0
    rd_effects: list[dict] = []

    try:
        target_character_id = int(claimed["target_character_id"])
        target_data = get_character_combat_data(connection, target_character_id)
        if target_data is None:
            raise ValueError("Target character not found.")

        profile = target_data["profile"]
        target_effects = get_character_combat_effects(
            connection, target_character_id
        )
        session_id = claimed.get("session_id")
        target_participant = ensure_combat_participant(
            connection,
            session_id=int(session_id),
            character_id=target_character_id,
            owner_id=claimed.get("target_owner_id"),
            is_npc=bool(profile.get("is_npc")),
        )

        defense_kind = "dodge"
        if defense_key and defense_key.startswith("parry:"):
            defense_kind = "parry"

        if not waive and defense_key:
            remaining_uses = defense_remaining_uses(
                target_effects,
                target_participant,
                defense_key,
                defense_kind,
            )
            if remaining_uses <= 0:
                connection.rollback()
                await interaction.followup.send(
                    tr("This defense has already been used this turn."),
                    ephemeral=True,
                )
                return

            target_participant = record_participant_use(
                connection,
                session_id=int(session_id),
                character_id=target_character_id,
                field="defense_uses",
                key=defense_key,
            )

        selected_effects = [
            effect
            for effect in target_effects
            if int(effect["effect_id"]) in set(effect_ids or [])
            and effect_is_available(effect, target_participant)
        ]
        _consume_effects(
            connection,
            target_participant,
            selected_effects,
        )

        rd = (
            int(rd_override)
            if rd_override is not None
            else int(claimed["rd"] or 0)
        )
        if rd_override is None:
            rd_effects = _available_effects(
                target_effects,
                target_participant,
                "rd",
            )
            rd += sum(int(effect["value"]) for effect in rd_effects)
        effective_rd = rd + (2 if int(claimed["hit_location"]) == 2 else 0)

        if waive:
            effective_nh = 0
        else:
            base_value = (
                int(nh_override)
                if nh_override is not None
                else int(defense_value or 0)
            )
            feint_penalty = int(claimed["feint"] or 0)
            effective_nh = max(0, base_value - feint_penalty + int(modifier))
            target_owner_id = claimed.get("target_owner_id")
            fate = (
                consume_deterministic_fate(int(target_owner_id), connection)
                if target_owner_id is not None
                else None
            )
            if fate is not None:
                dices = hdm_dices(nh=effective_nh, fate=fate)
            else:
                dices = [randint(1, 6) for _ in range(3)]
            outcome = classify_roll(sum(dices), effective_nh)

        attempt_number = int(claimed["defense_attempts"] or 0) + 1
        max_attempts = max(1, int(claimed["max_defense_attempts"] or 1))

        if (
            not waive
            and not outcome["success"]
            and not outcome["critical_failure"]
            and attempt_number < max_attempts
        ):
            refreshed = get_combat_participant(
                connection, int(session_id), target_character_id
            )
            remaining_options = _defense_options(
                target_data,
                target_effects,
                refreshed,
                allow_parry=claimed.get("attack_kind", "melee") == "melee",
            )
            can_try_again = bool(remaining_options)

        if can_try_again:
            update_pending_attack_attempts(
                connection, attack_id, attempt_number, "pending"
            )
            add_combat_log(
                connection,
                session_id=claimed.get("session_id"),
                channel_id=int(claimed["channel_id"]),
                event_type="defense",
                actor_character_id=target_character_id,
                target_character_id=claimed.get("attacker_character_id"),
                description=tr(
                    "{target} attempted {defense} (attempt {attempt}/{maximum}): {result}.",
                    target=profile["name"],
                    defense=defense_label,
                    attempt=attempt_number,
                    maximum=max_attempts,
                    result=_roll_result_text(outcome),
                ),
            )
            connection.commit()
        else:
            suffers_damage = (
                waive or outcome["critical_failure"] or not outcome["success"]
            )
            old_pv = int(profile["current_pv"] or 0)
            new_pv = old_pv

            if suffers_damage:
                chosen_damage = (
                    int(claimed["critical_damage"])
                    if outcome["critical_failure"]
                    else int(claimed["raw_damage"])
                )
                if rd_effects:
                    _consume_effects(
                        connection,
                        target_participant,
                        rd_effects,
                    )
                penetrating_damage = max(0, chosen_damage - effective_rd)
                injury_data = compute_injury(
                    penetrating_damage,
                    int(claimed["damage_type"]),
                    int(claimed["hit_location"]),
                    int(profile["normal_diffuse_homogeneous_unded"] or 0),
                    int(profile["st"]),
                    int(profile["additional_max_pv"] or 0),
                    old_pv,
                )
                old_pv, new_pv = apply_character_injury(
                    connection,
                    target_character_id,
                    injury_data["final_injury"],
                )
                health_outcome = resolve_damage_health(
                    target_data["profile"],
                    old_pv,
                    new_pv,
                    int(target_data["encumbrance_penalty"]),
                )
                max_pv = int(profile["st"]) + int(
                    profile["additional_max_pv"] or 0
                )
                shock_added = compute_shock_penalty(
                    injury_data["final_injury"], max_pv
                )
                if shock_added:
                    set_character_shock(
                        connection,
                        target_character_id,
                        int(target_data["conditions"]["shock"]) + shock_added,
                    )

            add_combat_log(
                connection,
                session_id=claimed.get("session_id"),
                channel_id=int(claimed["channel_id"]),
                event_type="defense",
                actor_character_id=target_character_id,
                target_character_id=claimed.get("attacker_character_id"),
                description=tr(
                    "{target} used {defense}: {result}.",
                    target=profile["name"],
                    defense=defense_label,
                    result=tr("waived") if waive else _roll_result_text(outcome),
                ),
            )
            if injury_data is not None:
                add_combat_log(
                    connection,
                    session_id=claimed.get("session_id"),
                    channel_id=int(claimed["channel_id"]),
                    event_type="damage",
                    actor_character_id=claimed.get("attacker_character_id"),
                    target_character_id=target_character_id,
                    value=int(injury_data["final_injury"]),
                    hp_before=old_pv,
                    hp_after=new_pv,
                    description=tr(
                        "{target} suffered {injury} HP.",
                        target=profile["name"],
                        injury=injury_data["final_injury"],
                    ),
                )

            finish_pending_attack(connection, attack_id, "resolved")
            connection.commit()

    except Exception:
        connection.rollback()
        await interaction.followup.send(
            tr("Error resolving defense. No damage was applied."),
            ephemeral=True,
        )
        return

    if can_try_again:
        embed = _build_interim_defense_embed(
            profile=target_data["profile"],
            defense_label=defense_label,
            dices=dices,
            effective_nh=effective_nh,
            outcome=outcome,
            attempt_number=attempt_number,
            max_attempts=max_attempts,
            remaining_options=remaining_options,
            rd=effective_rd,
        )
        view = DefenseView(
            attack_id=attack_id,
            connection=connection,
            dm_id=dm_id,
            target_owner_id=claimed.get("target_owner_id"),
            target_name=target_data["profile"]["name"],
            defenses=remaining_options,
            repeat_callback=repeat_callback,
            resolve_callback=resolve_defense,
            locale=get_locale(),
        )
    else:
        rd_result = compute_armor_dr(
            target_data["armor_layers"], int(claimed["hit_location"])
        )
        embed = _build_defense_embed(
            defense_label=defense_label,
            waive=waive,
            dices=dices,
            effective_nh=effective_nh,
            outcome=outcome,
            injury_data=injury_data,
            chosen_damage=chosen_damage,
            old_pv=old_pv,
            new_pv=new_pv,
            profile=target_data["profile"],
            rd=effective_rd,
            rd_warnings=rd_result["warnings"],
            health_outcome=health_outcome,
        )
        view = NextActionView(
            connection=connection,
            claimed=claimed,
            dm_id=dm_id,
            repeat_callback=repeat_callback,
            locale=get_locale(),
        )

    try:
        if interaction.message is not None:
            await interaction.edit_original_response(embed=embed, view=view)
        else:
            message_id = claimed.get("message_id")
            if message_id is None or interaction.channel is None:
                await interaction.followup.send(embed=embed, view=view)
                return
            message = await interaction.channel.fetch_message(int(message_id))
            await message.edit(embed=embed, view=view)
    except (discord.HTTPException, discord.NotFound, discord.Forbidden):
        await interaction.followup.send(embed=embed, view=view)
