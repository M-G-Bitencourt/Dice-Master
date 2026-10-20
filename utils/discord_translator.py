"""Discord application command translator backed by the locale catalogs."""

from __future__ import annotations

from typing import Any

from discord import Locale, app_commands

from utils.i18n import load_catalogs


class DiceMasterTranslator(app_commands.Translator):
    """Translate command metadata from canonical English source strings."""

    async def translate(
        self,
        string: app_commands.locale_str,
        locale: Locale,
        context: app_commands.TranslationContext,
    ) -> str | None:
        catalog = load_catalogs().get(locale.value)
        if catalog is None or locale.value == "en-US":
            return None

        location = context.location
        data: Any = context.data

        if location == app_commands.TranslationContextLocation.command_name:
            command_name = getattr(data, "name", None)
            if command_name is None:
                return None
            return catalog.command_names.get(str(command_name))

        if location == app_commands.TranslationContextLocation.command_description:
            command_name = getattr(data, "name", None)
            if command_name is None:
                return None
            return catalog.command_descriptions.get(str(command_name))

        if location == app_commands.TranslationContextLocation.parameter_name:
            command = getattr(data, "command", None)
            parameter_name = getattr(data, "name", None)
            if command is None or parameter_name is None:
                return None
            parameter = catalog.parameter(
                str(command.name), str(parameter_name)
            )
            translated = parameter.get("name")
            return translated if isinstance(translated, str) else None

        if location == app_commands.TranslationContextLocation.parameter_description:
            command = getattr(data, "command", None)
            parameter_name = getattr(data, "name", None)
            if command is None or parameter_name is None:
                return None
            parameter = catalog.parameter(
                str(command.name), str(parameter_name)
            )
            translated = parameter.get("description")
            return translated if isinstance(translated, str) else None

        if location == app_commands.TranslationContextLocation.choice_name:
            return catalog.choices.get(string.message)

        return None
