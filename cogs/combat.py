"""Primary combat cog: commands and combat session control."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from cogs.combat_helpers.combat_attack import perform_attack, repeat_attack
from cogs.combat_helpers.combat_feint import perform_feint
from cogs.combat_helpers.combat_effects import perform_effect_change
from cogs.combat_helpers.combat_turn import advance_combat_turn
from cogs.combat_helpers.combat_embeds import build_panel_embed
from cogs.combat_helpers.combat_support import (
    _clamp,
    _friendly_character_error,
    _is_gm_user,
)
from cogs.combat_helpers.combat_views import CombatPanelView
from utils.combat import HIT_LOCATIONS, MANEUVERS
from utils.db_functions import (
    _resolve_character_id,
    add_combat_log,
    close_combat_session,
    ensure_combat_participant,
    get_active_combat_session,
    get_active_combat_sessions,
    get_character_combat_data,
    get_character_profile_by_id,
    get_combat_participants,
    get_equipped_melee_modes,
    get_equipped_ranged_weapons,
    get_last_damage_log,
    get_or_create_combat_session,
    get_pending_attack_for_channel,
    get_recent_combat_log,
    mark_combat_log_reverted,
    set_character_current_pv,
    set_combat_session_active,
    set_combat_session_panel,
    set_participant_initiative,
    supersede_pending_attacks,
)


__all__ = [
    "Combat",
    "CombatPanelView",
    "setup",
]


class Combat(commands.Cog):
    """Primary combat flow with automatic sheet-driven attack and defence."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        project_root = Path(__file__).resolve().parent.parent
        database_path = project_root / "data" / "database.db"

        self.db_connection = sqlite3.connect(database_path)
        self.db_connection.execute("PRAGMA foreign_keys = ON;")
        self.db_connection.execute("PRAGMA busy_timeout = 5000;")

        try:
            self.dm_id = int(self.bot.config["BOT"]["DM_ID"])
        except AttributeError as error:
            raise RuntimeError(
                "Architectural Error: 'bot.config' must be injected before loading Cogs."
            ) from error
        except (KeyError, ValueError) as error:
            raise ValueError(f"Configuration Malformation: {error}") from error

        if hasattr(self.bot, "add_view"):
            for session in get_active_combat_sessions(self.db_connection):
                self.bot.add_view(
                    CombatPanelView(
                        connection=self.db_connection,
                        channel_id=int(session["channel_id"]),
                        guild_id=session["guild_id"],
                        dm_id=self.dm_id,
                    )
                )

    def _is_gm(self, interaction: discord.Interaction) -> bool:
        """Return True when the caller is the configured GM or an administrator."""
        return _is_gm_user(interaction.user, self.dm_id)

    def _can_manage_character(
        self, interaction: discord.Interaction, character_id: int
    ) -> bool:
        """Return True when the caller owns the character or is the GM."""
        if self._is_gm(interaction):
            return True

        try:
            profile = get_character_profile_by_id(
                self.db_connection, character_id
            )
        except ValueError:
            return False

        return int(profile.get("owner_id") or 0) == int(interaction.user.id)

    def _resolve_managed_character(
        self, interaction: discord.Interaction, character_option: str | None
    ) -> int:
        """Resolve an explicit character or the caller's active character."""
        if character_option is None:
            return _resolve_character_id(
                self.db_connection, interaction.user.id
            )

        character_id = int(character_option)
        if not self._can_manage_character(interaction, character_id):
            raise ValueError(
                "Você não pode gerenciar efeitos deste personagem."
            )
        return character_id

    async def character_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        """List characters for target and GM actor selection."""
        pattern = f"%{current.strip()}%"
        rows = self.db_connection.execute(
            """
            SELECT character_id, name, is_npc
            FROM characters
            WHERE name LIKE ?
            ORDER BY name COLLATE NOCASE ASC
            LIMIT 25
            """,
            (pattern,),
        ).fetchall()

        return [
            app_commands.Choice(
                name=_clamp(
                    f"{row[1]}{' [NPC]' if row[2] else ''}",
                    100,
                ),
                value=str(row[0]),
            )
            for row in rows
        ]

    async def participant_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        """List only characters already registered in the active combat."""
        session = get_active_combat_session(
            self.db_connection, interaction.channel_id
        )
        if session is None:
            return []

        pattern = current.strip().casefold()
        choices = []
        for participant in get_combat_participants(
            self.db_connection, int(session["session_id"])
        ):
            name = str(participant["character_name"])
            if pattern and pattern not in name.casefold():
                continue
            label = f"{name}{' [NPC]' if participant['is_npc'] else ''}"
            choices.append(
                app_commands.Choice(
                    name=_clamp(label, 100),
                    value=str(participant["character_id"]),
                )
            )
        return choices[:25]

    async def weapon_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        """List weapons belonging only to combat participants."""
        session = get_active_combat_session(
            self.db_connection, interaction.channel_id
        )
        if session is None:
            return []

        participants = get_combat_participants(
            self.db_connection, int(session["session_id"])
        )
        if not participants:
            return []

        if self._is_gm(interaction):
            characters = participants
            show_character = True
        else:
            try:
                character_id = _resolve_character_id(
                    self.db_connection, interaction.user.id
                )
            except ValueError:
                return []
            characters = [
                participant
                for participant in participants
                if int(participant["character_id"]) == character_id
            ]
            if not characters:
                return []
            show_character = False

        pattern = current.strip().casefold()
        choices: list[app_commands.Choice[str]] = []

        for participant in characters:
            character_id = int(participant["character_id"])
            character_name = participant["character_name"]

            for mode in get_equipped_melee_modes(
                self.db_connection, character_id
            ):
                label = (
                    f"{character_name} - {mode['weapon_name']} "
                    f"({mode['mode_name']})"
                    if show_character
                    else f"{mode['weapon_name']} ({mode['mode_name']})"
                )
                if pattern and pattern not in label.casefold():
                    continue
                choices.append(
                    app_commands.Choice(
                        name=_clamp(label, 100),
                        value=f"melee:{character_id}:{mode['mode_id']}",
                    )
                )

            for weapon in get_equipped_ranged_weapons(
                self.db_connection, character_id
            ):
                label = (
                    f"{character_name} - {weapon['weapon_name']} "
                    f"({weapon['damage']})"
                    if show_character
                    else f"{weapon['weapon_name']} ({weapon['damage']})"
                )
                if pattern and pattern not in label.casefold():
                    continue
                choices.append(
                    app_commands.Choice(
                        name=_clamp(label, 100),
                        value=(
                            f"ranged:{character_id}:"
                            f"{weapon['ranged_weapon_id']}"
                        ),
                    )
                )

        return choices[:25]

    async def skill_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        """List the caller's skills for ranged attack selection."""
        try:
            character_id = _resolve_character_id(
                self.db_connection, interaction.user.id
            )
            data = get_character_combat_data(
                self.db_connection, character_id
            )
        except ValueError:
            return []

        if data is None:
            return []

        pattern = current.strip().casefold()
        choices = []
        for skill in data["skills"]:
            label = f"{skill['name']} (NH {skill['nh']})"
            if pattern and pattern not in label.casefold():
                continue
            choices.append(
                app_commands.Choice(
                    name=_clamp(label, 100),
                    value=str(skill["skill_id"]),
                )
            )
        return choices[:25]

    def _resolve_actor(
        self,
        interaction: discord.Interaction,
        actor_option: str | None,
        weapon_character_id: int | None,
    ) -> int:
        """Resolve the acting character from GM override, weapon or caller."""
        if actor_option is not None:
            if not self._is_gm(interaction):
                raise ValueError(
                    "Apenas o mestre pode escolher outro personagem como ator."
                )
            actor_character_id = int(actor_option)
            if (
                weapon_character_id is not None
                and weapon_character_id != actor_character_id
            ):
                raise ValueError(
                    "A arma escolhida não pertence ao personagem informado."
                )
            return actor_character_id

        if weapon_character_id is not None and self._is_gm(interaction):
            return weapon_character_id

        return _resolve_character_id(self.db_connection, interaction.user.id)

    def _find_mode(self, actor_character_id: int, weapon_value: str | None) -> dict:
        """Resolve the selected equipped melee mode for an actor."""
        modes = get_equipped_melee_modes(
            self.db_connection, actor_character_id
        )
        if not modes:
            raise ValueError(
                "O personagem não possui arma corpo a corpo equipada."
            )

        if weapon_value is None:
            return modes[0]

        try:
            _, raw_mode_id = weapon_value.split(":", 1)
            mode_id = int(raw_mode_id)
        except (ValueError, AttributeError):
            raise ValueError("A arma selecionada é inválida.")

        for mode in modes:
            if int(mode["mode_id"]) == mode_id:
                return mode

        raise ValueError("A arma selecionada não está equipada no personagem.")

    def _find_ranged_weapon(
        self, actor_character_id: int, weapon_value: str | None
    ) -> dict:
        """Resolve the selected equipped ranged weapon for an actor."""
        weapons = get_equipped_ranged_weapons(
            self.db_connection, actor_character_id
        )
        if not weapons:
            raise ValueError(
                "O personagem não possui arma à distância equipada."
            )

        if weapon_value is None:
            return weapons[0]

        try:
            ranged_weapon_id = int(str(weapon_value).rsplit(":", 1)[-1])
        except (ValueError, AttributeError):
            raise ValueError("A arma à distância selecionada é inválida.")

        for weapon in weapons:
            if int(weapon["ranged_weapon_id"]) == ranged_weapon_id:
                return weapon

        raise ValueError(
            "A arma à distância selecionada não está equipada no personagem."
        )

    def _find_skill_by_id(self, data: dict, skill_id: str | None) -> dict | None:
        """Resolve one skill from the actor's skill list by primary key."""
        if skill_id is None:
            return None
        try:
            numeric_id = int(skill_id)
        except (ValueError, TypeError):
            return None
        for skill in data["skills"]:
            if int(skill["skill_id"]) == numeric_id:
                return skill
        return None

    def _build_panel_payload(
        self, session: dict | None, channel_id: int | None = None
    ):
        """Build the panel embed and view for the current channel state."""
        pending = (
            get_pending_attack_for_channel(
                self.db_connection, int(session["channel_id"])
            )
            if session is not None
            else None
        )
        participants = (
            get_combat_participants(
                self.db_connection, int(session["session_id"])
            )
            if session is not None
            else []
        )
        recent_log = (
            get_recent_combat_log(
                self.db_connection, int(session["session_id"]), limit=5
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
        view = CombatPanelView(
            connection=self.db_connection,
            channel_id=(
                int(session["channel_id"])
                if session is not None
                else int(channel_id or 0)
            ),
            guild_id=session.get("guild_id") if session else None,
            dm_id=self.dm_id,
        )
        return embed, view

    async def _edit_stored_panel(self, session: dict) -> bool:
        """Edit the stored panel message; return False when it is unavailable."""
        panel_message_id = session.get("panel_message_id")
        get_channel = getattr(self.bot, "get_channel", None)
        channel = (
            get_channel(int(session["channel_id"]))
            if get_channel is not None
            else None
        )
        if panel_message_id is None or channel is None:
            return False
        try:
            message = await channel.fetch_message(int(panel_message_id))
            embed, view = self._build_panel_payload(session)
            await message.edit(embed=embed, view=view)
            return True
        except (discord.HTTPException, discord.NotFound, discord.Forbidden):
            return False

    @staticmethod
    def _basic_speed(profile: dict) -> float:
        """Return the GURPS Basic Speed used as default initiative."""
        return round(
            (float(profile["dx"]) + float(profile["ht"])) / 4.0
            + float(profile.get("additional_basic_speed") or 0),
            2,
        )

    async def _send_panel_to_channel(
        self, session: dict, channel=None
    ) -> None:
        """Send a fresh panel when no stored panel message is available."""
        if channel is None:
            get_channel = getattr(self.bot, "get_channel", None)
            channel = (
                get_channel(int(session["channel_id"]))
                if get_channel is not None
                else None
            )
        if channel is None:
            return
        embed, view = self._build_panel_payload(session)
        message = await channel.send(embed=embed, view=view)
        with self.db_connection:
            set_combat_session_panel(
                self.db_connection, int(session["session_id"]), message.id
            )

    @app_commands.command(
        name="combat_start",
        description="Cria ou reabre o painel de combate deste canal.",
    )
    async def combat_start(self, interaction: discord.Interaction):
        with self.db_connection:
            session = get_or_create_combat_session(
                self.db_connection,
                interaction.guild_id,
                interaction.channel_id,
            )

        if await self._edit_stored_panel(session):
            await interaction.response.send_message(
                "Painel de combate atualizado.", ephemeral=True
            )
            return

        embed, view = self._build_panel_payload(session)
        await interaction.response.send_message(embed=embed, view=view)
        message = await interaction.original_response()
        with self.db_connection:
            set_combat_session_panel(
                self.db_connection, int(session["session_id"]), message.id
            )

    @app_commands.command(
        name="combat_end",
        description="Encerra o combate e descarta o ataque pendente.",
    )
    async def combat_end(self, interaction: discord.Interaction):
        if not self._is_gm(interaction):
            await interaction.response.send_message(
                "Erro: apenas o mestre pode encerrar o combate.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        with self.db_connection:
            close_combat_session(self.db_connection, interaction.channel_id)
            supersede_pending_attacks(self.db_connection, interaction.channel_id)

        await interaction.followup.send(
            "Combate encerrado e ataque pendente descartado.",
            ephemeral=True,
        )

    @app_commands.command(
        name="combat_manage_effect",
        description="Adiciona ou remove um efeito do catálogo externo em um personagem.",
    )
    @app_commands.autocomplete(personagem=character_autocomplete)
    @app_commands.describe(
        acao="Adicionar ou remover o efeito.",
        efeito_id="ID do efeito no catálogo externo.",
        personagem="Personagem alvo. Jogadores usam o próprio personagem.",
    )
    @app_commands.choices(
        acao=[
            app_commands.Choice(name="Adicionar", value="add"),
            app_commands.Choice(name="Remover", value="remove"),
        ]
    )
    async def combat_effect(
        self,
        interaction: discord.Interaction,
        acao: app_commands.Choice[str],
        efeito_id: int,
        personagem: str | None = None,
    ):
        await perform_effect_change(
            self,
            interaction,
            acao.value,
            efeito_id=efeito_id,
            personagem=personagem,
        )

    @app_commands.command(
        name="combat_enter",
        description="Adiciona um personagem ao combate com iniciativa.",
    )
    @app_commands.autocomplete(personagem=character_autocomplete)
    @app_commands.describe(
        personagem="Personagem que entrará no combate. Jogadores usam o próprio.",
        iniciativa=(
            "Iniciativa (aceita decimais); se omitida, usa a Velocidade Básica."
        ),
    )
    async def combat_enter(
        self,
        interaction: discord.Interaction,
        personagem: str | None = None,
        iniciativa: float | None = None,
    ):
        await interaction.response.defer(ephemeral=True)
        try:
            character_id = self._resolve_managed_character(
                interaction, personagem
            )
            profile = get_character_profile_by_id(
                self.db_connection, character_id
            )
        except (ValueError, TypeError) as error:
            await interaction.followup.send(
                f"Erro: {_friendly_character_error(error)}",
                ephemeral=True,
            )
            return

        if iniciativa is not None and not 0 <= iniciativa <= 99:
            await interaction.followup.send(
                "Erro: a iniciativa deve estar entre 0 e 99.",
                ephemeral=True,
            )
            return

        initiative_value = (
            round(float(iniciativa), 2)
            if iniciativa is not None
            else self._basic_speed(profile)
        )

        with self.db_connection:
            session = get_or_create_combat_session(
                self.db_connection,
                interaction.guild_id,
                interaction.channel_id,
            )
            ensure_combat_participant(
                self.db_connection,
                session_id=int(session["session_id"]),
                character_id=character_id,
                owner_id=profile.get("owner_id"),
                is_npc=bool(profile.get("is_npc")),
                initiative=initiative_value,
            )
            set_participant_initiative(
                self.db_connection,
                int(session["session_id"]),
                character_id,
                initiative_value,
            )
            if session.get("active_character_id") is None:
                set_combat_session_active(
                    self.db_connection,
                    int(session["session_id"]),
                    character_id,
                    1,
                )
            add_combat_log(
                self.db_connection,
                session_id=int(session["session_id"]),
                channel_id=interaction.channel_id,
                event_type="enter",
                actor_character_id=character_id,
                description=f"{profile['name']} entrou no combate.",
            )

        session = get_active_combat_session(
            self.db_connection, interaction.channel_id
        )
        if session is not None:
            if not await self._edit_stored_panel(session):
                await self._send_panel_to_channel(
                    session, interaction.channel
                )

        await interaction.followup.send(
            f"**{profile['name']}** entrou no combate com iniciativa "
            f"`{initiative_value:g}`.",
            ephemeral=True,
        )

    @app_commands.command(
        name="combat_next_turn",
        description="Encerra o turno atual e passa para o próximo participante.",
    )
    async def combat_next_turn(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        session = get_active_combat_session(
            self.db_connection, interaction.channel_id
        )
        if session is None:
            await interaction.followup.send(
                "Erro: não existe combate ativo neste canal.",
                ephemeral=True,
            )
            return

        active_character_id = session.get("active_character_id")
        if not self._is_gm(interaction) and (
            active_character_id is None
            or not self._can_manage_character(
                interaction, int(active_character_id)
            )
        ):
            await interaction.followup.send(
                "Erro: apenas o participante ativo ou o mestre podem avançar o turno.",
                ephemeral=True,
            )
            return

        try:
            result = advance_combat_turn(
                self.db_connection, interaction.channel_id
            )
        except ValueError as error:
            await interaction.followup.send(
                f"Erro: {error}",
                ephemeral=True,
            )
            return

        session = result["session"]
        next_participant = result["next_participant"]
        round_number = result["round_number"]

        if session is not None:
            if not await self._edit_stored_panel(session):
                await self._send_panel_to_channel(
                    session, interaction.channel
                )

        await interaction.followup.send(
            f"Turno de **{next_participant['character_name']}** "
            f"(rodada {round_number}).",
            ephemeral=True,
        )

    @app_commands.command(
        name="combat_undo",
        description="Desfaz o último dano aplicado neste canal.",
    )
    async def combat_undo(self, interaction: discord.Interaction):
        if not self._is_gm(interaction):
            await interaction.response.send_message(
                "Erro: apenas o mestre pode desfazer dano.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        active_session = get_active_combat_session(
            self.db_connection, interaction.channel_id
        )
        log_entry = get_last_damage_log(
            self.db_connection,
            interaction.channel_id,
            int(active_session["session_id"])
            if active_session is not None
            else None,
        )
        if log_entry is None:
            await interaction.followup.send(
                "Erro: nenhum dano pendente de reversão.",
                ephemeral=True,
            )
            return

        target_character_id = int(log_entry["target_character_id"])
        try:
            profile = get_character_profile_by_id(
                self.db_connection, target_character_id
            )
        except ValueError:
            await interaction.followup.send(
                "Erro: personagem do dano não foi localizado.",
                ephemeral=True,
            )
            return

        current_pv = int(profile.get("current_pv") or 0)
        if current_pv != int(log_entry["hp_after"]):
            await interaction.followup.send(
                "Erro: o PV do alvo mudou desde esse dano; reversão cancelada.",
                ephemeral=True,
            )
            return

        with self.db_connection:
            set_character_current_pv(
                self.db_connection,
                target_character_id,
                int(log_entry["hp_before"]),
            )
            mark_combat_log_reverted(
                self.db_connection, int(log_entry["log_id"])
            )
            add_combat_log(
                self.db_connection,
                session_id=log_entry.get("session_id"),
                channel_id=interaction.channel_id,
                event_type="undo",
                target_character_id=target_character_id,
                value=int(log_entry["value"] or 0),
                hp_before=int(log_entry["hp_after"]),
                hp_after=int(log_entry["hp_before"]),
                description=(
                    f"Dano de {log_entry['value']} desfeito em "
                    f"{profile['name']} (PV {log_entry['hp_after']} -> "
                    f"{log_entry['hp_before']})."
                ),
            )

        session = get_active_combat_session(
            self.db_connection, interaction.channel_id
        )
        if session is not None:
            if not await self._edit_stored_panel(session):
                await self._send_panel_to_channel(
                    session, interaction.channel
                )

        await interaction.followup.send(
            f"Dano desfeito: **{profile['name']}** voltou a "
            f"`{log_entry['hp_before']}` PV.",
            ephemeral=True,
        )

    @app_commands.command(
        name="combat_feint",
        description="Executa uma finta e aplica penalidade à próxima defesa do alvo.",
    )
    @app_commands.autocomplete(
        alvo=participant_autocomplete,
        personagem=participant_autocomplete,
        pericia=skill_autocomplete,
    )
    @app_commands.describe(
        alvo="Personagem alvo da finta.",
        personagem="Apenas para o mestre: personagem que está fintando.",
        pericia="Perícia de combate usada na finta.",
        nh_manual="Substitui o NH calculado pela perícia.",
        defesa="NH de resistência do alvo. Se omitido, usa a melhor perícia de combate.",
        modificador="Modificador situacional adicional de NH.",
    )
    async def combat_feint(
        self,
        interaction: discord.Interaction,
        alvo: str,
        personagem: str | None = None,
        pericia: str | None = None,
        nh_manual: int | None = None,
        defesa: int | None = None,
        modificador: int | None = None,
    ):
        await perform_feint(
            self,
            interaction,
            alvo=alvo,
            personagem=personagem,
            pericia=pericia,
            nh_manual=nh_manual,
            defesa=defesa,
            modificador=modificador,
        )

    @app_commands.command(
        name="combat_attack",
        description="Ataca com uma arma equipada usando NH, dano e defesa automáticos.",
    )
    @app_commands.autocomplete(
        alvo=participant_autocomplete,
        arma=weapon_autocomplete,
        personagem=participant_autocomplete,
    )
    @app_commands.describe(
        alvo="Personagem alvo do ataque.",
        arma="Arma equipada. Se omitido, usa a primeira arma corpo a corpo equipada.",
        personagem="Apenas para o mestre: personagem que está atacando.",
        local="Local atingido.",
        manobra="Manobra de combate aplicada.",
        modificador="Modificador situacional adicional de NH.",
        nh_manual="Substitui o NH calculado pela arma.",
    )
    @app_commands.choices(
        local=[
            app_commands.Choice(
                name=f"{location['name']} ({location['penalty']:+d})",
                value=hit_location_id,
            )
            for hit_location_id, location in HIT_LOCATIONS.items()
        ],
        manobra=[
            app_commands.Choice(name=maneuver["label"], value=key)
            for key, maneuver in MANEUVERS.items()
        ],
    )
    async def combat_attack(
        self,
        interaction: discord.Interaction,
        alvo: str,
        arma: str | None = None,
        personagem: str | None = None,
        local: app_commands.Choice[int] | None = None,
        manobra: app_commands.Choice[str] | None = None,
        modificador: int | None = None,
        nh_manual: int | None = None,
    ):
        await perform_attack(
            self,
            interaction,
            alvo=alvo,
            arma=arma,
            personagem=personagem,
            local=local,
            manobra=manobra,
            modificador=modificador,
            nh_manual=nh_manual,
        )

    async def _repeat_attack_from_action(
        self, interaction: discord.Interaction, claimed: dict
    ):
        await repeat_attack(self, interaction, claimed)



async def setup(bot: commands.Bot) -> None:
    """Mandatory asynchronous entry point to load the extension."""
    await bot.add_cog(Combat(bot))
