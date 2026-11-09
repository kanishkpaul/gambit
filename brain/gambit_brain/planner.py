"""Planner: today's training, split by the stage allocations, with rest days and variety.

The stage follows your rolling rating, so allocations shift on their own as you improve. Time done
is measured from what you actually did (Solve sets, post-mortems, endgames, games), never typed in.
There are no streaks and no quotas: a plan you didn't finish is just information.
"""

from __future__ import annotations

import sqlite3
import time
from datetime import date, datetime, timedelta
from typing import Any

from . import config, metrics
from .db import get_setting

ACTIVITIES: dict[str, dict[str, Any]] = {
    "solving": {"label": "Solve", "view": "solve", "why": "Retrieval on your own blunders and the themes you miss."},
    "analysis": {"label": "Game Lab", "view": "lab", "why": "One post-mortem of a recent game, your analysis first."},
    "endgames": {"label": "Endgames", "view": "endgames", "why": "Theoretical positions against perfect defence."},
    "master_games": {"label": "Master games", "view": None, "fallback": "solving",
                     "why": "Arrives in v0.5; its time goes to Solve until then."},
    "openings": {"label": "Openings", "view": None, "fallback": "analysis",
                 "why": "Arrives in v0.5; its time goes to Game Lab until then."},
    "play": {"label": "Serious play", "view": "sparring",
             "why": "Long games, online or against Maia. Games are tests; play after you study."},
}
STUDY_ORDER = ["solving", "endgames", "analysis"]


def _day_bounds(d: date) -> tuple[int, int]:
    start = int(datetime(d.year, d.month, d.day).timestamp())
    return start, start + 86_400


def stage(conn: sqlite3.Connection) -> dict[str, Any]:
    override = get_setting(conn, "stage_override", None)
    pool = metrics.default_pool(conn)
    basis = None
    s = 1
    if pool:
        ratings = [r[0] for r in conn.execute(
            "SELECT my_rating FROM games WHERE platform = ? AND time_class = ? AND rated = 1 AND my_rating IS NOT NULL "
            "ORDER BY played_at DESC LIMIT ?", (pool["platform"], pool["time_class"], config.ROLLING_WINDOW))]
        if ratings:
            mean = sum(ratings) / len(ratings)
            bounds = config.STAGE_THRESHOLDS.get(pool["platform"], config.STAGE_THRESHOLDS["chesscom"])
            s = 1 + sum(mean >= b for b in bounds)
            basis = {**pool, "rating": round(mean), "games": len(ratings), "next_at": next((b for b in bounds if mean < b), None)}
    if override in (1, 2, 3, 4):
        return {"stage": override, "auto": s, "basis": basis, "override": True}
    return {"stage": s, "auto": s, "basis": basis, "override": False}


def minutes_done(conn: sqlite3.Connection, d: date) -> dict[str, int]:
    lo, hi = _day_bounds(d)
    now = int(time.time())
    out = {k: 0.0 for k in ACTIVITIES}
    for r in conn.execute("SELECT started_at, ended_at, timebox_min FROM solve_sessions WHERE started_at >= ? AND started_at < ?",
                          (lo, hi)):
        end = min(r["ended_at"] or now, r["started_at"] + r["timebox_min"] * 60)
        out["solving"] += max(0, end - r["started_at"]) / 60
    for r in conn.execute("SELECT started_at, closed_at FROM lab_sessions WHERE started_at >= ? AND started_at < ?", (lo, hi)):
        end = min(r["closed_at"] or now, r["started_at"] + config.LAB_TIMEBOX_MIN * 60)
        out["analysis"] += max(0, end - r["started_at"]) / 60
    out["endgames"] += (conn.execute("SELECT COALESCE(SUM(ms), 0) FROM reviews WHERE mode = 'endgame' AND at >= ? AND at < ?",
                                     (lo, hi)).fetchone()[0]) / 60_000
    for g in conn.execute(
            """SELECT g.id, g.base_s, g.ply_count, (SELECT SUM(spent_ms) FROM moves m WHERE m.game_id = g.id) AS spent
               FROM games g WHERE g.played_at >= ? AND g.played_at < ? AND g.platform != 'pgn'""", (lo, hi)):
        if g["spent"]:
            out["play"] += g["spent"] / 60_000
        elif g["base_s"]:
            out["play"] += (2 * g["base_s"] * 0.6) / 60
    return {k: round(v) for k, v in out.items()}


def _day_minutes(conn: sqlite3.Connection, d: date) -> int:
    rest = set(get_setting(conn, "rest_days", config.PLANNER_REST_DAYS))
    if d.weekday() in rest:
        return 0
    weekly = float(get_setting(conn, "weekly_hours", config.PLANNER_WEEKLY_HOURS))
    days = max(1, 7 - len(rest))
    return int(round(weekly * 60 / days / 5) * 5)


def plan_for(conn: sqlite3.Connection, d: date, st: int) -> list[dict[str, Any]]:
    total = _day_minutes(conn, d)
    if total == 0:
        return []
    alloc = dict(config.STAGE_ALLOCATIONS[st])
    for key, meta in ACTIVITIES.items():
        if meta.get("fallback") and key in alloc:
            alloc[meta["fallback"]] = alloc.get(meta["fallback"], 0) + alloc.pop(key)
    # Variety: the study blocks rotate daily; play always comes last.
    k = d.toordinal() % len(STUDY_ORDER)
    order = STUDY_ORDER[k:] + STUDY_ORDER[:k] + ["play"]
    blocks = []
    for key in order:
        share = alloc.get(key, 0)
        if share:
            minutes = int(round(total * share / 100 / 5) * 5)
            if minutes:
                blocks.append({"activity": key, "label": ACTIVITIES[key]["label"], "view": ACTIVITIES[key]["view"],
                               "why": ACTIVITIES[key]["why"], "minutes": minutes})
    return blocks


def today(conn: sqlite3.Connection, now: float | None = None) -> dict[str, Any]:
    d = date.fromtimestamp(now or time.time())
    st = stage(conn)
    blocks = plan_for(conn, d, st["stage"])
    done = minutes_done(conn, d)
    for b in blocks:
        b["done"] = done.get(b["activity"], 0)
    monday = d - timedelta(days=d.weekday())
    week = []
    for i in range(7):
        day = monday + timedelta(days=i)
        planned = sum(b["minutes"] for b in plan_for(conn, day, st["stage"]))
        week.append({"date": day.isoformat(), "weekday": day.weekday(), "planned": planned,
                     "done": sum(minutes_done(conn, day).values()) if day <= d else None, "today": day == d})
    folded = [ACTIVITIES[k]["label"] for k in ("master_games", "openings") if config.STAGE_ALLOCATIONS[st["stage"]].get(k)]
    return {
        "date": d.isoformat(), "rest_day": not blocks, "stage": st, "blocks": blocks,
        "planned": sum(b["minutes"] for b in blocks), "done": sum(done.values()), "week": week,
        "weekly_hours": get_setting(conn, "weekly_hours", config.PLANNER_WEEKLY_HOURS),
        "rest_days": get_setting(conn, "rest_days", config.PLANNER_REST_DAYS),
        "allocation": config.STAGE_ALLOCATIONS[st["stage"]], "folded": folded,
    }
