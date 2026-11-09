"""Solve: retrieval practice on your own blunders and on library puzzles, scheduled with FSRS.

Solve first, reveal later: the client only ever receives a position. Solutions stay here until the
item is finished, and grading happens here.
"""

from __future__ import annotations

import json
import math
import random
import sqlite3
import time
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import chess
from fsrs import Card, Rating, Scheduler

from . import config
from .chesslib import Eval
from .db import get_setting, set_setting, tx

SCHEDULER = Scheduler(
    desired_retention=config.FSRS_DESIRED_RETENTION,
    learning_steps=tuple(timedelta(minutes=m) for m in config.FSRS_LEARNING_STEPS_MIN),
    relearning_steps=tuple(timedelta(minutes=m) for m in config.FSRS_RELEARNING_STEPS_MIN),
)
CONFIDENCE = ("guess", "unsure", "sure")
# Solve schedules puzzles and your own positions; endgames share the card table but not the sets.
SOLVABLE = "JOIN items i ON i.id = c.item_id WHERE i.kind IN ('puzzle', 'own')"

# Live check for own positions: (fen, uci) → centipawns lost against the best move, or None if unavailable.
LiveCheck = Callable[[str, str], Awaitable[int | None]]


# ── Own positions → items ────────────────────────────────────────────────────────────────────────


def _mirror_uci(uci: str) -> str:
    m = chess.Move.from_uci(uci)
    return chess.Move(chess.square_mirror(m.from_square), chess.square_mirror(m.to_square), m.promotion).uci()


def sync_own_items(conn: sqlite3.Connection) -> int:
    """Turn every deep-checked blunder of yours into an item, plus a colour-mirrored twin.

    The item starts one move earlier, with the opponent's move as the lead-in: noticing what that move
    threatened is usually the whole point.
    """
    rows = conn.execute(
        """SELECT m.game_id, m.ply, m.motifs, e.best_uci, e.pv, e.cp, e.mate, m.color
           FROM moves m
           JOIN games g ON g.id = m.game_id
           JOIN evals e ON e.epd = m.epd_before
           WHERE m.class = 'blunder' AND m.color = g.my_color AND g.deep_at IS NOT NULL
             AND e.best_uci IS NOT NULL
             AND NOT EXISTS (SELECT 1 FROM items i WHERE i.kind = 'own' AND i.ref = m.game_id || ':' || m.ply)"""
    ).fetchall()
    added = 0
    with tx(conn):
        for r in rows:
            sign = 1 if r["color"] == "white" else -1
            if sign * Eval(r["cp"], r["mate"]).clamped() < config.OWN_MIN_EVAL_BEFORE:
                continue
            added += add_own_item(conn, r["game_id"], r["ply"], r["best_uci"], r["pv"], r["motifs"])
    return added


def add_own_item(conn: sqlite3.Connection, game_id: int, ply: int, best_uci: str, pv: str | None,
                 motifs: str | None) -> int:
    """One position from your game (ply = your move) and its colour-mirrored twin. Call inside a transaction.

    The item starts one move earlier, with the opponent's move as the lead-in. Returns items added.
    """
    m = conn.execute(
        """SELECT m.fen_before, prev.fen_before AS prev_fen, prev.uci AS prev_uci FROM moves m
           LEFT JOIN moves prev ON prev.game_id = m.game_id AND prev.ply = m.ply - 1
           WHERE m.game_id = ? AND m.ply = ?""", (game_id, ply)).fetchone()
    if m is None:
        return 0
    fen, lead = (m["prev_fen"], m["prev_uci"]) if m["prev_fen"] else (m["fen_before"], None)
    themes, ref, now = motifs or "[]", f"{game_id}:{ply}", int(time.time())
    pv = pv or best_uci
    before = conn.total_changes
    conn.execute(
        """INSERT OR IGNORE INTO items (kind, ref, fen, lead_uci, solution, reveal, themes, created_at)
           VALUES ('own', ?, ?, ?, ?, ?, ?, ?)""",
        (ref, fen, lead, best_uci, pv, themes, now),
    )
    conn.execute(
        """INSERT OR IGNORE INTO items (kind, ref, fen, lead_uci, solution, reveal, themes, created_at)
           VALUES ('own', ?, ?, ?, ?, ?, ?, ?)""",
        (ref + ":m", chess.Board(fen).mirror().fen(), lead and _mirror_uci(lead), _mirror_uci(best_uci),
         " ".join(_mirror_uci(u) for u in pv.split()), themes, now),
    )
    return conn.total_changes - before


# ── Choosing what to solve ───────────────────────────────────────────────────────────────────────


def solve_rating(conn: sqlite3.Connection) -> dict[str, float]:
    return get_setting(conn, "solve_rating", None) or {"r": config.SOLVE_START_RATING, "n": 0}


def theme_weights(conn: sqlite3.Connection) -> dict[str, float]:
    weights = dict(config.THEME_WEIGHTS)
    motifs = Counter(
        t for (m,) in conn.execute(
            "SELECT m.motifs FROM moves m JOIN games g ON g.id = m.game_id "
            "WHERE m.class = 'blunder' AND m.color = g.my_color AND m.motifs IS NOT NULL")
        for t in json.loads(m)
    )
    total = sum(motifs.values())
    for motif, n in motifs.items():
        for theme in config.MOTIF_THEMES.get(motif, []):
            weights[theme] = weights.get(theme, 0) + config.MOTIF_BOOST * n / total
    return weights


def _pick_puzzles(conn: sqlite3.Connection, n: int, target: int, rng: random.Random) -> list[sqlite3.Row]:
    weights = theme_weights(conn)
    themes, w = list(weights), list(weights.values())
    picked: list[sqlite3.Row] = []
    seen_ids: set[str] = set()
    for _ in range(n * 3):
        if len(picked) >= n:
            break
        theme = rng.choices(themes, w)[0]
        for widen in (1, 2, 4):
            lo, hi = target - config.SOLVE_RATING_WINDOW * widen, target + config.SOLVE_RATING_WINDOW * widen
            row = conn.execute(
                """SELECT p.* FROM puzzles p
                   WHERE p.rating BETWEEN ? AND ? AND (' ' || p.themes || ' ') LIKE ?
                     AND NOT EXISTS (SELECT 1 FROM items i WHERE i.kind = 'puzzle' AND i.ref = p.id)
                   ORDER BY random() LIMIT 1""",
                (lo, hi, f"% {theme} %"),
            ).fetchone()
            if row and row["id"] not in seen_ids:
                picked.append(row)
                seen_ids.add(row["id"])
                break
    return picked


def _puzzle_item(conn: sqlite3.Connection, p: sqlite3.Row) -> int:
    moves = p["moves"].split()
    conn.execute(
        """INSERT OR IGNORE INTO items (kind, ref, fen, lead_uci, solution, themes, rating, created_at)
           VALUES ('puzzle', ?, ?, ?, ?, ?, ?, ?)""",
        (p["id"], p["fen"], moves[0], " ".join(moves[1:]), json.dumps(p["themes"].split()), p["rating"],
         int(time.time())),
    )
    return conn.execute("SELECT id FROM items WHERE kind = 'puzzle' AND ref = ?", (p["id"],)).fetchone()[0]


def _primary_theme(themes: list[str]) -> str:
    for t in themes:
        if t in config.THEME_WEIGHTS or t in config.MOTIF_THEMES:
            return t
    return themes[0] if themes else ""


def interleave(items: list[dict[str, Any]], rng: random.Random) -> list[dict[str, Any]]:
    """Mix the set so the same theme or the same side to move rarely comes twice in a row."""
    pool = items[:]
    rng.shuffle(pool)
    out: list[dict[str, Any]] = []
    def clash(x: dict[str, Any], prev: dict[str, Any] | None) -> int:
        if prev is None:
            return 0
        return 2 * (x["theme"] == prev["theme"]) + (x["turn"] == prev["turn"])

    while pool:
        prev = out[-1] if out else None
        best = min(range(len(pool)), key=lambda i: clash(pool[i], prev))
        out.append(pool.pop(best))
    return out


def _turn_after_lead(fen: str, lead: str | None) -> str:
    b = chess.Board(fen)
    if lead:
        b.push_uci(lead)
    return "white" if b.turn == chess.WHITE else "black"


def build_set(conn: sqlite3.Connection, mode: str, rng: random.Random | None = None) -> list[int]:
    rng = rng or random.Random()
    now = int(time.time())
    sr = solve_rating(conn)["r"]
    ids: list[int] = []
    if mode == "speed":
        target = int(sr + config.SPEED_RATING_OFFSET)
        with tx(conn):
            ids = [_puzzle_item(conn, p) for p in _pick_puzzles(conn, 60, target, rng)]
    elif mode == "calibration":
        with tx(conn):
            ids = [_puzzle_item(conn, p) for p in _calibration_puzzles(conn, sr, rng)]
    else:
        sync_own_items(conn)
        due = [r[0] for r in conn.execute(
            "SELECT c.item_id FROM cards c JOIN items i ON i.id = c.item_id "
            "WHERE c.due <= ? AND i.kind IN ('puzzle', 'own') ORDER BY c.due LIMIT ?", (now, config.SOLVE_MAX_DUE))]
        new_own = [r[0] for r in conn.execute(
            """SELECT i.id FROM items i
               WHERE i.kind = 'own' AND NOT EXISTS (SELECT 1 FROM cards c WHERE c.item_id = i.id)
               ORDER BY i.created_at DESC, i.id LIMIT ?""", (config.SOLVE_MAX_NEW_OWN,))]
        ids = due + new_own
        # Puzzles picked for an earlier set that you never reached come back first.
        room = config.SOLVE_SET_SIZE - len(ids)
        if room > 0:
            ids += [r[0] for r in conn.execute(
                """SELECT i.id FROM items i WHERE i.kind = 'puzzle'
                     AND NOT EXISTS (SELECT 1 FROM cards c WHERE c.item_id = i.id)
                     AND NOT EXISTS (SELECT 1 FROM reviews r WHERE r.item_id = i.id)
                   ORDER BY i.id LIMIT ?""", (room,))]
        room = config.SOLVE_SET_SIZE - len(ids)
        if room > 0:
            with tx(conn):
                ids += [_puzzle_item(conn, p)
                        for p in _pick_puzzles(conn, room, int(sr + config.SOLVE_TARGET_OFFSET), rng)]
    rows = {r["id"]: r for r in _items(conn, ids)}
    meta = [{"id": i, "theme": _primary_theme(json.loads(rows[i]["themes"])),
             "turn": _turn_after_lead(rows[i]["fen"], rows[i]["lead_uci"])} for i in ids if i in rows]
    return [m["id"] for m in interleave(meta, rng)] if mode == "standard" else [m["id"] for m in meta]


def _calibration_puzzles(conn: sqlite3.Connection, sr: float, rng: random.Random) -> list[sqlite3.Row]:
    """A fresh set spread evenly from your rating − spread to + spread, any theme, never seen before."""
    n, spread = config.CALIBRATION_SIZE, config.CALIBRATION_SPREAD
    out: list[sqlite3.Row] = []
    for k in range(n):
        target = sr - spread + k * (2 * spread / max(1, n - 1))
        chosen = [o["id"] for o in out]
        for widen in (40, 80, 160, 320):
            row = conn.execute(
                f"""SELECT p.* FROM puzzles p WHERE p.rating BETWEEN ? AND ?
                      AND NOT EXISTS (SELECT 1 FROM items i WHERE i.kind = 'puzzle' AND i.ref = p.id)
                      AND p.id NOT IN ({",".join("?" * len(chosen)) or "''"})
                    ORDER BY random() LIMIT 1""", (target - widen, target + widen, *chosen)).fetchone()
            if row:
                out.append(row)
                break
    rng.shuffle(out)
    return out


def performance_rating(results: list[tuple[int, bool]]) -> int | None:
    """The rating at which your expected score against these puzzle ratings equals your actual score."""
    if not results:
        return None
    score = sum(ok for _, ok in results)
    ratings = [r for r, _ in results]
    if score == 0:
        return min(ratings) - 400
    if score == len(results):
        return max(ratings) + 400
    lo, hi = 0.0, 4000.0
    for _ in range(60):
        mid = (lo + hi) / 2
        exp = sum(1 / (1 + 10 ** ((r - mid) / 400)) for r in ratings)
        lo, hi = (mid, hi) if exp < score else (lo, mid)
    return round((lo + hi) / 2)


def _items(conn: sqlite3.Connection, ids: list[int]) -> list[sqlite3.Row]:
    if not ids:
        return []
    return conn.execute(f"SELECT * FROM items WHERE id IN ({','.join('?' * len(ids))})", ids).fetchall()


# ── Grading ──────────────────────────────────────────────────────────────────────────────────────


def grade(correct: bool, confidence: str | None, ms: int | None) -> Rating:
    if not correct:
        return Rating.Again
    if confidence == "guess":
        return Rating.Hard
    if confidence == "sure" and ms is not None and ms < config.FAST_SOLVE_MS:
        return Rating.Easy
    return Rating.Good


def update_card(conn: sqlite3.Connection, item_id: int, rating: Rating, at: datetime) -> Card:
    row = conn.execute("SELECT card FROM cards WHERE item_id = ?", (item_id,)).fetchone()
    card = Card.from_json(row[0]) if row else Card()
    card, _ = SCHEDULER.review_card(card, rating, at)
    conn.execute(
        "INSERT INTO cards (item_id, card, due) VALUES (?,?,?) "
        "ON CONFLICT(item_id) DO UPDATE SET card = excluded.card, due = excluded.due",
        (item_id, card.to_json(), int(card.due.timestamp())),
    )
    return card


def update_rating(conn: sqlite3.Connection, puzzle_rating: int, correct: bool) -> dict[str, float]:
    sr = solve_rating(conn)
    expected = 1 / (1 + 10 ** ((puzzle_rating - sr["r"]) / 400))
    k = config.SOLVE_K_EARLY if sr["n"] < config.SOLVE_K_EARLY_N else config.SOLVE_K
    sr = {"r": round(sr["r"] + k * ((1.0 if correct else 0.0) - expected), 1), "n": sr["n"] + 1}
    set_setting(conn, "solve_rating", sr)
    return sr


@dataclass
class Attempt:
    item: sqlite3.Row
    step: int = 0  # index into the solution of the move you're about to play
    answer: list[str] = field(default_factory=list)
    confidence: str | None = None
    line: str | None = None
    ms: int | None = None
    started: float = field(default_factory=time.monotonic)


@dataclass
class Session:
    id: int
    mode: str
    queue: list[int]
    started_at: float
    timebox_min: int
    pos: int = 0
    current: Attempt | None = None
    results: list[dict[str, Any]] = field(default_factory=list)


def _san_line(fen: str, ucis: list[str]) -> list[str]:
    b, out = chess.Board(fen), []
    for u in ucis:
        m = chess.Move.from_uci(u)
        if m not in b.legal_moves:
            break
        out.append(b.san(m))
        b.push(m)
    return out


class Solver:
    """Runs Solve sessions. One session at a time; state lives here, results in SQLite."""

    def __init__(self, conn: sqlite3.Connection, live_check: LiveCheck | None = None):
        self.conn, self.live_check = conn, live_check
        self.session: Session | None = None

    # Overview -------------------------------------------------------------------------------------
    def overview(self) -> dict[str, Any]:
        c, now = self.conn, int(time.time())
        sync_own_items(c)
        today = now - now % 86_400
        sr = solve_rating(c)
        return {
            "due": c.execute(f"SELECT COUNT(*) FROM cards c {SOLVABLE} AND c.due <= ?", (now,)).fetchone()[0],
            "due_later_today": c.execute(f"SELECT COUNT(*) FROM cards c {SOLVABLE} AND c.due > ? AND c.due < ?",
                                         (now, today + 86_400)).fetchone()[0],
            "new_own": c.execute("SELECT COUNT(*) FROM items i WHERE kind = 'own' "
                                 "AND NOT EXISTS (SELECT 1 FROM cards c WHERE c.item_id = i.id)").fetchone()[0],
            "library": c.execute("SELECT COUNT(*) FROM puzzles").fetchone()[0],
            "learning": c.execute(f"SELECT COUNT(*) FROM cards c {SOLVABLE}").fetchone()[0],
            "reviews_today": c.execute("SELECT COUNT(*) FROM reviews WHERE at >= ? AND mode IN ('standard', 'speed')",
                                       (today,)).fetchone()[0],
            "solve_rating": round(sr["r"]), "rated_attempts": sr["n"],
            "set_size": config.SOLVE_SET_SIZE, "timebox_min": config.SOLVE_TIMEBOX_MIN,
            "speed_timebox_min": config.SPEED_TIMEBOX_MIN, "session": self._session_info(),
        }

    def _session_info(self) -> dict[str, Any] | None:
        s = self.session
        if s is None:
            return None
        return {"id": s.id, "mode": s.mode, "total": len(s.queue), "index": s.pos,
                "started_at": int(time.time() - (time.monotonic() - s.started_at)), "timebox_min": s.timebox_min,
                "warn_min": config.SOLVE_SOFT_WARNING_MIN if s.mode == "standard" else None}

    # Sessions -------------------------------------------------------------------------------------
    def start(self, mode: str, rng: random.Random | None = None) -> dict[str, Any]:
        if mode not in ("standard", "speed", "calibration"):
            raise ValueError("unknown mode")
        if self.session:
            self.end()
        queue = build_set(self.conn, mode, rng)
        if not queue:
            raise ValueError("Nothing to solve yet. Import the puzzle library or analyse some games first.")
        timebox = {"standard": config.SOLVE_TIMEBOX_MIN, "speed": config.SPEED_TIMEBOX_MIN,
                   "calibration": config.CALIBRATION_SIZE * config.CALIBRATION_SECONDS // 60 + 5}[mode]
        with tx(self.conn):
            sid = self.conn.execute(
                "INSERT INTO solve_sessions (mode, started_at, timebox_min, planned) VALUES (?,?,?,?)",
                (mode, int(time.time()), timebox, len(queue))).lastrowid
        self.session = Session(sid, mode, queue, time.monotonic(), timebox)
        return self._session_info() or {}

    def _elapsed_min(self) -> float:
        return (time.monotonic() - self.session.started_at) / 60 if self.session else 0

    def next(self) -> dict[str, Any]:
        s = self.session
        if s is None:
            raise ValueError("No session is running.")
        if s.current is not None:  # e.g. the UI reloaded mid-item: hand back the same position
            return self._payload(s.current)
        if self._elapsed_min() >= s.timebox_min:
            return {"done": True, "reason": "timebox", "summary": self.end()}
        if s.pos >= len(s.queue):
            return {"done": True, "reason": "complete", "summary": self.end()}
        row = self.conn.execute("SELECT * FROM items WHERE id = ?", (s.queue[s.pos],)).fetchone()
        s.current = Attempt(row)
        return self._payload(s.current)

    def _payload(self, a: Attempt) -> dict[str, Any]:
        s = self.session
        assert s is not None
        # Deliberately no themes, source, rating or solution: sets are unlabelled until you answer.
        return {"done": False, "item_id": a.item["id"], "index": s.pos, "total": len(s.queue), "mode": s.mode,
                "fen": a.item["fen"], "lead_uci": a.item["lead_uci"],
                "played": a.answer, "replies": self._replies(a),
                "turn": _turn_after_lead(a.item["fen"], a.item["lead_uci"]),
                "elapsed_min": round(self._elapsed_min(), 2), "timebox_min": s.timebox_min,
                "time_limit_s": config.CALIBRATION_SECONDS if s.mode == "calibration" else None}

    @staticmethod
    def _replies(a: Attempt) -> list[str]:
        sol = a.item["solution"].split()
        return [sol[i] for i in range(1, a.step, 2)]

    async def move(self, item_id: int, uci: str, confidence: str | None = None, line: str | None = None,
                   ms: int | None = None) -> dict[str, Any]:
        s = self.session
        if s is None or s.current is None or s.current.item["id"] != item_id:
            raise ValueError("That position isn't the current one.")
        a = s.current
        item = a.item
        board = chess.Board(item["fen"])
        if item["lead_uci"]:
            board.push_uci(item["lead_uci"])
        sol = item["solution"].split()
        for u in sol[: a.step]:
            board.push_uci(u)
        try:
            move = chess.Move.from_uci(uci)
        except ValueError as e:
            raise ValueError("That isn't a move.") from e
        if move not in board.legal_moves:
            raise ValueError("That move isn't legal here.")
        if a.step == 0:
            a.confidence = confidence if confidence in CONFIDENCE else None
            a.line = (line or "").strip() or None
            a.ms = ms if ms is not None else int((time.monotonic() - a.started) * 1000)
        a.answer.append(uci)

        correct = uci == sol[a.step]
        if not correct:
            board.push(move)
            correct = board.is_checkmate()  # any mate solves a mating puzzle (Lichess's rule)
            board.pop()
        if s.mode == "calibration" and a.ms is not None and a.ms > (config.CALIBRATION_SECONDS + 2) * 1000:
            correct = False  # over the time limit: a calibration answer has to come in time
        elif not correct and item["kind"] == "own" and self.live_check is not None:
            lost = await self.live_check(board.fen(), uci)
            correct = lost is not None and lost <= config.OWN_ACCEPT_CP
        if not correct:
            return self._finish(a, False)
        if item["kind"] == "own" or uci != sol[a.step] or a.step + 1 >= len(sol):
            return self._finish(a, True)
        reply = sol[a.step + 1]
        a.step += 2
        if a.step >= len(sol):
            return self._finish(a, True)
        return {"result": "correct", "done": False, "reply_uci": reply}

    def skip(self, item_id: int) -> dict[str, Any]:
        """Time ran out on a calibration position: it counts as not solved."""
        s = self.session
        if s is None or s.current is None or s.current.item["id"] != item_id:
            raise ValueError("That position isn't the current one.")
        a = s.current
        a.ms = a.ms or int((time.monotonic() - a.started) * 1000)
        return self._finish(a, False)

    def _finish(self, a: Attempt, correct: bool) -> dict[str, Any]:
        s = self.session
        assert s is not None
        item, now = a.item, datetime.now(UTC)
        first = self.conn.execute("SELECT COUNT(*) FROM reviews WHERE item_id = ?", (item["id"],)).fetchone()[0] == 0
        rating = grade(correct, a.confidence, a.ms) if s.mode == "standard" else None
        card = None
        sr = None
        with tx(self.conn):
            if rating is not None:
                card = update_card(self.conn, item["id"], rating, now)
            if first and item["rating"] and s.mode == "standard":
                sr = update_rating(self.conn, item["rating"], correct)
            self.conn.execute(
                """INSERT INTO reviews (item_id, session_id, at, mode, first_seen, correct, confidence, answer, line,
                     ms, grade) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (item["id"], s.id, int(now.timestamp()), s.mode, int(first), int(correct), a.confidence,
                 " ".join(a.answer), a.line, a.ms, int(rating) if rating is not None else None),
            )
        confident_miss = not correct and a.confidence == "sure"
        s.results.append({"correct": correct, "confident_miss": confident_miss, "ms": a.ms, "kind": item["kind"],
                          "rating": item["rating"]})
        s.current = None
        s.pos += 1
        return {"result": "solved" if correct else "wrong", "done": True, "reveal": self._reveal(item, card, sr),
                "confident_miss": confident_miss}

    def _reveal(self, item: sqlite3.Row, card: Card | None, sr: dict[str, float] | None) -> dict[str, Any]:
        start = chess.Board(item["fen"])
        if item["lead_uci"]:
            start.push_uci(item["lead_uci"])
        line = (item["reveal"] or item["solution"]).split()
        source: dict[str, Any] = {"kind": item["kind"]}
        if item["kind"] == "own":
            game_id, ply, *mirrored = item["ref"].split(":")
            g = self.conn.execute("SELECT played_at, opp_name, url, time_class, platform FROM games WHERE id = ?",
                                  (int(game_id),)).fetchone()
            if g:
                source.update(dict(g), move_number=(int(ply) + 1) // 2, mirrored=bool(mirrored))
        else:
            p = self.conn.execute("SELECT game_url FROM puzzles WHERE id = ?", (item["ref"],)).fetchone()
            source.update(rating=item["rating"], id=item["ref"], url=f"https://lichess.org/training/{item['ref']}",
                          game_url=p["game_url"] if p else None)
        days = None
        if card is not None:
            days = max(0.0, (card.due - datetime.now(UTC)).total_seconds() / 86_400)
        return {
            "fen": start.fen(), "solution": line, "solution_san": _san_line(start.fen(), line),
            "themes": json.loads(item["themes"]), "source": source,
            "next_review_days": None if days is None else round(days, 2),
            "solve_rating": None if sr is None else round(sr["r"]),
        }

    def end(self) -> dict[str, Any]:
        s = self.session
        if s is None:
            return {}
        res = s.results
        with tx(self.conn):
            self.conn.execute("UPDATE solve_sessions SET ended_at = ? WHERE id = ?", (int(time.time()), s.id))
        times = sorted(r["ms"] for r in res if r["ms"] is not None and r["correct"])
        perf = None
        if s.mode == "calibration" and res:
            rated = [(r["rating"], r["correct"]) for r in res if r["rating"]]
            perf = performance_rating(rated)
            with tx(self.conn):
                self.conn.execute(
                    """INSERT INTO calibrations (session_id, started_at, finished_at, attempted, solved, performance, mean_rating)
                       VALUES (?,?,?,?,?,?,?)""",
                    (s.id, int(time.time() - self._elapsed_min() * 60), int(time.time()), len(res),
                     sum(r["correct"] for r in res), perf, round(sum(r for r, _ in rated) / len(rated)) if rated else None))
        summary = {
            "mode": s.mode, "attempted": len(res), "solved": sum(r["correct"] for r in res),
            "confident_misses": sum(r["confident_miss"] for r in res),
            "median_ms": times[len(times) // 2] if times else None,
            "minutes": math.ceil(self._elapsed_min()), "planned": len(s.queue),
            "solve_rating": round(solve_rating(self.conn)["r"]),
            "performance": perf,
        }
        self.session = None
        return summary
