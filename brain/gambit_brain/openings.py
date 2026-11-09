"""Openings: a narrow repertoire built from your own games.

For every position in your first eight moves where it's your turn, your repertoire move is the one
you play most (or one you pin). gambit flags repertoire moves the engine dislikes, shows where each
recent game left your preparation, and drills only the positions you've actually gone wrong in.
Time on openings is capped by the stage allocation in the planner.
"""

from __future__ import annotations

import random
import sqlite3
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import Any

import chess
from fsrs import Rating

from . import config
from .chesslib import Eval, epd
from .db import tx
from .solve import update_card


def rebuild(conn: sqlite3.Connection) -> dict[str, Any]:
    """Recount your moves per position; pinned moves are kept as you set them."""
    rows = conn.execute(
        """SELECT m.epd_before, m.fen_before, m.uci, m.san, m.ply, g.my_color, g.played_at
           FROM moves m JOIN games g ON g.id = m.game_id
           WHERE m.ply <= ? AND m.color = g.my_color AND g.platform != 'sparring'""", (config.OPENING_PLIES,)).fetchall()
    tally: dict[tuple[str, str], Counter] = defaultdict(Counter)
    info: dict[tuple[str, str, str], tuple[str, str, int, int]] = {}
    for r in rows:
        key = (r["my_color"], r["epd_before"])
        tally[key][r["uci"]] += 1
        prev = info.get((*key, r["uci"]))
        if prev is None or r["played_at"] > prev[3]:
            info[(*key, r["uci"])] = (r["fen_before"], r["san"], r["ply"], r["played_at"])
    pinned = {(r["color"], r["epd"]) for r in conn.execute("SELECT color, epd FROM repertoire WHERE source = 'pinned'")}
    kept = 0
    with tx(conn):
        conn.execute("DELETE FROM repertoire WHERE source = 'games'")
        for (color, epd), counter in tally.items():
            if (color, epd) in pinned:
                continue
            uci, n = max(counter.items(), key=lambda kv: (kv[1], info[(color, epd, kv[0])][3]))
            if n < config.OPENING_MIN_GAMES:
                continue
            fen, san, ply, _ = info[(color, epd, uci)]
            conn.execute("INSERT INTO repertoire (color, epd, fen, uci, san, source, games, ply) VALUES (?,?,?,?,?,'games',?,?)",
                         (color, epd, fen, uci, san, n, ply))
            kept += 1
    return {"positions": kept, "pinned": len(pinned)}


def pin(conn: sqlite3.Connection, color: str, fen: str, san: str) -> dict[str, Any]:
    board = chess.Board(fen)
    try:
        move = board.parse_san(san)
    except ValueError as e:
        raise ValueError(f"“{san}” isn't a legal move here.") from e
    with tx(conn):
        conn.execute(
            """INSERT INTO repertoire (color, epd, fen, uci, san, source, games, ply) VALUES (?,?,?,?,?,'pinned',0,?)
               ON CONFLICT(color, epd) DO UPDATE SET uci = excluded.uci, san = excluded.san, source = 'pinned'""",
            (color, epd(board), fen, move.uci(), board.san(move), (board.fullmove_number - 1) * 2 + (0 if board.turn else 1) + 1))
    return {"pinned": board.san(move)}


def _evals(conn: sqlite3.Connection, epds: list[str]) -> dict[str, sqlite3.Row]:
    out: dict[str, sqlite3.Row] = {}
    for i in range(0, len(epds), 500):
        chunk = epds[i : i + 500]
        out.update({r["epd"]: r for r in conn.execute(f"SELECT * FROM evals WHERE epd IN ({','.join('?' * len(chunk))})", chunk)})
    return out


def overview(conn: sqlite3.Connection) -> dict[str, Any]:
    rep = conn.execute("SELECT * FROM repertoire ORDER BY color, ply").fetchall()
    # Leaks: repertoire moves the batch analysis says cost real material.
    afters = {}
    for r in rep:
        b = chess.Board(r["fen"])
        b.push_uci(r["uci"])
        afters[r["epd"]] = b.epd(en_passant="legal")
    ev = _evals(conn, [r["epd"] for r in rep] + list(afters.values()))
    leaks = []
    for r in rep:
        before, after = ev.get(r["epd"]), ev.get(afters[r["epd"]])
        if not before or not after:
            continue
        sign = 1 if r["color"] == "white" else -1
        loss = sign * Eval(before["cp"], before["mate"]).clamped() - sign * Eval(after["cp"], after["mate"]).clamped()
        if loss >= config.OPENING_LEAK_CP:
            best = None
            if before["best_uci"]:
                b = chess.Board(r["fen"])
                mv = chess.Move.from_uci(before["best_uci"])
                best = b.san(mv) if mv in b.legal_moves else None
            leaks.append({"color": r["color"], "fen": r["fen"], "san": r["san"], "ply": r["ply"], "games": r["games"],
                          "cost": round(loss / 100, 1), "engine": best, "pinned": r["source"] == "pinned"})
    return {"positions": {"white": sum(r["color"] == "white" for r in rep), "black": sum(r["color"] == "black" for r in rep)},
            "lines": lines(conn), "leaks": sorted(leaks, key=lambda x: -x["cost"])[:12],
            "departures": departures(conn), "drill_due": _due_count(conn), "plies": config.OPENING_PLIES}


def lines(conn: sqlite3.Connection, max_lines: int = 12) -> dict[str, list[dict[str, Any]]]:
    """Your main lines per colour: follow your move, branch on the replies you've met most."""
    rep = {(r["color"], r["epd"]): r for r in conn.execute("SELECT * FROM repertoire")}
    replies: dict[str, Counter] = defaultdict(Counter)
    for r in conn.execute(
            """SELECT m.epd_before, m.uci FROM moves m JOIN games g ON g.id = m.game_id
               WHERE m.ply <= ? AND m.color != g.my_color""", (config.OPENING_PLIES,)):
        replies[r["epd_before"]][r["uci"]] += 1
    out: dict[str, list[dict[str, Any]]] = {"white": [], "black": []}
    for color in ("white", "black"):
        stack: list[tuple[chess.Board, list[str], int]] = [(chess.Board(), [], 0)]
        while stack and len(out[color]) < max_lines:
            board, sans, count = stack.pop()
            ended = True
            if (board.turn == chess.WHITE) == (color == "white"):
                r = rep.get((color, board.epd(en_passant="legal")))
                if r and len(sans) < config.OPENING_PLIES:
                    nb = board.copy()
                    nb.push_uci(r["uci"])
                    stack.append((nb, [*sans, r["san"]], max(count, r["games"])))
                    ended = False
            else:
                top = replies.get(board.epd(en_passant="legal"), Counter()).most_common(3)
                for uci, n in reversed(top):
                    if n < config.OPENING_MIN_GAMES or len(sans) >= config.OPENING_PLIES:
                        continue
                    nb = board.copy()
                    nb.push_uci(uci)
                    stack.append((nb, [*sans, board.san(chess.Move.from_uci(uci))], n))
                    ended = False
            if ended and len(sans) >= 2:
                out[color].append({"moves": sans, "games": count})
    return out


def departures(conn: sqlite3.Connection, limit: int = 15) -> list[dict[str, Any]]:
    """Where each recent game left your preparation."""
    rep = {(r["color"], r["epd"]): r for r in conn.execute("SELECT * FROM repertoire")}
    out = []
    for g in conn.execute("SELECT id, my_color, opp_name, played_at, result FROM games WHERE platform != 'sparring' "
                          "ORDER BY played_at DESC LIMIT ?", (limit,)).fetchall():
        moves = conn.execute("SELECT ply, epd_before, uci, san, color FROM moves WHERE game_id = ? AND ply <= ? ORDER BY ply",
                             (g["id"], config.OPENING_PLIES)).fetchall()
        event = None
        for m in moves:
            if m["color"] != g["my_color"]:
                continue
            r = rep.get((g["my_color"], m["epd_before"]))
            if r is None:
                event = {"kind": "new", "ply": m["ply"], "played": m["san"]}
                break
            if r["uci"] != m["uci"]:
                event = {"kind": "deviated", "ply": m["ply"], "played": m["san"], "usual": r["san"]}
                break
        out.append({"game_id": g["id"], "opp_name": g["opp_name"], "played_at": g["played_at"], "result": g["result"],
                    "color": g["my_color"], "event": event})
    return out


# ── Drill: only the positions you've actually gone wrong in ───────────────────────────────────


def sync_drill(conn: sqlite3.Connection) -> int:
    """Positions where a recent game deviated from your repertoire become drill items."""
    rep = {(r["color"], r["epd"]): r for r in conn.execute("SELECT * FROM repertoire")}
    now, added = int(time.time()), 0
    with tx(conn):
        for d in departures(conn, limit=200):
            ev = d["event"]
            if not ev or ev["kind"] != "deviated":
                continue
            m = conn.execute("SELECT epd_before FROM moves WHERE game_id = ? AND ply = ?", (d["game_id"], ev["ply"])).fetchone()
            r = rep.get((d["color"], m["epd_before"]))
            if r is None:
                continue
            prev = conn.execute("SELECT fen_before, uci FROM moves WHERE game_id = ? AND ply = ?",
                                (d["game_id"], ev["ply"] - 1)).fetchone()
            fen, lead = (prev["fen_before"], prev["uci"]) if prev else (r["fen"], None)
            cur = conn.execute(
                """INSERT OR IGNORE INTO items (kind, ref, fen, lead_uci, solution, themes, created_at)
                   VALUES ('opening', ?, ?, ?, ?, ?, ?)""", (f"{d['color']}:{r['epd']}", fen, lead, r["uci"], "[]", now))
            added += cur.rowcount
        # A pinned change of mind supersedes an old answer.
        for (color, epd), r in rep.items():
            conn.execute("UPDATE items SET solution = ? WHERE kind = 'opening' AND ref = ?", (r["uci"], f"{color}:{epd}"))
    return added


def _due_count(conn: sqlite3.Connection) -> int:
    sync_drill(conn)
    now = int(time.time())
    return conn.execute(
        """SELECT COUNT(*) FROM items i LEFT JOIN cards c ON c.item_id = i.id
           WHERE i.kind = 'opening' AND (c.due IS NULL OR c.due <= ?)""", (now,)).fetchone()[0]


def drill_next(conn: sqlite3.Connection, rng: random.Random | None = None) -> dict[str, Any] | None:
    sync_drill(conn)
    now = int(time.time())
    rows = conn.execute(
        """SELECT i.* FROM items i LEFT JOIN cards c ON c.item_id = i.id
           WHERE i.kind = 'opening' AND (c.due IS NULL OR c.due <= ?) ORDER BY c.due IS NOT NULL, c.due""", (now,)).fetchall()
    if not rows:
        return None
    r = rows[0]
    b = chess.Board(r["fen"])
    if r["lead_uci"]:
        b.push_uci(r["lead_uci"])
    return {"item_id": r["id"], "fen": r["fen"], "lead_uci": r["lead_uci"], "turn": "white" if b.turn else "black",
            "remaining": len(rows)}


def drill_answer(conn: sqlite3.Connection, item_id: int, uci: str) -> dict[str, Any]:
    r = conn.execute("SELECT * FROM items WHERE id = ? AND kind = 'opening'", (item_id,)).fetchone()
    if r is None:
        raise ValueError("That position isn't in your drill.")
    b = chess.Board(r["fen"])
    if r["lead_uci"]:
        b.push_uci(r["lead_uci"])
    try:
        mv = chess.Move.from_uci(uci)
    except ValueError as e:
        raise ValueError("That isn't a move.") from e
    if mv not in b.legal_moves:
        raise ValueError("That move isn't legal here.")
    correct = uci == r["solution"]
    now = datetime.now(UTC)
    with tx(conn):
        card = update_card(conn, item_id, Rating.Good if correct else Rating.Again, now)
        conn.execute("INSERT INTO reviews (item_id, at, mode, first_seen, correct, answer, grade) VALUES (?,?,'opening',0,?,?,?)",
                     (item_id, int(now.timestamp()), int(correct), uci, int(Rating.Good if correct else Rating.Again)))
    answer = chess.Move.from_uci(r["solution"])
    return {"correct": correct, "answer_san": b.san(answer), "answer_uci": r["solution"],
            "next_review_days": round(max(0.0, (card.due - now).total_seconds() / 86_400), 2)}

