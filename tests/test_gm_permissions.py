"""Tests for per-guild GM shield command permissions."""

from __future__ import annotations

from types import SimpleNamespace

from discord import AppCommandType

from utils.gm_permissions import apply_gm_permissions


class FakeHTTP:
    def __init__(self):
        self.calls = []

    async def edit_application_command_permissions(self, *args):
        self.calls.append(args)


class FakeGuild:
    def __init__(self, guild_id: int, has_dm: bool):
        self.id = guild_id
        self._has_dm = has_dm

    def get_member(self, user_id: int):
        return object() if self._has_dm else None


def make_bot(*guilds):
    return SimpleNamespace(
        application_id=123,
        config={"BOT": {"DM_ID": "999"}},
        guilds=list(guilds),
        http=FakeHTTP(),
    )


def make_command():
    return SimpleNamespace(
        name="GM Shield",
        type=AppCommandType.user,
        id=456,
    )


class TestGMShieldPermissions:
    async def test_applies_the_dm_override_in_every_guild(self):
        bot = make_bot(
            FakeGuild(1, True),
            FakeGuild(2, False),
        )

        applied = await apply_gm_permissions(bot, [make_command()])

        assert applied is True
        assert len(bot.http.calls) == 2
        for index, call in enumerate(bot.http.calls, start=1):
            application_id, guild_id, command_id, payload = call
            assert (application_id, guild_id, command_id) == (
                123,
                index,
                456,
            )
            assert payload["permissions"] == [
                {
                    "id": str(index),
                    "type": 1,
                    "permission": False,
                },
                {"id": "999", "type": 2, "permission": True},
            ]

    async def test_returns_false_without_the_context_menu(self):
        bot = make_bot(FakeGuild(1, True))

        assert await apply_gm_permissions(bot, []) is False
        assert bot.http.calls == []
