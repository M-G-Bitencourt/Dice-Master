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
            name="Ferimento",
            value=_clamp(
                f"PV {health_outcome['current_pv']}/{health_outcome['max_pv']} "
                f"- 1/3 ou menos\n"
                f"Deslocamento: {health_outcome['move']}\n"
                f"Esquiva: {health_outcome['dodge']}",
                1000,
            ),
            inline=False,
        )

    checks = health_outcome.get("checks") or []
    if checks:
        lines = []
        for check in checks:
            result = str(check["effect"])
            if not check["success"]:
                result += f" (falha por {-check['margin']})"
            lines.append(
                f"{check['label']}: {_dice_pool(check['dices'])} "
                f"vs HT {check['target']} -> {result}"
            )
        embed.add_field(
            name="Testes de HT",
            value=_clamp("\n".join(lines), 1000),
            inline=False,
        )

    if health_outcome.get("status"):
        embed.add_field(
            name="Estado do personagem",
            value=_clamp(str(health_outcome["status"]).capitalize(), 1000),
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
    title = _clamp(f"Ataque: {actor_name} -> {target_name}", 256)
    description = _clamp(
        f"{weapon_name} ({mode_name or 'Padrão'})\n{maneuver_label}",
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
        name="Rolagem",
        value=_clamp(
            f"Dados: {_dice_pool(attack_dices)}\n"
            f"NH efetivo: `{breakdown['effective']}`\n"
            f"Resultado: {_roll_result_text(outcome)}",
            1000,
        ),
        inline=False,
    )
    embed.add_field(
        name="Modificadores",
        value=_format_modifiers(breakdown),
        inline=False,
    )

    if outcome["success"] and damage_data is not None:
        if outcome["critical_success"]:
            damage_dices = damage_data.get("critical_dices") or []
            damage_total = damage_data["critical_damage"]
            dice_label = "Dados críticos"
        else:
            damage_dices = damage_data.get("dices") or []
            damage_total = damage_data["damage"]
            dice_label = "Dados"
        damage_lines = [
            f"Dano da arma: {damage_data.get('expression', 'não disponível')}",
            f"{dice_label}: {_dice_pool(damage_dices)}",
            f"Modificadores: {int(damage_data.get('total_modifier', 0)):+d}",
            f"Dano total: {damage_total} {damage_type_label}",
            f"Local: {hit_location_name}",
            f"RD: {rd}",
        ]
        embed.add_field(
            name="Dano",
            value=_clamp("\n".join(damage_lines), 1000),
            inline=False,
        )

    if injury_data is not None and new_pv is not None and profile is not None:
        max_pv = _max_pv(profile)
        embed.add_field(
            name="PV",
            value=code_block([resource_bar("PV", new_pv, max_pv)]),
            inline=False,
        )
        embed.add_field(
            name="Lesão",
            value=_clamp(
                f"PV {old_pv} -> {new_pv}\n"
                f"{injury_data['penetrating_damage']} penetrante x "
                f"{injury_data['multiplier']:.1f} = "
                f"{injury_data['final_injury']} PV",
                1000,
            ),
            inline=False,
        )

    _add_health_fields(embed, health_outcome)

    if rd_warnings:
        embed.add_field(
            name="Aviso de armadura",
            value=_clamp(" ".join(rd_warnings), 1000),
            inline=False,
        )

    if defense_options:
        embed.add_field(
            name="Defesas disponíveis",
            value=_clamp(
                "\n".join(option["label"] for option in defense_options),
                1000,
            ),
            inline=False,
        )

    if feint_penalty:
        embed.add_field(
            name="Finta",
            value=_clamp(
                f"-{feint_penalty} nas defesas contra este ataque.",
                1000,
            ),
            inline=False,
        )

    if defense_note:
        embed.add_field(
            name="Defesa",
            value=_clamp(defense_note, 1000),
            inline=False,
        )

    if critical_failure_dices:
        embed.add_field(
            name="Tabela de Falhas Críticas",
            value=_clamp(
                f"Dados: {critical_failure_dices} = {sum(critical_failure_dices)}",
                1000,
            ),
            inline=False,
        )

    if awaiting_defense and target_owner_id is not None:
        embed.set_footer(
            text="Aguardando defesa do alvo. O ataque expira em 15 minutos."
        )
    elif awaiting_defense:
        embed.set_footer(text="NPC: aguardando defesa do mestre. Expira em 15 minutos.")
    else:
        embed.set_footer(text="Resultado do ataque resolvido.")

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
        title = f"Defesa abandonada: {target_name}"
        description = "O alvo optou por não defender."
        color = discord.Color.dark_red()
    elif outcome["critical_failure"]:
        title = f"Falha crítica na defesa: {target_name}"
        description = "A defesa colapsou e o ataque atingiu o alvo."
        color = discord.Color.brand_red()
    elif outcome["critical_success"]:
        title = f"Defesa decisiva: {target_name}"
        description = "O alvo evitou o ataque com uma defesa decisiva."
        color = discord.Color.gold()
    elif outcome["success"]:
        title = f"Defesa bem-sucedida: {target_name}"
        description = "O alvo evitou o ataque."
        color = discord.Color.green()
    else:
        title = f"Defesa fracassou: {target_name}"
        description = "O ataque atingiu o alvo."
        color = discord.Color.red()

    embed = discord.Embed(
        title=_clamp(title, 256),
        description=_clamp(description, 4000),
        color=color,
    )

    if waive:
        defense_value = "Desistiu da defesa"
    else:
        defense_value = (
            f"{defense_label}\n"
            f"Dados: {_dice_pool(dices)}\n"
            f"NH efetivo: `{effective_nh}`\n"
            f"Resultado: {_roll_result_text(outcome)}"
        )
    embed.add_field(name="Defesa", value=_clamp(defense_value, 1000), inline=False)

    if injury_data is not None:
        embed.add_field(
            name="Dano",
            value=_clamp(
                f"Dano bruto: {chosen_damage}\n"
                f"RD: {rd}\n"
                f"Penetrante: {injury_data['penetrating_damage']}\n"
                f"Multiplicador: x{injury_data['multiplier']:.1f}\n"
                f"Dano aplicado: {injury_data['final_injury']} PV",
                1000,
            ),
            inline=False,
        )
    else:
        embed.add_field(
            name="Dano aplicado",
            value="Nenhum dano aplicado.",
            inline=False,
        )

    embed.add_field(
        name="PV",
        value=code_block([resource_bar("PV", new_pv, _max_pv(profile))]),
        inline=False,
    )
    embed.add_field(
        name="Transição",
        value=_clamp(f"PV {old_pv} -> {new_pv}", 1000),
        inline=False,
    )

    _add_health_fields(embed, health_outcome)

    if rd_warnings:
        embed.add_field(
            name="Aviso de armadura",
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
        title=_clamp(f"Defesa falhou: {profile['name']}", 256),
        description=_clamp(
            f"Tentativa {attempt_number} de {max_attempts}. "
            "O ataque continua pendente; escolha outra defesa ou desista.",
            4000,
        ),
        color=discord.Color.orange(),
    )
    embed.add_field(
        name="Defesa",
        value=_clamp(
            f"{defense_label}\n"
            f"Dados: {_dice_pool(dices)}\n"
            f"NH efetivo: `{effective_nh}`\n"
            f"Resultado: {_roll_result_text(outcome)}",
            1000,
        ),
        inline=False,
    )
    embed.add_field(
        name="Tentativas",
        value=f"`{attempt_number}/{max_attempts}`",
        inline=False,
    )
    embed.add_field(
        name="RD",
        value=f"`{rd}`",
        inline=False,
    )
    if remaining_options:
        embed.add_field(
            name="Defesas restantes",
            value=_clamp(
                "\n".join(option["label"] for option in remaining_options),
                1000,
            ),
            inline=False,
        )
    embed.set_footer(text="Nenhum dano foi aplicado ainda.")
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
            title="Combate encerrado",
            description="A sessão de combate deste canal foi encerrada.",
            color=discord.Color.dark_grey(),
        )

    if session is None:
        return discord.Embed(
            title="Painel de Combate",
            description=(
                "Nenhuma sessão ativa neste canal.\n\n"
                "Use `/combat_start` para criar uma sessão e "
                "`/combat_attack` para começar."
            ),
            color=discord.Color.blue(),
        )

    embed = discord.Embed(
        title="Painel de Combate",
        description=(
            "Ataques usam `/combat_attack`. A defesa é feita pelos botões "
            "anexados à mensagem do ataque."
        ),
        color=discord.Color.green(),
    )
    embed.add_field(
        name="Sessão",
        value=f"Rodada {int(session.get('round_number') or 1)}",
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
            name="Turno atual",
            value=_clamp(str(active_name), 1000),
            inline=False,
        )

    if participants:
        participant_lines = [
            (
                ("-> " if active_character_id is not None and int(participant["character_id"]) == int(active_character_id) else "   ")
                + f"{participant.get('character_name') or participant['character_id']}"
                f"{' [NPC]' if participant.get('is_npc') else ''}"
                f" (Inic. {float(participant.get('initiative') or 0):g})"
            )
            for participant in participants[:15]
        ]
        if len(participants) > 15:
            participant_lines.append("*Exibindo 15 participantes.*")
        embed.add_field(
            name="Participantes",
            value=_clamp("\n".join(participant_lines), 1000),
            inline=False,
        )

    if recent_log:
        log_lines = [
            f"* {entry.get('description') or entry.get('event_type')}"
            f"{' [DESFEITO]' if entry.get('reverted') else ''}"
            for entry in recent_log[:5]
        ]
        embed.add_field(
            name="Últimos eventos",
            value=_clamp("\n".join(log_lines), 1000),
            inline=False,
        )

    if pending is None:
        embed.add_field(
            name="Ataque pendente",
            value="Nenhum. Use `/combat_attack` para atacar.",
            inline=False,
        )
    else:
        embed.add_field(
            name="Ataque pendente",
            value=_clamp(
                f"{pending['weapon_name']} ({pending['mode_name'] or 'Padrão'})\n"
                f"Alvo: {pending['target_character_id']}\n"
                f"Dano: {pending['raw_damage']}\n"
                f"Status: {pending['status']}",
                1000,
            ),
            inline=False,
        )

    embed.set_footer(text="Somente o alvo ou o mestre podem usar os botões de defesa.")
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
        title = f"Fintar: {actor_name} enganou {target_name}"
        description = (
            f"O próximo ataque de {actor_name} contra {target_name} "
            f"ignora {feint_value} de defesa."
        )
        color = discord.Color.green()
    elif not actor_success:
        title = f"Fintar: {actor_name} falhou"
        description = "O atacante não conseguiu executar a finta."
        color = discord.Color.red()
    else:
        title = f"Fintar: {target_name} resistiu"
        description = "O alvo percebeu a finta; nenhuma penalidade foi aplicada."
        color = discord.Color.orange()

    embed = discord.Embed(
        title=_clamp(title, 256),
        description=_clamp(description, 4000),
        color=color,
    )
    def roll_line(
        dices: list[int], nh: int, success: bool, margin: int
    ) -> str:
        state = f"sucesso por {margin}" if success else f"falha por {abs(margin)}"
        return (
            f"Dados: {_dice_pool(dices)}\n"
            f"NH efetivo: `{nh}`\n"
            f"Resultado: {state}"
        )

    attacker_value = roll_line(
        actor_dices, actor_nh, actor_success, actor_margin
    )
    if shock:
        attacker_value += f"\nChoque: -{int(shock)}"
    embed.add_field(
        name="Atacante",
        value=_clamp(attacker_value, 1000),
        inline=False,
    )
    embed.add_field(
        name="Alvo",
        value=_clamp(
            roll_line(target_dices, target_nh, target_success, target_margin),
            1000,
        ),
        inline=False,
    )
    embed.add_field(
        name="Resultado",
        value=_clamp(
            f"Penalidade de finta: {feint_value}" if success else "Sem penalidade.",
            1000,
        ),
        inline=False,
    )
    return embed
