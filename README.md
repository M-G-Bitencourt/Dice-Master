![Python](https://img.shields.io/badge/Python-3.14+-blue?logo=python&logoColor=white)

![Dice Master Banner](/assets/github_banner.png)

# Dice-Master
Dice Master is a Discord bot designed to simplify GURPS sessions. It streamlines gameplay by automating dice rolls, damage calculations, and character sheet management directly in the chat.

## General Commands
| Command | Description |
| :---: | :---: |
| /help | List all available commands and their descriptions. |

## Battle Commands
| Command | Description |
| :---: | :---: |
| /dmg | Roll damage without altering the database. |
| /atk | Execute a full melee attack, calculating effective skill modified by evaluate, feint, or shock, determining success, and rolling damage. |
| /ranged_attack | Execute a full ranged attack, calculating effective skill modified by aim or shock, determining success, and rolling damage. |
| /def | Resolve all defense and damage evaluation phases, including penetrating damage verification, final injury calculation with hit location and damage type modifiers, and limb crippling or amputation. |
| /fnt | Execute a feint maneuver. |
| /apt | Execute an aim maneuver with a ranged weapon. |
| /eval | Execute an evaluate maneuver with a melee weapon. |

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
| /list_skills | Displays all skills possessed by your character, their Skill Level (SL), and their description.|
| /master_list_skills| Displays all skills possessed by any character, their Skill Level (SL), and their description |
| /list_spells | Displays all spells possessed by your character, their SL, their cost, and their description |
| /master_list_spells | Displays all spells possessed by any character, their SL, their cost, and their description |
| /list_traits | Displays all advantages and disadvantages possessed by your character, their cost, and their description |
| /master_list_traits | Displays all advantages and disadvantages possessed by any character, their cost, and their description |

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

### Battle Commands

<p align="center">
  <img src="/assets/atk_slash_command.png" alt="/atk local parameter autocomplete" width="45%">
  <img src="/assets/atk.png" alt="/atk attack result" width="45%">
  <br>
  <em>`/atk` local parameter autocomplete | `/atk` attack result</em>
</p>

<p align="center">
  <img src="/assets/def.png" alt="/def defense and damage resolution" width="45%">
  <br>
  <em>`/def` defense and damage resolution</em>
</p>

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
  <img src="/assets/skills.png" alt="/list_skills paginated skill list" width="45%">
  <br>
  <em>`/sheet` character sheet hub | `/list_skills` paginated skill list</em>
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
