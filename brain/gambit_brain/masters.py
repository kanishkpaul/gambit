"""Master games: guess-the-move through classical games in the structures your repertoire leads to.

Games come from Lichess broadcasts (live relays of over-the-board events; public, no account
needed), kept when both players are rated 2300+ and the game is finished. A game is picked from the
ones that pass through a position in your repertoire when there are any. You guess one side's moves
after the opening; a guess the engine rates as good as the master's counts too.
"""

from __future__ import annotations

import io
import random
import sqlite3
import time
from collections.abc import Awaitable, Callable
from typing import Any

import chess
import chess.pgn
import httpx

from . import config
from .chesslib import Eval, epd
from .db import tx

Analyse = Callable[[str, int], Awaitable[tuple[Eval, list[str], int]]]
Emit = Callable[[dict[str, Any]], Awaitable[None]]


def store_pgn_blob(conn: sqlite3.Connection, text: str) -> int:
    """Split a multi-game PGN and keep the finished master games. Returns games added."""
    added = 0
    stream = io.StringIO(text)
    while (game := chess.pgn.read_game(stream)) is not None:
        h = game.headers
        if h.get("Result") not in ("1-0", "0-1", "1/2-1/2") or h.get("Variant", "Standard") != "Standard":
            continue
        try:
            we, be = int(h.get("WhiteElo", "0") or 0), int(h.get("BlackElo", "0") or 0)
        except ValueError:
            continue
        if min(we, be) < config.MASTER_MIN_ELO or game.errors:
            continue
        moves = list(game.mainline_moves())
        if len(moves) < 40:
            continue
        source = h.get("Site") or f"{h.get('White')}-{h.get('Black')}-{h.get('Date')}-{h.get('Round')}"
        exporter = chess.pgn.StringExporter(headers=True, variations=False, comments=False)
        with tx(conn):
            cur = conn.execute(
                """INSERT OR IGNORE INTO master_games (source_id, event, white, black, white_elo, black_elo, date, result,
                     eco, opening, pgn, ply_count) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (source, h.get("BroadcastName") or h.get("Event"), h.get("White"), h.get("Black"), we, be, h.get("Date"),
                 h["Result"], h.get("ECO"), h.get("Opening"), game.accept(exporter), len(moves)))
            if cur.rowcount:
                gid = cur.lastrowid
                b = game.board()
                for ply, m in enumerate(moves[: config.OPENING_PLIES], start=1):
                    b.push(m)
                    conn.execute("INSERT OR IGNORE INTO master_positions (epd, game_id, ply) VALUES (?,?,?)", (epd(b), gid, ply))
                added += 1
    return added


async def import_broadcasts(conn: sqlite3.Connection, emit: Emit, pages: int = config.MASTER_BROADCAST_PAGES) -> dict[str, Any]:
    added = 0
    async with httpx.AsyncClient(headers={"User-Agent": config.USER_AGENT}, timeout=httpx.Timeout(20, read=120)) as http:
        tours = []
        for page in range(1, pages + 1):
            r = await http.get(f"{config.LICHESS_API}/api/broadcast/top", params={"page": page})
            r.raise_for_status()
            j = r.json()
            for t in j.get("active", []) + (j.get("past", {}) or {}).get("currentPageResults", []):
                tours.append((t.get("tour") or t)["id"])
        for i, tid in enumerate(dict.fromkeys(tours)):
            r = await http.get(f"{config.LICHESS_API}/api/broadcast/{tid}.pgn")
            if r.status_code == 429:
                break
            if r.status_code != 200:
                continue
            added += store_pgn_blob(conn, r.text)
            await emit({"stage": "import", "done": i + 1, "total": len(tours), "added": added})
    return {"added": added, "total": conn.execute("SELECT COUNT(*) FROM master_games").fetchone()[0]}


class Guessing:
    def __init__(self, conn: sqlite3.Connection, analyse: Analyse, locked: Callable[[], bool], rng: random.Random | None = None):
        self.conn, self.analyse, self.locked = conn, analyse, locked
        self.rng = rng or random.Random()
        self.current: dict[str, Any] | None = None

    def overview(self) -> dict[str, Any]:
        total = self.conn.execute("SELECT COUNT(*) FROM master_games").fetchone()[0]
        matching = self.conn.execute(
            """SELECT COUNT(DISTINCT mp.game_id) FROM master_positions mp JOIN repertoire r ON r.epd = mp.epd
               WHERE mp.ply >= ?""", (config.MASTER_MATCH_MIN_PLY,)).fetchone()[0]
        history = [dict(r) for r in self.conn.execute(
            """SELECT s.started_at, s.guesses, s.matched, s.as_good, g.white, g.black, g.event FROM guess_sessions s
               JOIN master_games g ON g.id = s.game_id WHERE s.finished_at IS NOT NULL ORDER BY s.started_at DESC LIMIT 10""")]
        return {"games": total, "matching": matching, "history": history, "moves_per_game": config.MASTER_GUESS_MOVES,
                "current": self._view() if self.current else None}

    def start(self) -> dict[str, Any]:
        if self.locked():
            raise ValueError("The fair-play lock is on. Finish your live game first.")
        # Prefer games passing through your repertoire, with the side you play in that structure.
        row = self.conn.execute(
            """SELECT mp.game_id, r.color FROM master_positions mp JOIN repertoire r ON r.epd = mp.epd
               WHERE mp.ply >= ? AND NOT EXISTS (SELECT 1 FROM guess_sessions s WHERE s.game_id = mp.game_id)
               ORDER BY mp.ply DESC, random() LIMIT 1""", (config.MASTER_MATCH_MIN_PLY,)).fetchone()
        if row:
            gid, side, why = row["game_id"], row["color"], "repertoire"
        else:
            r2 = self.conn.execute("""SELECT id FROM master_games g WHERE NOT EXISTS (SELECT 1 FROM guess_sessions s
                                      WHERE s.game_id = g.id) ORDER BY random() LIMIT 1""").fetchone()
            if r2 is None:
                raise ValueError("No master games yet. Fetch some from the Lichess broadcasts first.")
            g = self.conn.execute("SELECT result FROM master_games WHERE id = ?", (r2["id"],)).fetchone()
            gid, why = r2["id"], "any"
            side = "black" if g["result"] == "0-1" else "white"
        g = self.conn.execute("SELECT * FROM master_games WHERE id = ?", (gid,)).fetchone()
        game = chess.pgn.read_game(io.StringIO(g["pgn"]))
        moves = [m.uci() for m in game.mainline_moves()]
        start = config.MASTER_START_PLY
        if (start % 2 == 0) != (side == "white"):
            start += 1  # begin with the guessing side to move
        with tx(self.conn):
            sid = self.conn.execute(
                "INSERT INTO guess_sessions (game_id, side, start_ply, started_at) VALUES (?,?,?,?)",
                (gid, side, start, int(time.time()))).lastrowid
        self.current = {"session_id": sid, "game": g, "moves": moves, "side": side, "pos": start, "guesses": 0,
                        "matched": 0, "as_good": 0, "why": why, "limit": start + 2 * config.MASTER_GUESS_MOVES}
        return self._view()

    def _view(self) -> dict[str, Any]:
        c = self.current
        assert c is not None
        g = c["game"]
        return {"session_id": c["session_id"], "white": g["white"], "black": g["black"], "white_elo": g["white_elo"],
                "black_elo": g["black_elo"], "event": g["event"], "date": g["date"], "opening": g["opening"],
                "side": c["side"], "moves": c["moves"][: c["pos"]], "guesses": c["guesses"], "matched": c["matched"],
                "as_good": c["as_good"], "remaining": max(0, (min(c["limit"], len(c["moves"])) - c["pos"] + 1) // 2),
                "why": c["why"]}

    async def guess(self, uci: str) -> dict[str, Any]:
        c = self.current
        if c is None:
            raise ValueError("No game is in progress.")
        if self.locked():
            raise ValueError("The fair-play lock is on.")
        board = chess.Board()
        for u in c["moves"][: c["pos"]]:
            board.push_uci(u)
        move = chess.Move.from_uci(uci)
        if move not in board.legal_moves:
            raise ValueError("That move isn't legal here.")
        master = c["moves"][c["pos"]]
        matched = uci == master
        as_good = False
        if not matched:
            # Is your move as good as the master's? Compare the two resulting positions.
            sign = 1 if board.turn == chess.WHITE else -1
            mine, theirs = board.copy(), board.copy()
            mine.push(move)
            theirs.push_uci(master)

            async def score(b: chess.Board) -> int:
                if b.is_checkmate():
                    return config.MATE_CP if b.turn != board.turn else -config.MATE_CP
                if b.is_game_over():
                    return 0
                ev, _, _ = await self.analyse(b.fen(), config.MASTER_NODES)
                return sign * ev.clamped()

            mine_cp, master_cp = await score(mine), await score(theirs)
            as_good = mine_cp >= master_cp - config.MASTER_AS_GOOD_CP
        c["guesses"] += 1
        c["matched"] += int(matched)
        c["as_good"] += int(as_good)
        master_san = board.san(chess.Move.from_uci(master))
        c["pos"] += 1
        reply = None
        if c["pos"] < len(c["moves"]):
            reply = c["moves"][c["pos"]]
            c["pos"] += 1
        done = c["pos"] >= min(c["limit"], len(c["moves"]))
        out = {"matched": matched, "as_good": as_good, "master_uci": master, "master_san": master_san,
               "reply_uci": None if done else reply, "done": done}
        if done:
            out["summary"] = self.finish()
        return out

    def finish(self) -> dict[str, Any]:
        c = self.current
        if c is None:
            return {}
        with tx(self.conn):
            self.conn.execute("UPDATE guess_sessions SET finished_at = ?, guesses = ?, matched = ?, as_good = ? WHERE id = ?",
                              (int(time.time()), c["guesses"], c["matched"], c["as_good"], c["session_id"]))
        g = c["game"]
        self.current = None
        return {"guesses": c["guesses"], "matched": c["matched"], "as_good": c["as_good"], "result": g["result"],
                "white": g["white"], "black": g["black"], "event": g["event"]}
