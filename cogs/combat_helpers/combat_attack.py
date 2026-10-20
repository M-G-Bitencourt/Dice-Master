"""Attack construction and publication for the /combat_attack flow."""

from __future__ import annotations

import json
from random import randint
from types import SimpleNamespace

import discord
from discord import app_commands

from cogs.battle import damage_func
from cogs.combat_helpers.combat_embeds import _build_attack_embed
from cogs.combat_helpers.combat_health import resolve_damage_health
from cogs.combat_helpers.combat_resolution import resolve_defense
from cogs.combat_helpers.combat_rules import (
    _available_effects,
    _consume_effects,
    _defense_options,
    _select_available_effects,
)
from cogs.combat_helpers.combat_support import (
    _clamp,
    _friendly_character_error,
    _roll_result_text,
)
from cogs.combat_helpers.combat_views import DefenseView
from utils.combat import (
    DAMAGE_TYPE_LABELS,
    HIT_LOCATIONS,
    MANEUVERS,
    build_modifier_breakdown,
    classify_roll,
    compute_armor_dr,
    compute_injury,
    compute_shock_penalty,
    max_defense_attempts,
    normalize_damage_type,
    parse_damage_expression,
)
from utils.db_functions import (
    add_combat_log,
    apply_character_injury,
    clear_character_conditions,
    create_pending_attack,
    get_active_combat_session,
    get_character_combat_data,
    get_character_combat_effects,
    get_combat_participant,
    reset_combat_participant_turn,
    set_character_combat_stance,
    set_character_feint,
    set_character_shock,
    supersede_pending_attacks,
    update_pending_attack_message,
)
from utils.dice_mechanics import consume_deterministic_fate, hdm_dices


async def perform_attack(
    cog,
    interaction: discord.Interaction,
    alvo: str,
    arma: str | None = None,
    personagem: str | None = None,
    local: app_commands.Choice[int] | None = None,
    manobra: app_commands.Choice[str] | None = None,
    modificador: int | None = None,
    nh_manual: int | None = None,
):
    """Resolve an attack and publish defence controls."""
    await interaction.response.defer()

    if modificador is not None and not -20 <= modificador <= 20:
        await interaction.edit_original_response(
            content="Erro: o modificador situacional deve estar entre -20 e +20."
        )
        return
    if nh_manual is not None and not 0 <= nh_manual <= 60:
        await interaction.edit_original_response(
            content="Erro: o NH manual deve estar entre 0 e 60."
        )
        return

    attack_kind = "melee"
    ranged_weapon = None
    mode = None
    weapon_character_id = None
    selection_value = arma

    try:
        if arma is not None and arma.startswith("ranged:"):
            parts = arma.split(":", 2)
            if len(parts) != 3:
                raise ValueError("A arma à distância selecionada é inválida.")
            attack_kind = "ranged"
            weapon_character_id = int(parts[1])
            selection_value = f"ranged:{parts[1]}:{parts[2]}"
        elif arma is not None and arma.startswith("melee:"):
            parts = arma.split(":", 2)
            if len(parts) != 3:
                raise ValueError("A arma corpo a corpo selecionada é inválida.")
            weapon_character_id = int(parts[1])
            selection_value = f"{parts[1]}:{parts[2]}"
        elif arma is not None:
            weapon_character_id = int(arma.split(":", 1)[0])

        actor_character_id = cog._resolve_actor(
            interaction, personagem, weapon_character_id
        )
        target_character_id = int(alvo)

        if attack_kind == "ranged":
            ranged_weapon = cog._find_ranged_weapon(
                actor_character_id, selection_value
            )
        else:
            try:
                mode = cog._find_mode(
                    actor_character_id, selection_value
                )
            except ValueError:
                if arma is not None:
                    raise
                ranged_weapon = cog._find_ranged_weapon(
                    actor_character_id, None
                )
                attack_kind = "ranged"
    except (ValueError, AttributeError) as error:
        await interaction.edit_original_response(
            content=f"Erro: {_friendly_character_error(error)}."
        )
        return

    active_session = get_active_combat_session(
        cog.db_connection, interaction.channel_id
    )
    if active_session is None:
        await interaction.edit_original_response(
            content=(
                "Erro: não existe combate ativo neste canal. "
                "Use `/combat_enter` para participar."
            )
        )
        return

    actor_participant = get_combat_participant(
        cog.db_connection,
        int(active_session["session_id"]),
        actor_character_id,
    )
    target_participant = get_combat_participant(
        cog.db_connection,
        int(active_session["session_id"]),
        target_character_id,
    )
    if actor_participant is None or target_participant is None:
        await interaction.edit_original_response(
            content=(
                "Erro: atacante e alvo precisam estar no combate. "
                "Use `/combat_enter` para participar."
            )
        )
        return

    if (
        active_session.get("active_character_id") is not None
        and int(active_session["active_character_id"])
        != actor_character_id
        and not cog._is_gm(interaction)
    ):
        await interaction.edit_original_response(
            content=(
                "Erro: não é o turno deste personagem. "
                "Use `/combat_next_turn` para avançar o turno."
            )
        )
        return

    try:
        actor_data = get_character_combat_data(
            cog.db_connection, actor_character_id
        )
        target_data = get_character_combat_data(
            cog.db_connection, target_character_id
        )
    except ValueError as error:
        await interaction.edit_original_response(
            content=f"Erro: {_friendly_character_error(error)}."
        )
        return

    if actor_data is None:
        await interaction.edit_original_response(
            content="Erro: o personagem atacante não foi localizado."
        )
        return
    if target_data is None:
        await interaction.edit_original_response(
            content="Erro: o personagem alvo não foi localizado."
        )
        return

    parsed_damage = None
    if attack_kind == "ranged":
        parsed_damage = parse_damage_expression(
            ranged_weapon["damage"]
        )
        if parsed_damage is None:
            await interaction.edit_original_response(
                content=(
                    "Erro: o dano da arma à distância é inválido. "
                    "Use uma expressão como `2d+1 imp`."
                )
            )
            return

        ranged_skill_id = ranged_weapon.get("skill_id")
        if ranged_skill_id is None:
            await interaction.edit_original_response(
                content=(
                    "Erro: a arma à distância não possui uma perícia "
                    "configurada. Cadastre a perícia na arma."
                )
            )
            return
        skill = actor_data["skill_by_id"].get(int(ranged_skill_id))
        if skill is None:
            skill_label = ranged_weapon.get("skill_name") or "não configurada"
            await interaction.edit_original_response(
                content=(
                    "Erro: o personagem não possui a perícia "
                    f"**{skill_label}** exigida por esta arma à distância."
                )
            )
            return

        weapon_name = ranged_weapon["weapon_name"]
        mode_name = "Disparo"
        skill_name = skill["name"]
        damage_type = int(parsed_damage["damage_type"])
        gdp_geb = 0
    else:
        skill = None
        mode_skill_id = mode.get("skill_id")
        if mode_skill_id is not None:
            skill = actor_data["skill_by_id"].get(int(mode_skill_id))
        unarmed_default = (
            skill is None
            and bool(mode.get("is_unarmed"))
            and bool(mode.get("is_fallback"))
        )
        if skill is None and nh_manual is None and not unarmed_default:
            mode_skill = mode.get("skill_name") or "não configurada"
            await interaction.edit_original_response(
                content=(
                    "Erro: o personagem não possui a perícia "
                    f"**{mode_skill}** usada por este modo de arma. "
                    "Cadastre a perícia ou use `nh_manual`."
                )
            )
            return

        weapon_name = mode["weapon_name"]
        mode_name = mode["mode_name"]
        if skill is not None:
            skill_name = skill["name"]
        elif unarmed_default:
            skill_name = (
                f"{mode.get('skill_name') or 'Combate Desarmado'} (DX-4)"
            )
        else:
            skill_name = mode.get("skill_name") or "Arma"
        damage_type = normalize_damage_type(mode["damage_type"])
        gdp_geb = (
            1 if str(mode["damage_base"]).strip().lower() == "geb" else 0
        )

    if nh_manual is not None:
        base_nh = int(nh_manual)
    elif skill is not None:
        base_nh = int(skill["nh"])
    else:
        base_nh = int(actor_data["profile"]["dx"]) - 4
    hit_location_id = int(local.value) if local is not None else 0
    location = HIT_LOCATIONS[hit_location_id]
    maneuver_key = manobra.value if manobra is not None else "normal"
    if attack_kind == "ranged" and maneuver_key == "all_out_strong":
        await interaction.edit_original_response(
            content=(
                "Erro: Ataque Total (Forte) não se aplica a armas à distância."
            )
        )
        return
    maneuver = MANEUVERS[maneuver_key]
    conditions = actor_data["conditions"]

    condition_modifier = (
        ("Mira", min(int(conditions["aim"]), 3))
        if attack_kind == "ranged"
        else ("Avaliar", min(int(conditions["evaluate"]), 3))
    )
    modifiers: list[tuple[str, int]] = [
        (maneuver["label"], int(maneuver["attack_modifier"])),
        ("Local", int(location["penalty"])),
        condition_modifier,
        ("Choque", -int(conditions["shock"])),
        ("Carga", int(actor_data["encumbrance_penalty"])),
        ("Situacional", int(modificador or 0)),
    ]
    mode_attack_modifier = int(mode.get("attack_modifier") or 0) if mode else 0
    if mode_attack_modifier:
        modifiers.append(("Modo", mode_attack_modifier))
    breakdown = build_modifier_breakdown(base_nh, modifiers)
    actor_effects = get_character_combat_effects(
        cog.db_connection, actor_character_id
    )
    target_effects = get_character_combat_effects(
        cog.db_connection, target_character_id
    )

    rd_result = compute_armor_dr(
        target_data["armor_layers"], hit_location_id
    )
    rd = int(rd_result["total"])

    actor_profile = actor_data["profile"]
    target_profile = target_data["profile"]
    target_is_npc = bool(target_profile.get("is_npc"))
    target_owner_id = (
        None if target_is_npc else target_profile.get("owner_id")
    )
    target_no_defense = bool(target_data["conditions"]["no_defense"])
    actor_owner_id = actor_profile.get("owner_id")

    pending_id: int | None = None
    defenses: list[dict] = []
    target_cannot_defend = False
    max_attempts = 1
    critical_failure_dices: list[int] | None = None
    critical_injury: dict | None = None
    critical_old_pv: int | None = None
    critical_new_pv: int | None = None
    critical_health: dict | None = None
    old_message_ids: list[int] = []
    damage_data: dict | None = None
    outcome: dict = {
        "critical_success": False,
        "success": False,
        "critical_failure": False,
        "margin": 0,
    }
    attack_roll = 0

    with cog.db_connection:
        session = active_session
        old_message_ids = supersede_pending_attacks(
            cog.db_connection, interaction.channel_id
        )
        clear_character_conditions(
            cog.db_connection, actor_character_id
        )
        set_character_combat_stance(
            cog.db_connection,
            actor_character_id,
            no_defense=0 if maneuver["allows_defense"] else 1,
            defense_bonus=int(maneuver["defense_modifier"]),
        )

        combat_effects = _select_available_effects(
            actor_effects,
            actor_participant,
            {"attack", "damage"},
        )
        attack_effects = [
            effect
            for effect in combat_effects
            if effect.get("applies_to") == "attack"
        ]
        damage_effects = [
            effect
            for effect in combat_effects
            if effect.get("applies_to") == "damage"
        ]
        if attack_effects:
            breakdown = build_modifier_breakdown(
                base_nh,
                modifiers
                + [
                    (effect["name"], int(effect["value"]))
                    for effect in attack_effects
                ],
            )

        target_no_defense = bool(target_data["conditions"]["no_defense"])
        defenses = _defense_options(
            target_data,
            target_effects,
            target_participant,
            allow_parry=attack_kind == "melee",
        )
        target_cannot_defend = target_no_defense or not defenses
        max_attempts = max_defense_attempts(target_effects)

        fate = (
            consume_deterministic_fate(actor_owner_id, cog.db_connection)
            if actor_owner_id is not None
            else None
        )
        if fate is not None:
            dices = hdm_dices(nh=breakdown["effective"], fate=fate)
        else:
            dices = [randint(1, 6) for _ in range(3)]
        attack_roll = sum(dices)
        outcome = classify_roll(attack_roll, breakdown["effective"])

        if outcome["critical_failure"]:
            critical_failure_dices = [randint(1, 6) for _ in range(3)]

        if outcome["success"]:
            if attack_kind == "ranged":
                damage_dices = [
                    randint(1, 6)
                    for _ in range(int(parsed_damage["dice_count"]))
                ]
                ranged_raw = (
                    sum(damage_dices) + int(parsed_damage["modifier"])
                )
                ranged_critical = (
                    6 * int(parsed_damage["dice_count"])
                    + int(parsed_damage["modifier"])
                )
                damage_dice_count = int(parsed_damage["dice_count"])
                damage_data = {
                    "critical_damage": ranged_critical,
                    "critical_dices": [6] * damage_dice_count,
                    "damage": ranged_raw,
                    "dice_count": damage_dice_count,
                    "dices": damage_dices,
                    "expression": parsed_damage["expression"],
                    "st_mod": 0,
                    "dice_sum": sum(damage_dices),
                    "strong_bonus": 0,
                    "total_modifier": int(parsed_damage["modifier"]),
                    "weapon_modifier": int(parsed_damage["modifier"]),
                }
            else:
                damage_data = damage_func(
                    int(actor_profile["st"]),
                    gdp_geb,
                    int(mode["damage_modifier"] or 0),
                    1 if maneuver["strong"] else 0,
                )
            damage_bonus = sum(
                int(effect["value"]) for effect in damage_effects
            )
            damage_data["damage"] = max(
                0, int(damage_data["damage"]) + damage_bonus
            )
            damage_data["critical_damage"] = max(
                0, int(damage_data["critical_damage"]) + damage_bonus
            )
            damage_data["total_modifier"] = (
                int(damage_data["total_modifier"]) + damage_bonus
            )

            if outcome["critical_success"] or target_cannot_defend:
                chosen_damage = (
                    int(damage_data["critical_damage"])
                    if outcome["critical_success"]
                    else int(damage_data["damage"])
                )
                target_rd_effects = _available_effects(
                    target_effects,
                    target_participant,
                    "rd",
                )
                auto_rd = rd + sum(
                    int(effect["value"])
                    for effect in target_rd_effects
                )
                penetrating = max(
                    0,
                    chosen_damage
                    - auto_rd
                    - (2 if hit_location_id == 2 else 0),
                )
                _consume_effects(
                    cog.db_connection,
                    target_participant,
                    target_rd_effects,
                )
                critical_injury = compute_injury(
                    penetrating,
                    damage_type,
                    hit_location_id,
                    int(
                        target_profile[
                            "normal_diffuse_homogeneous_unded"
                        ]
                        or 0
                    ),
                    int(target_profile["st"]),
                    int(target_profile["additional_max_pv"] or 0),
                    int(target_profile["current_pv"] or 0),
                )
                critical_old_pv, critical_new_pv = apply_character_injury(
                    cog.db_connection,
                    target_character_id,
                    critical_injury["final_injury"],
                )
                critical_health = resolve_damage_health(
                    target_profile,
                    critical_old_pv,
                    critical_new_pv,
                    int(target_data["encumbrance_penalty"]),
                )
                max_pv = int(target_profile["st"]) + int(
                    target_profile["additional_max_pv"] or 0
                )
                shock_added = compute_shock_penalty(
                    critical_injury["final_injury"], max_pv
                )
                if shock_added:
                    set_character_shock(
                        cog.db_connection,
                        target_character_id,
                        int(target_data["conditions"]["shock"]) + shock_added,
                    )
            else:
                pending_id = create_pending_attack(
                    cog.db_connection,
                    session_id=session["session_id"],
                    guild_id=interaction.guild_id,
                    channel_id=interaction.channel_id,
                    attacker_id=interaction.user.id,
                    attacker_character_id=actor_character_id,
                    target_character_id=target_character_id,
                    target_owner_id=target_owner_id,
                    weapon_name=weapon_name,
                    mode_name=mode_name,
                    skill_name=skill_name,
                    mode_id=mode.get("mode_id") if mode else None,
                    attack_kind=attack_kind,
                    ranged_weapon_id=(
                        int(ranged_weapon["ranged_weapon_id"])
                        if ranged_weapon is not None
                        else None
                    ),
                    damage_expression=(
                        parsed_damage["expression"]
                        if parsed_damage is not None
                        else None
                    ),
                    maneuver=maneuver_key,
                    custom_modifier=int(modificador or 0),
                    nh_base=base_nh,
                    nh_effective=breakdown["effective"],
                    attack_roll=attack_roll,
                    attack_margin=outcome["margin"],
                    raw_damage=int(damage_data["damage"]),
                    critical_damage=int(damage_data["critical_damage"]),
                    max_defense_attempts=max_attempts,
                    defense_attempts=0,
                    rd=rd,
                    damage_type=damage_type,
                    hit_location=hit_location_id,
                    feint=int(conditions["feint"]),
                    is_critical=0,
                    modifiers_json=json.dumps(
                        breakdown, ensure_ascii=False
                    ),
                )

        _consume_effects(
            cog.db_connection,
            actor_participant,
            attack_effects,
        )
        if outcome["success"]:
            _consume_effects(
                cog.db_connection,
                actor_participant,
                damage_effects,
            )
        if int(conditions["feint"]):
            set_character_feint(
                cog.db_connection, actor_character_id, 0
            )

        add_combat_log(
            cog.db_connection,
            session_id=int(session["session_id"]),
            channel_id=interaction.channel_id,
            event_type="attack",
            actor_character_id=actor_character_id,
            target_character_id=target_character_id,
            value=(
                int(damage_data["damage"])
                if damage_data is not None
                else 0
            ),
            description=(
                f"{actor_profile['name']} atacou {target_profile['name']} "
                f"com {weapon_name}: {_roll_result_text(outcome)}."
            ),
        )
        if critical_injury is not None:
            add_combat_log(
                cog.db_connection,
                session_id=int(session["session_id"]),
                channel_id=interaction.channel_id,
                event_type="damage",
                actor_character_id=actor_character_id,
                target_character_id=target_character_id,
                value=int(critical_injury["final_injury"]),
                hp_before=critical_old_pv,
                hp_after=critical_new_pv,
                description=(
                    f"{target_profile['name']} sofreu "
                    f"{critical_injury['final_injury']} PV por ataque."
                ),
            )

    embed = _build_attack_embed(
        actor_name=actor_profile["name"],
        target_name=target_profile["name"],
        target_owner_id=target_owner_id,
        weapon_name=weapon_name,
        mode_name=mode_name,
        maneuver_label=maneuver["label"],
        hit_location_name=location["name"],
        damage_type_label=DAMAGE_TYPE_LABELS.get(damage_type, "Especial"),
        attack_roll=attack_roll,
        attack_dices=dices,
        breakdown=breakdown,
        outcome=outcome,
        damage_data=damage_data if outcome["success"] else None,
        rd=rd,
        rd_warnings=rd_result["warnings"],
        defense_options=defenses if pending_id is not None else [],
        injury_data=critical_injury,
        old_pv=critical_old_pv,
        new_pv=critical_new_pv,
        profile=target_profile if critical_injury is not None else None,
        health_outcome=critical_health,
        defense_note=(
            (
                "Sem defesa: o alvo está em Ataque Total."
                if target_no_defense
                else "Sem defesas disponíveis neste turno."
            )
            if target_cannot_defend and outcome["success"]
            else None
        ),
        feint_penalty=(
            int(conditions["feint"]) if pending_id is not None else 0
        ),
        awaiting_defense=pending_id is not None,
        critical_failure_dices=critical_failure_dices,
    )

    if target_owner_id is not None:
        content = f"<@{target_owner_id}>"
    else:
        content = _clamp(f"Alvo: **{target_profile['name']}**", 1900)

    view = None
    if pending_id is not None:
        view = DefenseView(
            attack_id=pending_id,
            connection=cog.db_connection,
            dm_id=cog.dm_id,
            target_owner_id=target_owner_id,
            target_name=target_profile["name"],
            defenses=defenses,
            repeat_callback=cog._repeat_attack_from_action,
            resolve_callback=resolve_defense,
        )

    try:
        await interaction.edit_original_response(
            content=content,
            embed=embed,
            view=view,
        )
    except (discord.HTTPException, discord.NotFound, discord.Forbidden):
        await interaction.followup.send(content=content, embed=embed, view=view)

    if pending_id is not None:
        try:
            message = await interaction.original_response()
            with cog.db_connection:
                update_pending_attack_message(
                    cog.db_connection, pending_id, message.id
                )
        except (discord.HTTPException, discord.NotFound):
            pass

    await disable_superseded_messages(interaction, old_message_ids)


async def repeat_attack(
    cog,
    interaction: discord.Interaction,
    claimed: dict,
):
    mode_id = claimed.get("mode_id")
    ranged_weapon_id = claimed.get("ranged_weapon_id")
    if mode_id is None and ranged_weapon_id is None:
        await interaction.response.send_message(
            "Erro: este ataque não possui dados suficientes para repetição.",
            ephemeral=True,
        )
        return

    actor_character_id = int(claimed["attacker_character_id"])
    target_character_id = int(claimed["target_character_id"])
    if claimed.get("session_id") is not None:
        with cog.db_connection:
            reset_combat_participant_turn(
                cog.db_connection,
                int(claimed["session_id"]),
                actor_character_id,
            )
            reset_combat_participant_turn(
                cog.db_connection,
                int(claimed["session_id"]),
                target_character_id,
            )
            set_character_combat_stance(
                cog.db_connection,
                target_character_id,
                no_defense=0,
                defense_bonus=0,
            )
    personagem = (
        str(actor_character_id) if cog._is_gm(interaction) else None
    )
    if claimed.get("attack_kind") == "ranged":
        weapon_value = (
            f"ranged:{actor_character_id}:{int(ranged_weapon_id)}"
        )
    else:
        weapon_value = f"{actor_character_id}:{int(mode_id)}"

    await perform_attack(
        cog,
        interaction,
        alvo=str(target_character_id),
        arma=weapon_value,
        personagem=personagem,
        local=SimpleNamespace(value=int(claimed["hit_location"])),
        manobra=SimpleNamespace(
            value=claimed.get("maneuver") or "normal"
        ),
        modificador=int(claimed.get("custom_modifier") or 0),
        nh_manual=int(claimed.get("nh_base") or 0),
    )


async def disable_superseded_messages(
    interaction: discord.Interaction,
    message_ids: list[int],
) -> None:
    """Best-effort removal of stale defence controls."""
    channel = interaction.channel
    if channel is None:
        return

    for message_id in message_ids:
        try:
            message = await channel.fetch_message(int(message_id))
            await message.edit(
                content="Ataque substituído por um novo ataque.",
                view=None,
            )
        except (discord.HTTPException, discord.NotFound, discord.Forbidden):
            continue
