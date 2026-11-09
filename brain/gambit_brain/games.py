"""Turning platform game records into rows: games, moves and any evaluations the platform shipped."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass

from . import chesslib
from .db import tx


@dataclass
class GameMeta:
    platform: str
    platform_id: str
    url: str | None
    played_at: int
    time_class: str
    time_control: str | None
    rated: bool
    my_color: str
    my_rating: int | None
    opp_rating: int | None
    opp_name: str | None
    result: str  # win | loss | draw
    termination: str | None
    eco: str | None
    opening: str | None
    pgn: str


def exists(conn: sqlite3.Connection, platform: str, platform_id: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM games WHERE platform = ? AND platform_id = ?", (platform, platform_id)
        ).fetchone()
        is not None
    )


def store(conn: sqlite3.Connection, meta: GameMeta) -> int | None:
    """Insert one game with its moves. Returns the new id, or None if skipped (duplicate/unsupported)."""
    if exists(conn, meta.platform, meta.platform_id):
        return None
    base_s, inc_s = chesslib.parse_time_control(meta.time_control)
    parsed = chesslib.parse_pgn(meta.pgn, base_s, inc_s)
    if parsed is None or not parsed.moves:
        return None
    now = int(time.time())
    with tx(conn):
        cur = conn.execute(
            """INSERT INTO games (platform, platform_id, url, played_at, time_class, time_control, base_s, inc_s,
                 rated, my_color, my_rating, opp_rating, opp_name, result, termination, eco, opening, ply_count, pgn)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                meta.platform, meta.platform_id, meta.url, meta.played_at, meta.time_class, meta.time_control,
                base_s, inc_s, int(meta.rated), meta.my_color, meta.my_rating, meta.opp_rating, meta.opp_name,
                meta.result, meta.termination, meta.eco, meta.opening, len(parsed.moves), meta.pgn,
            ),
        )
        gid = cur.lastrowid
        conn.executemany(
            """INSERT INTO moves (game_id, ply, color, san, uci, fen_before, epd_before, epd_after, phase,
                 clock_ms, spent_ms, time_trouble) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            [
                (gid, m.ply, m.color, m.san, m.uci, m.fen_before, m.epd_before, m.epd_after, m.phase,
                 m.clock_ms, m.spent_ms, int(m.time_trouble))
                for m in parsed.moves
            ],
        )
        rows = [(k, e.cp, e.mate, "lichess") for k, e in parsed.embedded.items()]
        if parsed.final_terminal is not None:
            rows.append((parsed.final_epd, parsed.final_terminal.cp, parsed.final_terminal.mate, "terminal"))
        conn.executemany(
            """INSERT INTO evals (epd, cp, mate, source, updated_at) VALUES (?,?,?,?,?)
               ON CONFLICT(epd) DO NOTHING""",
            [(*r, now) for r in rows],
        )
    return gid
