"""Ephemeral views for the GM shield panel."""

from __future__ import annotations

import sqlite3

import discord

from utils.ansi import code_block, resource_bar
from utils.db_functions import (
    get_all_combat_effects,
    get_character_combat_effects,
    get_character_combat_profile,
    link_character_effect,
    unlink_character_effect,
)
from utils.i18n import catalog_label, get_locale, locale_context, t as tr
from utils.gm_directives import gm_shield_store

KIND_LABELS = {
    "generic": "Any roll",
    "skill_test": "Skill Test",
    "quick_contest": "Quick Contest",
    "generic_roll": "Generic Roll",
    "reaction": "Reaction",
    "panic": "Panic",
    "panic_table": "Panic Table",
    "attack": "Attack",
    "defense": "Defense",
    "health_consciousness": "Consciousness Check",
    "health_death": "Death Check",
}

PRESET_LABELS = {
    "min": "Minimum",
    "low": "Low",
    "average": "Average",
    "high": "High",
    "max": "Maximum",
    "exact": "Exact",
}

OUTCOME_LABELS = {
    "random": "Random",
    "success": "Success",
    "failure": "Failure",
    "critical_success": "Critical Success",
    "critical_failure": "Critical Failure",
    "win": "Win",
    "lose": "Lose",
    "dying": "Dying",
    "dead": "Dead",
    "disastrous": "Disastrous",
    "bad": "Bad",
    "good": "Good",
    "excellent": "Excellent",
}


def _clamp(value: object, limit: int = 1000) -> str:
    return str(value)[:limit]


def _is_dm(interaction: discord.Interaction, dm_id: int) -> bool:
    return int(getattr(interaction.user, "id", 0)) == int(dm_id)


class GMShieldView(discord.ui.View):
    """Shared state and authorization for the GM shield panel."""

    def __init__(
        self,
        *,
        connection: sqlite3.Connection,
        dm_id: int,
        player_id: int,
        character: dict,
        locale: str | None = None,
    ):
        super().__init__(timeout=900)
        self.connection = connection
        self.dm_id = dm_id
        self.player_id = player_id
        self.character = character
        self.character_id = int(character["character_id"])
        self.locale = locale or get_locale()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        with locale_context(self.locale):
            if not _is_dm(interaction, self.dm_id):
                await interaction.response.send_message(
                    tr("Error: only the GM can use this panel."),
                    ephemeral=True,
                )
                return False
            return True

    def build_embed(self, *, closed: bool = False) -> discord.Embed:
        with locale_context(self.locale):
            if closed:
                return discord.Embed(
                    title=tr("Panel closed"),
                    color=discord.Color.dark_grey(),
                )

            try:
                profile, _effects = get_character_combat_profile(
                    self.connection, self.character_id
                )
            except ValueError:
                profile = self.character
            max_pv = int(
                profile.get("max_pv")
                or (
                    int(profile["st"])
                    + int(profile.get("additional_max_pv") or 0)
                )
            )
            current_pv = int(profile.get("current_pv") or 0)
            embed = discord.Embed(
                title=f"{tr('GM Shield')} - {profile['name']}"[:256],
                color=discord.Color.dark_red(),
            )
            embed.add_field(
                name=tr("Current State"),
                value=code_block(
                    [resource_bar(tr("HP"), current_pv, max(1, max_pv))]
                ),
                inline=False,
            )

            directives = gm_shield_store.active_for(
                character_id=self.character_id,
                player_id=self.player_id,
            )
            directive_lines = []
            for directive in directives:
                kind = tr(
                    KIND_LABELS.get(directive.roll_kind, directive.roll_kind)
                )
                outcome = tr(
                    OUTCOME_LABELS.get(directive.outcome, directive.outcome)
                )
                detail = f"{kind}: {outcome}"
                preset = directive.payload.get("damage_preset")
                if preset:
                    preset_label = PRESET_LABELS.get(preset, preset)
                    detail += f" ({tr('Damage')}: {tr(preset_label)})"
                directive_lines.append(f"* {detail}")
            embed.add_field(
                name=tr("Pending Directives"),
                value=_clamp(
                    "\n".join(directive_lines)
                    if directive_lines
                    else tr("None.")
                ),
                inline=False,
            )

            flags = gm_shield_store.get_flags(self.character_id)
            state_lines = []
            if flags.get("no_faint"):
                state_lines.append(f"* {tr('Cannot faint')}")
            if flags.get("no_death"):
                state_lines.append(f"* {tr('Cannot die from death checks')}")
            embed.add_field(
                name=tr("Active States"),
                value=_clamp(
                    "\n".join(state_lines) if state_lines else tr("None.")
                ),
                inline=False,
            )
            return embed


class GMShieldSubView(GMShieldView):
    """Base subview with a back button."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        back = discord.ui.Button(
            label=tr("Back"),
            style=discord.ButtonStyle.secondary,
        )
        back.callback = self.restore_hub
        self.add_item(back)

    async def restore_hub(self, interaction: discord.Interaction):
        with locale_context(self.locale):
            hub = GMShieldHubView(
                connection=self.connection,
                dm_id=self.dm_id,
                player_id=self.player_id,
                character=self.character,
                locale=self.locale,
            )
            await interaction.response.edit_message(
                embed=hub.build_embed(), view=hub
            )


class NavigationSelect(discord.ui.Select):
    """Select one GM shield category."""

    def __init__(self):
        super().__init__(
            placeholder=tr("Choose a category..."),
            options=[
                discord.SelectOption(label=tr("Next Rolls"), value="rolls"),
                discord.SelectOption(label=tr("Attack"), value="attack"),
                discord.SelectOption(label=tr("Defense"), value="defense"),
                discord.SelectOption(label=tr("Health"), value="health"),
                discord.SelectOption(label=tr("Effects"), value="effects"),
            ],
        )

    async def callback(self, interaction: discord.Interaction):
        view: GMShieldHubView = self.view  # type: ignore
        with locale_context(view.locale):
            category = self.values[0]
            if category == "rolls":
                new_view = GMShieldNextRollView(
                    connection=view.connection,
                    dm_id=view.dm_id,
                    player_id=view.player_id,
                    character=view.character,
                    locale=view.locale,
                )
            elif category == "attack":
                new_view = GMShieldAttackView(
                    connection=view.connection,
                    dm_id=view.dm_id,
                    player_id=view.player_id,
                    character=view.character,
                    locale=view.locale,
                )
            elif category == "defense":
                new_view = GMShieldDefenseView(
                    connection=view.connection,
                    dm_id=view.dm_id,
                    player_id=view.player_id,
                    character=view.character,
                    locale=view.locale,
                )
            elif category == "health":
                new_view = GMShieldHealthView(
                    connection=view.connection,
                    dm_id=view.dm_id,
                    player_id=view.player_id,
                    character=view.character,
                    locale=view.locale,
                )
            else:
                new_view = GMShieldEffectsView(
                    connection=view.connection,
                    dm_id=view.dm_id,
                    player_id=view.player_id,
                    character=view.character,
                    locale=view.locale,
                )
            await interaction.response.edit_message(
                embed=new_view.build_embed(), view=new_view
            )


class CloseButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label=tr("Close panel"), style=discord.ButtonStyle.danger
        )

    async def callback(self, interaction: discord.Interaction):
        view: GMShieldHubView = self.view  # type: ignore
        with locale_context(view.locale):
            await interaction.response.edit_message(
                embed=view.build_embed(closed=True), view=None
            )


class GMShieldHubView(GMShieldView):
    """Main GM shield hub."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.add_item(NavigationSelect())
        self.add_item(CloseButton())


class RollOptionSelect(discord.ui.Select):
    """Select a roll kind and its requested outcome."""

    OPTIONS = (
        ("Skill Test", "Success", "skill_test:success"),
        ("Skill Test", "Failure", "skill_test:failure"),
        ("Skill Test", "Critical Success", "skill_test:critical_success"),
        ("Skill Test", "Critical Failure", "skill_test:critical_failure"),
        ("Quick Contest", "Win", "quick_contest:win"),
        ("Quick Contest", "Lose", "quick_contest:lose"),
        (
            "Quick Contest",
            "Opponent fails",
            "quick_contest:critical_success",
        ),
        ("Quick Contest", "You fail", "quick_contest:critical_failure"),
        ("Generic Roll", "Minimum", "generic_roll:min"),
        ("Generic Roll", "Maximum", "generic_roll:max"),
        ("Generic Roll", "Exact", "generic_roll:exact"),
        ("Reaction", "Disastrous", "reaction:disastrous"),
        ("Reaction", "Bad", "reaction:bad"),
        ("Reaction", "Good", "reaction:good"),
        ("Reaction", "Excellent", "reaction:excellent"),
        ("Panic", "Success", "panic:success"),
        ("Panic", "Failure", "panic:failure"),
        ("Panic", "Critical Success", "panic:critical_success"),
        ("Panic", "Critical Failure", "panic:critical_failure"),
        ("Panic Table", "Minimum", "panic_table:min"),
        ("Panic Table", "Maximum", "panic_table:max"),
        ("Panic Table", "Exact", "panic_table:exact"),
    )

    def __init__(self):
        super().__init__(
            placeholder=tr("Select the next result..."),
            options=[
                discord.SelectOption(
                    label=f"{tr(kind)}: {tr(outcome)}",
                    value=value,
                )
                for kind, outcome, value in self.OPTIONS
            ],
        )

    async def callback(self, interaction: discord.Interaction):
        view: GMShieldNextRollView = self.view  # type: ignore
        with locale_context(view.locale):
            kind, outcome = self.values[0].split(":", 1)
            if outcome == "exact":
                await interaction.response.send_modal(
                    ExactTotalModal(
                        title=tr("Exact total"),
                        label=tr("Total"),
                        on_submit_callback=view.apply_exact,
                        kind=kind,
                        locale=view.locale,
                    )
                )
                return
            payload = {}
            if outcome in {"min", "max"}:
                payload["preset"] = outcome
                outcome = "random"
            elif kind == "reaction":
                payload = {}
            gm_shield_store.set(
                character_id=view.character_id,
                player_id=view.player_id,
                roll_kind=kind,
                outcome=outcome,
                payload=payload,
            )
            await interaction.response.edit_message(
                embed=view.build_embed(), view=view
            )


class ClearButton(discord.ui.Button):
    def __init__(self, roll_kind: str | None = None):
        super().__init__(
            label=tr("Clear all") if roll_kind is None else tr("Clear"),
            style=discord.ButtonStyle.secondary,
        )
        self.roll_kind = roll_kind

    async def callback(self, interaction: discord.Interaction):
        view: GMShieldView = self.view  # type: ignore
        with locale_context(view.locale):
            gm_shield_store.remove(
                character_id=view.character_id,
                roll_kind=self.roll_kind,
            )
            if self.roll_kind is None:
                gm_shield_store.remove(player_id=view.player_id)
            await interaction.response.edit_message(
                embed=view.build_embed(), view=view
            )


class GMShieldNextRollView(GMShieldSubView):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.add_item(RollOptionSelect())
        self.add_item(ClearButton())

    async def apply_exact(
        self, interaction: discord.Interaction, total: int, kind: str
    ):
        with locale_context(self.locale):
            gm_shield_store.set(
                character_id=self.character_id,
                player_id=self.player_id,
                roll_kind=kind,
                outcome="random",
                payload={"preset": "exact", "exact_total": total},
            )
            await interaction.response.send_message(
                tr("Pending result updated."), ephemeral=True
            )


class AttackOutcomeSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder=tr("Attack result..."),
            options=[
                discord.SelectOption(label=tr("Random"), value="random"),
                discord.SelectOption(label=tr("Success"), value="success"),
                discord.SelectOption(label=tr("Failure"), value="failure"),
                discord.SelectOption(
                    label=tr("Critical Success"), value="critical_success"
                ),
                discord.SelectOption(
                    label=tr("Critical Failure"), value="critical_failure"
                ),
            ],
        )

    async def callback(self, interaction: discord.Interaction):
        view: GMShieldAttackView = self.view  # type: ignore
        with locale_context(view.locale):
            view.outcome = self.values[0]
            await interaction.response.edit_message(
                embed=view.build_embed(), view=view
            )


class AttackDamageSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder=tr("Damage preset..."),
            options=[
                discord.SelectOption(label=tr("None"), value="none"),
                discord.SelectOption(label=tr("Minimum"), value="min"),
                discord.SelectOption(label=tr("Low"), value="low"),
                discord.SelectOption(label=tr("Average"), value="average"),
                discord.SelectOption(label=tr("High"), value="high"),
                discord.SelectOption(label=tr("Maximum"), value="max"),
                discord.SelectOption(label=tr("Exact"), value="exact"),
            ],
        )

    async def callback(self, interaction: discord.Interaction):
        view: GMShieldAttackView = self.view  # type: ignore
        with locale_context(view.locale):
            value = self.values[0]
            if value == "exact":
                await interaction.response.send_modal(
                    ExactTotalModal(
                        title=tr("Exact damage"),
                        label=tr("Damage"),
                        on_submit_callback=view.apply_exact_damage,
                        kind="attack",
                        locale=view.locale,
                    )
                )
                return
            view.damage_preset = None if value == "none" else value
            view.damage_exact = None
            await interaction.response.edit_message(
                embed=view.build_embed(), view=view
            )


class ApplyButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label=tr("Apply"), style=discord.ButtonStyle.primary
        )

    async def callback(self, interaction: discord.Interaction):
        view: GMShieldAttackView = self.view  # type: ignore
        with locale_context(view.locale):
            gm_shield_store.set(
                character_id=view.character_id,
                player_id=view.player_id,
                roll_kind="attack",
                outcome=view.outcome,
                payload={
                    "damage_preset": view.damage_preset,
                    "damage_exact": view.damage_exact,
                },
            )
            await interaction.response.edit_message(
                embed=view.build_embed(), view=view
            )


class GMShieldAttackView(GMShieldSubView):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.outcome = "random"
        self.damage_preset: str | None = None
        self.damage_exact: int | None = None
        self.add_item(AttackOutcomeSelect())
        self.add_item(AttackDamageSelect())
        self.add_item(ApplyButton())
        self.add_item(ClearButton("attack"))

    def build_embed(self, *, closed: bool = False) -> discord.Embed:
        embed = super().build_embed(closed=closed)
        if not closed:
            with locale_context(self.locale):
                value = (
                    f"{tr('Result')}: `{tr(OUTCOME_LABELS.get(self.outcome, self.outcome))}`\n"
                    f"{tr('Damage')}: `{tr(PRESET_LABELS.get(self.damage_preset, self.damage_preset)) if self.damage_preset else tr('None')}`"
                )
                if self.damage_exact is not None:
                    value += f" `{self.damage_exact}`"
                if (
                    self.outcome == "critical_success"
                    and self.damage_preset is not None
                ):
                    value += "\n" + tr(
                        "Damage presets convert critical success to normal success."
                    )
                embed.add_field(
                    name=tr("Attack Settings"),
                    value=value,
                    inline=False,
                )
        return embed

    async def apply_exact_damage(
        self, interaction: discord.Interaction, total: int, kind: str
    ):
        with locale_context(self.locale):
            self.damage_preset = "exact"
            self.damage_exact = int(total)
            gm_shield_store.set(
                character_id=self.character_id,
                player_id=self.player_id,
                roll_kind="attack",
                outcome=self.outcome,
                payload={
                    "damage_preset": "exact",
                    "damage_exact": int(total),
                },
            )
            await interaction.response.send_message(
                tr("Pending result updated."), ephemeral=True
            )


class DefenseOutcomeSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder=tr("Next defense result..."),
            options=[
                discord.SelectOption(label=tr("Clear"), value="clear"),
                discord.SelectOption(label=tr("Success"), value="success"),
                discord.SelectOption(label=tr("Failure"), value="failure"),
                discord.SelectOption(
                    label=tr("Critical Success"), value="critical_success"
                ),
                discord.SelectOption(
                    label=tr("Critical Failure"), value="critical_failure"
                ),
            ],
        )

    async def callback(self, interaction: discord.Interaction):
        view: GMShieldDefenseView = self.view  # type: ignore
        with locale_context(view.locale):
            value = self.values[0]
            if value == "clear":
                gm_shield_store.remove(
                    character_id=view.character_id,
                    roll_kind="defense",
                )
            else:
                gm_shield_store.set(
                    character_id=view.character_id,
                    player_id=view.player_id,
                    roll_kind="defense",
                    outcome=value,
                )
            await interaction.response.edit_message(
                embed=view.build_embed(), view=view
            )


class GMShieldDefenseView(GMShieldSubView):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.add_item(DefenseOutcomeSelect())


class HealthConsciousnessSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder=tr("Next consciousness check..."),
            options=[
                discord.SelectOption(label=tr("Clear"), value="clear"),
                discord.SelectOption(label=tr("Success"), value="success"),
                discord.SelectOption(label=tr("Failure"), value="failure"),
            ],
        )

    async def callback(self, interaction: discord.Interaction):
        view: GMShieldHealthView = self.view  # type: ignore
        with locale_context(view.locale):
            value = self.values[0]
            if value == "clear":
                gm_shield_store.remove(
                    character_id=view.character_id,
                    roll_kind="health_consciousness",
                )
            else:
                gm_shield_store.set(
                    character_id=view.character_id,
                    player_id=view.player_id,
                    roll_kind="health_consciousness",
                    outcome=value,
                )
            await interaction.response.edit_message(
                embed=view.build_embed(), view=view
            )


class HealthDeathSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder=tr("Next death check..."),
            options=[
                discord.SelectOption(label=tr("Clear"), value="clear"),
                discord.SelectOption(label=tr("Success"), value="success"),
                discord.SelectOption(label=tr("Dying"), value="dying"),
                discord.SelectOption(label=tr("Dead"), value="dead"),
            ],
        )

    async def callback(self, interaction: discord.Interaction):
        view: GMShieldHealthView = self.view  # type: ignore
        with locale_context(view.locale):
            value = self.values[0]
            if value == "clear":
                gm_shield_store.remove(
                    character_id=view.character_id,
                    roll_kind="health_death",
                )
            else:
                gm_shield_store.set(
                    character_id=view.character_id,
                    player_id=view.player_id,
                    roll_kind="health_death",
                    outcome=value,
                )
            await interaction.response.edit_message(
                embed=view.build_embed(), view=view
            )


class NoFaintButton(discord.ui.Button):
    def __init__(self, active: bool = False):
        super().__init__(
            label=tr("Cannot faint"),
            style=(
                discord.ButtonStyle.success
                if active
                else discord.ButtonStyle.secondary
            ),
        )

    async def callback(self, interaction: discord.Interaction):
        view: GMShieldHealthView = self.view  # type: ignore
        with locale_context(view.locale):
            current = gm_shield_store.get_flag(
                view.character_id, "no_faint"
            )
            gm_shield_store.set_flag(
                view.character_id, "no_faint", not current
            )
            new_view = GMShieldHealthView(
                connection=view.connection,
                dm_id=view.dm_id,
                player_id=view.player_id,
                character=view.character,
                locale=view.locale,
            )
            await interaction.response.edit_message(
                embed=new_view.build_embed(), view=new_view
            )


class NoDeathButton(discord.ui.Button):
    def __init__(self, active: bool = False):
        super().__init__(
            label=tr("Cannot die from checks"),
            style=(
                discord.ButtonStyle.success
                if active
                else discord.ButtonStyle.secondary
            ),
        )

    async def callback(self, interaction: discord.Interaction):
        view: GMShieldHealthView = self.view  # type: ignore
        with locale_context(view.locale):
            current = gm_shield_store.get_flag(
                view.character_id, "no_death"
            )
            gm_shield_store.set_flag(
                view.character_id, "no_death", not current
            )
            new_view = GMShieldHealthView(
                connection=view.connection,
                dm_id=view.dm_id,
                player_id=view.player_id,
                character=view.character,
                locale=view.locale,
            )
            await interaction.response.edit_message(
                embed=new_view.build_embed(), view=new_view
            )


class GMShieldHealthView(GMShieldSubView):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        flags = gm_shield_store.get_flags(self.character_id)
        self.add_item(HealthConsciousnessSelect())
        self.add_item(HealthDeathSelect())
        self.add_item(NoFaintButton(flags.get("no_faint", False)))
        self.add_item(NoDeathButton(flags.get("no_death", False)))

    def build_embed(self, *, closed: bool = False) -> discord.Embed:
        embed = super().build_embed(closed=closed)
        if not closed:
            with locale_context(self.locale):
                flags = gm_shield_store.get_flags(self.character_id)
                state = []
                if flags.get("no_faint"):
                    state.append(tr("Cannot faint"))
                if flags.get("no_death"):
                    state.append(tr("Cannot die from death checks"))
                embed.add_field(
                    name=tr("Health States"),
                    value="\n".join(state) if state else tr("None."),
                    inline=False,
                )
        return embed


class EffectSelect(discord.ui.Select):
    def __init__(self, effects: list[dict]):
        options = [
            discord.SelectOption(
                label=str(effect["name"])[:100],
                value=str(effect["effect_id"]),
                description=catalog_label(
                    "effect_types", str(effect.get("applies_to") or "")
                )[:100],
            )
            for effect in effects[:25]
        ]
        super().__init__(
            placeholder=tr("Select an effect..."),
            options=options or [
                discord.SelectOption(label=tr("No effects available"), value="0")
            ],
            disabled=not options,
        )

    async def callback(self, interaction: discord.Interaction):
        view: GMShieldEffectsView = self.view  # type: ignore
        with locale_context(view.locale):
            view.selected_effect_id = int(self.values[0]) or None
            await interaction.response.edit_message(
                embed=view.build_embed(), view=view
            )


class EffectActionButton(discord.ui.Button):
    def __init__(self, *, add: bool):
        super().__init__(
            label=tr("Add effect") if add else tr("Remove effect"),
            style=(
                discord.ButtonStyle.success
                if add
                else discord.ButtonStyle.danger
            ),
        )
        self.add = add

    async def callback(self, interaction: discord.Interaction):
        view: GMShieldEffectsView = self.view  # type: ignore
        with locale_context(view.locale):
            if view.selected_effect_id is None:
                await interaction.response.send_message(
                    tr("Select an effect first."), ephemeral=True
                )
                return
            if self.add:
                link_character_effect(
                    view.connection,
                    view.character_id,
                    view.selected_effect_id,
                )
            else:
                unlink_character_effect(
                    view.connection,
                    view.character_id,
                    view.selected_effect_id,
                )
            view.connection.commit()
            new_view = GMShieldEffectsView(
                connection=view.connection,
                dm_id=view.dm_id,
                player_id=view.player_id,
                character=view.character,
                locale=view.locale,
            )
            await interaction.response.edit_message(
                embed=new_view.build_embed(), view=new_view
            )


class GMShieldEffectsView(GMShieldSubView):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.selected_effect_id: int | None = None
        self.catalog = get_all_combat_effects(self.connection, 25)
        self.add_item(EffectSelect(self.catalog))
        self.add_item(EffectActionButton(add=True))
        self.add_item(EffectActionButton(add=False))

    def build_embed(self, *, closed: bool = False) -> discord.Embed:
        embed = super().build_embed(closed=closed)
        if not closed:
            with locale_context(self.locale):
                active = get_character_combat_effects(
                    self.connection, self.character_id
                )
                active_lines = [
                    f"* {effect['name']} ({catalog_label('effect_types', str(effect.get('applies_to') or ''))})"
                    for effect in active[:25]
                ]
                embed.add_field(
                    name=tr("Active Effects"),
                    value=_clamp(
                        "\n".join(active_lines)
                        if active_lines
                        else tr("None.")
                    ),
                    inline=False,
                )
        return embed


class ExactTotalModal(discord.ui.Modal):
    """Ask for an exact total and delegate the update."""

    total = discord.ui.TextInput(
        label="Total",
        required=True,
        max_length=6,
        placeholder="10",
    )

    def __init__(
        self,
        *,
        title: str,
        label: str,
        on_submit_callback,
        kind: str,
        locale: str | None = None,
    ):
        super().__init__(title=title)
        self.on_submit_callback = on_submit_callback
        self.kind = kind
        self.locale = locale or get_locale()
        with locale_context(self.locale):
            self.total.label = tr(label)

    async def on_submit(self, interaction: discord.Interaction):
        with locale_context(self.locale):
            try:
                value = int(str(self.total.value).strip())
            except ValueError:
                await interaction.response.send_message(
                    tr("Error: enter an integer value."), ephemeral=True
                )
                return
            await self.on_submit_callback(interaction, value, self.kind)
