"""Calculation: the pieces stay frozen while you list candidates and write your main line.

Then one deliberate look at a different area of the board, then the engine checks the line. In
visualization mode the pieces vanish after a few seconds and you calculate from memory.
Positions are long library puzzles (themes long / veryLong) near your level, never seen before.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from collections.abc import Awaitable, Callable
from typing import Any

import chess

from . import config, solve
from .chesslib import Eval
from .db import tx

Analyse = Callable[[str, int], Awaitable[tuple[Eval, list[str], int]]]
MOVE_NUMBER = re.compile(r"^\d+\.+$|^\d+\.{3}$")


def parse_line(board: chess.Board, text: str) -> tuple[list[chess.Move], str | None]:
    """SAN tokens (move numbers allowed) → moves, stopping at the first one that isn't legal."""
    b = board.copy()
    moves: list[chess.Move] = []
    for raw in text.replace(",", " ").split():
        tok = re.sub(r"^\d+\.+", "", raw).strip()
        if not tok or MOVE_NUMBER.match(raw):
            continue
        try:
            m = b.parse_san(tok)
        except ValueError:
            return moves, tok
        moves.append(m)
        b.push(m)
    return moves, None


class Calc:
    def __init__(self, conn: sqlite3.Connection, analyse: Analyse, locked: Callable[[], bool]):
        self.conn, self.analyse, self.locked = conn, analyse, locked
        self.current: dict[str, Any] | None = None

    def overview(self) -> dict[str, Any]:
        rows = self.conn.execute(
            "SELECT COUNT(*) n, SUM(first_correct) ok, SUM(saw_it) saw, AVG(plies_matched) depth FROM calc_attempts").fetchone()
        recent = [dict(r) for r in self.conn.execute(
            "SELECT at, mode, first_correct, saw_it, plies_matched, line_len FROM calc_attempts ORDER BY at DESC LIMIT 20")]
        n = rows["n"] or 0
        return {"attempts": n, "first_correct": round((rows["ok"] or 0) / n, 3) if n else None,
                "saw_but_rejected": round(((rows["saw"] or 0) - (rows["ok"] or 0)) / n, 3) if n else None,
                "avg_plies_matched": round(rows["depth"] or 0, 2) if n else None, "recent": recent,
                "visual_seconds": config.CALC_VISUAL_SECONDS,
                "library_ready": self.conn.execute("SELECT COUNT(*) FROM puzzles").fetchone()[0] > 0}

    def next(self, mode: str) -> dict[str, Any]:
        if mode not in ("board", "visual"):
            raise ValueError("unknown mode")
        target = int(solve.solve_rating(self.conn)["r"] + config.CALC_RATING_OFFSET)
        theme_sql = " OR ".join("(' ' || p.themes || ' ') LIKE ?" for _ in config.CALC_THEMES)
        params = [f"% {t} %" for t in config.CALC_THEMES]
        row = None
        for widen in (100, 200, 400, 800):
            row = self.conn.execute(
                f"""SELECT p.* FROM puzzles p WHERE p.rating BETWEEN ? AND ? AND ({theme_sql})
                      AND NOT EXISTS (SELECT 1 FROM calc_attempts c WHERE c.puzzle_id = p.id)
                    ORDER BY random() LIMIT 1""", (target - widen, target + widen, *params)).fetchone()
            if row:
                break
        if row is None:
            raise ValueError("No calculation positions yet. Import the puzzle library in Solve first.")
        moves = row["moves"].split()
        board = chess.Board(row["fen"])
        board.push_uci(moves[0])
        self.current = {"puzzle": row, "mode": mode, "fen": board.fen(), "started": time.monotonic()}
        # Solve first: only the position, never the solution or the themes.
        return {"puzzle_id": row["id"], "mode": mode, "start_fen": row["fen"], "lead_uci": moves[0], "fen": board.fen(),
                "turn": "white" if board.turn == chess.WHITE else "black", "visual_seconds": config.CALC_VISUAL_SECONDS}

    async def submit(self, puzzle_id: str, candidates: list[str], line: str, scan_note: str | None) -> dict[str, Any]:
        cur = self.current
        if cur is None or cur["puzzle"]["id"] != puzzle_id:
            raise ValueError("That position isn't the current one.")
        if self.locked():
            raise ValueError("The fair-play lock is on. Finish your live game first.")
        board = chess.Board(cur["fen"])
        mover = board.turn
        sol = cur["puzzle"]["moves"].split()[1:]
        moves, bad = parse_line(board, line)
        if not moves:
            raise ValueError(f"“{bad}” isn't a legal move here." if bad else "Write at least your first move.")
        cand_moves = []
        for c in candidates:
            got, _ = parse_line(board, c)
            if got:
                cand_moves.append(got[0])
        ucis = [m.uci() for m in moves]
        matched = 0
        for u, s in zip(ucis, sol, strict=False):
            if u != s:
                break
            matched += 1
        b = board.copy()
        b.push(moves[0])
        first_ok = ucis[0] == sol[0] or b.is_checkmate()
        saw = first_ok or any(m.uci() == sol[0] for m in cand_moves)

        # The engine checks where your line ends, and where the best line ends, from your side.
        end = board.copy()
        for m in moves:
            end.push(m)
        best_end = board.copy()
        for u in sol:
            best_end.push_uci(u)
        sign = 1 if mover == chess.WHITE else -1

        async def score(b: chess.Board) -> int:
            if b.is_checkmate():
                return config.MATE_CP if b.turn != mover else -config.MATE_CP
            if b.is_game_over():
                return 0
            ev, _, _ = await self.analyse(b.fen(), config.CALC_NODES)
            return sign * ev.clamped()

        end_cp, best_cp = await score(end), await score(best_end)
        ms = int((time.monotonic() - cur["started"]) * 1000)

        def san_of(ms_: list[chess.Move]) -> list[str]:
            bb, out = board.copy(), []
            for m in ms_:
                out.append(bb.san(m))
                bb.push(m)
            return out

        with tx(self.conn):
            self.conn.execute(
                """INSERT INTO calc_attempts (at, puzzle_id, mode, candidates, line, scan_note, first_correct, saw_it,
                     plies_matched, line_len, ms, end_cp, best_cp) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (int(time.time()), puzzle_id, cur["mode"], json.dumps(candidates), line, scan_note, int(first_ok),
                 int(saw), matched, len(moves), ms, end_cp, best_cp))
        self.current = None
        return {
            "first_correct": first_ok, "saw_it": saw, "plies_matched": matched, "line_len": len(moves),
            "stopped_at": bad, "your_line": san_of(moves), "best_line": san_of([chess.Move.from_uci(u) for u in sol]),
            "best_ucis": sol, "your_ucis": ucis, "end_cp": end_cp, "best_cp": best_cp,
            "rating": cur["puzzle"]["rating"], "themes": cur["puzzle"]["themes"].split(), "ms": ms,
            "fen": cur["fen"],
        }
