"""Transient GM shield directives used by the GM control panel."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import RLock
from typing import Any

DEFAULT_TTL_SECONDS = 60 * 60
HEALTH_FLAGS = ("no_faint", "no_death")


@dataclass
class GMDirective:
    """One pending lucky result for a character or player."""

    scope: str
    scope_id: int
    roll_kind: str
    outcome: str
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.monotonic)
    expires_at: float = field(
        default_factory=lambda: time.monotonic() + DEFAULT_TTL_SECONDS
    )


class GMDirectiveStore:
    """In-memory directive and health-flag storage with no audit trail."""

    def __init__(self, ttl_seconds: int = DEFAULT_TTL_SECONDS):
        self.ttl_seconds = ttl_seconds
        self._directives: dict[tuple[str, int, str], GMDirective] = {}
        self._flags: dict[tuple[int, str], bool] = {}
        self._lock = RLock()

    def _now(self) -> float:
        return time.monotonic()

    def _prune(self) -> None:
        now = self._now()
        expired = [
            key
            for key, directive in self._directives.items()
            if directive.expires_at <= now
        ]
        for key in expired:
            self._directives.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._directives.clear()
            self._flags.clear()

    def clear_character(self, character_id: int) -> None:
        with self._lock:
            for key in list(self._directives):
                if key[0] == "character" and key[1] == int(character_id):
                    self._directives.pop(key, None)
            for key in list(self._flags):
                if key[0] == int(character_id):
                    self._flags.pop(key, None)

    def set(
        self,
        *,
        character_id: int | None = None,
        player_id: int | None = None,
        roll_kind: str,
        outcome: str,
        payload: dict[str, Any] | None = None,
    ) -> GMDirective:
        if character_id is not None:
            scope, scope_id = "character", int(character_id)
        elif player_id is not None:
            scope, scope_id = "player", int(player_id)
        else:
            raise ValueError("A character_id or player_id is required.")

        now = self._now()
        directive = GMDirective(
            scope=scope,
            scope_id=scope_id,
            roll_kind=str(roll_kind),
            outcome=str(outcome),
            payload=dict(payload or {}),
            created_at=now,
            expires_at=now + self.ttl_seconds,
        )
        with self._lock:
            self._prune()
            self._directives[(scope, scope_id, directive.roll_kind)] = directive
        return directive

    def peek(
        self,
        *,
        character_id: int | None,
        player_id: int | None,
        roll_kind: str,
    ) -> GMDirective | None:
        with self._lock:
            self._prune()
            return self._lookup(
                character_id=character_id,
                player_id=player_id,
                roll_kind=roll_kind,
            )

    def consume(
        self,
        *,
        character_id: int | None,
        player_id: int | None,
        roll_kind: str,
    ) -> GMDirective | None:
        with self._lock:
            self._prune()
            directive = self._lookup(
                character_id=character_id,
                player_id=player_id,
                roll_kind=roll_kind,
            )
            if directive is not None:
                self._directives.pop(
                    (directive.scope, directive.scope_id, directive.roll_kind),
                    None,
                )
            return directive

    def _lookup(
        self,
        *,
        character_id: int | None,
        player_id: int | None,
        roll_kind: str,
    ) -> GMDirective | None:
        candidates: list[tuple[str, int, str]] = []
        if character_id is not None:
            candidates.append(("character", int(character_id), str(roll_kind)))
            candidates.append(("character", int(character_id), "generic"))
        if player_id is not None:
            candidates.append(("player", int(player_id), str(roll_kind)))
            candidates.append(("player", int(player_id), "generic"))

        for key in candidates:
            directive = self._directives.get(key)
            if directive is not None:
                return directive
        return None

    def set_flag(self, character_id: int, flag: str, enabled: bool = True) -> None:
        if flag not in HEALTH_FLAGS:
            raise ValueError(f"Unknown GM shield flag: {flag}")
        with self._lock:
            key = (int(character_id), flag)
            if enabled:
                self._flags[key] = True
            else:
                self._flags.pop(key, None)

    def get_flag(self, character_id: int, flag: str) -> bool:
        with self._lock:
            return bool(self._flags.get((int(character_id), flag), False))

    def get_flags(self, character_id: int) -> dict[str, bool]:
        with self._lock:
            return {
                flag: bool(self._flags.get((int(character_id), flag), False))
                for flag in HEALTH_FLAGS
            }

    def active_for(
        self,
        *,
        character_id: int | None,
        player_id: int | None,
    ) -> list[GMDirective]:
        with self._lock:
            self._prune()
            directives: list[GMDirective] = []
            for directive in self._directives.values():
                if (
                    character_id is not None
                    and directive.scope == "character"
                    and directive.scope_id == int(character_id)
                ):
                    directives.append(directive)
                if (
                    player_id is not None
                    and directive.scope == "player"
                    and directive.scope_id == int(player_id)
                ):
                    directives.append(directive)
            return sorted(
                directives,
                key=lambda item: (item.scope, item.roll_kind),
            )

    def remove(
        self,
        *,
        character_id: int | None = None,
        player_id: int | None = None,
        roll_kind: str | None = None,
    ) -> None:
        with self._lock:
            for key in list(self._directives):
                scope, scope_id, kind = key
                if character_id is not None and scope == "character":
                    if scope_id != int(character_id):
                        continue
                elif player_id is not None and scope == "player":
                    if scope_id != int(player_id):
                        continue
                else:
                    continue
                if roll_kind is not None and kind != roll_kind:
                    continue
                self._directives.pop(key, None)


gm_shield_store = GMDirectiveStore()


def consume_health_directive(
    character_id: int | None,
    player_id: int | None,
    check_type: str,
) -> str | None:
    """Consume a pending consciousness or death check outcome."""
    directive = gm_shield_store.consume(
        character_id=character_id,
        player_id=player_id,
        roll_kind=f"health_{check_type}",
    )
    return directive.outcome if directive is not None else None
