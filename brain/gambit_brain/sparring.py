"""Sparring: long games against Maia-3 79M at a human level just above yours.

The bot's moves are sampled from Maia's policy at its level, so it makes human mistakes rather than
engine moves. Every game is saved like an imported one (platform 'sparring'), so Mirror analyses it
and Game Lab can take it apart. Results against each level are tracked, so the human-level label is
checked against what actually happens when you play it.
"""

from __future__ import annotations

import asyncio
import io
import random
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import chess
import chess.pgn

from . import config, games, humanlevel
from .lab import playing_elo
from .maia import Maia, sample_move

LEVEL_MIN, LEVEL_MAX = 600, 2600  # Maia-3's trained range, roughly


def _round_level(x: float) -> int:
    return int(max(LEVEL_MIN, min(LEVEL_MAX, round(x / 50) * 50)))


@dataclass
class Game:
    board: chess.Board
    you: chess.Color
    level: int
    you_elo: int
    base_s: int
    inc_s: int
    clocks: dict[bool, float]  # seconds left
    started: float = field(default_factory=time.time)
    clock_marks: list[float] = field(default_factory=list)  # clock after each move


class Sparring:
    def __init__(self, conn: sqlite3.Connection, maia: Maia, locked, rng: random.Random | None = None):
        self.conn, self.maia, self.locked = conn, maia, locked
        self.rng = rng or random.Random()
        self.game: Game | None = None

    # Before a game ----------------------------------------------------------------------------------
    def overview(self) -> dict[str, Any]:
        me = playing_elo(self.conn)
        level = _round_level(me + config.SPARRING_OFFSET)
        return {"suggested_level": level, "your_elo": me, "label": humanlevel.describe(self.conn, level),
                "record": self.record(), "game": self.view() if self.game else None,
                "time_controls": config.SPARRING_TIME_CONTROLS}

    def record(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """SELECT opp_rating AS level, COUNT(*) n, SUM(result = 'win') w, SUM(result = 'draw') d,
                      SUM(result = 'loss') l FROM games WHERE platform = 'sparring' GROUP BY opp_rating
               ORDER BY opp_rating""").fetchall()
        return [{**dict(r), "score": round((r["w"] + 0.5 * r["d"]) / r["n"], 3)} for r in rows]

    # A game -----------------------------------------------------------------------------------------
    async def start(self, color: str, base_min: int, inc_s: int, level: int | None = None) -> dict[str, Any]:
        if self.locked():
            raise ValueError("The fair-play lock is on. Finish your live game first.")
        if self.game is not None:
            raise ValueError("A sparring game is already in progress.")
        me = playing_elo(self.conn)
        level = _round_level(level if level is not None else me + config.SPARRING_OFFSET)
        if color == "random":
            color = self.rng.choice(["white", "black"])
        you = chess.WHITE if color == "white" else chess.BLACK
        base_s = int(base_min) * 60
        self.game = Game(chess.Board(), you, level, me, base_s, int(inc_s), {True: base_s, False: base_s})
        await asyncio.to_thread(self.maia.load)
        out = self.view()
        if you == chess.BLACK:
            out["reply"] = await self._bot_move()
        return out

    def view(self) -> dict[str, Any]:
        g = self.game
        assert g is not None
        return {"you": "white" if g.you == chess.WHITE else "black", "level": g.level,
                "label": humanlevel.describe(self.conn, g.level), "base_s": g.base_s, "inc_s": g.inc_s,
                "moves": [m.uci() for m in g.board.move_stack],
                "clocks": {"white": round(g.clocks[True], 1), "black": round(g.clocks[False], 1)},
                "claimable_draw": g.board.can_claim_draw()}

    def _think_seconds(self) -> float:
        """Human-ish thinking time: a few percent of the clock, quicker in the opening."""
        g = self.game
        assert g is not None
        left = g.clocks[not g.you]
        move_no = g.board.fullmove_number
        share = 0.003 if move_no < 8 else 0.03  # quick in the opening, more time once it gets complicated
        return max(1.0, min(left * share * self.rng.uniform(0.4, 1.8), 45.0))

    async def _bot_move(self) -> dict[str, Any]:
        g = self.game
        assert g is not None
        ucis = [m.uci() for m in g.board.move_stack]
        uci = await asyncio.to_thread(sample_move, self.maia, chess.STARTING_FEN, ucis, g.level, g.you_elo,
                                      config.SPARRING_TEMPERATURE, self.rng)
        think = self._think_seconds()
        bot = not g.you
        g.clocks[bot] = max(0.0, g.clocks[bot] - think) + g.inc_s
        g.board.push_uci(uci)
        g.clock_marks.append(g.clocks[bot])
        out = {"uci": uci, "think_ms": int(think * 1000), "clocks": self.view()["clocks"]}
        over = self._over()
        if over:
            out["over"] = self._finish(*over)
        return out

    def _over(self) -> tuple[str, str] | None:
        b = self.game.board  # type: ignore[union-attr]
        if b.is_checkmate():
            return ("loss" if b.turn == self.game.you else "win"), "checkmate"  # type: ignore[union-attr]
        if b.is_stalemate():
            return "draw", "stalemate"
        if b.is_insufficient_material():
            return "draw", "insufficient"
        if b.is_seventyfive_moves() or b.is_fivefold_repetition():
            return "draw", "repetition"
        return None

    async def move(self, uci: str, your_clock_ms: int) -> dict[str, Any]:
        g = self.game
        if g is None:
            raise ValueError("No sparring game is in progress.")
        if self.locked():
            raise ValueError("The fair-play lock is on.")
        if g.board.turn != g.you:
            raise ValueError("It isn't your move.")
        move = chess.Move.from_uci(uci)
        if move not in g.board.legal_moves:
            raise ValueError("That move isn't legal here.")
        # Your clock is kept by the app; trust it but never let it run up.
        left = max(0.0, min(your_clock_ms / 1000, g.clocks[g.you]))
        if left <= 0:
            return {"over": self._finish("loss", "timeout")}
        g.clocks[g.you] = left + g.inc_s
        g.board.push(move)
        g.clock_marks.append(g.clocks[g.you])
        over = self._over()
        if over:
            return {"over": self._finish(*over)}
        return {"reply": await self._bot_move()}

    def resign(self) -> dict[str, Any]:
        if self.game is None:
            raise ValueError("No sparring game is in progress.")
        return {"over": self._finish("loss", "resign")}

    def flag(self) -> dict[str, Any]:
        if self.game is None:
            raise ValueError("No sparring game is in progress.")
        return {"over": self._finish("loss", "timeout")}

    def claim_draw(self) -> dict[str, Any]:
        g = self.game
        if g is None:
            raise ValueError("No sparring game is in progress.")
        if not g.board.can_claim_draw():
            raise ValueError("There's no draw to claim here: it needs a threefold repetition or 50 quiet moves.")
        return {"over": self._finish("draw", "repetition")}

    def _pgn(self, result: str) -> str:
        g = self.game
        assert g is not None
        game = chess.pgn.Game()
        you_name, bot_name = "You", f"Maia {g.level}"
        white_you = g.you == chess.WHITE
        tag = {"win": "1-0" if white_you else "0-1", "loss": "0-1" if white_you else "1-0", "draw": "1/2-1/2"}[result]
        game.headers.update({
            "Event": "gambit sparring", "Site": "gambit", "Date": datetime.now(UTC).strftime("%Y.%m.%d"),
            "White": you_name if white_you else bot_name, "Black": bot_name if white_you else you_name,
            "WhiteElo": str(g.you_elo if white_you else g.level), "BlackElo": str(g.level if white_you else g.you_elo),
            "TimeControl": f"{g.base_s}+{g.inc_s}", "Result": tag,
        })
        node = game
        for m, clk in zip(g.board.move_stack, g.clock_marks, strict=False):
            node = node.add_variation(m)
            node.set_clock(clk)
        out = io.StringIO()
        game.accept(chess.pgn.FileExporter(out))
        return out.getvalue()

    def _finish(self, result: str, reason: str) -> dict[str, Any]:
        g = self.game
        assert g is not None
        gid = None
        if g.board.move_stack:
            meta = games.GameMeta(
                platform="sparring", platform_id=f"{int(g.started)}-{g.level}", url=None, played_at=int(time.time()),
                time_class=games._speed(g.base_s, g.inc_s), time_control=f"{g.base_s}+{g.inc_s}", rated=False,
                my_color="white" if g.you == chess.WHITE else "black", my_rating=g.you_elo, opp_rating=g.level,
                opp_name=f"Maia {g.level}", result=result, termination=reason, eco=None, opening=None,
                pgn=self._pgn(result))
            gid = games.store(self.conn, meta)
        level = g.level
        self.game = None
        return {"result": result, "reason": reason, "game_id": gid, "level": level,
                "record": next((r for r in self.record() if r["level"] == level), None)}
