"""Game importers for Chess.com (Published-Data API) and Lichess (game export).

Both are incremental: Chess.com keeps an ETag per monthly archive, Lichess a `since` cursor.
Requests are strictly serial, as both platforms ask.
"""

from __future__ import annotations

import asyncio
import json
import re
import sqlite3
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from . import config, games
from .db import tx

Progress = Callable[[dict[str, Any]], Awaitable[None] | None]


class ImportError_(Exception):
    """A user-facing import failure (bad username, network down, token rejected)."""


def _client(token: str | None = None) -> httpx.AsyncClient:
    headers = {"User-Agent": config.USER_AGENT}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return httpx.AsyncClient(headers=headers, timeout=httpx.Timeout(30, read=120), follow_redirects=True)


async def _emit(progress: Progress | None, data: dict[str, Any]) -> None:
    if progress is not None:
        res = progress(data)
        if asyncio.iscoroutine(res):
            await res


def _cursor(conn: sqlite3.Connection, platform: str, username: str) -> str | None:
    row = conn.execute(
        "SELECT cursor FROM sync_state WHERE platform = ? AND username = ?", (platform, username.lower())
    ).fetchone()
    return row[0] if row else None


def _save_cursor(conn: sqlite3.Connection, platform: str, username: str, cursor: str) -> None:
    conn.execute(
        """INSERT INTO sync_state (platform, username, cursor, synced_at) VALUES (?,?,?,?)
           ON CONFLICT(platform, username) DO UPDATE SET cursor = excluded.cursor, synced_at = excluded.synced_at""",
        (platform, username.lower(), cursor, int(time.time())),
    )


# ── Chess.com ────────────────────────────────────────────────────────────────────────────────────

CHESSCOM_TERMINATION = {
    "checkmated": "checkmate", "resigned": "resign", "timeout": "timeout", "abandoned": "abandon",
    "agreed": "agreement", "repetition": "repetition", "stalemate": "stalemate",
    "insufficient": "insufficient", "50move": "fifty", "timevsinsufficient": "timeout_draw",
}
DRAW_CODES = {"agreed", "repetition", "stalemate", "insufficient", "50move", "timevsinsufficient"}


def _opening_from_eco_url(url: str | None) -> str | None:
    if not url:
        return None
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    words = []
    for part in slug.split("-"):
        if re.match(r"^\d+\.", part) or re.match(r"^\d+\.\.\.", part):
            break
        words.append(part)
    return " ".join(words) or None


def chesscom_meta(g: dict[str, Any], username: str) -> games.GameMeta | None:
    if g.get("rules") != "chess" or g.get("initial_setup", "").split(" ")[0] not in (
        "", "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR",
    ):
        return None
    me = username.lower()
    white, black = g["white"], g["black"]
    if white["username"].lower() == me:
        my_color, mine, theirs = "white", white, black
    elif black["username"].lower() == me:
        my_color, mine, theirs = "black", black, white
    else:
        return None
    if mine["result"] == "win":
        result, code = "win", theirs["result"]
    elif mine["result"] in DRAW_CODES:
        result, code = "draw", mine["result"]
    else:
        result, code = "loss", mine["result"]
    eco_header = re.search(r'\[ECO "([^"]+)"\]', g.get("pgn", ""))
    return games.GameMeta(
        platform="chesscom",
        platform_id=g.get("uuid") or g["url"].rsplit("/", 1)[-1],
        url=g.get("url"),
        played_at=int(g["end_time"]),
        time_class=g.get("time_class", "rapid"),
        time_control=g.get("time_control"),
        rated=bool(g.get("rated", True)),
        my_color=my_color,
        my_rating=mine.get("rating"),
        opp_rating=theirs.get("rating"),
        opp_name=theirs.get("username"),
        result=result,
        termination=CHESSCOM_TERMINATION.get(code, code),
        eco=eco_header.group(1) if eco_header else None,
        opening=_opening_from_eco_url(g.get("eco")),
        pgn=g.get("pgn", ""),
    )


async def import_chesscom(conn: sqlite3.Connection, username: str, progress: Progress | None = None) -> dict:
    username = username.strip()
    etags: dict[str, str] = json.loads(_cursor(conn, "chesscom", username) or "{}")
    stored = seen = 0
    async with _client() as http:
        r = await http.get(f"{config.CHESSCOM_API}/player/{username.lower()}/games/archives")
        if r.status_code == 404:
            raise ImportError_(f"Chess.com has no player called “{username}”.")
        r.raise_for_status()
        archives: list[str] = r.json().get("archives", [])
        for i, url in enumerate(archives):
            # Months before last month never change; the last two may still have been partial.
            if url in etags and i < len(archives) - 2:
                continue
            headers = {"If-None-Match": etags[url]} if url in etags else {}
            year, month = url.rsplit("/", 2)[-2:]
            await _emit(progress, {"platform": "chesscom", "step": f"{year}-{month}",
                                   "done": i, "total": len(archives), "stored": stored})
            resp = await http.get(url, headers=headers)
            if resp.status_code == 304:
                continue
            if resp.status_code == 429:
                await asyncio.sleep(config.RATE_LIMIT_WAIT_S)
                resp = await http.get(url, headers=headers)
            resp.raise_for_status()
            for g in resp.json().get("games", []):
                seen += 1
                meta = chesscom_meta(g, username)
                if meta and games.store(conn, meta):
                    stored += 1
            etags[url] = resp.headers.get("ETag", "*")
            with tx(conn):
                _save_cursor(conn, "chesscom", username, json.dumps(etags))
            await asyncio.sleep(0)
    await _emit(progress, {"platform": "chesscom", "step": "done", "done": len(archives),
                           "total": len(archives), "stored": stored})
    return {"platform": "chesscom", "seen": seen, "stored": stored}


# ── Lichess ──────────────────────────────────────────────────────────────────────────────────────

LICHESS_SPEED = {"ultraBullet": "bullet", "bullet": "bullet", "blitz": "blitz", "rapid": "rapid",
                 "classical": "classical", "correspondence": "daily"}
LICHESS_TERMINATION = {"mate": "checkmate", "resign": "resign", "outoftime": "timeout", "timeout": "abandon",
                       "stalemate": "stalemate", "draw": "agreement", "cheat": "other",
                       "variantEnd": "other", "unknownFinish": "other", "insufficientMaterialClaim": "insufficient"}


def lichess_meta(g: dict[str, Any], username: str) -> games.GameMeta | None:
    if g.get("variant") != "standard" or g.get("status") in ("aborted", "noStart", "created", "started"):
        return None
    me = username.lower()
    players = g.get("players", {})
    w, b = players.get("white", {}), players.get("black", {})

    def name(p: dict) -> str:
        return (p.get("user") or {}).get("name", "") or ""

    if name(w).lower() == me:
        my_color, mine, theirs = "white", w, b
    elif name(b).lower() == me:
        my_color, mine, theirs = "black", b, w
    else:
        return None
    winner = g.get("winner")
    result = "draw" if winner is None else ("win" if winner == my_color else "loss")
    clock = g.get("clock") or {}
    tc = f"{clock['initial']}+{clock['increment']}" if clock else None
    opening = g.get("opening") or {}
    return games.GameMeta(
        platform="lichess",
        platform_id=g["id"],
        url=f"https://lichess.org/{g['id']}",
        played_at=int((g.get("lastMoveAt") or g.get("createdAt")) / 1000),
        time_class=LICHESS_SPEED.get(g.get("speed", ""), "rapid"),
        time_control=tc,
        rated=bool(g.get("rated")),
        my_color=my_color,
        my_rating=mine.get("rating"),
        opp_rating=theirs.get("rating"),
        opp_name=name(theirs) or (f"AI level {theirs['aiLevel']}" if "aiLevel" in theirs else None),
        result=result,
        termination=LICHESS_TERMINATION.get(g.get("status", ""), g.get("status")),
        eco=opening.get("eco"),
        opening=opening.get("name"),
        pgn=g.get("pgn", ""),
    )


async def import_lichess(
    conn: sqlite3.Connection, username: str, token: str | None, progress: Progress | None = None
) -> dict:
    username = username.strip()
    since = int(_cursor(conn, "lichess", username) or 0)
    params = {
        "since": since + 1 if since else None, "sort": "dateAsc", "pgnInJson": "true", "clocks": "true",
        "evals": "true", "opening": "true", "accuracy": "true",
        "perfType": "ultraBullet,bullet,blitz,rapid,classical,correspondence",
    }
    params = {k: v for k, v in params.items() if v is not None}
    stored = seen = 0
    cursor = since
    async with _client(token) as http:
        for attempt in range(2):
            async with http.stream(
                "GET", f"{config.LICHESS_API}/api/games/user/{username}", params=params,
                headers={"Accept": "application/x-ndjson"},
            ) as resp:
                if resp.status_code == 429 and attempt == 0:
                    await _emit(progress, {"platform": "lichess", "step": "rate limited, waiting a minute",
                                           "stored": stored})
                    await asyncio.sleep(config.RATE_LIMIT_WAIT_S)
                    continue
                if resp.status_code == 404:
                    raise ImportError_(f"Lichess has no player called “{username}”.")
                if resp.status_code == 401:
                    raise ImportError_("Lichess rejected the token. Replace it in Settings.")
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    g = json.loads(line)
                    seen += 1
                    meta = lichess_meta(g, username)
                    if meta and games.store(conn, meta):
                        stored += 1
                    cursor = max(cursor, int(g.get("createdAt", 0)))
                    if seen % 25 == 0:
                        with tx(conn):
                            _save_cursor(conn, "lichess", username, str(cursor))
                        await _emit(progress, {"platform": "lichess", "step": "streaming", "done": seen,
                                               "total": None, "stored": stored})
            break
    with tx(conn):
        _save_cursor(conn, "lichess", username, str(cursor))
    await _emit(progress, {"platform": "lichess", "step": "done", "done": seen, "total": seen, "stored": stored})
    return {"platform": "lichess", "seen": seen, "stored": stored}
