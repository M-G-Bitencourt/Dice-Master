# Locale catalogs

The bot loads every `*.toml` file in this directory at startup. No code change is required to register a new language.

## Files

- `en-US.toml` is the canonical English source.
- `pt-BR.toml` is the complete Brazilian Portuguese locale.
- Additional files are discovered automatically and appear in `/language`.

## Minimal structure

```toml
[meta]
code = "fr-FR"
name = "French (France)"
native_name = "Français (France)"
discord_locale = "fr"
aliases = ["fr", "fr-fr", "french"]

[commands.sheet]
name = "fiche"
description = "Envoie votre fiche de personnage..."

[commands.sheet.parameters.character]
name = "personnage"
description = "..."

[choices]
"Success" = "Succès"
"Torso (+0)" = "Torse (+0)"

[messages]
"Language set to {language}." = "Langue définie sur {language}."

[catalog.hit_locations]
torso = "Torse"
```

## Command metadata

Slash command names and descriptions use English source strings in code. The Discord translator looks up translations by canonical command name and internal parameter name.

- `[commands.<canonical_name>]`: command `name` and `description`.
- `[commands.<canonical_name>.parameters.<python_parameter_name>]`: public `name` and `description`.
- `[choices]`: English choice label to localized label. Dynamic hit-location labels include the penalty suffix, for example `"Torso (+0)"`.

Every command, parameter, and choice should have a translation. The test suite verifies this.

## Runtime messages

`[messages]` uses the English source string as the key. Placeholders use `{name}` syntax.

```toml
[messages]
"Error: initiative must be between 0 and 99." = "Erro: a iniciativa deve estar entre 0 e 99."
"Language set to {language}." = "Idioma definido para {language}."
```

Missing keys fall back to the English source text. Prefer translating the exact source string used in code.

## System labels

`[catalog.<kind>]` contains stable keys for labels shared by the UI and database values:

- `resources`, `attributes`
- `hit_locations`, `body_parts`
- `damage_types`, `damage_bases`, `maneuvers`
- `effect_types`, `health_labels`, `health_effects`, `health_status`
- `encumbrance`, `equipment_badges`, `parry`
- `difficulties`, `trait_categories`, `schools`, `mode_names`, `weapon_names`
- `fate`, `condition_names`, `condition_fields`, `help_categories`

Database content such as character names, custom items, and homebrew skills is never translated.

## Rules

- Do not use emojis. Use ASCII badges such as `[EQUIPPED]` and `[ADMIN]`.
- Keep placeholders exactly as they appear in the English source.
- Keep command names lowercase, using only letters, digits, and underscores, with at most 32 characters.
- Keep command and parameter descriptions at or below 100 characters.
- If a locale is not supported by Discord, the command menu remains in English, but bot responses still use the new locale.

## Applying a new locale

1. Copy `en-US.toml` to `<code>.toml` and translate it.
2. Restart the bot.
3. Run `/sync` as the bot owner so Discord receives the new command localizations.
4. Run `/language` in a server and select the new locale.
