"""Locale catalog loading, lookup and per-task locale context."""

from __future__ import annotations

import os
import tomllib
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

LOCALES_DIRECTORY = Path(__file__).resolve().parent.parent / "locales"
DEFAULT_LOCALE = "en-US"
DEFAULT_LOCALE_ENV = "DICE_MASTER_DEFAULT_LOCALE"

_current_locale: ContextVar[str | None] = ContextVar(
    "dice_master_current_locale", default=None
)
_default_locale = os.environ.get(DEFAULT_LOCALE_ENV, DEFAULT_LOCALE)
_catalogs: dict[str, "LocaleCatalog"] | None = None


@dataclass
class LocaleCatalog:
    """One auto-discovered locale file and its lookup indexes."""

    code: str
    name: str
    native_name: str
    discord_locale: str | None
    aliases: tuple[str, ...] = ()
    messages: dict[str, str] = field(default_factory=dict)
    commands: dict[str, dict[str, Any]] = field(default_factory=dict)
    catalog: dict[str, dict[str, str]] = field(default_factory=dict)

    command_names: dict[str, str] = field(default_factory=dict)
    command_descriptions: dict[str, str] = field(default_factory=dict)
    choices: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for command_name, metadata in self.commands.items():
            if not isinstance(metadata, dict):
                continue

            localized_name = metadata.get("name")
            if isinstance(localized_name, str):
                self.command_names[command_name] = localized_name

            localized_description = metadata.get("description")
            if isinstance(localized_description, str):
                self.command_descriptions[command_name] = localized_description

    def description_for(self, command_name: str) -> str | None:
        """Return the localized description registered for one command."""
        metadata = self.commands.get(command_name)
        if isinstance(metadata, dict):
            description = metadata.get("description")
            if isinstance(description, str):
                return description
        return None

    def parameter(self, command_name: str, parameter_name: str) -> dict[str, Any]:
        """Return the translation block for one canonical parameter."""
        metadata = self.commands.get(command_name)
        if not isinstance(metadata, dict):
            return {}
        parameters = metadata.get("parameters")
        if not isinstance(parameters, dict):
            return {}
        parameter = parameters.get(parameter_name)
        return parameter if isinstance(parameter, dict) else {}


def _normalize_key(value: str) -> str:
    return value.strip().lower().replace("_", "-")


def _load_catalog(path: Path) -> LocaleCatalog | None:
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return None

    meta = data.get("meta", {})
    if not isinstance(meta, dict):
        return None

    code = str(meta.get("code") or path.stem).strip()
    if not code:
        return None

    aliases = meta.get("aliases", [])
    if not isinstance(aliases, list):
        aliases = []

    messages = data.get("messages", {})
    if not isinstance(messages, dict):
        messages = {}

    commands = data.get("commands", {})
    if not isinstance(commands, dict):
        commands = {}

    catalog = data.get("catalog", {})
    if not isinstance(catalog, dict):
        catalog = {}

    choices = data.get("choices", {})
    if not isinstance(choices, dict):
        choices = {}

    normalized_messages = {
        str(key): str(value)
        for key, value in messages.items()
        if isinstance(value, str)
    }

    normalized_catalog: dict[str, dict[str, str]] = {}
    for kind, values in catalog.items():
        if not isinstance(values, dict):
            continue
        normalized_catalog[str(kind)] = {
            str(key): str(value)
            for key, value in values.items()
            if isinstance(value, str)
        }

    return LocaleCatalog(
        code=code,
        name=str(meta.get("name") or code),
        native_name=str(meta.get("native_name") or meta.get("name") or code),
        discord_locale=(
            str(meta["discord_locale"]) if meta.get("discord_locale") else None
        ),
        aliases=tuple(str(alias) for alias in aliases),
        messages=normalized_messages,
        commands=commands,
        catalog=normalized_catalog,
        choices={
            str(key): str(value)
            for key, value in choices.items()
            if isinstance(value, str)
        },
    )


def load_catalogs(force: bool = False) -> dict[str, LocaleCatalog]:
    """Load every locale file from the project locales directory once."""
    global _catalogs

    if _catalogs is not None and not force:
        return _catalogs

    catalogs: dict[str, LocaleCatalog] = {}
    if LOCALES_DIRECTORY.is_dir():
        for path in sorted(LOCALES_DIRECTORY.glob("*.toml")):
            catalog = _load_catalog(path)
            if catalog is not None:
                catalogs[catalog.code] = catalog

    _catalogs = catalogs
    return catalogs


def available_locales() -> list[LocaleCatalog]:
    """Return every discovered locale sorted by display name."""
    return sorted(
        load_catalogs().values(),
        key=lambda catalog: (catalog.name.casefold(), catalog.code),
    )


def normalize_locale(code: str | None) -> str | None:
    """Resolve aliases and case differences to one catalog code."""
    if not code:
        return None

    catalogs = load_catalogs()
    normalized = _normalize_key(str(code))

    for catalog in catalogs.values():
        if _normalize_key(catalog.code) == normalized:
            return catalog.code
        if any(_normalize_key(alias) == normalized for alias in catalog.aliases):
            return catalog.code

    return None


def configure_default_locale(code: str | None) -> str:
    """Set the process default locale, falling back to English."""
    global _default_locale

    candidate = code or os.environ.get(DEFAULT_LOCALE_ENV) or DEFAULT_LOCALE
    normalized = normalize_locale(candidate) or DEFAULT_LOCALE
    _default_locale = normalized
    return _default_locale


def default_locale() -> str:
    """Return the configured fallback locale."""
    normalized = normalize_locale(_default_locale)
    if normalized is not None:
        return normalized
    return DEFAULT_LOCALE


def set_locale(code: str | None) -> str:
    """Set the locale for the current asyncio task context."""
    normalized = normalize_locale(code) or default_locale()
    _current_locale.set(normalized)
    return normalized


def get_locale() -> str:
    """Return the locale for the current asyncio task context."""
    return _current_locale.get() or default_locale()


@contextmanager
def locale_context(code: str | None) -> Iterator[str]:
    """Temporarily apply one locale to the current task context."""
    token = _current_locale.set(normalize_locale(code) or default_locale())
    try:
        yield _current_locale.get() or default_locale()
    finally:
        _current_locale.reset(token)


def get_catalog(code: str | None = None) -> LocaleCatalog:
    """Return a catalog by code, falling back to the default locale."""
    normalized = normalize_locale(code) or default_locale()
    catalogs = load_catalogs()
    return catalogs.get(normalized) or catalogs.get(DEFAULT_LOCALE) or LocaleCatalog(
        code=DEFAULT_LOCALE,
        name="English (US)",
        native_name="English (US)",
        discord_locale="en-US",
    )


def t(text: str, locale: str | None = None, **params: Any) -> str:
    """Translate one English source string into the active locale."""
    catalog = get_catalog(locale or get_locale())
    translated = catalog.messages.get(text, text)

    if params:
        try:
            translated = translated.format(**params)
        except (KeyError, IndexError, ValueError):
            return translated

    return translated


def parameter_name(
    command_name: str, parameter_name: str, locale: str | None = None
) -> str | None:
    """Return a localized public parameter name."""
    catalog = get_catalog(locale or get_locale())
    value = catalog.parameter(command_name, parameter_name).get("name")
    return value if isinstance(value, str) else None


def parameter_description(
    command_name: str, parameter_name: str, locale: str | None = None
) -> str | None:
    """Return a localized parameter description."""
    catalog = get_catalog(locale or get_locale())
    value = catalog.parameter(command_name, parameter_name).get("description")
    return value if isinstance(value, str) else None


def choice_name(source: str, locale: str | None = None) -> str | None:
    """Return a localized choice label by its English source label."""
    catalog = get_catalog(locale or get_locale())
    return catalog.choices.get(source)


def catalog_label(kind: str, key: str, locale: str | None = None) -> str:
    """Return one system catalog label such as a hit location or damage type."""
    catalog = get_catalog(locale or get_locale())
    values = catalog.catalog.get(kind, {})
    if key in values:
        return values[key]

    default_catalog = get_catalog(DEFAULT_LOCALE)
    return default_catalog.catalog.get(kind, {}).get(key, key)


def catalog_label_from_value(
    kind: str, value: str, locale: str | None = None
) -> str:
    """Resolve a localized or source catalog value by case-insensitive text."""
    text = str(value or "").strip()
    if not text:
        return text

    normalized = text.casefold()
    target = get_catalog(locale or get_locale())
    catalogs = [target, get_catalog(default_locale())]
    catalogs.extend(load_catalogs().values())

    for catalog in catalogs:
        for key, candidate in catalog.catalog.get(kind, {}).items():
            if candidate.casefold() == normalized:
                return catalog_label(kind, key, locale)
    return text


def catalog_key(kind: str, value: str, locale: str | None = None) -> str | None:
    """Resolve a localized or source catalog value back to its stable key."""
    catalog = get_catalog(locale or get_locale())
    for key, candidate in catalog.catalog.get(kind, {}).items():
        if candidate == value:
            return key

    default_catalog = get_catalog(default_locale())
    for key, candidate in default_catalog.catalog.get(kind, {}).items():
        if candidate == value:
            return key

    return None


def command_metadata(
    command_name: str, locale: str | None = None
) -> dict[str, Any] | None:
    """Return the localized command metadata block for one canonical name."""
    catalog = get_catalog(locale or get_locale())
    metadata = catalog.commands.get(command_name)
    return metadata if isinstance(metadata, dict) else None


def command_display_name(command_name: str, locale: str | None = None) -> str:
    """Return a localized command name with canonical fallback."""
    metadata = command_metadata(command_name, locale)
    if metadata and isinstance(metadata.get("name"), str):
        return metadata["name"]
    return command_name


def command_display_description(
    command_name: str, fallback: str, locale: str | None = None
) -> str:
    """Return a localized command description with canonical fallback."""
    metadata = command_metadata(command_name, locale)
    if metadata and isinstance(metadata.get("description"), str):
        return metadata["description"]
    return fallback


tr = t
