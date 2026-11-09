import json
import random

import chess
import chess.pgn
import httpx
import pytest

from gambit_brain import calc, calibration, coach, config, games, importers, masters, openings, puzzles, solve
from gambit_brain.chesslib import Eval

from .conftest import chesscom_game

HEADER = "PuzzleId,FEN,Moves,Rating,RatingDeviation,Popularity,NbPlays,Themes,GameUrl,OpeningTags,DailyDate"
MATE = "6k1/p4ppp/8/8/8/8/5PPP/1R4K1 b - - 0 1,a7a6 b1b8"  # after ...a6, Rb8# is a back-rank mate


async def _seed_puzzles(conn, n=40, themes="mate mateIn1 long"):
    rows = [f"P{i:03d},{MATE},{900 + i * 15},70,95,5000,{themes},,," for i in range(n)]
    await puzzles.import_rows(conn, [HEADER, *rows])


# ── Calibration ────────────────────────────────────────────────────────────────────────────────


def test_performance_rating():
    assert solve.performance_rating([(1200, True), (1200, False)]) == 1200
    assert solve.performance_rating([(1200, True)] * 3) == 1600
    p = solve.performance_rating([(1000, True), (1400, False), (1200, True), (1200, False)])
    assert 1150 < p < 1250


async def test_calibration_is_cold_timed_and_recorded(conn):
    await _seed_puzzles(conn)
    assert calibration.status(conn)["due"]
    s = solve.Solver(conn)
    info = s.start("calibration", random.Random(0))
    assert info["total"] == config.CALIBRATION_SIZE
    ratings = []
    for i in range(4):
        p = s.next()
        assert p["time_limit_s"] == config.CALIBRATION_SECONDS
        ratings.append(s.session.current.item["rating"])
        if i % 2:
            await s.move(p["item_id"], "b1b8", ms=5000)
        else:
            s.skip(p["item_id"])
    summary = s.end()
    assert summary["attempted"] == 4 and summary["solved"] == 2 and summary["performance"]
    assert conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 0  # nothing scheduled
    assert solve.solve_rating(conn)["n"] == 0  # the solve rating doesn't move
    st = calibration.status(conn)
    assert not st["due"] and st["last"]["performance"] == summary["performance"]
    # Spread around the solve rating (1200 ± 300).
    assert min(ratings) >= 850 and max(ratings) <= 1550


async def test_calibration_answers_must_come_in_time(conn):
    await _seed_puzzles(conn)
    s = solve.Solver(conn)
    s.start("calibration", random.Random(0))
    p = s.next()
    r = await s.move(p["item_id"], "b1b8", ms=(config.CALIBRATION_SECONDS + 10) * 1000)
    assert r["result"] == "wrong"


# ── Calculation ────────────────────────────────────────────────────────────────────────────────


def test_parse_line_accepts_move_numbers():
    b = chess.Board()
    moves, bad = calc.parse_line(b, "1. e4 e5 2. Nf3 Nc6 3.Bb5")
    assert [m.uci() for m in moves] == ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5"] and bad is None
    moves, bad = calc.parse_line(b, "e4 Ke2")
    assert len(moves) == 1 and bad == "Ke2"


async def test_calc_scores_line_and_candidates(conn):
    await _seed_puzzles(conn)

    async def analyse(fen, nodes):
        return Eval(cp=0), [], nodes

    c = calc.Calc(conn, analyse, lambda: False)
    p = c.next("visual")
    assert "moves" not in p and p["turn"] == "white" and p["visual_seconds"] == config.CALC_VISUAL_SECONDS
    r = await c.submit(p["puzzle_id"], ["Rb8#", "Kf1"], "Kf1", "back rank looked fine")
    assert not r["first_correct"] and r["saw_it"] and r["plies_matched"] == 0
    assert r["best_line"] == ["Rb8#"] and r["best_cp"] == config.MATE_CP
    p = c.next("board")
    r = await c.submit(p["puzzle_id"], [], "1. Rb8#", None)
    assert r["first_correct"] and r["plies_matched"] == 1
    ov = c.overview()
    assert ov["attempts"] == 2 and ov["first_correct"] == 0.5 and ov["saw_but_rejected"] == 0.5


async def test_calc_refuses_under_lock(conn):
    await _seed_puzzles(conn)

    async def analyse(fen, nodes):
        return Eval(cp=0), [], nodes

    c = calc.Calc(conn, analyse, lambda: True)
    p = c.next("board")
    with pytest.raises(ValueError, match="fair-play"):
        await c.submit(p["puzzle_id"], [], "Rb8#", None)


# ── Openings ───────────────────────────────────────────────────────────────────────────────────

E4 = '[Result "1-0"]\n\n1. e4 e5 2. Nf3 Nc6 3. Bc4 Nf6 4. d3 Be7 5. O-O O-O 6. Re1 d6 7. h3 h6 8. c3 a6 1-0'
D4 = '[Result "0-1"]\n\n1. d4 d5 2. c4 e6 3. Nc3 Nf6 4. Bg5 Be7 5. e3 O-O 6. Nf3 h6 7. Bh4 b6 8. Rc1 Bb7 0-1'


def _store(conn, pgn, uuid, t):
    g = chesscom_game(pgn=pgn, uuid=uuid, end_time=t, result="win" if "1-0" in pgn else "resigned")
    return games.store(conn, importers.chesscom_meta(g, "me"))


def test_repertoire_departures_and_drill(conn):
    for i in range(3):
        _store(conn, E4, f"e{i}", 1_700_000_000 + i)
    _store(conn, D4, "d0", 1_700_000_100)  # the latest game: you opened 1. d4 instead
    res = openings.rebuild(conn)
    assert res["positions"] >= 8
    start = conn.execute("SELECT san FROM repertoire WHERE color = 'white' AND ply = 1").fetchone()[0]
    assert start == "e4"
    deps = openings.departures(conn)
    assert deps[0]["event"] == {"kind": "deviated", "ply": 1, "played": "d4", "usual": "e4"}
    lines = openings.lines(conn)["white"]
    assert lines and lines[0]["moves"][:3] == ["e4", "e5", "Nf3"]

    nxt = openings.drill_next(conn)
    assert nxt and nxt["turn"] == "white"
    r = openings.drill_answer(conn, nxt["item_id"], "d2d4")
    assert not r["correct"] and r["answer_san"] == "e4"
    r = openings.drill_answer(conn, nxt["item_id"], "e2e4")
    assert r["correct"] and r["next_review_days"] >= 0

    openings.pin(conn, "white", chess.STARTING_FEN, "d4")
    openings.rebuild(conn)
    assert conn.execute("SELECT san, source FROM repertoire WHERE color = 'white' AND ply = 1").fetchone()[:] == ("d4", "pinned")
    openings.sync_drill(conn)
    assert conn.execute("SELECT solution FROM items WHERE kind = 'opening'").fetchone()[0] == "d2d4"


# ── Master games ───────────────────────────────────────────────────────────────────────────────


def _master_pgn(seed=1, white_elo=2550, black_elo=2500, plies=60):
    rng = random.Random(seed)
    game = chess.pgn.Game()
    game.headers.update(
        {
            "White": "Master A",
            "Black": "Master B",
            "WhiteElo": str(white_elo),
            "BlackElo": str(black_elo),
            "Result": "1-0",
            "Site": f"https://lichess.org/broadcast/x/{seed}",
            "Event": "Test Open",
        }
    )
    node, board = game, chess.Board()
    while len(board.move_stack) < plies:
        legal = list(board.legal_moves)
        m = rng.choice(legal)
        board.push(m)
        if board.is_game_over():
            board.pop()
            continue
        node = node.add_variation(m)
    return str(game), [m.uci() for m in board.move_stack]


async def test_master_import_filters_and_guessing(conn):
    good, moves = _master_pgn()
    weak, _ = _master_pgn(seed=2, black_elo=1900)
    assert masters.store_pgn_blob(conn, good + "\n\n" + weak) == 1
    assert masters.store_pgn_blob(conn, good) == 0  # duplicate

    calls = []

    async def analyse(fen, nodes):
        calls.append(fen)
        return Eval(cp=0), [], nodes

    g = masters.Guessing(conn, analyse, lambda: False)
    v = g.start()
    assert v["side"] == "white" and len(v["moves"]) == config.MASTER_START_PLY
    r = await g.guess(moves[config.MASTER_START_PLY])
    assert r["matched"] and not calls
    b = chess.Board()
    for u in moves[: config.MASTER_START_PLY + 2]:
        b.push_uci(u)
    other = next(m.uci() for m in b.legal_moves if m.uci() != moves[config.MASTER_START_PLY + 2])
    r = await g.guess(other)
    assert not r["matched"] and r["as_good"] and len(calls) == 2  # equal evals: as good as the master's
    s = g.finish()
    assert (s["guesses"], s["matched"], s["as_good"]) == (2, 1, 1)


# ── Coach ──────────────────────────────────────────────────────────────────────────────────────


def test_weekly_grounding_removes_invented_numbers():
    facts = {"blunders_per_game_recent": 0.84, "rating_rolling_mean": 1012, "solve_attempts": 120, "solve_correct": 90}
    raw = {
        "headline": "A steady week at 1012.",
        "observations": [
            {"text": "You solved 90 of 120 positions.", "evidence": ["solve_attempts", "solve_correct"]},
            {"text": "You gained 45 points.", "evidence": ["rating_rolling_mean"]},
            {"text": "Blunders are at 0.84 a game.", "evidence": ["made_up_key"]},
        ],
        "next_week": {"solving": 40, "analysis": 20, "endgames": 15, "master_games": 5, "openings": 5, "play": 25},
        "focus": ["Check every capture.", "Win 3 games in a row with a 1500 opponent."],
    }
    out, removed = coach.ground_weekly(raw, facts)
    assert [o["text"] for o in out["observations"]] == ["You solved 90 of 120 positions."]
    assert out["headline"] == "A steady week at 1012." and len(removed) == 3
    assert sum(out["next_week"].values()) in (99, 100, 101) and out["next_week"]["solving"] == 36
    assert out["focus"] == ["Check every capture."]


def test_explain_grounding_removes_unlisted_moves_and_evals():
    raw = {"summary": "Nf3 keeps control.", "points": ["After Nf3 Nc6 you're +0.35.", "Qh5 wins the queen.", "It's +2.10 now."]}
    out, removed = coach.ground_explain(raw, [["Nf3", "Nc6"]], ["+0.35"], "e4")
    assert out["points"] == ["After Nf3 Nc6 you're +0.35."] and len(removed) == 2


class FakeOllama:
    """An Ollama server in a transport: answers /api/chat with a fixed payload and records the requests."""

    def __init__(self, payload=None, status=200, models=("qwen-test:8b",)):
        self.payload, self.status, self.models, self.calls = payload, status, models, []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.40.5"})
        if request.url.path == "/api/tags":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {"name": m, "size": 5_000_000_000, "details": {"parameter_size": "8B", "quantization_level": "Q4_K_M"}}
                        for m in self.models
                    ]
                },
            )
        body = json.loads(request.content)
        self.calls.append(body)
        if self.status != 200:
            return httpx.Response(self.status, json={"error": f"model '{body['model']}' not found"})
        return httpx.Response(200, json={"message": {"role": "assistant", "content": json.dumps(self.payload)}, "done": True})

    def client(self) -> coach.Ollama:
        return coach.Ollama("http://ollama.test", httpx.MockTransport(self.handler))


def _with_model(conn, name="qwen-test:8b"):
    from gambit_brain import db

    with db.tx(conn):
        db.set_setting(conn, "coach_model", name)


async def test_coach_weekly_end_to_end(conn):
    fake = FakeOllama(
        {
            "headline": "Quiet week.",
            "observations": [{"text": "No games yet.", "evidence": ["games_this_week"]}],
            "next_week": {"solving": 35, "analysis": 20, "endgames": 15, "master_games": 5, "openings": 5, "play": 20},
            "focus": [],
        }
    )
    _with_model(conn)
    c = coach.Coach(conn, None, lambda: False, fake.client())
    out = await c.weekly()
    assert out["headline"] == "Quiet week." and out["observations"][0]["evidence"] == ["games_this_week"]
    call = fake.calls[0]
    assert call["model"] == "qwen-test:8b" and call["stream"] is False and call["format"] == coach.WEEKLY_SCHEMA
    assert [m["role"] for m in call["messages"]] == ["system", "user"]
    sent = json.loads(call["messages"][1]["content"])["facts"]
    assert sent["games_this_week"] == 0
    latest = c.latest()
    assert latest["headline"] == "Quiet week." and latest["model"] == "qwen-test:8b"


async def test_coach_status_and_errors(conn):
    fake = FakeOllama({})
    c = coach.Coach(conn, None, lambda: False, fake.client())
    st = await c.status()
    assert st["running"] and st["models"][0]["params"] == "8B" and st["model"] is None and not st["installed"]
    with pytest.raises(coach.CoachError, match="Choose a local model"):
        await c.weekly()
    _with_model(conn)
    assert (await c.status())["installed"]
    with pytest.raises(coach.CoachError, match="fair-play"):
        await coach.Coach(conn, None, lambda: True, fake.client()).weekly()
    missing = FakeOllama({}, status=404)
    with pytest.raises(coach.CoachError, match="isn't installed"):
        await coach.Coach(conn, None, lambda: False, missing.client()).weekly()

    def down(request):
        raise httpx.ConnectError("refused", request=request)

    off = coach.Ollama("http://ollama.test", httpx.MockTransport(down))
    assert (await coach.Coach(conn, None, lambda: False, off).status())["running"] is False
    with pytest.raises(coach.CoachError, match="isn't running"):
        await coach.Coach(conn, None, lambda: False, off).weekly()
    garbled = FakeOllama("not an object")
    with pytest.raises(coach.CoachError, match="couldn't be read"):
        await coach.Coach(conn, None, lambda: False, garbled.client()).weekly()


async def test_coach_explain_uses_only_engine_lines(conn):
    async def multi(fen, nodes, n):
        b = chess.Board(fen)
        if b.turn == chess.WHITE:
            return [(Eval(cp=35), ["g1f3", "b8c6"]), (Eval(cp=20), ["d2d4"])]
        return [(Eval(cp=-10), ["e7e5"])]

    fake = FakeOllama({"summary": "Nf3 develops.", "points": ["Nf3 Nc6 is +0.35.", "Bb5 pins."]})
    _with_model(conn)
    c = coach.Coach(conn, multi, lambda: False, fake.client())
    out = await c.explain(chess.STARTING_FEN, "a2a3")
    assert out["points"] == ["Nf3 Nc6 is +0.35."] and out["removed"] == 1 and out["played"] == "a3"
    sent = json.loads(fake.calls[0]["messages"][1]["content"])
    assert sent["stockfish_lines"][0] == {"line": ["Nf3", "Nc6"], "eval": "+0.35"}
