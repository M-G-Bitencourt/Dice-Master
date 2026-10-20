"""Discord UI views and modals attached to combat messages."""

from __future__ import annotations

import sqlite3

import discord

from cogs.combat_helpers.combat_embeds import build_panel_embed
from cogs.combat_helpers.combat_turn import advance_combat_turn
from cogs.combat_helpers.combat_support import _can_defend, _clamp, _is_gm_user
from utils.db_functions import (
    close_combat_session,
    get_active_combat_session,
    get_character_conditions_by_id,
    get_combat_participants,
    get_pending_attack,
    get_pending_attack_for_channel,
    get_recent_combat_log,
    reset_combat_participant_turn,
    set_character_aim_evaluate,
    set_combat_session_panel,
    supersede_pending_attacks,
)


class DefenseButton(discord.ui.Button):
    """Button for one automatic defence option."""

    def __init__(self, option: dict):
        super().__init__(
            label=_clamp(option["label"], 80),
            style=discord.ButtonStyle.primary,
        )
        self.option = option

    async def callback(self, interaction: discord.Interaction):
        await self.view.handle_defense(interaction, self.option)


class DefenseAdjustModal(discord.ui.Modal, title="Ajustar defesa"):
    """Manual defence values for unusual advantages, powers or conditions."""

    nh = discord.ui.TextInput(
        label="NH de defesa",
        required=False,
        max_length=4,
        placeholder="Ex.: 12",
    )
    rd = discord.ui.TextInput(
        label="RD base",
        required=False,
        max_length=4,
        placeholder="Vazio usa a RD automática; crânio soma +2",
    )
    modifier = discord.ui.TextInput(
        label="Modificador situacional",
        required=False,
        max_length=4,
        placeholder="Ex.: +2 ou -2",
    )

    def __init__(
        self,
        attack_id: int,
        connection: sqlite3.Connection,
        dm_id: int,
        repeat_callback=None,
        defense_key: str | None = None,
        effect_ids: list[int] | None = None,
        resolve_callback=None,
    ):
        super().__init__()
        self.attack_id = attack_id
        self.connection = connection
        self.dm_id = dm_id
        self.repeat_callback = repeat_callback
        self.defense_key = defense_key
        self.effect_ids = effect_ids or []
        self.resolve_callback = resolve_callback

    async def on_submit(self, interaction: discord.Interaction):
        nh_text = str(self.nh.value or "").strip()
        rd_text = str(self.rd.value or "").strip()
        modifier_text = str(self.modifier.value or "").strip()

        try:
            nh_override = int(nh_text) if nh_text else None
            rd_override = int(rd_text) if rd_text else None
            modifier = int(modifier_text) if modifier_text else 0
        except ValueError:
            await interaction.response.send_message(
                "Erro: informe valores inteiros para NH, RD e modificador.",
                ephemeral=True,
            )
            return

        if nh_override is None:
            await interaction.response.send_message(
                "Erro: informe o NH de defesa para o ajuste manual.",
                ephemeral=True,
            )
            return
        if not 0 <= nh_override <= 60:
            await interaction.response.send_message(
                "Erro: o NH de defesa deve estar entre 0 e 60.",
                ephemeral=True,
            )
            return
        if rd_override is not None and not -20 <= rd_override <= 50:
            await interaction.response.send_message(
                "Erro: a RD manual deve estar entre -20 e 50.",
                ephemeral=True,
            )
            return
        if not -20 <= modifier <= 20:
            await interaction.response.send_message(
                "Erro: o modificador deve estar entre -20 e +20.",
                ephemeral=True,
            )
            return

        if self.resolve_callback is None:
            await interaction.response.send_message(
                "Erro: resolução de defesa indisponível.",
                ephemeral=True,
            )
            return
        await self.resolve_callback(
            interaction,
            self.connection,
            self.attack_id,
            defense_value=nh_override,
            defense_label="Defesa manual",
            dm_id=self.dm_id,
            nh_override=nh_override,
            rd_override=rd_override,
            modifier=modifier,
            defense_key=self.defense_key,
            effect_ids=self.effect_ids,
            repeat_callback=self.repeat_callback,
        )


class DefenseView(discord.ui.View):
    """Public defence controls attached to one pending attack."""

    def __init__(
        self,
        *,
        attack_id: int,
        connection: sqlite3.Connection,
        dm_id: int,
        target_owner_id: int | None,
        target_name: str,
        defenses: list[dict],
        repeat_callback=None,
        resolve_callback=None,
    ):
        super().__init__(timeout=900)
        self.attack_id = attack_id
        self.connection = connection
        self.dm_id = dm_id
        self.target_owner_id = target_owner_id
        self.target_name = target_name
        self.defenses = defenses
        self.repeat_callback = repeat_callback
        self.resolve_callback = resolve_callback

        for option in defenses:
            self.add_item(DefenseButton(option))

        waive_button = discord.ui.Button(
            label="Desistir",
            style=discord.ButtonStyle.danger,
        )
        waive_button.callback = self.handle_waive
        self.add_item(waive_button)

        adjust_button = discord.ui.Button(
            label="Ajustar",
            style=discord.ButtonStyle.secondary,
        )
        adjust_button.callback = self.handle_adjust
        self.add_item(adjust_button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        pending = get_pending_attack(self.connection, self.attack_id)
        if pending is None:
            await interaction.response.send_message(
                "Erro: este ataque não existe mais.",
                ephemeral=True,
            )
            return False

        if not _can_defend(interaction.user, pending, self.dm_id):
            await interaction.response.send_message(
                "Erro: apenas o alvo do ataque ou o mestre podem defender.",
                ephemeral=True,
            )
            return False

        return True

    async def handle_defense(
        self, interaction: discord.Interaction, option: dict
    ):
        if self.resolve_callback is None:
            await interaction.response.send_message(
                "Erro: resolução de defesa indisponível.",
                ephemeral=True,
            )
            return
        await self.resolve_callback(
            interaction,
            self.connection,
            self.attack_id,
            defense_value=option["value"],
            defense_label=option["label"],
            dm_id=self.dm_id,
            defense_key=option.get("key"),
            effect_ids=option.get("effect_ids"),
            repeat_callback=self.repeat_callback,
        )

    async def handle_waive(self, interaction: discord.Interaction):
        if self.resolve_callback is None:
            await interaction.response.send_message(
                "Erro: resolução de defesa indisponível.",
                ephemeral=True,
            )
            return
        await self.resolve_callback(
            interaction,
            self.connection,
            self.attack_id,
            defense_value=None,
            defense_label="Desistir",
            dm_id=self.dm_id,
            waive=True,
            repeat_callback=self.repeat_callback,
        )

    async def handle_adjust(self, interaction: discord.Interaction):
        option = self.defenses[0] if self.defenses else None
        await interaction.response.send_modal(
            DefenseAdjustModal(
                self.attack_id,
                self.connection,
                self.dm_id,
                self.repeat_callback,
                defense_key=option.get("key") if option else None,
                effect_ids=option.get("effect_ids") if option else None,
                resolve_callback=self.resolve_callback,
            )
        )


class NextActionView(discord.ui.View):
    """Fast next-turn actions attached to a resolved attack message."""

    def __init__(
        self,
        *,
        connection: sqlite3.Connection,
        claimed: dict,
        dm_id: int,
        repeat_callback=None,
    ):
        super().__init__(timeout=900)
        self.connection = connection
        self.claimed = claimed
        self.dm_id = dm_id
        self.repeat_callback = repeat_callback

        if (
            claimed.get("mode_id") is not None
            or claimed.get("ranged_weapon_id") is not None
        ):
            repeat_button = discord.ui.Button(
                label="Repetir ataque",
                style=discord.ButtonStyle.primary,
            )
            repeat_button.callback = self.repeat_attack
            self.add_item(repeat_button)

        attack_kind = claimed.get("attack_kind", "melee")
        if attack_kind == "ranged":
            aim_button = discord.ui.Button(
                label="Mirar",
                style=discord.ButtonStyle.secondary,
            )
            aim_button.callback = self.aim
            self.add_item(aim_button)
        else:
            evaluate_button = discord.ui.Button(
                label="Avaliar",
                style=discord.ButtonStyle.secondary,
            )
            evaluate_button.callback = self.evaluate
            self.add_item(evaluate_button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if _is_gm_user(interaction.user, self.dm_id):
            return True
        if int(getattr(interaction.user, "id", 0)) == int(
            self.claimed.get("attacker_id") or 0
        ):
            return True

        await interaction.response.send_message(
            "Erro: apenas o atacante ou o mestre podem usar estas ações.",
            ephemeral=True,
        )
        return False

    async def repeat_attack(self, interaction: discord.Interaction):
        if self.repeat_callback is None:
            await interaction.response.send_message(
                "Erro: repetição indisponível para este ataque.",
                ephemeral=True,
            )
            return
        await self.repeat_callback(interaction, self.claimed)

    async def _apply_maneuver(
        self, interaction: discord.Interaction, field: str
    ):
        await interaction.response.defer(ephemeral=True)
        actor_character_id = int(self.claimed["attacker_character_id"])

        with self.connection:
            if self.claimed.get("session_id") is not None:
                reset_combat_participant_turn(
                    self.connection,
                    int(self.claimed["session_id"]),
                    actor_character_id,
                )
            conditions = get_character_conditions_by_id(
                self.connection, actor_character_id
            )
            if field == "aim":
                set_character_aim_evaluate(
                    self.connection,
                    actor_character_id,
                    aim=min(3, int(conditions["aim"]) + 1),
                    evaluate=0,
                )
                message = "Mira preparada para o próximo ataque."
            else:
                set_character_aim_evaluate(
                    self.connection,
                    actor_character_id,
                    aim=0,
                    evaluate=min(3, int(conditions["evaluate"]) + 1),
                )
                message = "Avaliação preparada para o próximo ataque."

        await interaction.edit_original_response(view=None)
        await interaction.followup.send(message, ephemeral=True)

    async def aim(self, interaction: discord.Interaction):
        await self._apply_maneuver(interaction, "aim")

    async def evaluate(self, interaction: discord.Interaction):
        await self._apply_maneuver(interaction, "evaluate")


class CombatPanelView(discord.ui.View):
    """Public combat panel with refresh and close controls."""

    def __init__(
        self,
        *,
        connection: sqlite3.Connection,
        channel_id: int,
        guild_id: int | None,
        dm_id: int,
    ):
        super().__init__(timeout=None)
        self.connection = connection
        self.channel_id = channel_id
        self.guild_id = guild_id
        self.dm_id = dm_id

        refresh_button = discord.ui.Button(
            label="Atualizar",
            style=discord.ButtonStyle.secondary,
            custom_id=f"combat_panel:{self.channel_id}:refresh",
        )
        refresh_button.callback = self.refresh
        self.add_item(refresh_button)

        advance_button = discord.ui.Button(
            label="Avançar turno",
            style=discord.ButtonStyle.primary,
            custom_id=f"combat_panel:{self.channel_id}:advance",
        )
        advance_button.callback = self.advance_turn
        self.add_item(advance_button)

        close_button = discord.ui.Button(
            label="Encerrar",
            style=discord.ButtonStyle.danger,
            custom_id=f"combat_panel:{self.channel_id}:close",
        )
        close_button.callback = self.close
        self.add_item(close_button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return True

    async def refresh(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        session = get_active_combat_session(self.connection, self.channel_id)
        if session is None:
            await interaction.followup.send(
                "Erro: não existe combate ativo neste canal.",
                ephemeral=True,
            )
            return

        channel = interaction.channel
        if channel is None:
            await interaction.followup.send(
                "Erro: canal do combate não localizado.",
                ephemeral=True,
            )
            return

        pending = get_pending_attack_for_channel(
            self.connection, self.channel_id
        )
        participants = get_combat_participants(
            self.connection, int(session["session_id"])
        )
        recent_log = get_recent_combat_log(
            self.connection, int(session["session_id"]), limit=5
        )
        embed = build_panel_embed(
            session,
            pending,
            participants=participants,
            recent_log=recent_log,
        )
        new_view = CombatPanelView(
            connection=self.connection,
            channel_id=self.channel_id,
            guild_id=self.guild_id,
            dm_id=self.dm_id,
        )
        try:
            new_message = await channel.send(embed=embed, view=new_view)
        except (discord.HTTPException, discord.Forbidden):
            await interaction.followup.send(
                "Erro: não foi possível repostar o painel de combate.",
                ephemeral=True,
            )
            return

        with self.connection:
            set_combat_session_panel(
                self.connection,
                int(session["session_id"]),
                new_message.id,
            )

        old_ids = []
        if interaction.message is not None:
            old_ids.append(int(interaction.message.id))
        stored_id = session.get("panel_message_id")
        if stored_id is not None and int(stored_id) not in old_ids:
            old_ids.append(int(stored_id))

        delete_failed = False
        for old_id in old_ids:
            try:
                if (
                    interaction.message is not None
                    and old_id == int(interaction.message.id)
                ):
                    await interaction.message.delete()
                else:
                    old_message = await channel.fetch_message(old_id)
                    await old_message.delete()
            except (discord.HTTPException, discord.NotFound, discord.Forbidden):
                delete_failed = True

        if delete_failed:
            await interaction.followup.send(
                "Painel atualizado, mas não foi possível apagar o painel antigo.",
                ephemeral=True,
            )

    async def advance_turn(self, interaction: discord.Interaction):
        if not _is_gm_user(interaction.user, self.dm_id):
            await interaction.response.send_message(
                "Erro: apenas o mestre pode avançar o turno.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        try:
            result = advance_combat_turn(
                self.connection, self.channel_id
            )
        except ValueError as error:
            await interaction.followup.send(
                f"Erro: {error}",
                ephemeral=True,
            )
            return

        session = result["session"]
        pending = get_pending_attack_for_channel(
            self.connection, self.channel_id
        )
        participants = (
            get_combat_participants(
                self.connection, int(session["session_id"])
            )
            if session is not None
            else []
        )
        recent_log = (
            get_recent_combat_log(
                self.connection, int(session["session_id"]), limit=5
            )
            if session is not None
            else []
        )
        embed = build_panel_embed(
            session,
            pending,
            participants=participants,
            recent_log=recent_log,
        )
        await interaction.edit_original_response(embed=embed, view=self)

    async def close(self, interaction: discord.Interaction):
        if not _is_gm_user(interaction.user, self.dm_id):
            await interaction.response.send_message(
                "Erro: apenas o mestre pode encerrar o combate.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()
        with self.connection:
            close_combat_session(self.connection, self.channel_id)
            supersede_pending_attacks(self.connection, self.channel_id)

        embed = build_panel_embed(None, None, closed=True)
        await interaction.edit_original_response(embed=embed, view=None)
