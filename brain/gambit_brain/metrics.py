"""Slope: honest progress metrics. Rating against games played with the noise band, blunders per game,
clock profile, error phases and motifs, and Gate 0.
"""

from __future__ import annotations

import json
import sqlite3
import statistics
import time
from collections import Counter
from typing import Any

from . import config
from .db import get_setting

DAY = 86_400


def pools(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT platform, time_class, COUNT(*) n, SUM(rated) rated, MAX(played_at) last
           FROM games GROUP BY platform, time_class ORDER BY rated DESC"""
    ).fetchall()
    return [dict(r) for r in rows]


def default_pool(conn: sqlite3.Connection) -> dict[str, str] | None:
    """The pool to headline: the most-played serious time class, else the most-played pool."""
    ps = [p for p in pools(conn) if p["rated"]]
    if not ps:
        return None
    serious = [p for p in ps if p["time_class"] in config.SERIOUS_TIME_CLASSES and p["rated"] >= 20]
    best = max(serious or ps, key=lambda p: p["rated"])
    return {"platform": best["platform"], "time_class": best["time_class"]}


def _rolling(values: list[float], window: int) -> list[float]:
    out, acc = [], 0.0
    for i, v in enumerate(values):
        acc += v
        if i >= window:
            acc -= values[i - window]
        out.append(acc / min(i + 1, window))
    return out


def slope(conn: sqlite3.Connection, platform: str | None = None, time_class: str | None = None) -> dict[str, Any]:
    if platform is None or time_class is None:
        pool = default_pool(conn)
        if pool is None:
            return {"pools": pools(conn), "pool": None}
        platform, time_class = pool["platform"], pool["time_class"]
    sd = config.NOISE_SD.get(platform, 40)
    band = sd * config.NOISE_BAND_SDS
    w = config.ROLLING_WINDOW

    games = conn.execute(
        """SELECT id, played_at, my_rating, result, termination, analysed_at, base_s
           FROM games WHERE platform = ? AND time_class = ? ORDER BY played_at""",
        (platform, time_class),
    ).fetchall()
    rated = [g for g in conn.execute(
        "SELECT played_at, my_rating FROM games WHERE platform = ? AND time_class = ? AND rated = 1 "
        "AND my_rating IS NOT NULL ORDER BY played_at", (platform, time_class))]
    ratings = [r["my_rating"] for r in rated]
    means = _rolling(ratings, w)
    rating_series = [
        {"i": i + 1, "t": r["played_at"], "rating": r["my_rating"], "mean": round(m, 1),
         "lo": round(m - band, 1), "hi": round(m + band, 1)}
        for i, (r, m) in enumerate(zip(rated, means, strict=True))
    ]

    trend = None
    n = len(ratings)
    if n >= w + config.TREND_MIN_GAMES:
        span = min(config.TREND_LOOKBACK, n - w)
        delta = means[-1] - means[-1 - span]
        trend = {
            "from_i": n - span, "to_i": n, "from": round(means[-1 - span], 1), "to": round(means[-1], 1),
            "per_100": round(delta / span * 100, 1), "real": abs(delta) > band,
        }

    # Per-game error counts for analysed games (your moves only).
    per_game = {
        r["game_id"]: r for r in conn.execute(
            """SELECT m.game_id,
                 SUM(m.class = 'blunder') blunders, SUM(m.class = 'mistake') mistakes,
                 SUM(m.class = 'blunder' AND m.time_trouble) trouble_blunders
               FROM moves m JOIN games g ON g.id = m.game_id
               WHERE g.platform = ? AND g.time_class = ? AND g.analysed_at IS NOT NULL AND m.color = g.my_color
               GROUP BY m.game_id""", (platform, time_class))
    }
    analysed = [g for g in games if g["id"] in per_game]
    b_roll = _rolling([per_game[g["id"]]["blunders"] for g in analysed], w)
    m_roll = _rolling([per_game[g["id"]]["mistakes"] for g in analysed], w)
    error_series = [
        {"i": i + 1, "t": g["played_at"], "blunders": per_game[g["id"]]["blunders"],
         "blunders_mean": round(b, 3), "mistakes_mean": round(m, 3)}
        for i, (g, b, m) in enumerate(zip(analysed, b_roll, m_roll, strict=True))
    ]

    my_errors = conn.execute(
        """SELECT m.phase, m.motifs, m.time_trouble FROM moves m JOIN games g ON g.id = m.game_id
           WHERE g.platform = ? AND g.time_class = ? AND m.class = 'blunder' AND m.color = g.my_color""",
        (platform, time_class),
    ).fetchall()
    n_an = max(1, len(analysed))
    phases = Counter(r["phase"] for r in my_errors)
    motifs = Counter(t for r in my_errors for t in json.loads(r["motifs"] or "[]"))

    # Clock profile: clock left at your 30th move as a share of base time; losses on time.
    clock_rows = conn.execute(
        """SELECT m.clock_ms, g.base_s FROM moves m JOIN games g ON g.id = m.game_id
           WHERE g.platform = ? AND g.time_class = ? AND g.base_s > 0 AND m.color = g.my_color
             AND m.ply IN (59, 60) AND m.clock_ms IS NOT NULL""", (platform, time_class)).fetchall()
    shares = [r["clock_ms"] / 1000 / r["base_s"] for r in clock_rows]
    losses = [g for g in games if g["result"] == "loss"]
    clock = {
        "median_share_at_30": round(statistics.median(shares), 3) if shares else None,
        "games_reaching_30": len(shares),
        "loss_on_time_share": round(sum(g["termination"] == "timeout" for g in losses) / len(losses), 3)
        if losses else None,
        "time_trouble_blunder_share": round(sum(r["time_trouble"] for r in my_errors) / len(my_errors), 3)
        if my_errors else None,
    }

    return {
        "pools": pools(conn),
        "pool": {"platform": platform, "time_class": time_class},
        "noise": {"sd": sd, "band": band, "window": w},
        "rating": rating_series,
        "trend": trend,
        "errors": error_series,
        "phases": {p: round(phases.get(p, 0) / n_an, 3) for p in ("opening", "middlegame", "endgame")},
        "motifs": [{"motif": k, "count": v} for k, v in motifs.most_common()],
        "clock": clock,
        "gate0": gate0(conn, rated, means),
        "counts": {"games": len(games), "rated": n, "analysed": len(analysed)},
    }


def gate0(conn: sqlite3.Connection, rated: list[sqlite3.Row], means: list[float]) -> dict[str, Any]:
    start = get_setting(conn, "training_start")
    now = int(time.time())
    target = config.ORDINARY_ADULT_PER_YEAR
    if start is None or not rated:
        return {"state": "no_data", "target_per_year": target}
    days = (now - start) / DAY
    before = [m for r, m in zip(rated, means, strict=True) if r["played_at"] <= start]
    after = [m for r, m in zip(rated, means, strict=True) if r["played_at"] > start]
    out: dict[str, Any] = {"start": start, "days": round(days), "due_days": config.GATE0_DAYS,
                           "target_per_year": target, "games_since": len(after)}
    if not before or not after:
        return {**out, "state": "early"}
    rate = (after[-1] - before[-1]) / max(days, 1) * 365
    out["rate_per_year"] = round(rate)
    if days < config.GATE0_DAYS:
        return {**out, "state": "early"}
    return {**out, "state": "beating" if rate > target else "behind"}
