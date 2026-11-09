import random
import time
from datetime import date

import chess
import httpx
import pytest

from gambit_brain import config, db, endgames, games, guardrails, humanlevel, importers, planner, solve, sparring
from gambit_brain.maia import fit_from_totals

from .conftest import chesscom_game

# ── Endgames ───────────────────────────────────────────────────────────────────────────────────

MATE1 = endgames.Lesson("test_mate1", 1, "Back-rank mate", "6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1", "white", "mate",
                        "Rook to the back rank.")


class FakeTB:
    """Scripted tablebase: Ra8 is the only winning move; everything else draws."""

    async def probe(self, fen):
        b = chess.Board(fen)
        if b.turn == chess.WHITE:
            return {"category": "win", "dtm": 1, "moves": [{"uci": "a1a8", "san": "Ra8#", "category": "loss"},
                                                           {"uci": "g1f1", "san": "Kf1", "category": "draw"}]}
        reply = next(iter(b.legal_moves)).uci()
        return {"category": "draw", "dtm": 0, "moves": [{"uci": reply, "san": "x", "category": "draw"}]}


@pytest.fixture
def eg(conn, monkeypatch):
    monkeypatch.setitem(endgames.BY_KEY, MATE1.key, MATE1)
    monkeypatch.setattr(endgames, "CURRICULUM", [*endgames.CURRICULUM, MATE1])
    monkeypatch.setattr(endgames, "_variant", lambda lesson, rng: (chess.Board(lesson.fen), lesson.side))
    return endgames.Endgames(conn, FakeTB())


async def test_endgame_success_schedules_review(eg, conn):
    a = await eg.start("test_mate1")
    assert a["side"] == "white" and a["goal"] == "mate" and "idea" not in a  # the idea comes after
    r = await eg.move("a1a8")
    assert r["result"] == "success" and r["next_review_days"] > 0 and r["idea"]
    row = conn.execute("SELECT mode, correct, grade FROM reviews").fetchone()
    assert tuple(row) == ("endgame", 1, 4)  # mate in the optimal number of moves: Easy


async def test_endgame_failure_shows_keeping_moves(eg, conn):
    await eg.start("test_mate1")
    r = await eg.move("g1f1")
    assert r["result"] == "failed" and r["keeping_moves"] == ["Ra8#"]
    assert conn.execute("SELECT grade FROM reviews").fetchone()[0] == 1


async def test_endgame_cards_stay_out_of_solve_sets(eg, conn):
    await eg.start("test_mate1")
    await eg.move("g1f1")
    conn.execute("UPDATE cards SET due = 0")
    assert solve.build_set(conn, "standard", random.Random(0)) == []
    assert solve.Solver(conn).overview()["due"] == 0


def test_curriculum_positions_are_legal():
    for lesson in endgames.CURRICULUM:
        b = chess.Board(lesson.fen)
        assert b.is_valid() and len(b.piece_map()) <= 7, lesson.key


# ── Human-level labels ─────────────────────────────────────────────────────────────────────────

LEVELS = list(config.MAIA_LEVELS)


def _totals(peak: int, sharp: float = 3.0, moves: int = 30):
    return [-(moves * 1.5) - sharp * abs(lv - peak) / 100 for lv in LEVELS], moves


def test_fit_range_narrows_with_evidence():
    t, n = _totals(1200, sharp=1.0)
    wide = fit_from_totals(t, n)
    t10 = [x * 10 for x in t]
    narrow = fit_from_totals(t10, n * 10)
    assert wide["level"] == narrow["level"] == 1200
    assert (narrow["hi"] - narrow["lo"]) < (wide["hi"] - wide["lo"])


def _seed_fits(conn, n=20, my_rating=900, my_peak=1300, opp="Bot Martin", opp_peak=800):
    for i in range(n):
        gid = games.store(conn, importers.chesscom_meta(
            chesscom_game(uuid=f"h{i}", end_time=1_700_000_000 + i, rating=my_rating, time_class="rapid"), "me"))
        conn.execute("UPDATE games SET opp_name = ? WHERE id = ?", (opp, gid))
        humanlevel.store(conn, gid, {"me": _totals(my_peak), "opp": _totals(opp_peak)})


def test_personal_scale_and_describe(conn):
    _seed_fits(conn)
    s = humanlevel.personal_scale(conn)
    assert s["ready"] and s["maia_level"] == 1300 and s["offset"] == -400 and s["rating"] == 900
    d = humanlevel.describe(conn, 1500, 1400, 1600)
    assert d["scale"] == "Lichess blitz"
    assert d["personal"]["rating"] == 1100 and d["personal"]["lo"] == 1000 and d["vs_you"] == 200


def test_personal_scale_needs_enough_games(conn):
    _seed_fits(conn, n=5)
    s = humanlevel.personal_scale(conn)
    assert not s["ready"] and s["needed"] == config.PERSONAL_SCALE_MIN_GAMES
    assert "personal" not in humanlevel.describe(conn, 1500)


def test_opponent_profile_pools_games(conn):
    _seed_fits(conn)
    o = humanlevel.opponent(conn, "Bot Martin")
    assert o["games"] == 20 and o["fit"]["maia_level"] == 800 and o["fit"]["personal"]["rating"] == 400
    assert o["fit"]["lo"] <= 800 <= o["fit"]["hi"]


# ── Planner ────────────────────────────────────────────────────────────────────────────────────


def test_plan_follows_stage_allocation(conn):
    p = planner.today(conn, time.mktime(date(2026, 11, 10).timetuple()))  # a Tuesday
    assert not p["rest_day"] and p["stage"]["stage"] == 1
    mins = {b["activity"]: b["minutes"] for b in p["blocks"]}
    day = round(20 * 60 / 6 / 5) * 5
    assert abs(sum(mins.values()) - day) <= 10
    # Every activity is built; stage 1 is solving-heavy and play comes last.
    assert set(mins) == {"solving", "analysis", "endgames", "master_games", "openings", "play"}
    assert mins["solving"] > mins["analysis"] > mins["openings"] > 0 and p["blocks"][-1]["activity"] == "play"
    assert p["folded"] == []


def test_rest_day_and_settings(conn):
    sunday = time.mktime(date(2026, 11, 15).timetuple())
    assert planner.today(conn, sunday)["rest_day"]
    with db.tx(conn):
        db.set_setting(conn, "rest_days", [])
        db.set_setting(conn, "weekly_hours", 35)
    p = planner.today(conn, sunday)
    assert not p["rest_day"] and p["planned"] == pytest.approx(300, abs=10)


def test_stage_advances_with_rating(conn):
    for i in range(30):
        games.store(conn, importers.chesscom_meta(
            chesscom_game(uuid=f"s{i}", end_time=1_700_000_000 + i, rating=1700, time_class="rapid"), "me"))
    st = planner.stage(conn)
    assert st["stage"] == 2 and st["basis"]["next_at"] == 2000
    with db.tx(conn):
        db.set_setting(conn, "stage_override", 1)
    assert planner.stage(conn)["stage"] == 1 and planner.stage(conn)["auto"] == 2


def test_time_done_is_measured(conn):
    now = int(time.time())
    with db.tx(conn):
        conn.execute("INSERT INTO solve_sessions (mode, started_at, ended_at, timebox_min, planned) "
                     "VALUES ('standard', ?, ?, 30, 20)", (now - 1200, now))
    assert planner.minutes_done(conn, date.today())["solving"] == 20


# ── Sparring ───────────────────────────────────────────────────────────────────────────────────


class StubMaia:
    def load(self):
        pass

    def unload(self):
        pass


@pytest.fixture
def spar(conn, monkeypatch):
    def fake_sample(maia, start, ucis, self_elo, opp_elo, temperature=1.0, rng=None):
        b = chess.Board(start)
        for u in ucis:
            b.push_uci(u)
        return sorted(m.uci() for m in b.legal_moves)[0]

    monkeypatch.setattr(sparring, "sample_move", fake_sample)
    return sparring.Sparring(conn, StubMaia(), lambda: False, random.Random(1))


async def test_sparring_game_is_saved_and_tracked(spar, conn):
    g = await spar.start("white", 15, 10)
    assert g["you"] == "white" and g["level"] == 1100  # default 1000 + 100
    assert g["label"]["scale"] == "Lichess blitz"
    r = await spar.move("e2e4", 899_000)
    assert r["reply"]["uci"] and r["reply"]["think_ms"] >= 1000
    over = spar.resign()["over"]
    assert over["result"] == "loss" and over["game_id"]
    row = conn.execute("SELECT platform, opp_name, opp_rating, rated, time_class, pgn FROM games WHERE id = ?",
                       (over["game_id"],)).fetchone()
    assert (row["platform"], row["opp_name"], row["opp_rating"], row["rated"]) == ("sparring", "Maia 1100", 1100, 0)
    assert "[%clk" in row["pgn"]
    assert spar.record() == [{"level": 1100, "n": 1, "w": 0, "d": 0, "l": 1, "score": 0.0}]
    assert guardrails.stop_loss(conn)["streak"] == 0  # sparring never counts towards the stop-loss


async def test_sparring_as_black_bot_moves_first(spar):
    g = await spar.start("black", 30, 0)
    assert g["reply"]["uci"] and len(spar.view()["moves"]) == 1


async def test_sparring_refuses_under_lock(conn):
    s = sparring.Sparring(conn, StubMaia(), lambda: True)
    with pytest.raises(ValueError, match="fair-play"):
        await s.start("white", 15, 10)


async def test_watcher_imports_when_a_lichess_game_ends(conn):
    with db.tx(conn):
        db.set_setting(conn, "lichess_username", "me")
    state = {"playing": True}
    ended = []

    async def apply(locked, reason):
        with db.tx(conn):
            db.set_setting(conn, "fairplay_lock", locked)
            db.set_setting(conn, "fairplay_reason", reason if locked else None)

    async def on_end():
        ended.append(True)

    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=[{"playing": state["playing"]}]))
    w = guardrails.LichessWatcher(conn, apply, on_end)
    async with httpx.AsyncClient(transport=transport) as http:
        await w.check_once(http)
        state["playing"] = False
        await w.check_once(http)
    assert ended == [True]



def test_fit_at_the_edge_of_maia_is_not_a_number(conn):
    _seed_fits(conn, my_peak=2600)  # stronger than Maia's top level
    s = humanlevel.personal_scale(conn)
    assert not s["ready"] and s["beyond"] == "high"
    t, n = _totals(600)
    assert fit_from_totals(t, n)["edge"] == "low"
