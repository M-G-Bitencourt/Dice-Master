"""Tests for locale loading, fallback and catalog value mapping."""

from __future__ import annotations

import re

from utils.i18n import (
    available_locales,
    catalog_label,
    catalog_label_from_value,
    configure_default_locale,
    default_locale,
    locale_context,
    normalize_locale,
    t,
)

EMOJI_PATTERN = re.compile(
    "[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F]"
)


def test_discovers_english_and_brazilian_portuguese():
    codes = {catalog.code for catalog in available_locales()}

    assert {"en-US", "pt-BR"} <= codes


def test_normalizes_aliases_and_case():
    assert normalize_locale("pt") == "pt-BR"
    assert normalize_locale("PT_br") == "pt-BR"
    assert normalize_locale("en") == "en-US"
    assert normalize_locale("unknown") is None


def test_default_locale_can_be_configured():
    original = default_locale()
    try:
        assert configure_default_locale("pt-BR") == "pt-BR"
        assert default_locale() == "pt-BR"
        assert configure_default_locale("unknown") == "en-US"
    finally:
        configure_default_locale(original)


def test_messages_fall_back_to_english_source_text():
    with locale_context("en-US"):
        assert t("Language set to {language}.", language="English") == (
            "Language set to English."
        )

    with locale_context("pt-BR"):
        assert t("Language set to {language}.", language="Português") == (
            "Idioma definido para Português."
        )


def test_catalog_values_translate_in_both_directions():
    with locale_context("en-US"):
        assert catalog_label("hit_locations", "torso") == "Torso"
        assert catalog_label_from_value("hit_locations", "Tronco") == "Torso"
        assert catalog_label_from_value("damage_types", "corte") == "Cutting"

    with locale_context("pt-BR"):
        assert catalog_label("hit_locations", "torso") == "Tronco"
        assert catalog_label_from_value("hit_locations", "Torso") == "Tronco"
        assert catalog_label_from_value("damage_types", "cutting") == "Corte"


def test_locale_catalogs_do_not_contain_emojis():
    for catalog in available_locales():
        values = list(catalog.messages.values())
        values.extend(catalog.choices.values())
        for kind_values in catalog.catalog.values():
            values.extend(kind_values.values())

        for value in values:
            assert EMOJI_PATTERN.search(value) is None
