"""The one-time history audit: a time-boxed look at everything you've played, then filed and closed.

The report is snapshotted when the audit starts. After the time-box the report is hidden and only
filing (1–3 lessons) remains. Once filed it never reopens.
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections import Counter, defaultdict
from typing import Any

from . import config
from .db import tx

MIN = 60


def build_report(conn: sqlite3.Connection) -> dict[str, Any]:
    games = conn.execute(
        "SELECT id, played_at, time_class, platform, my_color, result, termination, opening, analysed_at "
        "FROM games ORDER BY played_at"
    ).fetchall()
    if not games:
        return {"empty": True}
    analysed_ids = {g["id"] for g in games if g["analysed_at"]}
    my_moves = conn.execute(
        """SELECT m.game_id, m.class, m.phase, m.motifs, m.time_trouble, m.ply
           FROM moves m JOIN games g ON g.id = m.game_id
           WHERE g.analysed_at IS NOT NULL AND m.color = g.my_color AND m.class IN ('blunder','mistake')"""
    ).fetchall()
    blunders = [m for m in my_moves if m["class"] == "blunder"]

    by_tc: dict[str, dict[str, Any]] = {}
    for tc in sorted({g["time_class"] for g in games}):
        gs = [g for g in games if g["time_class"] == tc]
        an = [g for g in gs if g["id"] in analysed_ids]
        bl = sum(1 for m in blunders if m["game_id"] in {g["id"] for g in an})
        by_tc[tc] = {
            "games": len(gs),
            "score": round(sum(1 if g["result"] == "win" else 0.5 if g["result"] == "draw" else 0 for g in gs)
                           / len(gs), 3),
            "blunders_per_game": round(bl / len(an), 2) if an else None,
        }

    motifs = Counter(t for m in blunders for t in json.loads(m["motifs"] or "[]"))
    phases = Counter(m["phase"] for m in blunders)
    first_blunder_move = [
        min(m["ply"] for m in blunders if m["game_id"] == gid) for gid in {m["game_id"] for m in blunders}
    ]

    # Openings by family ("Sicilian Defense: Najdorf" → "Sicilian Defense").
    fam: dict[tuple[str, str], list[sqlite3.Row]] = defaultdict(list)
    for g in games:
        if g["opening"]:
            fam[(g["opening"].split(":")[0].strip(), g["my_color"])].append(g)
    openings = []
    for (name, color), gs in fam.items():
        if len(gs) < config.AUDIT_MIN_OPENING_GAMES:
            continue
        score = sum(1 if g["result"] == "win" else 0.5 if g["result"] == "draw" else 0 for g in gs) / len(gs)
        openings.append({"name": name, "color": color, "games": len(gs), "score": round(score, 3)})
    openings.sort(key=lambda o: o["score"])

    # Tilt: score in games started within 2 h after two straight losses (same time class), vs overall.
    after_two: list[float] = []
    last: dict[str, list[tuple[int, float]]] = defaultdict(list)
    for g in games:
        prev = last[g["time_class"]]
        s = 1 if g["result"] == "win" else 0.5 if g["result"] == "draw" else 0
        if len(prev) >= 2 and all(p[1] == 0 for p in prev[-2:]) and g["played_at"] - prev[-1][0] < 2 * 3600:
            after_two.append(s)
        prev.append((g["played_at"], s))
    overall = sum(1 if g["result"] == "win" else 0.5 if g["result"] == "draw" else 0 for g in games) / len(games)
    losses = [g for g in games if g["result"] == "loss"]

    return {
        "empty": False,
        "games": len(games),
        "analysed": len(analysed_ids),
        "first": games[0]["played_at"],
        "last": games[-1]["played_at"],
        "by_time_class": by_tc,
        "blunders": len(blunders),
        "motifs": [{"motif": k, "count": v} for k, v in motifs.most_common(8)],
        "phases": {p: phases.get(p, 0) for p in ("opening", "middlegame", "endgame")},
        "time_trouble_share": round(sum(m["time_trouble"] for m in blunders) / len(blunders), 3) if blunders else None,
        "first_blunder_move_median": sorted(first_blunder_move)[len(first_blunder_move) // 2] // 2 + 1
        if first_blunder_move else None,
        "openings_worst": openings[:3],
        "openings_best": openings[::-1][:3],
        "losses_on_time": round(sum(g["termination"] == "timeout" for g in losses) / len(losses), 3)
        if losses else None,
        "tilt": {"overall": round(overall, 3), "after_two_losses": round(sum(after_two) / len(after_two), 3)
                 if after_two else None, "games_after_two_losses": len(after_two)},
    }


def state(conn: sqlite3.Connection) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM audit WHERE id = 1").fetchone()
    box = {"timebox_min": config.AUDIT_TIMEBOX_MIN, "warn_min": config.AUDIT_SOFT_WARNING_MIN,
           "max_lessons": config.AUDIT_MAX_LESSONS}
    if row is None:
        return {"state": "none", **box}
    lessons = json.loads(row["lessons"] or "[]")
    if row["filed_at"]:
        return {"state": "filed", "started_at": row["started_at"], "filed_at": row["filed_at"],
                "lessons": lessons, "report": json.loads(row["report"]), **box}
    elapsed = time.time() - row["started_at"]
    if elapsed > config.AUDIT_TIMEBOX_MIN * MIN:
        return {"state": "expired", "started_at": row["started_at"], "lessons": lessons, **box}
    return {"state": "open", "started_at": row["started_at"], "report": json.loads(row["report"]),
            "lessons": lessons, "now": int(time.time()), **box}


def start(conn: sqlite3.Connection) -> dict[str, Any]:
    if conn.execute("SELECT 1 FROM audit WHERE id = 1").fetchone():
        return state(conn)
    report = build_report(conn)
    if report.get("empty"):
        raise ValueError("Import some games before starting the audit.")
    with tx(conn):
        conn.execute("INSERT INTO audit (id, started_at, report) VALUES (1, ?, ?)",
                     (int(time.time()), json.dumps(report)))
    return state(conn)


def file(conn: sqlite3.Connection, lessons: list[str]) -> dict[str, Any]:
    lessons = [s.strip() for s in lessons if s and s.strip()]
    if not 1 <= len(lessons) <= config.AUDIT_MAX_LESSONS:
        raise ValueError(f"File between 1 and {config.AUDIT_MAX_LESSONS} lessons.")
    row = conn.execute("SELECT filed_at FROM audit WHERE id = 1").fetchone()
    if row is None:
        raise ValueError("The audit hasn't started.")
    if row["filed_at"]:
        raise ValueError("The audit is already filed and closed.")
    with tx(conn):
        conn.execute("UPDATE audit SET lessons = ?, filed_at = ? WHERE id = 1",
                     (json.dumps(lessons), int(time.time())))
    return state(conn)
