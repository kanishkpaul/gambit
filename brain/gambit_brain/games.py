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


# ── Pasted PGN (over-the-board games, other sites) ─────────────────────────────────────────────


def _speed(base_s: int | None, inc_s: int | None) -> str:
    """Lichess's speed buckets from the estimated game length (base + 40 × increment)."""
    if base_s is None:
        return "classical"
    est = base_s + 40 * (inc_s or 0)
    return "bullet" if est < 180 else "blitz" if est < 480 else "rapid" if est < 1500 else "classical"


def meta_from_pgn(pgn: str, my_color: str) -> GameMeta:
    """Metadata for a pasted, finished game. Raises ValueError with a user-facing message."""
    import calendar
    import hashlib

    parsed = chesslib.parse_pgn(pgn)
    if parsed is None or not parsed.moves:
        raise ValueError("That PGN couldn't be read as a standard game.")
    h = parsed.headers
    result = h.get("Result", "*")
    if result not in ("1-0", "0-1", "1/2-1/2"):
        raise ValueError("Only finished games can be analysed. Add the result (1-0, 0-1 or 1/2-1/2).")
    if my_color not in ("white", "black"):
        raise ValueError("Say which colour you played.")
    mine, theirs = ("White", "Black") if my_color == "white" else ("Black", "White")
    won = (result == "1-0") == (my_color == "white")
    tc = h.get("TimeControl")
    base_s, inc_s = chesslib.parse_time_control(tc)
    played_at = int(time.time())
    for d in (h.get("UTCDate"), h.get("Date")):
        if d and "?" not in d:
            try:
                played_at = calendar.timegm(time.strptime(d, "%Y.%m.%d"))
                break
            except ValueError:
                pass

    def rating(key: str) -> int | None:
        v = h.get(f"{key}Elo", "")
        return int(v) if v.isdigit() else None

    digest = hashlib.sha1(" ".join(m.uci for m in parsed.moves).encode() + h.get("Date", "").encode()).hexdigest()
    return GameMeta(
        platform="pgn", platform_id=digest[:16], url=h.get("Site") if h.get("Site", "").startswith("http") else None,
        played_at=played_at, time_class=_speed(base_s, inc_s), time_control=tc if base_s is not None else None,
        rated=False, my_color=my_color, my_rating=rating(mine), opp_rating=rating(theirs),
        opp_name=h.get(theirs) if h.get(theirs, "?") != "?" else None,
        result="draw" if result == "1/2-1/2" else "win" if won else "loss",
        termination=None, eco=h.get("ECO"), opening=h.get("Opening"), pgn=pgn,
    )
