"""Human-level labels: "this opponent plays like a human rated X", in terms you can use.

Three measurements, all from Maia-3 (trained on human Lichess blitz games, so its levels live on the
Lichess blitz scale):

1. A fit per game and side: the Maia level that best explains the moves, with a likelihood range.
2. Your personal scale: your own rating against the level your own moves resemble, pooled over your
   recent rated games. Research found no trustworthy published conversion at your level, so this
   measured offset translates any Maia level into your platform's numbers.
3. Pooled profiles of a repeat opponent (a bot you keep playing): totals add across games, so the
   range narrows as evidence grows.
"""

from __future__ import annotations

import asyncio
import json
import math
import sqlite3
from collections.abc import Awaitable, Callable
from typing import Any

from . import config, metrics
from .db import tx
from .maia import Maia, fit_from_totals

LEVELS = list(config.MAIA_LEVELS)


def _totals_for(maia: Maia, start_fen: str, ucis: list[str], plies: set[int], self_elo: int,
                opp_elo: int) -> tuple[list[float], int]:
    prof = maia.profile_game(start_fen, ucis, plies, self_elo, opp_elo)
    totals = [sum(math.log(max(p.probs[k], 1e-6)) for p in prof) for k in range(len(LEVELS))]
    return totals, len(prof)


def compute_game(conn: sqlite3.Connection, maia: Maia, game_id: int) -> dict[str, tuple[list[float], int]]:
    """Profile both sides of one game. Reads only; safe to run off the event loop."""
    g = conn.execute("SELECT my_color, my_rating, opp_rating FROM games WHERE id = ?", (game_id,)).fetchone()
    moves = conn.execute("SELECT ply, uci, color, fen_before FROM moves WHERE game_id = ? ORDER BY ply",
                         (game_id,)).fetchall()
    if g is None or not moves:
        return {}
    ucis = [m["uci"] for m in moves]
    mine = {m["ply"] for m in moves if m["color"] == g["my_color"]}
    theirs = {m["ply"] for m in moves} - mine
    me_elo = int(g["my_rating"] or config.DEFAULT_PLAYING_ELO)
    opp_elo = int(g["opp_rating"] or me_elo)
    start = moves[0]["fen_before"]
    return {"me": _totals_for(maia, start, ucis, mine, me_elo, opp_elo),
            "opp": _totals_for(maia, start, ucis, theirs, opp_elo, me_elo)}


def prune_stale(conn: sqlite3.Connection) -> int:
    """Drop fits computed over a different set of levels (config.MAIA_LEVELS changed); they're recomputed."""
    with tx(conn):
        cur = conn.execute("DELETE FROM maia_fits WHERE json_array_length(totals) != ?", (len(LEVELS),))
    return cur.rowcount


def store(conn: sqlite3.Connection, game_id: int, fits: dict[str, tuple[list[float], int]]) -> None:
    with tx(conn):
        for side, (totals, n) in fits.items():
            fit = fit_from_totals(totals, n)
            conn.execute(
                """INSERT INTO maia_fits (game_id, side, moves, totals, level) VALUES (?,?,?,?,?)
                   ON CONFLICT(game_id, side) DO UPDATE SET moves = excluded.moves, totals = excluded.totals,
                     level = excluded.level""",
                (game_id, side, n, json.dumps([round(t, 4) for t in totals]), fit["level"] if fit else None))


async def ensure_game(conn: sqlite3.Connection, maia: Maia, game_id: int) -> None:
    if conn.execute("SELECT COUNT(*) FROM maia_fits WHERE game_id = ?", (game_id,)).fetchone()[0] == 2:
        return
    fits = await asyncio.to_thread(compute_game, conn, maia, game_id)
    if fits:
        store(conn, game_id, fits)


async def sweep(conn: sqlite3.Connection, maia: Maia, locked: Callable[[], bool],
                emit: Callable[[dict[str, Any]], Awaitable[None]], limit: int = 500) -> int:
    """Fit every game that hasn't been fitted yet, newest first. Stops at the fair-play lock."""
    ids = [r[0] for r in conn.execute(
        """SELECT g.id FROM games g WHERE (SELECT COUNT(*) FROM maia_fits f WHERE f.game_id = g.id) < 2
           ORDER BY g.played_at DESC LIMIT ?""", (limit,))]
    for i, gid in enumerate(ids):
        if locked():
            break
        await ensure_game(conn, maia, gid)
        if i % 10 == 0:
            await emit({"stage": "maia", "done": i + 1, "total": len(ids)})
    return len(ids)


def _pooled(rows: list[sqlite3.Row]) -> tuple[list[float], int]:
    totals = [0.0] * len(LEVELS)
    n = 0
    for r in rows:
        for k, t in enumerate(json.loads(r["totals"])):
            totals[k] += t
        n += r["moves"]
    return totals, n


def personal_scale(conn: sqlite3.Connection) -> dict[str, Any] | None:
    """Your rating against the Maia level of your own moves, over your recent rated games."""
    pool = metrics.default_pool(conn)
    if pool is None:
        return None
    rows = conn.execute(
        """SELECT f.totals, f.moves, g.my_rating FROM maia_fits f JOIN games g ON g.id = f.game_id
           WHERE f.side = 'me' AND g.rated = 1 AND g.my_rating IS NOT NULL AND g.platform = ? AND g.time_class = ?
           ORDER BY g.played_at DESC LIMIT ?""",
        (pool["platform"], pool["time_class"], config.PERSONAL_SCALE_GAMES)).fetchall()
    if len(rows) < config.PERSONAL_SCALE_MIN_GAMES:
        return {**pool, "ready": False, "games": len(rows), "needed": config.PERSONAL_SCALE_MIN_GAMES}
    totals, n = _pooled(rows)
    fit = fit_from_totals(totals, n)
    if fit is None:
        return {**pool, "ready": False, "games": len(rows), "needed": config.PERSONAL_SCALE_MIN_GAMES}
    if fit["edge"]:  # your moves sit beyond Maia's range: no honest offset can be measured
        return {**pool, "ready": False, "games": len(rows), "needed": config.PERSONAL_SCALE_MIN_GAMES,
                "beyond": fit["edge"]}
    rating = sum(r["my_rating"] for r in rows) / len(rows)
    return {**pool, "ready": True, "games": len(rows), "rating": round(rating), "maia_level": fit["level"],
            "maia_lo": fit["lo"], "maia_hi": fit["hi"], "offset": round(rating - fit["level"])}


def describe(conn: sqlite3.Connection, level: int, lo: int | None = None, hi: int | None = None,
             scale: dict[str, Any] | None = None, edge: str | None = None) -> dict[str, Any]:
    """A Maia level in plain terms: the native scale, your platform's numbers, and relative to you.
    `edge` marks a fit at the end of Maia's range: shown as "or weaker"/"or stronger", never exact."""
    scale = scale if scale is not None else personal_scale(conn)
    out: dict[str, Any] = {"maia_level": level, "lo": lo, "hi": hi, "scale": config.MAIA_SCALE, "edge": edge}
    if scale and scale.get("ready"):
        off = scale["offset"]
        out["personal"] = {"platform": scale["platform"], "time_class": scale["time_class"],
                           "rating": level + off, "lo": None if lo is None else lo + off,
                           "hi": None if hi is None else hi + off, "games": scale["games"]}
        out["vs_you"] = level - scale["maia_level"]
    return out


def opponent(conn: sqlite3.Connection, name: str) -> dict[str, Any] | None:
    """Everything known about how human-like a repeat opponent (or bot) plays, pooled over games."""
    rows = conn.execute(
        """SELECT f.totals, f.moves, g.opp_rating FROM maia_fits f JOIN games g ON g.id = f.game_id
           WHERE f.side = 'opp' AND g.opp_name = ?""", (name,)).fetchall()
    if not rows:
        return None
    totals, n = _pooled(rows)
    fit = fit_from_totals(totals, n)
    blunders = conn.execute(
        """SELECT COUNT(DISTINCT g.id) AS games, SUM(m.class = 'blunder') AS b
           FROM games g JOIN moves m ON m.game_id = g.id
           WHERE g.opp_name = ? AND g.analysed_at IS NOT NULL AND m.color != g.my_color""", (name,)).fetchone()
    stated = [r["opp_rating"] for r in rows if r["opp_rating"]]
    return {
        "name": name, "games": len(rows), "moves": n,
        "fit": describe(conn, fit["level"], fit["lo"], fit["hi"], edge=fit["edge"]) if fit else None,
        "stated_rating": round(sum(stated) / len(stated)) if stated else None,
        "blunders_per_game": round(blunders["b"] / blunders["games"], 2) if blunders and blunders["games"] else None,
    }


def game_sides(conn: sqlite3.Connection, game_id: int) -> dict[str, Any]:
    """Per-game labels for both sides, ready for the UI."""
    scale = personal_scale(conn)
    out: dict[str, Any] = {}
    for r in conn.execute("SELECT side, totals, moves FROM maia_fits WHERE game_id = ?", (game_id,)):
        fit = fit_from_totals(json.loads(r["totals"]), r["moves"])
        if fit is None:
            out[r["side"]] = None
            continue
        out[r["side"]] = describe(conn, fit["level"], fit["lo"], fit["hi"], scale, fit["edge"]) | {"moves": r["moves"]}
    return out
