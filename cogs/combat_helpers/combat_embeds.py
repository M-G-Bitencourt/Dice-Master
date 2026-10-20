"""Discord embed payload builders for combat results and the combat panel."""

from __future__ import annotations

import discord

from cogs.combat_helpers.combat_support import (
    _clamp,
    _format_modifiers,
    _max_pv,
    _roll_result_text,
)
from utils.ansi import code_block, resource_bar
from utils.i18n import catalog_label, t as tr


def _dice_pool(dices: list[int]) -> str:
    """Format individual dice values and their total."""
    values = list(dices)
    return f"`{values} = {sum(values)}`"


def _add_health_fields(embed: discord.Embed, health_outcome: dict | None) -> None:
    """Append injury threshold, HT checks and status to a damage embed."""
    if health_outcome is None:
        return

    if health_outcome["wounded"]:
        embed.add_field(
            name=tr("Injury State"),
            value=_clamp(
                tr(
                    "HP {current}/{maximum} - 1/3 or less\nMove: {move}\nDodge: {dodge}",
                    current=health_outcome["current_pv"],
                    maximum=health_outcome["max_pv"],
                    move=health_outcome["move"],
                    dodge=health_outcome["dodge"],
                ),
                1000,
            ),
            inline=False,
        )

    checks = health_outcome.get("checks") or []
    if checks:
        lines = []
        for check in checks:
            label = check["label"]
            if check.get("label_key"):
                label = catalog_label("health_labels", check["label_key"])
                label = label.format(**(check.get("label_params") or {}))
            result = str(check["effect"])
            if check.get("effect_key"):
                result = catalog_label("health_effects", check["effect_key"])
            if not check["success"]:
                result += " " + tr("(failure by {margin})", margin=-check["margin"])
            lines.append(
                f"{label}: {_dice_pool(check['dices'])} "
                f"vs HT {check['target']} -> {result}"
            )
        embed.add_field(
            name=tr("HT Checks"),
            value=_clamp("\n".join(lines), 1000),
            inline=False,
        )

    if health_outcome.get("status"):
        status = str(health_outcome["status"])
        if health_outcome.get("status_key"):
            status = catalog_label("health_status", health_outcome["status_key"])
        embed.add_field(
            name=tr("Character Status"),
            value=_clamp(status.capitalize(), 1000),
            inline=False,
        )


def _build_attack_embed(
    *,
    actor_name: str,
    target_name: str,
    target_owner_id: int | None,
    weapon_name: str,
    mode_name: str | None,
    maneuver_label: str,
    hit_location_name: str,
    damage_type_label: str,
    attack_roll: int,
    attack_dices: list[int],
    breakdown: dict,
    outcome: dict,
    damage_data: dict | None,
    rd: int,
    rd_warnings: list[str],
    defense_options: list[dict],
    injury_data: dict | None = None,
    old_pv: int | None = None,
    new_pv: int | None = None,
    profile: dict | None = None,
    health_outcome: dict | None = None,
    defense_note: str | None = None,
    feint_penalty: int = 0,
    awaiting_defense: bool = False,
    critical_failure_dices: list[int] | None = None,
) -> discord.Embed:
    """Build the compact public attack result embed."""
    title = _clamp(
        tr("Attack: {actor} -> {target}", actor=actor_name, target=target_name),
        256,
    )
    description = _clamp(
        f"{weapon_name} ({mode_name or tr('Default')})\n{maneuver_label}",
        4000,
    )

    embed = discord.Embed(
        title=title,
        description=description,
        color=(
            discord.Color.gold()
            if outcome["critical_success"]
            else discord.Color.green()
            if outcome["success"]
            else discord.Color.brand_red()
            if outcome["critical_failure"]
            else discord.Color.red()
        ),
    )

    embed.add_field(
        name=tr("Roll"),
        value=_clamp(
            f"{tr('Dice')}: {_dice_pool(attack_dices)}\n"
            f"{tr("Effective skill")}: `{breakdown['effective']}`\n"
            f"{tr('Result')}: {_roll_result_text(outcome)}",
            1000,
        ),
        inline=False,
    )
    embed.add_field(
        name=tr("Modifiers"),
        value=_format_modifiers(breakdown),
        inline=False,
    )

    if outcome["success"] and damage_data is not None:
        if outcome["critical_success"]:
            damage_dices = damage_data.get("critical_dices") or []
            damage_total = damage_data["critical_damage"]
            dice_label = tr("Critical dice")
        else:
            damage_dices = damage_data.get("dices") or []
            damage_total = damage_data["damage"]
            dice_label = tr("Dice")
        damage_lines = [
            tr(
                "Weapon damage: {expression}",
                expression=damage_data.get("expression", tr("not available")),
            ),
            f"{dice_label}: {_dice_pool(damage_dices)}",
            f"{tr('Modifiers')}: {int(damage_data.get('total_modifier', 0)):+d}",
            tr(
                "Total damage: {damage} {damage_type}",
                damage=damage_total,
                damage_type=damage_type_label,
            ),
            tr("Location: {location}", location=hit_location_name),
            f"{tr('DR')}: {rd}",
        ]
        embed.add_field(
            name=tr("Damage"),
            value=_clamp("\n".join(damage_lines), 1000),
            inline=False,
        )

    if injury_data is not None and new_pv is not None and profile is not None:
        max_pv = _max_pv(profile)
        embed.add_field(
            name=tr("HP"),
            value=code_block([resource_bar(tr("HP"), new_pv, max_pv)]),
            inline=False,
        )
        embed.add_field(
            name=tr("Injury"),
            value=_clamp(
                tr(
                    "HP {old} -> {new}\n{penetrating} penetrating x {multiplier:.1f} = {injury} HP",
                    old=old_pv,
                    new=new_pv,
                    penetrating=injury_data["penetrating_damage"],
                    multiplier=injury_data["multiplier"],
                    injury=injury_data["final_injury"],
                ),
                1000,
            ),
            inline=False,
        )

    _add_health_fields(embed, health_outcome)

    if rd_warnings:
        embed.add_field(
            name=tr("Armor Warning"),
            value=_clamp(" ".join(rd_warnings), 1000),
            inline=False,
        )

    if defense_options:
        embed.add_field(
            name=tr("Available Defenses"),
            value=_clamp(
                "\n".join(option["label"] for option in defense_options),
                1000,
            ),
            inline=False,
        )

    if feint_penalty:
        embed.add_field(
            name=tr("Feint"),
            value=_clamp(
                tr(
                    "-{penalty} to defenses against this attack.",
                    penalty=feint_penalty,
                ),
                1000,
            ),
            inline=False,
        )

    if defense_note:
        embed.add_field(
            name=tr("Defense"),
            value=_clamp(defense_note, 1000),
            inline=False,
        )

    if critical_failure_dices:
        embed.add_field(
            name=tr("Critical Failure Table"),
            value=_clamp(
                f"{tr('Dice')}: {critical_failure_dices} = {sum(critical_failure_dices)}",
                1000,
            ),
            inline=False,
        )

    if awaiting_defense and target_owner_id is not None:
        embed.set_footer(
            text=tr("Awaiting target defense. The attack expires in 15 minutes.")
        )
    elif awaiting_defense:
        embed.set_footer(
            text=tr("NPC: awaiting GM defense. Expires in 15 minutes.")
        )
    else:
        embed.set_footer(text=tr("Attack result resolved."))

    return embed


def _build_defense_embed(
    *,
    defense_label: str,
    waive: bool,
    dices: list[int],
    effective_nh: int,
    outcome: dict,
    injury_data: dict | None,
    chosen_damage: int,
    old_pv: int,
    new_pv: int,
    profile: dict,
    rd: int,
    rd_warnings: list[str],
    health_outcome: dict | None = None,
) -> discord.Embed:
    """Build the compact public defence and injury result embed."""
    target_name = profile["name"]

    if waive:
        title = tr("Defense waived: {target}", target=target_name)
        description = tr("The target chose not to defend.")
        color = discord.Color.dark_red()
    elif outcome["critical_failure"]:
        title = tr("Critical defense failure: {target}", target=target_name)
        description = tr("The defense collapsed and the attack hit the target.")
        color = discord.Color.brand_red()
    elif outcome["critical_success"]:
        title = tr("Decisive defense: {target}", target=target_name)
        description = tr("The target avoided the attack with a decisive defense.")
        color = discord.Color.gold()
    elif outcome["success"]:
        title = tr("Successful defense: {target}", target=target_name)
        description = tr("The target avoided the attack.")
        color = discord.Color.green()
    else:
        title = tr("Defense failed: {target}", target=target_name)
        description = tr("The attack hit the target.")
        color = discord.Color.red()

    embed = discord.Embed(
        title=_clamp(title, 256),
        description=_clamp(description, 4000),
        color=color,
    )

    if waive:
        defense_value = tr("Waived the defense")
    else:
        defense_value = (
            f"{defense_label}\n"
            f"{tr('Dice')}: {_dice_pool(dices)}\n"
            f"{tr("Effective skill")}: `{effective_nh}`\n"
            f"{tr('Result')}: {_roll_result_text(outcome)}"
        )
    embed.add_field(name=tr("Defense"), value=_clamp(defense_value, 1000), inline=False)

    if injury_data is not None:
        embed.add_field(
            name=tr("Damage"),
            value=_clamp(
                tr(
                    "Raw damage: {raw}\nDR: {dr}\nPenetrating: {penetrating}\nMultiplier: x{multiplier:.1f}\nApplied damage: {applied} HP",
                    raw=chosen_damage,
                    dr=rd,
                    penetrating=injury_data["penetrating_damage"],
                    multiplier=injury_data["multiplier"],
                    applied=injury_data["final_injury"],
                ),
                1000,
            ),
            inline=False,
        )
    else:
        embed.add_field(
            name=tr("Applied damage"),
            value=tr("No damage applied."),
            inline=False,
        )

    embed.add_field(
        name=tr("HP"),
        value=code_block([resource_bar(tr("HP"), new_pv, _max_pv(profile))]),
        inline=False,
    )
    embed.add_field(
        name=tr("Transition"),
        value=_clamp(f"{tr('HP')} {old_pv} -> {new_pv}", 1000),
        inline=False,
    )

    _add_health_fields(embed, health_outcome)

    if rd_warnings:
        embed.add_field(
            name=tr("Armor Warning"),
            value=_clamp(" ".join(rd_warnings), 1000),
            inline=False,
        )

    return embed


def _build_interim_defense_embed(
    *,
    profile: dict,
    defense_label: str,
    dices: list[int],
    effective_nh: int,
    outcome: dict,
    attempt_number: int,
    max_attempts: int,
    remaining_options: list[dict],
    rd: int,
) -> discord.Embed:
    """Build the result shown when another defence attempt is still allowed."""
    embed = discord.Embed(
        title=_clamp(
            tr("Defense attempt failed: {target}", target=profile["name"]), 256
        ),
        description=_clamp(
            tr(
                "Attempt {attempt} of {maximum}. The attack remains pending; choose another defense or waive.",
                attempt=attempt_number,
                maximum=max_attempts,
            ),
            4000,
        ),
        color=discord.Color.orange(),
    )
    embed.add_field(
        name=tr("Defense"),
        value=_clamp(
            f"{defense_label}\n"
            f"{tr('Dice')}: {_dice_pool(dices)}\n"
            f"{tr("Effective skill")}: `{effective_nh}`\n"
            f"{tr('Result')}: {_roll_result_text(outcome)}",
            1000,
        ),
        inline=False,
    )
    embed.add_field(
        name=tr("Attempts"),
        value=f"`{attempt_number}/{max_attempts}`",
        inline=False,
    )
    embed.add_field(
        name=tr("DR"),
        value=f"`{rd}`",
        inline=False,
    )
    if remaining_options:
        embed.add_field(
            name=tr("Remaining Defenses"),
            value=_clamp(
                "\n".join(option["label"] for option in remaining_options),
                1000,
            ),
            inline=False,
        )
    embed.set_footer(text=tr("No damage has been applied yet."))
    return embed


def build_panel_embed(
    session: dict | None,
    pending: dict | None,
    *,
    participants: list[dict] | None = None,
    recent_log: list[dict] | None = None,
    closed: bool = False,
) -> discord.Embed:
    """Build the public combat dashboard embed."""
    if closed:
        return discord.Embed(
            title=tr("Combat ended"),
            description=tr("The combat session in this channel was closed."),
            color=discord.Color.dark_grey(),
        )

    if session is None:
        return discord.Embed(
            title=tr("Combat Panel"),
            description=tr(
                "No active session in this channel.\n\nUse `/combat_start` to create a session and `/combat_attack` to begin."
            ),
            color=discord.Color.blue(),
        )

    embed = discord.Embed(
        title=tr("Combat Panel"),
        description=tr(
            "Attacks use `/combat_attack`. Defense is resolved with the buttons attached to the attack message."
        ),
        color=discord.Color.green(),
    )
    embed.add_field(
        name=tr("Session"),
        value=tr(
            "Round {round}",
            round=int(session.get("round_number") or 1),
        ),
        inline=False,
    )

    active_character_id = session.get("active_character_id")
    if active_character_id is not None:
        active_name = next(
            (
                participant.get("character_name")
                for participant in (participants or [])
                if int(participant["character_id"])
                == int(active_character_id)
            ),
            str(active_character_id),
        )
        embed.add_field(
            name=tr("Current Turn"),
            value=_clamp(str(active_name), 1000),
            inline=False,
        )

    if participants:
        participant_lines = [
            (
                ("-> " if active_character_id is not None and int(participant["character_id"]) == int(active_character_id) else "   ")
                + f"{participant.get('character_name') or participant['character_id']}"
                f"{' [NPC]' if participant.get('is_npc') else ''}"
                f" ({tr('Init.')} {float(participant.get('initiative') or 0):g})"
            )
            for participant in participants[:15]
        ]
        if len(participants) > 15:
            participant_lines.append(tr("*Showing 15 participants.*"))
        embed.add_field(
            name=tr("Participants"),
            value=_clamp("\n".join(participant_lines), 1000),
            inline=False,
        )

    if recent_log:
        log_lines = [
            f"* {entry.get('description') or entry.get('event_type')}"
            f"{' ' + tr('[UNDONE]') if entry.get('reverted') else ''}"
            for entry in recent_log[:5]
        ]
        embed.add_field(
            name=tr("Recent Events"),
            value=_clamp("\n".join(log_lines), 1000),
            inline=False,
        )

    if pending is None:
        embed.add_field(
            name=tr("Pending Attack"),
            value=tr("None. Use `/combat_attack` to attack."),
            inline=False,
        )
    else:
        embed.add_field(
            name=tr("Pending Attack"),
            value=_clamp(
                f"{pending['weapon_name']} ({pending['mode_name'] or tr('Default')})\n"
                f"{tr('Target')}: {pending['target_character_id']}\n"
                f"{tr('Damage')}: {pending['raw_damage']}\n"
                f"{tr('Status')}: {pending['status']}",
                1000,
            ),
            inline=False,
        )

    embed.set_footer(
        text=tr("Only the target or the GM can use the defense buttons.")
    )
    return embed


def _build_feint_embed(
    *,
    actor_name: str,
    target_name: str,
    actor_nh: int,
    target_nh: int,
    actor_roll: int,
    actor_dices: list[int],
    target_roll: int,
    target_dices: list[int],
    actor_success: bool,
    target_success: bool,
    actor_margin: int,
    target_margin: int,
    feint_value: int,
    success: bool,
    shock: int = 0,
) -> discord.Embed:
    """Build the public feint contest result embed."""
    if success:
        title = tr("Feint: {actor} deceived {target}", actor=actor_name, target=target_name)
        description = tr(
            "{actor}'s next attack against {target} ignores {value} of defense.",
            actor=actor_name,
            target=target_name,
            value=feint_value,
        )
        color = discord.Color.green()
    elif not actor_success:
        title = tr("Feint: {actor} failed", actor=actor_name)
        description = tr("The attacker could not execute the feint.")
        color = discord.Color.red()
    else:
        title = tr("Feint: {target} resisted", target=target_name)
        description = tr("The target saw through the feint; no penalty was applied.")
        color = discord.Color.orange()

    embed = discord.Embed(
        title=_clamp(title, 256),
        description=_clamp(description, 4000),
        color=color,
    )
    def roll_line(
        dices: list[int], nh: int, success: bool, margin: int
    ) -> str:
        state = (
            tr("success by {margin}", margin=margin)
            if success
            else tr("failure by {margin}", margin=abs(margin))
        )
        return (
            f"{tr('Dice')}: {_dice_pool(dices)}\n"
            f"{tr("Effective skill")}: `{nh}`\n"
            f"{tr('Result')}: {state}"
        )

    attacker_value = roll_line(
        actor_dices, actor_nh, actor_success, actor_margin
    )
    if shock:
        attacker_value += f"\n{tr('Shock')}: -{int(shock)}"
    embed.add_field(
        name=tr("Attacker"),
        value=_clamp(attacker_value, 1000),
        inline=False,
    )
    embed.add_field(
        name=tr("Target"),
        value=_clamp(
            roll_line(target_dices, target_nh, target_success, target_margin),
            1000,
        ),
        inline=False,
    )
    embed.add_field(
        name=tr("Result"),
        value=_clamp(
            tr("Feint penalty: {value}", value=feint_value)
            if success
            else tr("No penalty."),
            1000,
        ),
        inline=False,
    )
    return embed
