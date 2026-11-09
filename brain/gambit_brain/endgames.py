"""Endgames: theoretical positions played against perfect tablebase defence, on a spaced schedule.

Every position was checked against the Lichess tablebase (tablebase.lichess.org, free and
unauthenticated, up to 7 pieces). Each attempt is randomly mirrored left–right and, half the time,
colour-flipped, so the pattern is learned on different squares and from both sides.
"""

from __future__ import annotations

import json
import random
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import chess
import httpx

from . import config
from .db import tx
from .solve import update_card


@dataclass(frozen=True)
class Lesson:
    key: str
    stage: int
    title: str
    fen: str  # the canonical position; the user plays `side`
    side: str  # 'white' | 'black'
    goal: str  # 'mate' | 'promote' | 'capture' | 'hold'
    idea: str  # shown after the attempt, never before


CURRICULUM: list[Lesson] = [
    Lesson("kq_mate", 1, "Queen and king against king", "8/8/8/4k3/8/8/8/4K2Q w - - 0 1", "white", "mate",
           "Use the queen a knight's move from the king to shrink its box, then bring your king up. "
           "Watch for stalemate."),
    Lesson("kr_mate", 1, "Rook and king against king", "8/8/8/4k3/8/8/8/4K2R w - - 0 1", "white", "mate",
           "Cut the king off with the rook, walk your king into opposition, then check along the edge."),
    Lesson("kp_in_front", 1, "King in front of the pawn", "8/8/3k4/8/3K4/8/3P4/8 w - - 0 1", "white", "promote",
           "With your king two squares in front of the pawn, you win whoever moves. "
           "Keep the king ahead; push only when it's safe."),
    Lesson("kp_opposition", 1, "Winning with the opposition", "8/8/8/3k4/8/3K4/3P4/8 b - - 0 1", "white", "promote",
           "Take the opposition, then outflank: the defending king must give way and your king reaches a key square."),
    Lesson("kp_defend", 1, "Holding king and pawn", "8/3k4/8/3PK3/8/8/8/8 b - - 0 1", "black", "hold",
           "Stay in front of the pawn and take the opposition when the attacking king comes to the sixth rank."),
    Lesson("rook_pawn", 1, "The rook-pawn draw", "7k/8/7K/7P/8/8/8/8 b - - 0 1", "black", "hold",
           "Shuttle in the corner. A rook pawn can't drive the king out, and stalemate is your friend."),
    Lesson("lucena", 2, "Lucena: building the bridge", "1K6/1P1k4/8/8/8/8/r7/2R5 w - - 0 1", "white", "promote",
           "Check the king away, lift the rook to the fourth rank, then use it as a shield against the checks."),
    Lesson("philidor", 2, "Philidor: the third-rank defence", "4k3/r7/8/3PK3/8/8/8/7R b - - 0 1", "black", "hold",
           "Keep your rook on the sixth rank until the pawn advances, then check from behind."),
    Lesson("rook_vs_pawn", 2, "Rook against pawn", "8/8/8/8/8/4k3/4p3/1R2K3 w - - 0 1", "white", "capture",
           "Keep the defending king cut off, block the pawn with your king, then pick it up."),
    Lesson("bb_mate", 3, "Two bishops mate", "8/8/8/4k3/8/8/8/2B1KB2 w - - 0 1", "white", "mate",
           "Bishops side by side make a wall; push the king to a corner with your king's help."),
    Lesson("bn_mate", 3, "Bishop and knight mate", "8/8/8/4k3/8/8/8/2BNK3 w - - 0 1", "white", "mate",
           "Drive the king to the edge, then to the corner your bishop controls, with the W manoeuvre for the knight."),
]
BY_KEY = {lesson.key: lesson for lesson in CURRICULUM}


# ── Tablebase ────────────────────────────────────────────────────────────────────────────────────


class Tablebase:
    """Lichess tablebase client with a small in-memory cache."""

    def __init__(self, http: httpx.AsyncClient | None = None):
        self._http = http
        self._cache: dict[str, dict[str, Any]] = {}

    async def probe(self, fen: str) -> dict[str, Any]:
        key = " ".join(fen.split()[:4])
        if key in self._cache:
            return self._cache[key]
        http = self._http or httpx.AsyncClient(headers={"User-Agent": config.USER_AGENT}, timeout=10)
        try:
            r = await http.get(config.TABLEBASE_URL, params={"fen": fen})
            if r.status_code == 429:
                raise RuntimeError("The tablebase is busy. Wait a minute and try again.")
            r.raise_for_status()
            data = r.json()
        except httpx.HTTPError as e:
            raise RuntimeError("Couldn't reach the Lichess tablebase. Endgames need a connection.") from e
        finally:
            if self._http is None:
                await http.aclose()
        self._cache[key] = data
        return data


# A defender's result after your move, seen from the attacker to move: anything but a win holds.
HELD = {"draw", "cursed-win", "blessed-loss", "loss"}


# ── Attempts ─────────────────────────────────────────────────────────────────────────────────────


def _variant(lesson: Lesson, rng: random.Random) -> tuple[chess.Board, str]:
    board = chess.Board(lesson.fen)
    side = lesson.side
    if rng.random() < 0.5:
        board = board.transform(chess.flip_horizontal)
    if rng.random() < 0.5:
        board = board.mirror()
        side = "black" if side == "white" else "white"
    return board, side


def ensure_items(conn: sqlite3.Connection) -> None:
    now = int(time.time())
    with tx(conn):
        for lesson in CURRICULUM:
            conn.execute(
                """INSERT OR IGNORE INTO items (kind, ref, fen, solution, themes, created_at)
                   VALUES ('endgame', ?, ?, ?, ?, ?)""",
                (lesson.key, lesson.fen, lesson.goal, json.dumps([f"stage{lesson.stage}"]), now))


@dataclass
class Attempt:
    lesson: Lesson
    item_id: int
    board: chess.Board
    side: chess.Color
    optimal_moves: int | None
    user_moves: int = 0
    started: float = field(default_factory=time.monotonic)
    played: list[str] = field(default_factory=list)
    promoted: bool = False


class Endgames:
    def __init__(self, conn: sqlite3.Connection, tb: Tablebase | None = None):
        self.conn, self.tb = conn, tb or Tablebase()
        self.attempt: Attempt | None = None
        ensure_items(conn)

    def overview(self) -> dict[str, Any]:
        now = int(time.time())
        rows = {r["ref"]: r for r in self.conn.execute(
            """SELECT i.id, i.ref, c.due, c.card,
                      (SELECT COUNT(*) FROM reviews r WHERE r.item_id = i.id) AS attempts,
                      (SELECT COUNT(*) FROM reviews r WHERE r.item_id = i.id AND r.correct = 1) AS successes
               FROM items i LEFT JOIN cards c ON c.item_id = i.id WHERE i.kind = 'endgame'""")}
        out = []
        for lesson in CURRICULUM:
            r = rows.get(lesson.key)
            status = "new" if not r or r["due"] is None else "due" if r["due"] <= now else "learning"
            out.append({"key": lesson.key, "stage": lesson.stage, "title": lesson.title, "goal": lesson.goal,
                        "side": lesson.side, "status": status, "due": r["due"] if r else None,
                        "attempts": r["attempts"] if r else 0, "successes": r["successes"] if r else 0})
        return {"lessons": out, "due": sum(x["status"] == "due" for x in out),
                "attempt": self._attempt_view() if self.attempt else None}

    def _next_key(self, stage_cap: int) -> str | None:
        ov = self.overview()["lessons"]
        due = [x for x in ov if x["status"] == "due"]
        if due:
            return min(due, key=lambda x: x["due"])["key"]
        new = [x for x in ov if x["status"] == "new" and x["stage"] <= stage_cap]
        return new[0]["key"] if new else None

    async def start(self, key: str | None = None, stage_cap: int = 4,
                    rng: random.Random | None = None) -> dict[str, Any]:
        rng = rng or random.Random()
        key = key or self._next_key(stage_cap)
        if key is None:
            raise ValueError("Nothing is due, and you've started every endgame at your stage.")
        lesson = BY_KEY.get(key)
        if lesson is None:
            raise ValueError("Unknown endgame.")
        board, side = _variant(lesson, rng)
        item_id = self.conn.execute("SELECT id FROM items WHERE kind = 'endgame' AND ref = ?", (key,)).fetchone()[0]
        probe = await self.tb.probe(board.fen())
        mover_is_user = (board.turn == chess.WHITE) == (side == "white")
        dtm = probe.get("dtm")
        optimal = (abs(dtm) + 1) // 2 if dtm else None
        self.attempt = Attempt(lesson, item_id, board, chess.WHITE if side == "white" else chess.BLACK, optimal)
        lead = None
        if not mover_is_user:  # the defender moves first, with the tablebase's best
            lead = probe["moves"][0]["uci"]
            board.push_uci(lead)
            dtm = (await self.tb.probe(board.fen())).get("dtm")
            self.attempt.optimal_moves = (abs(dtm) + 1) // 2 if dtm else None
        out = self._attempt_view()
        out["lead_uci"] = lead
        return out

    def _attempt_view(self) -> dict[str, Any]:
        a = self.attempt
        assert a is not None
        start = a.board.copy()
        while start.move_stack:
            start.pop()
        return {"key": a.lesson.key, "title": a.lesson.title, "goal": a.lesson.goal, "stage": a.lesson.stage,
                "side": "white" if a.side == chess.WHITE else "black", "fen": start.fen(),
                "moves": [m.uci() for m in a.board.move_stack], "user_moves": a.user_moves,
                "move_limit": self._limit(a)}

    def _limit(self, a: Attempt) -> int:
        if a.lesson.goal == "hold":
            return config.ENDGAME_HOLD_MOVES
        base = a.optimal_moves or config.ENDGAME_DEFAULT_MOVES
        return base * 2 + 5

    async def move(self, uci: str) -> dict[str, Any]:
        a = self.attempt
        if a is None:
            raise ValueError("No endgame is in progress.")
        board = a.board
        if board.turn != a.side:
            raise ValueError("It isn't your move.")
        try:
            move = chess.Move.from_uci(uci)
        except ValueError as e:
            raise ValueError("That isn't a move.") from e
        if move not in board.legal_moves:
            raise ValueError("That move isn't legal here.")
        before_fen = board.fen()
        before = await self.tb.probe(before_fen)
        board.push(move)
        a.user_moves += 1
        a.played.append(uci)
        a.promoted = a.promoted or bool(move.promotion)
        lesson = a.lesson

        # Did the move throw the result away?
        after = None if board.is_game_over() else await self.tb.probe(board.fen())
        if lesson.goal == "hold":
            kept = board.is_game_over() and not board.is_checkmate() or (after and after.get("category") != "win")
        else:
            kept = board.is_checkmate() or (after is not None and after.get("category") == "loss")
        if not kept:
            good = HELD if lesson.goal == "hold" else {"loss"}
            keeping = [m["san"] for m in before.get("moves", []) if m.get("category") in good][:4]
            return self._finish(False, "That move gives the result away.", keeping)

        if self._succeeded(board):
            return self._finish(True, None, [])
        if a.user_moves >= self._limit(a):
            return self._finish(False, "Out of moves: the result was still there, but too slowly to count.", [])
        reply = after["moves"][0]["uci"]  # perfect defence: the tablebase's first choice
        board.push_uci(reply)
        if board.is_game_over() or self._succeeded(board):
            ok = self._succeeded(board) or (lesson.goal == "hold" and not board.is_checkmate())
            return self._finish(ok, None if ok else "The defence held.", [], reply)
        return {"result": "ok", "done": False, "reply_uci": reply, "user_moves": a.user_moves,
                "move_limit": self._limit(a)}

    def _succeeded(self, board: chess.Board) -> bool:
        a = self.attempt
        assert a is not None
        goal = a.lesson.goal
        if goal == "mate":
            return board.is_checkmate() and board.turn != a.side
        if goal == "promote":
            return a.promoted
        if goal == "capture":
            return not board.pieces(chess.PAWN, not a.side)
        if goal == "hold":
            return a.user_moves >= config.ENDGAME_HOLD_MOVES or (board.is_game_over() and not board.is_checkmate())
        return False

    def _finish(self, success: bool, why: str | None, keeping: list[str], reply: str | None = None) -> dict[str, Any]:
        from fsrs import Rating

        a = self.attempt
        assert a is not None
        ms = int((time.monotonic() - a.started) * 1000)
        if not success:
            rating = Rating.Again
        elif a.optimal_moves and a.user_moves <= a.optimal_moves + 2:
            rating = Rating.Easy
        else:
            rating = Rating.Good
        now = datetime.now(UTC)
        first = self.conn.execute("SELECT COUNT(*) FROM reviews WHERE item_id = ?", (a.item_id,)).fetchone()[0] == 0
        with tx(self.conn):
            card = update_card(self.conn, a.item_id, rating, now)
            self.conn.execute(
                """INSERT INTO reviews (item_id, at, mode, first_seen, correct, answer, ms, grade)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (a.item_id, int(now.timestamp()), "endgame",
                 int(first),
                 int(success), " ".join(a.played), ms, int(rating)))
        days = max(0.0, (card.due - now).total_seconds() / 86_400)
        out = {"result": "success" if success else "failed", "done": True, "reply_uci": reply, "reason": why,
               "keeping_moves": keeping, "user_moves": a.user_moves, "optimal_moves": a.optimal_moves,
               "idea": a.lesson.idea, "next_review_days": round(days, 2)}
        self.attempt = None
        return out

    def abandon(self) -> None:
        self.attempt = None

