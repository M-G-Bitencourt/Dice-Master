![Python](https://img.shields.io/badge/Python-3.14+-blue?logo=python&logoColor=white)

![Dice Master Banner](/assets/github_banner.png)

# Dice-Master

[Leia este documento em português](README.pt-BR.md)

Dice Master is a Discord bot designed to simplify GURPS sessions. It streamlines gameplay by automating dice rolls, damage calculations, and character sheet management directly in the chat.

## Localization

The default language is English. Server administrators can change the bot language with `/language`; English and Brazilian Portuguese are available. Responses, embeds, buttons, modals, and error messages follow the server language, while Discord localizes slash command names and descriptions according to each user's client language. Portuguese clients see localized command names such as `/ficha`, `/inventario`, and `/combate_atacar`. New languages can be added through `locales/` without changing code; see `locales/README.md`.

## General Commands
| Command | Description |
| :---: | :---: |
| /help | List all available commands and their descriptions. |

## Settings Commands
| Command | Description |
| :---: | :---: |
| /language | Change the bot language for this server. |

## Battle Commands
| Command | Description |
| :---: | :---: |
| /damage | Roll damage without altering the database. |
| /combat_aim | Execute an aim maneuver with a ranged weapon. |
| /combat_evaluate | Execute an evaluate maneuver with a melee weapon. |

## Administrative Commands
| Command | Description |
| :---: | :---: |
| /manage_character_resource_pool | Manage HP, FP, and ER for all characters. |
| /restore_character_resources    | Restore a character's HP, FP, and ER to their maximum values. |
| /switch_character               | Switch the player's active character. |
| /manage_next_turn_conditions    | Manage shock, evaluate, aim, and feint statuses. |
| /clear_next_turn_conditions     | Clear all feint, evaluate, aim, and shock modifiers. |
| /view_next_turn_conditions      | View feint, aim, evaluate, and shock modifiers for a specific character. |
| /manage_xp                      | Adds or removes character points from a character. |


## Combat Commands
| Command | Description |
| :---: | :---: |
| /combat_start | Creates or refreshes the combat panel for the current channel. |
| /combat_attack | Attacks with an equipped melee or ranged weapon using automatic skill, encumbrance, damage, hit location and defence resolution. |
| /combat_feint | Runs a quick contest and applies the resulting penalty to the actor's next attack. |
| /combat_enter | Adds a character to the combat with initiative; the default is Basic Speed, preserving decimals. |
| /combat_next_turn | Advances to the next participant and starts a new round when needed. |
| /combat_undo | Reverts the last damage applied in the channel (GM only). |
| /combat_end | Ends the combat and discards the pending attack. |
| /combat_manage_effect | Adds or removes a catalog effect from a character; the catalog is managed externally. |

Phase 1 supports equipped melee weapons. Attacks are published with defence buttons; the target or the GM resolves them in place. Only one attack may be pending per channel, and a new attack supersedes the previous one. Armour uses the configured layer order. Each flexible layer beneath a rigid layer loses 1 DR, and multiple rigid layers produce a warning for the GM. The GM can override RD and NH through the adjustment modal.

Phase 2 adds structured effects from an external catalog, per-turn defence uses, extra defence attempts, turn rotation resets via `/combat_next_turn` and quick actions after a resolved attack. The bot only links or unlinks catalog effects; resources and costs are managed externally. A resolved attack offers `Repetir ataque`, `Mirar` and `Avaliar` to the attacker or GM. The combat panel lists participants and the current round.

Phase 3 adds equipped ranged weapons with parsed damage expressions such as `2d+1 imp`, initiative and active-turn tracking, a persistent combat panel message, combat event history in the panel, and GM damage undo. Initiative defaults to Basic Speed and accepts decimal values. Ranged weapons carry their required skill ID; attacks check that the character owns that skill. Ranged attacks use Aim instead of Evaluate and cannot be parried unless the table allows it; targets still dodge by default. Encumbrance penalties apply to melee attacks, ranged attacks and feints. Unarmed attacks are provided by internal weapons tied to unarmed skills; characters without a specific unarmed skill use the generic unarmed modes with a DX-4 default.

Phase 4 starts by splitting the combat flow into focused modules and adds `/combat_feint`. A successful feint stores a defence penalty on the attacker, consumed by their next attack. Failed feints clear the attacker's previous transient conditions. Characters enter combat only through `/combat_enter`; attacks and feints require both characters to be participants. Defence is resolved through the buttons attached to a pending attack, not by a slash command. The panel offers an on-demand repost refresh and a GM-only advance-turn button.

## Damage Rules

- At 1/3 of maximum PV or less, Basic Move and Dodge are halved.
- Crossing to 0 PV or below triggers an automatic HT check for consciousness.
- Reaching -1x, -2x, -3x and further multiples of maximum PV triggers automatic death checks.
- A death check failure by 1 or 2 means dying; failure by 3 or more means dead.
- At -5x maximum PV the character is dead; at -10x the body is obliterated.
- Checks are resolved per damage event and shown in the attack or defence embed. Persistent injury states remain external to the bot.
- Damage embeds show the weapon expression, rolled dice, the summed modifiers and the total damage. Defence resolution then shows raw damage, DR, penetrating damage, multiplier and applied damage.
- Injury inflicts shock on the target's next turn: -1 per HP lost, capped at -4. Characters with 20+ maximum PV use one point per `max_pv // 10` injury. Shock accumulates across hits up to -4, affects DX/IQ-based attacks and feints, never defences, and expires at the end of the character's turn.

## Skill Test Commands
| Command | Description |
| :---: | :---: |
| /test | Perform a success roll. |
| /qkd | Resolve a quick contest and return the winner. |

## Sheet Commands
| Command | Description |
| :---: | :---: |
| /sheet | Display your character sheet in an ephemeral message. |
| /sheet_view | Display any player or NPC character sheet for the GM. |

## Inventory Commands
| Command | Description |
| :---: | :---: |
| /manage_money | Adds or removes money from a character. |
| /inventory | Displays the complete inventory. |

## Other Tests Commands
| Command | Description |
| :--- | :--- |
| /roll | Roll a variable number of d6s and return their sum. |
| /react | Perform a reaction roll. |
| /panic | Execute a panic check and return the result. |

## Screenshots

### Administrative Commands

<p align="center">
  <img src="/assets/restore_character_resource.png" alt="/restore_character_resources output" width="45%">
  <br>
  <em>`/restore_character_resources` output</em>
</p>

### Skill Test Commands

<p align="center">
  <img src="/assets/test.png" alt="/test success roll" width="45%">
  <img src="/assets/quick_dispute.png" alt="/qkd quick contest result" width="45%">
  <br>
  <em>`/test` success roll | `/qkd` quick contest result</em>
</p>

### Sheet Commands

<p align="center">
  <img src="/assets/sheet.png" alt="/sheet character sheet hub" width="45%">
  <br>
  <em>`/sheet` character sheet hub</em>
</p>

### Inventory Commands

<p align="center">
  <img src="/assets/manage_money.png" alt="/manage_money transaction" width="45%">
  <br>
  <em>`/manage_money` transaction</em>
</p>

### Other Tests Commands

<p align="center">
  <img src="/assets/react.png" alt="/react reaction roll" width="45%">
  <img src="/assets/panic.png" alt="/panic panic check" width="45%">
  <br>
  <em>`/react` reaction roll | `/panic` panic check</em>
</p>
