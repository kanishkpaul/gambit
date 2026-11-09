"""Guardrails that run on their own: live-game detection for the fair-play lock, and the stop-loss.

Lichess: the public `/api/users/status` endpoint says whether you're playing right now, so the lock
turns itself on during a Lichess game and off again afterwards. Chess.com has no such endpoint; use
the manual switch there.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

import httpx

from . import config
from .db import get_setting, set_setting, tx

log = logging.getLogger("gambit.guardrails")


def _day_start(now: float | None = None) -> int:
    d = datetime.fromtimestamp(now or time.time())
    return int(d.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())


def stop_loss(conn: sqlite3.Connection, now: float | None = None) -> dict[str, Any]:
    """Straight losses today (serious and casual alike), and whether you flagged a loss that made you angry."""
    now = now or time.time()
    start = _day_start(now)
    today = [r["result"] for r in conn.execute(
        "SELECT result FROM games WHERE played_at >= ? AND platform NOT IN ('pgn', 'sparring') ORDER BY played_at DESC",
        (start,))]
    streak = 0
    for r in today:
        if r != "loss":
            break
        streak += 1
    tilt_until = get_setting(conn, "tilt_until", 0) or 0
    tilted = tilt_until > now
    if tilted or streak >= config.STOP_LOSS_STOP:
        level = "stop"
    elif streak >= config.STOP_LOSS_CAUTION:
        level = "caution"
    else:
        level = "clear"
    return {"level": level, "streak": streak, "games_today": len(today), "tilted": tilted,
            "caution_at": config.STOP_LOSS_CAUTION, "stop_at": config.STOP_LOSS_STOP}


def set_tilt(conn: sqlite3.Connection, on: bool) -> None:
    """'That loss made me angry': stop playing for the rest of the day."""
    with tx(conn):
        set_setting(conn, "tilt_until", _day_start() + 86_400 if on else 0)


class LichessWatcher:
    """Polls Lichess and drives the fair-play lock. `apply(locked, reason)` does the locking."""

    def __init__(self, conn: sqlite3.Connection, apply: Callable[[bool, str], Awaitable[None]],
                 on_game_end: Callable[[], Awaitable[None]] | None = None):
        self.conn, self.apply, self.on_game_end = conn, apply, on_game_end
        self.task: asyncio.Task | None = None
        self.last: dict[str, Any] = {"checked_at": None, "playing": None}

    def start(self) -> None:
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._loop())

    async def check_once(self, http: httpx.AsyncClient) -> None:
        user = (get_setting(self.conn, "lichess_username", "") or "").strip()
        if not user:
            return
        r = await http.get(f"{config.LICHESS_API}/api/users/status", params={"ids": user})
        r.raise_for_status()
        rows = r.json()
        playing = bool(rows and rows[0].get("playing"))
        was = self.last.get("playing")
        self.last = {"checked_at": int(time.time()), "playing": playing}
        if was and not playing and self.on_game_end is not None:
            await self.on_game_end()  # fetch the finished game straight away (stop-loss, post-mortem)
        reason = get_setting(self.conn, "fairplay_reason", None)
        locked = bool(get_setting(self.conn, "fairplay_lock", False))
        if playing and not locked:
            await self.apply(True, "lichess")
        elif not playing and locked and reason == "lichess":
            await self.apply(False, "lichess")

    async def _loop(self) -> None:
        async with httpx.AsyncClient(headers={"User-Agent": config.USER_AGENT}, timeout=10) as http:
            while True:
                try:
                    await self.check_once(http)
                except Exception as e:  # offline or rate-limited: try again next round
                    log.info("lichess status check failed: %s", e)
                await asyncio.sleep(config.LICHESS_STATUS_POLL_S)
