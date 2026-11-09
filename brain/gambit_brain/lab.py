"""Game Lab: engine-locked post-mortems.

You annotate the game and log 1–3 critical moments first. Only then does the brain compute and send
Stockfish's view, Maia at your level against a stronger level, and your time use against what was at
stake. The session is time-boxed and closes with 1–3 lessons; your moments become Solve positions.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from collections.abc import Awaitable, Callable
from typing import Any

import chess

from . import config, humanlevel, solve
from .analysis import classify
from .chesslib import Eval, epd
from .db import tx
from .maia import Maia, band_fit, nearest_level

Analyse = Callable[[str, int], Awaitable[tuple[Eval, list[str], int]]]
Emit = Callable[[dict[str, Any]], Awaitable[None]]
MIN = 60


class LabError(ValueError):
    pass


def _san_line(fen: str, ucis: list[str], limit: int = 6) -> list[str]:
    b, out = chess.Board(fen), []
    for u in ucis[:limit]:
        m = chess.Move.from_uci(u)
        if m not in b.legal_moves:
            break
        out.append(b.san(m))
        b.push(m)
    return out


def playing_elo(conn: sqlite3.Connection, game: sqlite3.Row | None = None) -> int:
    """Your rating for Maia: this game's, else your latest rated game's, else the default."""
    if game is not None and game["my_rating"]:
        return int(game["my_rating"])
    row = conn.execute("SELECT my_rating FROM games WHERE rated = 1 AND my_rating IS NOT NULL "
                       "ORDER BY played_at DESC LIMIT 1").fetchone()
    return int(row[0]) if row else config.DEFAULT_PLAYING_ELO


class Lab:
    def __init__(self, conn: sqlite3.Connection, analyse: Analyse, maia: Maia, locked: Callable[[], bool], emit: Emit):
        self.conn, self.analyse, self.maia, self.locked, self.emit = conn, analyse, maia, locked, emit
        self._unlocking: set[int] = set()

    # Listing ----------------------------------------------------------------------------------------
    def games(self, limit: int = 40) -> dict[str, Any]:
        rows = self.conn.execute(
            """SELECT g.id, g.platform, g.played_at, g.time_class, g.time_control, g.my_color, g.my_rating,
                      g.opp_name, g.opp_rating, g.result, g.opening, g.ply_count,
                      s.id AS session_id, s.unlocked_at, s.closed_at
               FROM games g LEFT JOIN lab_sessions s ON s.game_id = g.id
               ORDER BY g.played_at DESC LIMIT ?""", (min(limit, 200),)).fetchall()
        open_ = self.conn.execute(
            "SELECT game_id FROM lab_sessions WHERE closed_at IS NULL ORDER BY started_at DESC LIMIT 1").fetchone()
        return {"games": [dict(r) for r in rows], "open_game_id": open_[0] if open_ else None,
                "timebox_min": config.LAB_TIMEBOX_MIN}

    # A session ------------------------------------------------------------------------------------
    def _session(self, session_id: int) -> sqlite3.Row:
        s = self.conn.execute("SELECT * FROM lab_sessions WHERE id = ?", (session_id,)).fetchone()
        if s is None:
            raise LabError("That post-mortem doesn't exist.")
        return s

    def _state(self, s: sqlite3.Row) -> str:
        if s["closed_at"]:
            return "closed"
        if time.time() - s["started_at"] > config.LAB_TIMEBOX_MIN * MIN:
            return "expired"
        return "revealed" if s["unlocked_at"] else "annotate"

    def open(self, game_id: int) -> dict[str, Any]:
        g = self.conn.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()
        if g is None:
            raise LabError("That game isn't in your library.")
        s = self.conn.execute("SELECT * FROM lab_sessions WHERE game_id = ?", (game_id,)).fetchone()
        if s is None:
            other = self.conn.execute(
                "SELECT game_id FROM lab_sessions WHERE closed_at IS NULL AND game_id != ?", (game_id,)).fetchone()
            if other:
                raise LabError("Another post-mortem is still open. Close it with its lessons first.")
            with tx(self.conn):
                self.conn.execute("INSERT INTO lab_sessions (game_id, started_at) VALUES (?, ?)",
                                  (game_id, int(time.time())))
            s = self.conn.execute("SELECT * FROM lab_sessions WHERE game_id = ?", (game_id,)).fetchone()
        return self.view(s["id"])

    def view(self, session_id: int) -> dict[str, Any]:
        s = self._session(session_id)
        g = self.conn.execute("SELECT * FROM games WHERE id = ?", (s["game_id"],)).fetchone()
        moves = self.conn.execute(
            "SELECT ply, san, uci, color, clock_ms, spent_ms FROM moves WHERE game_id = ? ORDER BY ply",
            (g["id"],)).fetchall()
        first = self.conn.execute("SELECT fen_before FROM moves WHERE game_id = ? AND ply = 1", (g["id"],)).fetchone()
        state = self._state(s)
        lessons = [r["text"] for r in self.conn.execute(
            "SELECT text FROM lessons WHERE source = 'lab' AND ref = ? ORDER BY id", (str(s["id"]),))]
        return {
            "session": {"id": s["id"], "state": state, "started_at": s["started_at"],
                        "unlocked": bool(s["unlocked_at"]),
                        "closed_at": s["closed_at"], "timebox_min": config.LAB_TIMEBOX_MIN,
                        "warn_min": config.LAB_SOFT_WARNING_MIN, "max_moments": config.LAB_MAX_MOMENTS,
                        "max_lessons": config.LAB_MAX_LESSONS, "unlocking": s["id"] in self._unlocking},
            "game": {"id": g["id"], "platform": g["platform"], "url": g["url"], "played_at": g["played_at"],
                     "time_class": g["time_class"], "time_control": g["time_control"], "my_color": g["my_color"],
                     "my_rating": g["my_rating"], "opp_name": g["opp_name"], "opp_rating": g["opp_rating"],
                     "result": g["result"], "termination": g["termination"], "opening": g["opening"],
                     "start_fen": first["fen_before"] if first else chess.STARTING_FEN,
                     "moves": [dict(m) for m in moves]},
            "notes": json.loads(s["notes"]),
            "moments": [dict(m) for m in self.conn.execute(
                "SELECT ply, note, candidate FROM lab_moments WHERE session_id = ? ORDER BY ply", (s["id"],))],
            # Solve first: nothing from the engine or Maia until you've unlocked.
            "reveal": json.loads(s["reveal"]) if s["unlocked_at"] and s["reveal"] else None,
            "lessons": lessons,
        }

    def _editable(self, s: sqlite3.Row) -> None:
        state = self._state(s)
        if state == "closed":
            raise LabError("This post-mortem is filed and closed.")
        if state == "expired":
            raise LabError("Time's up for annotating. Unlock the engine if you haven't, then file your lessons.")
        if s["unlocked_at"]:
            raise LabError("The engine is unlocked, so your own annotations are final.")

    def note(self, session_id: int, ply: int, text: str) -> dict[str, Any]:
        s = self._session(session_id)
        self._editable(s)
        notes = json.loads(s["notes"])
        if text.strip():
            notes[str(ply)] = text.strip()
        else:
            notes.pop(str(ply), None)
        with tx(self.conn):
            self.conn.execute("UPDATE lab_sessions SET notes = ? WHERE id = ?", (json.dumps(notes), session_id))
        return self.view(session_id)

    def moment(self, session_id: int, ply: int, note: str, candidate: str | None) -> dict[str, Any]:
        s = self._session(session_id)
        self._editable(s)
        if not note.strip():
            raise LabError("Say briefly what you were thinking at this moment.")
        n = self.conn.execute("SELECT COUNT(*) FROM lab_moments WHERE session_id = ? AND ply != ?",
                              (session_id, ply)).fetchone()[0]
        if n >= config.LAB_MAX_MOMENTS:
            raise LabError(f"Pick at most {config.LAB_MAX_MOMENTS} critical moments: the ones that decided the game.")
        if not self.conn.execute("SELECT 1 FROM moves WHERE game_id = ? AND ply = ?", (s["game_id"], ply)).fetchone():
            raise LabError("That move isn't in this game.")
        with tx(self.conn):
            self.conn.execute(
                """INSERT INTO lab_moments (session_id, ply, note, candidate, created_at) VALUES (?,?,?,?,?)
                   ON CONFLICT(session_id, ply) DO UPDATE SET note = excluded.note, candidate = excluded.candidate""",
                (session_id, ply, note.strip(), (candidate or "").strip() or None, int(time.time())))
        return self.view(session_id)

    def remove_moment(self, session_id: int, ply: int) -> dict[str, Any]:
        self._editable(self._session(session_id))
        with tx(self.conn):
            self.conn.execute("DELETE FROM lab_moments WHERE session_id = ? AND ply = ?", (session_id, ply))
        return self.view(session_id)

    # Unlock: compute the reveal ---------------------------------------------------------------------
    async def unlock(self, session_id: int) -> dict[str, Any]:
        s = self._session(session_id)
        if s["closed_at"]:
            raise LabError("This post-mortem is filed and closed.")
        if s["unlocked_at"]:
            return self.view(session_id)
        if self.locked():
            raise LabError("The fair-play lock is on. Finish your live game first.")
        n = self.conn.execute("SELECT COUNT(*) FROM lab_moments WHERE session_id = ?", (session_id,)).fetchone()[0]
        if n == 0 and self._state(s) != "expired":
            raise LabError("Log at least one critical moment before unlocking the engine.")
        if session_id in self._unlocking:
            return self.view(session_id)
        self._unlocking.add(session_id)
        try:
            reveal = await self._compute(s)
            with tx(self.conn):
                self.conn.execute("UPDATE lab_sessions SET reveal = ?, unlocked_at = ? WHERE id = ?",
                                  (json.dumps(reveal), int(time.time()), session_id))
        finally:
            self._unlocking.discard(session_id)
        return self.view(session_id)

    async def _ensure_evals(self, positions: dict[str, str], nodes: int, need_best: set[str],
                            label: str) -> dict[str, sqlite3.Row]:
        """Fill missing evaluations (and best moves where asked) with the live engine."""
        def load() -> dict[str, sqlite3.Row]:
            keys = list(positions)
            got: dict[str, sqlite3.Row] = {}
            for i in range(0, len(keys), 500):
                chunk = keys[i : i + 500]
                got.update({r["epd"]: r for r in self.conn.execute(
                    f"SELECT * FROM evals WHERE epd IN ({','.join('?' * len(chunk))})", chunk)})
            return got

        have = load()
        todo = [(e, f) for e, f in positions.items()
                if e not in have or (e in need_best and not have[e]["best_uci"] and have[e]["source"] != "terminal")]
        for i, (e, f) in enumerate(todo):
            if self.locked():
                raise LabError("The fair-play lock came on. Unlock again once your game is over.")
            board = chess.Board(f)
            if board.is_checkmate():
                ev, pv, used = Eval(mate=-1 if board.turn == chess.WHITE else 1), [], 0
            elif board.is_game_over():
                ev, pv, used = Eval(cp=0), [], 0
            else:
                ev, pv, used = await self.analyse(f, nodes)
            self.conn.execute(
                """INSERT INTO evals (epd, cp, mate, best_uci, pv, nodes, source, updated_at)
                   VALUES (?,?,?,?,?,?,'sf',?)
                   ON CONFLICT(epd) DO UPDATE SET cp=excluded.cp, mate=excluded.mate, best_uci=excluded.best_uci,
                     pv=excluded.pv, nodes=excluded.nodes, source='sf', updated_at=excluded.updated_at""",
                (e, ev.cp, ev.mate, pv[0] if pv else None, " ".join(pv), used, int(time.time())))
            if i % 5 == 0:
                await self.emit({"stage": label, "done": i + 1, "total": len(todo)})
        return load()

    async def _compute(self, s: sqlite3.Row) -> dict[str, Any]:
        g = self.conn.execute("SELECT * FROM games WHERE id = ?", (s["game_id"],)).fetchone()
        moves = self.conn.execute("SELECT * FROM moves WHERE game_id = ? ORDER BY ply", (g["id"],)).fetchall()
        mine = [m for m in moves if m["color"] == g["my_color"]]
        final = chess.Board(moves[-1]["fen_before"])
        final.push_uci(moves[-1]["uci"])
        positions = {m["epd_before"]: m["fen_before"] for m in moves}
        positions[epd(final)] = final.fen()
        await self.emit({"stage": "engine", "done": 0, "total": len(positions)})
        evals = await self._ensure_evals(positions, config.LAB_ENGINE_NODES, set(), "engine")

        def ev(key: str) -> Eval:
            r = evals[key]
            return Eval(r["cp"], r["mate"])

        rows = []
        for m in moves:
            before, after = ev(m["epd_before"]), ev(m["epd_after"])
            best = evals[m["epd_before"]]["best_uci"] == m["uci"]
            cp_loss, _, cls = classify(before, after, m["color"] == "white", best)
            rows.append({"ply": m["ply"], "san": m["san"], "uci": m["uci"], "color": m["color"], "cp_loss": cp_loss,
                         "class": cls, "spent_ms": m["spent_ms"], "clock_ms": m["clock_ms"]})

        # The engine's critical moments: your costliest errors.
        mine_rows = [r for r in rows if r["color"] == g["my_color"]]
        engine_plies = [r["ply"] for r in sorted(mine_rows, key=lambda r: -r["cp_loss"])
                        if r["cp_loss"] >= config.MISTAKE_CP][: config.LAB_CRITICAL_MOMENTS]
        your = {m["ply"]: m for m in self.conn.execute(
            "SELECT ply, note, candidate FROM lab_moments WHERE session_id = ?", (s["id"],))}
        # Best moves (and lines) for every moment either of you picked, deep enough to trust.
        wanted = {moves[p - 1]["epd_before"]: moves[p - 1]["fen_before"] for p in set(engine_plies) | set(your)}
        evals.update(await self._ensure_evals(wanted, config.LAB_ENGINE_NODES, set(wanted), "best moves"))
        for p in set(engine_plies) | set(your):
            m, r = moves[p - 1], rows[p - 1]
            e = evals[m["epd_before"]]
            r["best_san"] = _san_line(m["fen_before"], [e["best_uci"]], 1)[0] if e["best_uci"] else None
            r["best_line"] = _san_line(m["fen_before"], (e["pv"] or "").split())
            r["best_uci"] = e["best_uci"]

        evals_series = [ev(m["epd_before"]).clamped() for m in moves] + [ev(epd(final)).clamped()]

        maia_part = None
        human = None
        if not self.locked():
            await self.emit({"stage": "maia", "done": 0, "total": len(mine)})
            maia_part = await asyncio.to_thread(self._maia, g, moves)
            try:
                await humanlevel.ensure_game(self.conn, self.maia, g["id"])
                human = {"sides": humanlevel.game_sides(self.conn, g["id"]),
                         "opponent": humanlevel.opponent(self.conn, g["opp_name"]) if g["opp_name"] else None}
            except Exception:  # a bonus, like Maia itself
                human = None

        # Time against what was at stake: your error size or the opponent's error you could punish.
        time_rows = []
        for r in mine_rows:
            prev = rows[r["ply"] - 2] if r["ply"] >= 2 else None
            stake = max(r["cp_loss"], prev["cp_loss"] if prev else 0)
            spent_s = None if r["spent_ms"] is None else round(r["spent_ms"] / 1000, 1)
            time_rows.append({"ply": r["ply"], "spent_s": spent_s, "stake": stake,
                              "critical": stake >= config.MISTAKE_CP})
        spent = [t for t in time_rows if t["spent_s"] is not None]
        total = sum(t["spent_s"] for t in spent) or None
        crit = [t for t in spent if t["critical"]]

        return {
            "evals": evals_series,
            "moves": rows,
            "engine_moments": engine_plies,
            "your_moments": sorted(your),
            "found": sorted(set(engine_plies) & set(your)),
            "maia": maia_part,
            "human": human,
            "time": {"moves": time_rows,
                     "critical_share_of_moves": round(len(crit) / len(spent), 3) if spent else None,
                     "critical_share_of_time": round(sum(t["spent_s"] for t in crit) / total, 3) if total else None},
        }

    def _maia(self, g: sqlite3.Row, moves: list[sqlite3.Row]) -> dict[str, Any] | None:
        try:
            me = playing_elo(self.conn, g)
            opp = int(g["opp_rating"] or me)
            mine = {m["ply"] for m in moves if m["color"] == g["my_color"]}
            prof = self.maia.profile_game(moves[0]["fen_before"], [m["uci"] for m in moves], mine, me, opp)
        except Exception as e:  # Maia is a bonus: the post-mortem works without it
            return {"error": f"{e.__class__.__name__}: {e}"}
        levels = list(config.MAIA_LEVELS)
        k_self = nearest_level(me)
        k_high = nearest_level(me + config.MAIA_HIGHER_BY)
        out = []
        for p in prof:
            fen = moves[p.ply - 1]["fen_before"]
            out.append({"ply": p.ply, "p_self": round(p.probs[k_self], 3), "p_high": round(p.probs[k_high], 3),
                        "top_self": _san_line(fen, [p.tops[k_self]], 1)[0] if p.tops[k_self] else None,
                        "top_high": _san_line(fen, [p.tops[k_high]], 1)[0] if p.tops[k_high] else None})
        return {"self_level": levels[k_self], "high_level": levels[k_high], "rating_used": me,
                "fit": band_fit(prof), "moves": out}

    # Exploring after the unlock, with the reassurance limiter --------------------------------------
    async def engine(self, session_id: int, fen: str) -> dict[str, Any]:
        s = self._session(session_id)
        if not s["unlocked_at"]:
            raise LabError("The engine is locked until you've logged your critical moments.")
        if self.locked():
            raise LabError("The fair-play lock is on. Finish your live game first.")
        board = chess.Board(fen)
        if not board.is_valid():
            raise LabError("That position isn't legal.")
        checks = json.loads(s["checks"])
        key = epd(board)
        checks[key] = checks.get(key, 0) + 1
        with tx(self.conn):
            self.conn.execute("UPDATE lab_sessions SET checks = ? WHERE id = ?", (json.dumps(checks), session_id))
        if board.is_game_over():
            return {"cp": 0, "mate": None, "line": [], "checks": checks[key], "nudge": False}
        ev, pv, _ = await self.analyse(fen, config.LAB_ENGINE_NODES)
        return {"cp": ev.cp, "mate": ev.mate, "line": _san_line(fen, pv), "checks": checks[key],
                "nudge": checks[key] >= config.ENGINE_CHECK_NUDGE}

    # Close: lessons, Solve items, file shut ----------------------------------------------------------
    def close(self, session_id: int, lessons: list[str]) -> dict[str, Any]:
        s = self._session(session_id)
        if s["closed_at"]:
            raise LabError("This post-mortem is already filed and closed.")
        lessons = [x.strip() for x in lessons if x and x.strip()]
        if not 1 <= len(lessons) <= config.LAB_MAX_LESSONS:
            raise LabError(f"File between 1 and {config.LAB_MAX_LESSONS} lessons.")
        reveal = json.loads(s["reveal"]) if s["reveal"] else None
        now = int(time.time())
        with tx(self.conn):
            for text in lessons:
                self.conn.execute("INSERT INTO lessons (source, ref, text, created_at) VALUES ('lab', ?, ?, ?)",
                                  (str(session_id), text, now))
            # Your moments and the engine's become Solve positions, where you got them wrong.
            if reveal:
                for p in set(reveal["your_moments"]) | set(reveal["engine_moments"]):
                    r = reveal["moves"][p - 1]
                    if r.get("best_uci") and r["cp_loss"] >= config.MISTAKE_CP and r["uci"] != r["best_uci"]:
                        m = self.conn.execute("SELECT motifs, epd_before FROM moves WHERE game_id = ? AND ply = ?",
                                              (s["game_id"], p)).fetchone()
                        e = self.conn.execute("SELECT pv FROM evals WHERE epd = ?", (m["epd_before"],)).fetchone()
                        solve.add_own_item(self.conn, s["game_id"], p, r["best_uci"], e["pv"] if e else None,
                                           m["motifs"])
            self.conn.execute("UPDATE lab_sessions SET closed_at = ? WHERE id = ?", (now, session_id))
        return self.view(session_id)
