"""JSON-RPC over a localhost WebSocket, plus the brain's lifelines.

Protocol
  request       {"id": 1, "method": "slope.get", "params": {...}}
  response      {"id": 1, "result": ...}  or  {"id": 1, "error": {"code": int, "message": str}}
  notification  {"method": "event", "params": {"topic": "analysis" | "import" | "settings", "data": ...}}

Lifelines: stdin EOF, a changed parent PID or SIGTERM shut the brain down, engines included.
Secrets arrive only over stdin (from the shell's Keychain read) and never go back over the socket.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
import threading
import time
from collections.abc import Awaitable, Callable
from typing import Any

import chess
import websockets
from websockets.asyncio.server import ServerConnection

from . import (
    analysis,
    audit,
    config,
    db,
    endgames,
    games,
    guardrails,
    humanlevel,
    importers,
    lab,
    metrics,
    planner,
    puzzles,
    solve,
    sparring,
)
from .maia import Maia

log = logging.getLogger("gambit.brain")

Handler = Callable[[dict[str, Any]], Awaitable[Any] | Any]

USER_SETTINGS = {"chesscom_username", "lichess_username", "training_start", "weekly_hours", "rest_days", "stage_override"}


class RpcError(Exception):
    def __init__(self, message: str, code: int = -32000):
        super().__init__(message)
        self.code = code


class Brain:
    def __init__(self, conn, secrets: dict[str, str] | None = None):
        self.conn = conn
        self.secrets: dict[str, str] = dict(secrets or {})
        self.clients: set[ServerConnection] = set()
        self.pool = analysis.EnginePool()
        self.job = analysis.BatchAnalysis(conn, self.pool, self._analysis_event)
        self.puzzles = puzzles.PuzzleImport(conn, lambda d: self.broadcast("puzzles", d))
        self.live = analysis.EnginePool(config.LIVE)
        self.solver = solve.Solver(conn, self.live_check)
        self.maia = Maia()
        self.lab = lab.Lab(conn, self.live_analyse, self.maia, self._locked, lambda d: self.broadcast("lab", d))
        self.watcher = guardrails.LichessWatcher(conn, self.apply_lock, self._game_ended)
        self.endgames = endgames.Endgames(conn)
        self.spar_maia = Maia(config.MAIA_SPARRING_MODEL)
        self.sparring = sparring.Sparring(conn, self.spar_maia, self._locked)
        self.sweep_task: asyncio.Task | None = None
        humanlevel.prune_stale(conn)
        self.import_task: asyncio.Task | None = None
        self.import_state: dict[str, Any] = {"state": "idle"}
        if db.get_setting(conn, "training_start") is None:
            with db.tx(conn):
                db.set_setting(conn, "training_start", int(time.time()))
        self.methods: dict[str, Handler] = {
            "ping": lambda p: {"t": time.time()},
            "settings.get": self.settings_get,
            "settings.set": self.settings_set,
            "fairplay.set": self.fairplay_set,
            "import.start": self.import_start,
            "import.status": lambda p: self.import_state,
            "analysis.start": self.analysis_start,
            "analysis.pause": self.analysis_pause,
            "analysis.status": lambda p: self.job.status(),
            "mirror.summary": self.mirror_summary,
            "slope.get": lambda p: metrics.slope(self.conn, p.get("platform"), p.get("time_class")),
            "audit.get": lambda p: audit.state(self.conn),
            "audit.start": lambda p: self._wrap(audit.start, self.conn),
            "audit.file": lambda p: self._wrap(audit.file, self.conn, p.get("lessons", [])),
            "puzzles.status": lambda p: self.puzzles.status(),
            "puzzles.import": lambda p: self.puzzles.start(),
            "solve.overview": lambda p: self.solver.overview(),
            "solve.start": lambda p: self._wrap(self.solver.start, p.get("mode", "standard")),
            "solve.next": lambda p: self._wrap(self.solver.next),
            "solve.move": self.solve_move,
            "solve.end": lambda p: self.solver.end(),
            "lab.games": lambda p: self.lab.games(int(p.get("limit", 40))),
            "lab.import_pgn": self.lab_import_pgn,
            "lab.open": lambda p: self._wrap(self.lab.open, int(p["game_id"])),
            "lab.view": lambda p: self._wrap(self.lab.view, int(p["session_id"])),
            "lab.note": lambda p: self._wrap(self.lab.note, int(p["session_id"]), int(p["ply"]),
                                             str(p.get("text", ""))),
            "lab.moment": lambda p: self._wrap(self.lab.moment, int(p["session_id"]), int(p["ply"]),
                                               str(p.get("note", "")), p.get("candidate")),
            "lab.moment_remove": lambda p: self._wrap(self.lab.remove_moment, int(p["session_id"]), int(p["ply"])),
            "lab.unlock": lambda p: self._awrap(self.lab.unlock(int(p["session_id"]))),
            "lab.engine": lambda p: self._awrap(self.lab.engine(int(p["session_id"]), str(p["fen"]))),
            "lab.close": lambda p: self._wrap(self.lab.close, int(p["session_id"]), list(p.get("lessons", []))),
            "endgames.overview": lambda p: self.endgames.overview(),
            "endgames.start": lambda p: self._awrap(self.endgames.start(p.get("key"), planner.stage(self.conn)["stage"])),
            "endgames.move": lambda p: self._awrap(self._endgame_move(str(p["uci"]))),
            "endgames.abandon": lambda p: self.endgames.abandon(),
            "sparring.overview": lambda p: self.sparring.overview(),
            "sparring.start": lambda p: self._awrap(self.sparring.start(
                str(p.get("color", "random")), int(p.get("base_min", 15)), int(p.get("inc_s", 10)), p.get("level"))),
            "sparring.move": lambda p: self._awrap(self.sparring.move(str(p["uci"]), int(p.get("clock_ms", 0)))),
            "sparring.resign": lambda p: self._wrap(self.sparring.resign),
            "sparring.flag": lambda p: self._wrap(self.sparring.flag),
            "sparring.claim_draw": lambda p: self._wrap(self.sparring.claim_draw),
            "planner.today": lambda p: planner.today(self.conn),
            "human.scale": lambda p: humanlevel.personal_scale(self.conn),
            "human.describe": lambda p: humanlevel.describe(self.conn, int(p["level"])),
            "human.opponent": lambda p: humanlevel.opponent(self.conn, str(p.get("name", ""))),
            "human.game": self.human_game,
            "human.sweep": lambda p: self.start_sweep(),
            "guard.status": self.guard_status,
            "guard.tilt": self.guard_tilt,
        }

    @staticmethod
    async def _awrap(coro):
        try:
            return await coro
        except ValueError as e:
            raise RpcError(str(e)) from e

    @staticmethod
    def _wrap(fn, *args):
        try:
            return fn(*args)
        except ValueError as e:
            raise RpcError(str(e)) from e

    # Events ---------------------------------------------------------------------------------------
    async def broadcast(self, topic: str, data: Any) -> None:
        if not self.clients:
            return
        msg = json.dumps({"method": "event", "params": {"topic": topic, "data": data}})
        await asyncio.gather(*(c.send(msg) for c in list(self.clients)), return_exceptions=True)

    # Settings -------------------------------------------------------------------------------------
    def settings_get(self, _p=None) -> dict[str, Any]:
        s = db.all_settings(self.conn)
        return {
            "chesscom_username": s.get("chesscom_username", ""),
            "lichess_username": s.get("lichess_username", ""),
            "training_start": s.get("training_start"),
            "weekly_hours": s.get("weekly_hours", config.PLANNER_WEEKLY_HOURS),
            "rest_days": s.get("rest_days", config.PLANNER_REST_DAYS),
            "stage_override": s.get("stage_override"),
            "fairplay_lock": bool(s.get("fairplay_lock", False)),
            "fairplay_reason": s.get("fairplay_reason"),
            "has_lichess_token": bool(self.secrets.get("lichess_token")),
            "has_anthropic_key": bool(self.secrets.get("anthropic_key")),
            "engine": {"workers": config.BATCH.workers, "nodes": config.BATCH.nodes,
                       "deep_nodes": config.BATCH.deep_nodes},
        }

    async def settings_set(self, p: dict[str, Any]) -> dict[str, Any]:
        bad = set(p) - USER_SETTINGS
        if bad:
            raise RpcError(f"unknown settings: {', '.join(sorted(bad))}")
        with db.tx(self.conn):
            for k, v in p.items():
                db.set_setting(self.conn, k, v.strip() if isinstance(v, str) else v)
        out = self.settings_get()
        await self.broadcast("settings", out)
        return out

    def set_secrets(self, secrets: dict[str, str]) -> None:
        self.secrets.update({k: v for k, v in secrets.items() if isinstance(v, str)})

    async def fairplay_set(self, p: dict[str, Any]) -> dict[str, Any]:
        await self.apply_lock(bool(p.get("locked")), "manual")
        return self.settings_get()

    async def apply_lock(self, locked: bool, reason: str) -> None:
        """Turn the fair-play lock on or off. On: every engine and Maia stops, not just the panels."""
        with db.tx(self.conn):
            db.set_setting(self.conn, "fairplay_lock", locked)
            db.set_setting(self.conn, "fairplay_reason", reason if locked else None)
        if locked:
            await self.job.halt()
            await self.live.stop()
            self.maia.unload()
            self.spar_maia.unload()
            if self.sweep_task and not self.sweep_task.done():
                self.sweep_task.cancel()
        await self.broadcast("settings", self.settings_get())

    def _locked(self) -> bool:
        return bool(db.get_setting(self.conn, "fairplay_lock", False))

    # Import ---------------------------------------------------------------------------------------
    async def import_start(self, _p=None) -> dict[str, Any]:
        if self.import_task and not self.import_task.done():
            return self.import_state
        s = self.settings_get()
        if not s["chesscom_username"] and not s["lichess_username"]:
            raise RpcError("Add a Chess.com or Lichess username first.")
        self.import_state = {"state": "running", "platform": None, "stored": 0, "results": []}
        self.import_task = asyncio.create_task(self._import(s))
        return self.import_state

    async def _import(self, s: dict[str, Any]) -> None:
        async def progress(d: dict[str, Any]) -> None:
            self.import_state = {**self.import_state, **d, "state": "running"}
            await self.broadcast("import", self.import_state)

        results, errors = [], []
        for platform, user in (("chesscom", s["chesscom_username"]), ("lichess", s["lichess_username"])):
            if not user:
                continue
            try:
                if platform == "chesscom":
                    results.append(await importers.import_chesscom(self.conn, user, progress))
                else:
                    results.append(await importers.import_lichess(
                        self.conn, user, self.secrets.get("lichess_token"), progress))
            except importers.ImportError_ as e:
                errors.append(str(e))
            except Exception as e:  # network trouble: keep what was stored, report the rest
                log.exception("import failed")
                errors.append(f"{'Chess.com' if platform == 'chesscom' else 'Lichess'}: {e.__class__.__name__}: {e}")
        self.import_state = {"state": "error" if errors and not results else "done", "results": results,
                             "errors": errors, "stored": sum(r["stored"] for r in results),
                             "finished_at": int(time.time())}
        await self.broadcast("import", self.import_state)
        if results and not self._locked() and db.get_setting(self.conn, "auto_analyse", True):
            self.job.start()

    # Analysis -------------------------------------------------------------------------------------
    def analysis_start(self, _p=None) -> dict[str, Any]:
        if self._locked():
            raise RpcError("The fair-play lock is on. Turn it off when your game is finished.")
        self.job.start()
        return self.job.status()

    def analysis_pause(self, _p=None) -> dict[str, Any]:
        self.job.pause()
        return self.job.status()

    # Train ----------------------------------------------------------------------------------------
    async def _endgame_move(self, uci: str) -> dict[str, Any]:
        if self._locked():
            raise RpcError("The fair-play lock is on. Finish your live game first.")
        try:
            return await self.endgames.move(uci)
        except RuntimeError as e:  # tablebase unreachable
            raise RpcError(str(e)) from e

    async def human_game(self, p: dict[str, Any]) -> dict[str, Any]:
        """Human-level labels for both sides of a game, plus the pooled profile of the opponent."""
        if self._locked():
            raise RpcError("The fair-play lock is on. Finish your live game first.")
        gid = int(p["game_id"])
        await humanlevel.ensure_game(self.conn, self.maia, gid)
        g = self.conn.execute("SELECT opp_name FROM games WHERE id = ?", (gid,)).fetchone()
        return {"sides": humanlevel.game_sides(self.conn, gid),
                "opponent": humanlevel.opponent(self.conn, g["opp_name"]) if g and g["opp_name"] else None,
                "scale": humanlevel.personal_scale(self.conn)}

    def start_sweep(self) -> dict[str, Any]:
        if self._locked():
            raise RpcError("The fair-play lock is on.")
        if self.sweep_task is None or self.sweep_task.done():
            self.sweep_task = asyncio.create_task(
                humanlevel.sweep(self.conn, self.maia, self._locked, lambda d: self.broadcast("human", d)))
        return {"running": True}

    async def _analysis_event(self, d: dict[str, Any]) -> None:
        await self.broadcast("analysis", d)
        if d.get("state") == "done" and not self._locked():
            self.start_sweep()  # once games are analysed, fit how human-like each side played

    async def _game_ended(self) -> None:
        await self.import_start()

    async def auto_import(self) -> None:
        while True:
            await asyncio.sleep(config.AUTO_IMPORT_MIN * 60)
            s = self.settings_get()
            if s["chesscom_username"] or s["lichess_username"]:
                try:
                    await self.import_start()
                except RpcError:
                    pass

    # Game Lab and guardrails --------------------------------------------------------------------
    async def live_analyse(self, fen: str, nodes: int):
        await self.live.start()
        return await self.live.analyse(fen, nodes)

    def lab_import_pgn(self, p: dict[str, Any]) -> dict[str, Any]:
        try:
            meta = games.meta_from_pgn(str(p.get("pgn", "")), str(p.get("color", "")))
        except ValueError as e:
            raise RpcError(str(e)) from e
        gid = games.store(self.conn, meta)
        if gid is None:
            row = self.conn.execute("SELECT id FROM games WHERE platform = 'pgn' AND platform_id = ?",
                                    (meta.platform_id,)).fetchone()
            if row is None:
                raise RpcError("That PGN couldn't be read as a standard game.")
            gid = row[0]
        return self._wrap(self.lab.open, gid)

    def guard_status(self, _p=None) -> dict[str, Any]:
        return {"stop_loss": guardrails.stop_loss(self.conn), "lichess": self.watcher.last,
                "fairplay_lock": self._locked(), "fairplay_reason": db.get_setting(self.conn, "fairplay_reason")}

    async def guard_tilt(self, p: dict[str, Any]) -> dict[str, Any]:
        guardrails.set_tilt(self.conn, bool(p.get("on", True)))
        out = self.guard_status()
        await self.broadcast("guard", out)
        return out

    # Solve ----------------------------------------------------------------------------------------
    async def solve_move(self, p: dict[str, Any]) -> dict[str, Any]:
        try:
            return await self.solver.move(int(p["item_id"]), str(p["uci"]), p.get("confidence"), p.get("line"),
                                          p.get("ms"))
        except (KeyError, ValueError) as e:
            raise RpcError(str(e)) from e

    async def live_check(self, fen: str, uci: str) -> int | None:
        """Centipawns your move loses against the best move, for grading your own positions.
        None (exact answers only) while the fair-play lock is on."""
        if self._locked():
            return None
        await self.live.start()
        board = chess.Board(fen)
        mover_white = board.turn == chess.WHITE
        nodes = self.live.budget.nodes
        best, _, _ = await self.live.analyse(fen, nodes)
        board.push_uci(uci)
        if board.is_checkmate():
            return 0
        after, _, _ = await self.live.analyse(board.fen(), nodes)
        sign = 1 if mover_white else -1
        return max(0, sign * best.clamped() - sign * after.clamped())

    # Mirror ---------------------------------------------------------------------------------------
    def mirror_summary(self, p: dict[str, Any]) -> dict[str, Any]:
        """Counts and the recent-games list. Deliberately no per-move answers: your blunder positions
        become Solve items, so Mirror shows where errors happened, never what the right move was."""
        c = self.conn
        limit = min(int(p.get("limit", 60)), 200)
        recent = c.execute(
            f"""SELECT g.id, g.platform, g.url, g.played_at, g.time_class, g.time_control, g.rated, g.my_color,
                  g.my_rating, g.opp_rating, g.opp_name, g.result, g.termination, g.opening, g.ply_count,
                  g.analysed_at IS NOT NULL analysed,
                  (SELECT COUNT(*) FROM moves m WHERE m.game_id = g.id AND m.color = g.my_color
                     AND m.class = 'blunder') blunders,
                  (SELECT COUNT(*) FROM moves m WHERE m.game_id = g.id AND m.color = g.my_color
                     AND m.class = 'mistake') mistakes
                FROM games g ORDER BY g.played_at DESC LIMIT {limit}"""
        ).fetchall()
        totals = c.execute(
            """SELECT COUNT(*) games, SUM(platform = 'chesscom') chesscom, SUM(platform = 'lichess') lichess,
                 MIN(played_at) first, MAX(played_at) last FROM games"""
        ).fetchone()
        return {"totals": dict(totals), "recent": [dict(r) for r in recent], "pools": metrics.pools(c),
                "analysis": self.job.status(), "import": self.import_state}

    # Dispatch -------------------------------------------------------------------------------------
    async def dispatch(self, raw: str) -> str | None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return json.dumps({"id": None, "error": {"code": -32700, "message": "parse error"}})
        mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
        fn = self.methods.get(method)
        if fn is None:
            return json.dumps({"id": mid, "error": {"code": -32601, "message": f"unknown method {method}"}})
        try:
            result = fn(params)
            if asyncio.iscoroutine(result):
                result = await result
            return json.dumps({"id": mid, "result": result})
        except RpcError as e:
            return json.dumps({"id": mid, "error": {"code": e.code, "message": str(e)}})
        except Exception as e:
            log.exception("method %s failed", method)
            return json.dumps({"id": mid, "error": {"code": -32603, "message": f"{e.__class__.__name__}: {e}"}})

    async def handle(self, ws: ServerConnection, token: str) -> None:
        path = ws.request.path if ws.request else ""
        if path != f"/?t={token}":
            await ws.close(code=4401, reason="bad token")
            return
        self.clients.add(ws)
        try:
            async for raw in ws:
                reply = await self.dispatch(raw if isinstance(raw, str) else raw.decode())
                if reply is not None:
                    await ws.send(reply)
        except websockets.ConnectionClosed:
            pass
        finally:
            self.clients.discard(ws)

    def shutdown_now(self, reason: str) -> None:
        print(f"brain: shutting down ({reason})", file=sys.stderr, flush=True)
        self.pool.kill_now()
        self.live.kill_now()
        try:
            self.conn.close()
        except Exception:
            pass
        os._exit(0)


def _lifelines(brain: Brain, loop: asyncio.AbstractEventLoop, watch_stdin: bool) -> None:
    parent = os.getppid()

    def stdin_watch() -> None:
        # Later lines may carry updated secrets (the user changed a token in Settings).
        for line in sys.stdin:
            try:
                msg = json.loads(line)
                if isinstance(msg.get("secrets"), dict):
                    loop.call_soon_threadsafe(brain.set_secrets, msg["secrets"])
                    loop.call_soon_threadsafe(
                        lambda: asyncio.ensure_future(brain.broadcast("settings", brain.settings_get())))
            except (json.JSONDecodeError, AttributeError):
                pass
        brain.shutdown_now("stdin EOF")

    def ppid_watch() -> None:
        while True:
            if os.getppid() != parent:
                brain.shutdown_now("parent changed")
            time.sleep(0.5)

    if watch_stdin:
        threading.Thread(target=stdin_watch, daemon=True).start()
        threading.Thread(target=ppid_watch, daemon=True).start()
    signal.signal(signal.SIGTERM, lambda *_: brain.shutdown_now("SIGTERM"))
    signal.signal(signal.SIGINT, lambda *_: brain.shutdown_now("SIGINT"))


async def serve(port: int, token: str, secrets: dict[str, str], watch_stdin: bool) -> None:
    conn = db.connect()
    brain = Brain(conn, secrets)
    brain.watcher.start()
    brain.auto_task = asyncio.create_task(brain.auto_import())
    _lifelines(brain, asyncio.get_running_loop(), watch_stdin)
    async with websockets.serve(lambda ws: brain.handle(ws, token), "127.0.0.1", port, max_size=2**22):
        print(f"brain: ready on {port}", file=sys.stderr, flush=True)
        await asyncio.Future()
