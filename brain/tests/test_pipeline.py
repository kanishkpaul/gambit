import asyncio
import json
import time

import pytest

from gambit_brain import analysis, audit, config, db, games, importers, metrics
from gambit_brain.server import Brain

from .conftest import BLUNDER_PGN, HAS_STOCKFISH, chesscom_game

FAST = config.EngineBudget(workers=2, nodes=5_000, deep_nodes=20_000, games_in_flight=2)


def test_chesscom_meta_and_store(conn):
    meta = importers.chesscom_meta(chesscom_game(), "Me")
    assert (meta.my_color, meta.result, meta.termination) == ("white", "loss", "resign")
    assert meta.opening == "Kings Pawn Opening Wayward Queen Attack"
    assert meta.eco == "C20"
    gid = games.store(conn, meta)
    assert gid is not None
    assert games.store(conn, meta) is None  # duplicates are skipped
    row = conn.execute("SELECT * FROM games WHERE id = ?", (gid,)).fetchone()
    assert (row["base_s"], row["inc_s"], row["ply_count"]) == (600, 0, 16)
    assert conn.execute("SELECT COUNT(*) FROM moves WHERE game_id = ?", (gid,)).fetchone()[0] == 16


def test_chesscom_result_codes():
    m = importers.chesscom_meta(chesscom_game(result="win"), "me")
    assert (m.result, m.termination) == ("win", "resign")
    m = importers.chesscom_meta(chesscom_game(result="agreed"), "me")
    assert (m.result, m.termination) == ("draw", "agreement")
    assert importers.chesscom_meta(chesscom_game(my="someone"), "me") is None


def test_lichess_meta():
    g = {"id": "abcd1234", "rated": True, "variant": "standard", "speed": "rapid", "status": "outoftime",
         "createdAt": 1_700_000_000_000, "lastMoveAt": 1_700_000_900_000, "winner": "white",
         "players": {"white": {"user": {"name": "Other"}, "rating": 1500},
                     "black": {"user": {"name": "Me"}, "rating": 1450}},
         "clock": {"initial": 600, "increment": 5}, "opening": {"eco": "B01", "name": "Scandinavian Defense: Main"},
         "pgn": BLUNDER_PGN}
    m = importers.lichess_meta(g, "me")
    assert (m.my_color, m.result, m.termination, m.time_control, m.played_at) == (
        "black", "loss", "timeout", "600+5", 1_700_000_900)
    assert importers.lichess_meta({**g, "variant": "chess960"}, "me") is None


@pytest.mark.skipif(not HAS_STOCKFISH, reason="needs stockfish")
async def test_batch_analysis_end_to_end(conn):
    for i in range(3):
        games.store(conn, importers.chesscom_meta(chesscom_game(uuid=f"g{i}", end_time=1_700_000_000 + i), "me"))
    events = []

    async def emit(d):
        events.append(d)

    pool = analysis.EnginePool(FAST)
    job = analysis.BatchAnalysis(conn, pool, emit)
    job.start()
    await asyncio.wait_for(job.task, 60)
    assert job.state == "done", job.error
    st = job.status()
    assert st["analysed"] == 3 and st["deep"] == 3
    assert not pool.running
    # Identical games share every position: evaluated once.
    n_epd = conn.execute("SELECT COUNT(DISTINCT epd_before) FROM moves").fetchone()[0]
    assert conn.execute("SELECT COUNT(*) FROM evals").fetchone()[0] <= n_epd + 1
    unclassified = conn.execute("SELECT COUNT(*) FROM moves WHERE class IS NULL").fetchone()[0]
    assert unclassified == 0
    # 5. Qb3?? / 8. Qxc7?? lose the queen: at least one white blunder, tagged.
    blunders = conn.execute(
        "SELECT san, motifs FROM moves WHERE class = 'blunder' AND color = 'white' AND game_id = 1").fetchall()
    assert blunders and all(json.loads(b["motifs"]) for b in blunders)
    assert any(e.get("phase") == "first" for e in events)


@pytest.mark.skipif(not HAS_STOCKFISH, reason="needs stockfish")
async def test_halt_kills_pool(conn):
    for i in range(6):
        games.store(conn, importers.chesscom_meta(chesscom_game(uuid=f"h{i}", end_time=1_700_000_000 + i), "me"))

    async def emit(_):
        pass

    pool = analysis.EnginePool(config.EngineBudget(workers=2, nodes=2_000_000))
    job = analysis.BatchAnalysis(conn, pool, emit)
    job.start()
    await asyncio.sleep(0.5)
    await job.halt()
    assert not pool.running and job.state == "paused"


def _seed_rated(conn, n=160, start_rating=800, step=2.0, analysed=True):
    """n rated rapid games over the last n hours, rating rising by `step` a game, fake classifications."""
    return _seed(conn, n, start_rating, step, analysed)


def _seed(conn, n, start_rating, step, analysed):
    t0 = int(time.time()) - n * 3600
    for i in range(n):
        gid = games.store(conn, importers.chesscom_meta(
            chesscom_game(uuid=f"r{i}", end_time=t0 + i * 3600, rating=int(start_rating + step * i),
                          result="win" if i % 2 else "resigned"), "me"))
        if analysed:
            cls = "blunder" if i < n // 2 else "ok"
            conn.execute("UPDATE moves SET class = 'ok' WHERE game_id = ?", (gid,))
            conn.execute(
                "UPDATE moves SET class = ?, motifs = '[\"hung_piece\"]' WHERE game_id = ? AND ply = 9", (cls, gid))
            conn.execute("UPDATE games SET analysed_at = 1 WHERE id = ?", (gid,))


def test_slope(conn):
    _seed_rated(conn)
    with db.tx(conn):
        db.set_setting(conn, "training_start", int(time.time()) - 140 * 3600)
    s = metrics.slope(conn)
    assert s["pool"] == {"platform": "chesscom", "time_class": "rapid"}
    assert len(s["rating"]) == 160 and s["rating"][-1]["hi"] - s["rating"][-1]["mean"] == 80
    assert s["trend"]["real"] and s["trend"]["per_100"] == pytest.approx(200, abs=1)
    assert s["errors"][0]["blunders_mean"] == 1 and s["errors"][-1]["blunders_mean"] == 0
    assert s["motifs"] == [{"motif": "hung_piece", "count": 80}]
    assert s["gate0"]["state"] == "early" and s["gate0"]["rate_per_year"] > 95


def test_slope_flat_is_not_a_trend(conn):
    _seed_rated(conn, step=0.2)
    assert metrics.slope(conn)["trend"]["real"] is False


def test_audit_lifecycle(conn):
    assert audit.state(conn)["state"] == "none"
    with pytest.raises(ValueError):
        audit.start(conn)
    _seed_rated(conn, n=20)
    st = audit.start(conn)
    assert st["state"] == "open" and st["report"]["games"] == 20 and st["report"]["blunders"] == 10
    assert audit.start(conn)["started_at"] == st["started_at"]  # idempotent
    with pytest.raises(ValueError):
        audit.file(conn, [])
    with pytest.raises(ValueError):
        audit.file(conn, ["a", "b", "c", "d"])
    assert audit.file(conn, ["Check what every capture leaves hanging"])["state"] == "filed"
    with pytest.raises(ValueError):
        audit.file(conn, ["again"])


def test_audit_expires(conn):
    _seed_rated(conn, n=5)
    audit.start(conn)
    conn.execute("UPDATE audit SET started_at = ?", (int(time.time()) - 46 * 60,))
    st = audit.state(conn)
    assert st["state"] == "expired" and "report" not in st


async def test_rpc_dispatch(conn):
    brain = Brain(conn, {"lichess_token": "secret"})
    r = json.loads(await brain.dispatch(json.dumps({"id": 1, "method": "settings.get"})))
    assert r["result"]["has_lichess_token"] is True
    assert "secret" not in json.dumps(r)
    r = json.loads(await brain.dispatch(json.dumps(
        {"id": 2, "method": "settings.set", "params": {"chesscom_username": "  me "}})))
    assert r["result"]["chesscom_username"] == "me"
    r = json.loads(await brain.dispatch(json.dumps({"id": 3, "method": "settings.set", "params": {"x": 1}})))
    assert r["error"]["message"].startswith("unknown settings")
    r = json.loads(await brain.dispatch(json.dumps({"id": 4, "method": "nope"})))
    assert r["error"]["code"] == -32601
    r = json.loads(await brain.dispatch(json.dumps({"id": 5, "method": "fairplay.set", "params": {"locked": True}})))
    assert r["result"]["fairplay_lock"] is True
    r = json.loads(await brain.dispatch(json.dumps({"id": 6, "method": "analysis.start"})))
    assert "fair-play lock" in r["error"]["message"]
    r = json.loads(await brain.dispatch(json.dumps({"id": 7, "method": "mirror.summary"})))
    assert r["result"]["totals"]["games"] == 0
    r = json.loads(await brain.dispatch(json.dumps({"id": 8, "method": "slope.get"})))
    assert r["result"]["pool"] is None
