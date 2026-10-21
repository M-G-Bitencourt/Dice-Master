"""Tests for transient GM shield directives and health flags."""

from __future__ import annotations

from utils.gm_directives import GMDirectiveStore


def test_specific_directive_wins_over_generic_and_player_fallback():
    store = GMDirectiveStore()
    store.set(
        character_id=1,
        player_id=10,
        roll_kind="generic",
        outcome="success",
    )
    store.set(
        character_id=1,
        player_id=10,
        roll_kind="skill_test",
        outcome="failure",
    )

    directive = store.consume(
        character_id=1,
        player_id=10,
        roll_kind="skill_test",
    )

    assert directive is not None
    assert directive.outcome == "failure"
    fallback = store.consume(
        character_id=1,
        player_id=10,
        roll_kind="skill_test",
    )
    assert fallback is not None
    assert fallback.outcome == "success"
    assert store.consume(
        character_id=1,
        player_id=10,
        roll_kind="skill_test",
    ) is None


def test_character_directive_wins_over_player_directive():
    store = GMDirectiveStore()
    store.set(player_id=10, roll_kind="attack", outcome="failure")
    store.set(
        character_id=1, player_id=10, roll_kind="attack", outcome="success"
    )

    directive = store.consume(
        character_id=1,
        player_id=10,
        roll_kind="attack",
    )

    assert directive is not None
    assert directive.outcome == "success"


def test_generic_character_directive_is_used_as_fallback():
    store = GMDirectiveStore()
    store.set(character_id=1, roll_kind="generic", outcome="critical_success")

    directive = store.consume(
        character_id=1,
        player_id=10,
        roll_kind="quick_contest",
    )

    assert directive is not None
    assert directive.outcome == "critical_success"


def test_expired_directive_is_discarded():
    store = GMDirectiveStore(ttl_seconds=-1)
    store.set(character_id=1, roll_kind="attack", outcome="success")

    assert store.consume(
        character_id=1,
        player_id=None,
        roll_kind="attack",
    ) is None


def test_flags_toggle_and_clear_with_character():
    store = GMDirectiveStore()
    store.set_flag(1, "no_faint", True)
    store.set_flag(1, "no_death", True)

    assert store.get_flags(1) == {"no_faint": True, "no_death": True}

    store.set_flag(1, "no_faint", False)
    assert store.get_flags(1) == {"no_faint": False, "no_death": True}

    store.clear_character(1)
    assert store.get_flags(1) == {"no_faint": False, "no_death": False}


def test_active_for_includes_character_and_player_entries():
    store = GMDirectiveStore()
    store.set(character_id=1, roll_kind="attack", outcome="success")
    store.set(player_id=1, roll_kind="generic", outcome="failure")

    directives = store.active_for(character_id=1, player_id=1)

    assert {directive.roll_kind for directive in directives} == {
        "attack",
        "generic",
    }
