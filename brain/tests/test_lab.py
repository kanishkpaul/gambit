import json
import time

import httpx
import pytest

from gambit_brain import analysis, config, db, games, guardrails
from gambit_brain.lab import Lab, LabError
from gambit_brain.maia import MoveProfile

from .conftest import BLUNDER_PGN, HAS_STOCKFISH

PGN = BLUNDER_PGN.replace('[Result "0-1"]', '[Result "0-1"]\n[Date "2026.11.01"]\n[WhiteElo "900"]\n[BlackElo "950"]')


class StubMaia:
    """Deterministic stand-in: likes your moves more at 1200 than elsewhere."""

    def profile_game(self, start_fen, ucis, my_plies, self_elo_hint, opp_elo, levels=None):
        levels = list(config.MAIA_LEVELS)
        return [MoveProfile(p, ucis[p - 1], [0.5 if lv == 1200 else 0.1 for lv in levels], [ucis[p - 1]] * len(levels))
                for p in sorted(my_plies)]

    def unload(self):
        pass


@pytest.fixture
async def lab_env(conn, monkeypatch):
    monkeypatch.setattr(config, "LAB_ENGINE_NODES", 5_000)
    monkeypatch.setattr(config, "MAIA_MIN_MOVES", 3)
    pool = analysis.EnginePool(config.EngineBudget(workers=1, threads=1, nodes=5_000))
    await pool.start()
    state = {"locked": False}
    events = []

    async def emit(d):
        events.append(d)

    lab = Lab(conn, pool.analyse, StubMaia(), lambda: state["locked"], emit)
    gid = games.store(conn, games.meta_from_pgn(PGN, "white"))
    yield lab, gid, state, events
    await pool.stop()


def test_pgn_import_rules():
    with pytest.raises(ValueError, match="finished"):
        games.meta_from_pgn(BLUNDER_PGN.replace("0-1", "*"), "white")  # an unfinished game
    with pytest.raises(ValueError, match="colour"):
        games.meta_from_pgn(BLUNDER_PGN, "")
    m = games.meta_from_pgn(PGN, "white")
    got = (m.platform, m.result, m.my_rating, m.opp_rating, m.time_class, m.rated)
    assert got == ("pgn", "loss", 900, 950, "rapid", False)
    assert m.played_at == 1_793_491_200  # 2026-11-01 UTC


@pytest.mark.skipif(not HAS_STOCKFISH, reason="needs stockfish")
async def test_engine_stays_locked_until_moments(lab_env, conn):
    lab, gid, _, _ = lab_env
    v = lab.open(gid)
    assert v["session"]["state"] == "annotate" and v["reveal"] is None
    blob = json.dumps(v)
    assert "cp_loss" not in blob and "best" not in blob  # no engine data before the unlock
    sid = v["session"]["id"]
    with pytest.raises(LabError, match="critical moment"):
        await lab.unlock(sid)
    with pytest.raises(LabError):
        await lab.engine(sid, v["game"]["start_fen"])
    lab.note(sid, 9, "Wanted to keep the queen active")
    for ply in (9, 11, 13):
        lab.moment(sid, ply, "Unsure here", "Qe2")
    with pytest.raises(LabError, match="at most 3"):
        lab.moment(sid, 15, "one more", None)
    lab.remove_moment(sid, 13)
    assert [m["ply"] for m in lab.view(sid)["moments"]] == [9, 11]


@pytest.mark.skipif(not HAS_STOCKFISH, reason="needs stockfish")
async def test_unlock_reveal_and_close(lab_env, conn):
    lab, gid, _, events = lab_env
    sid = lab.open(gid)["session"]["id"]
    lab.moment(sid, 9, "Moved the queen again", "Ne2")
    v = await lab.unlock(sid)
    r = v["reveal"]
    assert v["session"]["state"] == "revealed"
    assert len(r["evals"]) == 17 and len(r["moves"]) == 16
    assert 9 in r["engine_moments"] and r["found"] == [9]  # Qb3?? hangs the queen; you flagged it
    assert r["moves"][8]["class"] == "blunder" and r["moves"][8]["best_san"]
    assert r["maia"]["fit"]["level"] == 1200 and r["maia"]["self_level"] == 900
    assert r["time"]["moves"][0]["spent_s"] == 2.0
    assert any(e["stage"] == "engine" for e in events)
    with pytest.raises(LabError, match="final"):
        lab.note(sid, 1, "too late")

    fen = conn.execute("SELECT fen_before FROM moves WHERE game_id = ? AND ply = 9", (gid,)).fetchone()[0]
    nudges = [(await lab.engine(sid, fen))["nudge"] for _ in range(3)]
    assert nudges == [False, False, True]

    with pytest.raises(LabError, match="1 and 3"):
        lab.close(sid, [])
    v = lab.close(sid, ["Before moving the queen a third time, count what it leaves undefended."])
    assert v["session"]["state"] == "closed" and v["lessons"]
    refs = {r[0] for r in conn.execute("SELECT ref FROM items WHERE kind = 'own'")}
    assert f"{gid}:9" in refs and f"{gid}:9:m" in refs
    with pytest.raises(LabError, match="closed"):
        lab.close(sid, ["again"])


@pytest.mark.skipif(not HAS_STOCKFISH, reason="needs stockfish")
async def test_fair_play_lock_blocks_unlock(lab_env):
    lab, gid, state, _ = lab_env
    sid = lab.open(gid)["session"]["id"]
    lab.moment(sid, 9, "x", None)
    state["locked"] = True
    with pytest.raises(LabError, match="fair-play"):
        await lab.unlock(sid)


async def test_timebox_expiry(lab_env, conn):
    lab, gid, _, _ = lab_env
    sid = lab.open(gid)["session"]["id"]
    conn.execute("UPDATE lab_sessions SET started_at = ?", (int(time.time()) - (config.LAB_TIMEBOX_MIN + 1) * 60,))
    assert lab.view(sid)["session"]["state"] == "expired"
    with pytest.raises(LabError, match="Time's up"):
        lab.moment(sid, 9, "late", None)


async def test_one_open_post_mortem_at_a_time(lab_env, conn):
    lab, gid, _, _ = lab_env
    lab.open(gid)
    other = games.store(conn, games.meta_from_pgn(PGN.replace('[Date "2026.11.01"]', '[Date "2026.11.02"]'), "black"))
    with pytest.raises(LabError, match="still open"):
        lab.open(other)


# ── Guardrails ─────────────────────────────────────────────────────────────────────────────────


def _game_today(conn, i, result):
    from gambit_brain import importers

    from .conftest import chesscom_game

    code = {"loss": "resigned", "win": "win"}[result]
    g = chesscom_game(uuid=f"t{i}", end_time=int(time.time()) - 600 + i, result=code)
    games.store(conn, importers.chesscom_meta(g, "me"))


def test_stop_loss_levels(conn):
    assert guardrails.stop_loss(conn)["level"] == "clear"
    _game_today(conn, 0, "win")
    _game_today(conn, 1, "loss")
    _game_today(conn, 2, "loss")
    s = guardrails.stop_loss(conn)
    assert (s["level"], s["streak"], s["games_today"]) == ("caution", 2, 3)
    _game_today(conn, 3, "loss")
    assert guardrails.stop_loss(conn)["level"] == "stop"


def test_tilt_flag(conn):
    guardrails.set_tilt(conn, True)
    assert guardrails.stop_loss(conn)["level"] == "stop"
    guardrails.set_tilt(conn, False)
    assert guardrails.stop_loss(conn)["level"] == "clear"


async def test_lichess_watcher_drives_the_lock(conn):
    with db.tx(conn):
        db.set_setting(conn, "lichess_username", "me")
    playing = {"v": True}
    calls = []

    async def apply(locked, reason):
        calls.append((locked, reason))
        with db.tx(conn):
            db.set_setting(conn, "fairplay_lock", locked)
            db.set_setting(conn, "fairplay_reason", reason if locked else None)

    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=[{"id": "me", "playing": playing["v"]}]))
    w = guardrails.LichessWatcher(conn, apply)
    async with httpx.AsyncClient(transport=transport) as http:
        await w.check_once(http)
        await w.check_once(http)  # still playing: no second call
        playing["v"] = False
        await w.check_once(http)
    assert calls == [(True, "lichess"), (False, "lichess")]

    # A manual lock is never lifted by the watcher.
    await apply(True, "manual")
    calls.clear()
    async with httpx.AsyncClient(transport=transport) as http:
        await w.check_once(http)
    assert calls == []
