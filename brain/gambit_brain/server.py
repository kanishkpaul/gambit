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

import websockets
from websockets.asyncio.server import ServerConnection

from . import analysis, audit, config, db, importers, metrics

log = logging.getLogger("gambit.brain")

Handler = Callable[[dict[str, Any]], Awaitable[Any] | Any]

USER_SETTINGS = {"chesscom_username", "lichess_username", "training_start"}


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
        self.job = analysis.BatchAnalysis(conn, self.pool, lambda d: self.broadcast("analysis", d))
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
        }

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
            "fairplay_lock": bool(s.get("fairplay_lock", False)),
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
        locked = bool(p.get("locked"))
        with db.tx(self.conn):
            db.set_setting(self.conn, "fairplay_lock", locked)
        if locked:
            await self.job.halt()  # kills the Stockfish pool, not just the panels
        out = self.settings_get()
        await self.broadcast("settings", out)
        return out

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
    _lifelines(brain, asyncio.get_running_loop(), watch_stdin)
    async with websockets.serve(lambda ws: brain.handle(ws, token), "127.0.0.1", port, max_size=2**22):
        print(f"brain: ready on {port}", file=sys.stderr, flush=True)
        await asyncio.Future()
