![Python](https://img.shields.io/badge/Python-3.14+-blue?logo=python&logoColor=white)

![Dice Master Banner](/assets/github_banner.png)

# Dice-Master
Dice Master is a Discord bot designed to simplify GURPS sessions. It streamlines gameplay by automating dice rolls, damage calculations, and character sheet management directly in the chat.

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

## Other Tests Commands
| Command | Description |
| :--- | :--- |
| /roll | Roll a variable number of d6s and return their sum. |
| /react | Perform a reaction roll. |
| /panic | Execute a panic check and return the result. |