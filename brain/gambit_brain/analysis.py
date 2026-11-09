"""Batch analysis: a Stockfish pool, the overnight first pass, the critical-moment deep pass,
and move classification.

Budgets come from `config.BATCH` (measured in bakeoff/RESULTS.md).
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
from collections.abc import Awaitable, Callable
from typing import Any

import chess
import chess.engine

from . import config, tagger
from .chesslib import Eval, winning_chance
from .db import tx

log = logging.getLogger("gambit.analysis")


class EnginePool:
    """N single-thread Stockfish processes behind a queue. `stop()` kills them all (fair-play lock)."""

    def __init__(self, budget: config.EngineBudget = config.BATCH, path: str = config.STOCKFISH_PATH):
        self.budget, self.path = budget, path
        self._idle: asyncio.Queue[chess.engine.UciProtocol] = asyncio.Queue()
        self._all: list[tuple[asyncio.SubprocessTransport, chess.engine.UciProtocol]] = []

    @property
    def running(self) -> bool:
        return bool(self._all)

    async def _spawn(self) -> chess.engine.UciProtocol:
        transport, eng = await chess.engine.popen_uci(self.path)
        await eng.configure({"Threads": self.budget.threads, "Hash": self.budget.hash_mb})
        self._all.append((transport, eng))
        return eng

    async def start(self) -> None:
        if self._all:
            return
        for _ in range(self.budget.workers):
            self._idle.put_nowait(await self._spawn())

    async def stop(self) -> None:
        for transport, eng in self._all:
            try:
                await asyncio.wait_for(eng.quit(), 1)
            except Exception:
                transport.kill()
        self._all.clear()
        self._idle = asyncio.Queue()

    def kill_now(self) -> None:
        """Synchronous kill for shutdown paths that can't await."""
        for transport, _ in self._all:
            try:
                transport.kill()
            except Exception:
                pass
        self._all.clear()

    def _release(self, eng: chess.engine.UciProtocol) -> None:
        if any(e is eng for _, e in self._all):  # not if the pool was stopped meanwhile
            self._idle.put_nowait(eng)

    async def analyse(self, fen: str, nodes: int) -> tuple[Eval, list[str], int]:
        board = chess.Board(fen)
        if not board.is_valid():  # Stockfish 19 exits on invalid input
            raise ValueError(f"invalid position: {fen}")
        eng = await self._idle.get()
        try:
            info = await eng.analyse(board, chess.engine.Limit(nodes=nodes))
        except chess.engine.EngineTerminatedError:
            was_running = self.running
            self._all = [(t, e) for t, e in self._all if e is not eng]
            if was_running:  # replace the crashed worker; the caller sees this position fail
                self._idle.put_nowait(await self._spawn())
            raise
        except BaseException:
            self._release(eng)
            raise
        self._release(eng)
        pv = [m.uci() for m in info.get("pv", [])][: self.budget.pv_len]
        return Eval.from_pov(info["score"]), pv, int(info.get("nodes", nodes))


# ── Classification ───────────────────────────────────────────────────────────────────────────────


def classify(before: Eval, after: Eval, mover_white: bool, played_best: bool) -> tuple[int, float, str]:
    """(cp_loss, winning-chance loss 0..1, class) from the mover's point of view."""
    sign = 1 if mover_white else -1
    b, a = sign * before.clamped(), sign * after.clamped()
    cp_loss = max(0, b - a)
    wc_loss = max(0.0, (winning_chance(b) - winning_chance(a)) / 2)
    if played_best:
        cls = "best"
    elif a >= config.STILL_WINNING_CP or cp_loss < config.INACCURACY_CP:
        cls = "ok"
    elif cp_loss >= config.BLUNDER_CP:
        cls = "blunder"
    elif cp_loss >= config.MISTAKE_CP:
        cls = "mistake"
    else:
        cls = "inaccuracy"
    return cp_loss, wc_loss, cls


def _load_evals(conn: sqlite3.Connection, epds: list[str]) -> dict[str, sqlite3.Row]:
    out: dict[str, sqlite3.Row] = {}
    for i in range(0, len(epds), 500):
        chunk = epds[i : i + 500]
        q = f"SELECT * FROM evals WHERE epd IN ({','.join('?' * len(chunk))})"
        out.update({r["epd"]: r for r in conn.execute(q, chunk)})
    return out


def classify_game(conn: sqlite3.Connection, game_id: int) -> int:
    """Classify and tag every move of a game from stored evals. Returns how many moves were classified."""
    moves = conn.execute("SELECT * FROM moves WHERE game_id = ? ORDER BY ply", (game_id,)).fetchall()
    evals = _load_evals(conn, list({m["epd_before"] for m in moves} | {m["epd_after"] for m in moves}))
    updates = []
    for m in moves:
        rb, ra = evals.get(m["epd_before"]), evals.get(m["epd_after"])
        if rb is None or ra is None:
            continue
        before, after = Eval(rb["cp"], rb["mate"]), Eval(ra["cp"], ra["mate"])
        played_best = rb["best_uci"] == m["uci"]
        cp_loss, wc_loss, cls = classify(before, after, m["color"] == "white", played_best)
        motifs = None
        if cls in ("mistake", "blunder"):
            board = chess.Board(m["fen_before"])
            motifs = json.dumps(
                tagger.tag(
                    board, chess.Move.from_uci(m["uci"]), before, (rb["pv"] or "").split(),
                    after, (ra["pv"] or "").split(),
                )
            )
        updates.append((cp_loss, round(wc_loss, 4), cls, motifs, game_id, m["ply"]))
    with tx(conn):
        conn.executemany(
            "UPDATE moves SET cp_loss = ?, wc_loss = ?, class = ?, motifs = ? WHERE game_id = ? AND ply = ?",
            updates,
        )
    return len(updates)


# ── The batch job ────────────────────────────────────────────────────────────────────────────────

Emit = Callable[[dict[str, Any]], Awaitable[None]]


def _final_fen(fen_before: str, uci: str) -> str:
    b = chess.Board(fen_before)
    b.push(chess.Move.from_uci(uci))
    return b.fen()


class BatchAnalysis:
    """First pass over every unanalysed game (newest first), then a deep pass over your blunders.

    Pausing finishes the positions already in flight and stops. The fair-play lock pauses the job
    and kills the pool.
    """

    def __init__(self, conn: sqlite3.Connection, pool: EnginePool, emit: Emit, me_only_deep: bool = True):
        self.conn, self.pool, self.emit = conn, pool, emit
        self.me_only_deep = me_only_deep
        self.task: asyncio.Task | None = None
        self.state = "idle"  # idle | running | pausing | paused | done | error
        self.error: str | None = None
        self._inflight: dict[str, asyncio.Future] = {}
        self._positions = 0
        self._started = 0.0

    # Public control -------------------------------------------------------------------------------
    def status(self) -> dict[str, Any]:
        c = self.conn
        total = c.execute("SELECT COUNT(*) FROM games").fetchone()[0]
        first = c.execute("SELECT COUNT(*) FROM games WHERE analysed_at IS NOT NULL").fetchone()[0]
        deep = c.execute("SELECT COUNT(*) FROM games WHERE deep_at IS NOT NULL").fetchone()[0]
        elapsed = time.monotonic() - self._started if self._started else 0
        rate = self._positions / elapsed if elapsed > 5 else None
        remaining_positions = c.execute(
            "SELECT COALESCE(SUM(ply_count), 0) FROM games WHERE analysed_at IS NULL"
        ).fetchone()[0]
        eta = remaining_positions / rate if rate else None
        return {
            "state": self.state, "error": self.error, "games": total, "analysed": first, "deep": deep,
            "positions_per_s": round(rate, 1) if rate else None,
            "eta_s": round(eta) if eta and self.state == "running" else None,
        }

    def start(self) -> None:
        if self.task and not self.task.done():
            if self.state == "pausing":
                self.state = "running"
            return
        self.state, self.error = "running", None
        self.task = asyncio.create_task(self._run())

    def pause(self) -> None:
        if self.state == "running":
            self.state = "pausing"

    async def halt(self) -> None:
        """Stop immediately (fair-play lock): cancel the task and kill the engines."""
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except (asyncio.CancelledError, Exception):
                pass
        await self.pool.stop()
        if self.state in ("running", "pausing"):
            self.state = "paused"
        await self.emit(self.status())

    # Internals ------------------------------------------------------------------------------------
    async def _eval(self, epd: str, fen: str, nodes: int) -> None:
        if epd in self._inflight:
            await self._inflight[epd]
            return
        fut = asyncio.get_running_loop().create_future()
        fut.add_done_callback(lambda f: f.cancelled() or f.exception())  # mark retrieved
        self._inflight[epd] = fut
        try:
            ev, pv, used = await self.pool.analyse(fen, nodes)
            self.conn.execute(
                """INSERT INTO evals (epd, cp, mate, best_uci, pv, nodes, source, updated_at)
                   VALUES (?,?,?,?,?,?,'sf',?)
                   ON CONFLICT(epd) DO UPDATE SET cp=excluded.cp, mate=excluded.mate, best_uci=excluded.best_uci,
                     pv=excluded.pv, nodes=excluded.nodes, source='sf', updated_at=excluded.updated_at""",
                (epd, ev.cp, ev.mate, pv[0] if pv else None, " ".join(pv), used, int(time.time())),
            )
            self._positions += 1
            fut.set_result(None)
        except BaseException as e:
            fut.set_exception(e) if not isinstance(e, asyncio.CancelledError) else fut.cancel()
            raise
        finally:
            self._inflight.pop(epd, None)

    async def _first_pass_game(self, gid: int) -> None:
        rows = self.conn.execute(
            "SELECT ply, fen_before, epd_before, epd_after, uci FROM moves WHERE game_id = ? ORDER BY ply", (gid,)
        ).fetchall()
        wanted = {r["epd_before"]: r["fen_before"] for r in rows}
        last = rows[-1]
        wanted.setdefault(last["epd_after"], _final_fen(last["fen_before"], last["uci"]))
        have = _load_evals(self.conn, list(wanted))
        missing = [(e, f) for e, f in wanted.items() if e not in have]
        await asyncio.gather(*(self._eval(e, f, self.pool.budget.nodes) for e, f in missing))
        classify_game(self.conn, gid)
        self.conn.execute("UPDATE games SET analysed_at = ? WHERE id = ?", (int(time.time()), gid))

    async def _deep_pass_game(self, gid: int) -> None:
        where = "AND m.color = g.my_color" if self.me_only_deep else ""
        rows = self.conn.execute(
            f"""SELECT m.fen_before, m.epd_before, m.epd_after, m.uci FROM moves m JOIN games g ON g.id = m.game_id
                WHERE m.game_id = ? AND m.class = 'blunder' {where}""",
            (gid,),
        ).fetchall()
        jobs: dict[str, str] = {}
        for r in rows:
            jobs[r["epd_before"]] = r["fen_before"]
            jobs[r["epd_after"]] = _final_fen(r["fen_before"], r["uci"])
        have = _load_evals(self.conn, list(jobs))
        def settled(e: str) -> bool:
            r = have.get(e)
            return bool(r) and (r["source"] == "terminal" or (
                r["source"] == "sf" and (r["nodes"] or 0) >= self.pool.budget.deep_nodes))

        todo = [(e, f) for e, f in jobs.items() if not settled(e)]
        await asyncio.gather(*(self._eval(e, f, self.pool.budget.deep_nodes) for e, f in todo))
        if rows:
            classify_game(self.conn, gid)
        self.conn.execute("UPDATE games SET deep_at = ? WHERE id = ?", (int(time.time()), gid))

    async def _drain(self, ids: list[int], fn: Callable[[int], Awaitable[None]], phase: str) -> bool:
        """Run `fn` over game ids with a few games in flight. Returns False if paused."""
        sem = asyncio.Semaphore(self.pool.budget.games_in_flight)
        last_emit = 0.0

        async def one(gid: int) -> None:
            nonlocal last_emit
            async with sem:
                if self.state != "running":
                    return
                await fn(gid)
                if time.monotonic() - last_emit > 1:
                    last_emit = time.monotonic()
                    await self.emit({**self.status(), "phase": phase})

        await asyncio.gather(*(one(g) for g in ids))
        return self.state == "running"

    async def _run(self) -> None:
        try:
            await self.pool.start()
            self._started, self._positions = time.monotonic(), 0
            await self.emit({**self.status(), "phase": "first"})
            ids = [r[0] for r in self.conn.execute(
                "SELECT id FROM games WHERE analysed_at IS NULL ORDER BY played_at DESC")]
            if await self._drain(ids, self._first_pass_game, "first"):
                ids = [r[0] for r in self.conn.execute(
                    "SELECT id FROM games WHERE analysed_at IS NOT NULL AND deep_at IS NULL ORDER BY played_at DESC")]
                if await self._drain(ids, self._deep_pass_game, "deep"):
                    self.state = "done"
            if self.state == "pausing":
                self.state = "paused"
        except asyncio.CancelledError:
            raise
        except Exception as e:  # surfaced in the UI; the job can be restarted
            log.exception("analysis failed")
            self.state, self.error = "error", str(e)
        finally:
            if self.state != "running":
                await self.pool.stop()
            await self.emit({**self.status(), "phase": None})
