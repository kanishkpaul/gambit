import json
import random
import time

import chess
import pytest

from gambit_brain import config, db, games, importers, puzzles, solve
from gambit_brain.solve import Solver

from .conftest import chesscom_game

HEADER = "PuzzleId,FEN,Moves,Rating,RatingDeviation,Popularity,NbPlays,Themes,GameUrl,OpeningTags,DailyDate"
ROWS = [
    # Real Lichess puzzles. 00008: a 3-move crushing line; 0000D: 2 moves.
    "00008,r6k/pp2r2p/4Rp1Q/3p4/8/1N1P2R1/PqP2bPP/7K b - - 0 24,f2g3 e6e7 b2b1 b3c1 b1c1 h6c1,1219,77,95,10446,"
    "crushing hangingPiece long middlegame,https://lichess.org/787zsVup/black#48,,",
    "0000D,5rk1/1p3ppp/pq3b2/8/8/1P1Q1N2/P4PPP/3R2K1 w - - 2 27,d3d6 f8d8 d6d8 f6d8,1233,75,96,37700,"
    "advantage endgame short fork,https://lichess.org/F8M8OS71#53,,",
    # Mate in one with two mating moves (Qh7# and Qg7#... only one is in the solution).
    "MATE1,6k1/5ppp/8/8/8/8/5PPP/1Q4K1 b - - 0 1,h7h6 b1b8,1180,80,95,5000,mate mateIn1 oneMove,,,",
    # Filtered out: too few plays.
    "RARE1,6k1/5ppp/8/8/8/8/5PPP/1Q4K1 b - - 0 1,h7h6 b1b8,1200,80,95,12,mate mateIn1,,,",
]


async def load(conn):
    return await puzzles.import_rows(conn, [HEADER, *ROWS])


async def test_import_filters_and_upserts(conn):
    seen, kept = await load(conn)
    assert (seen, kept) == (4, 3)
    assert conn.execute("SELECT rating FROM puzzles WHERE id = '00008'").fetchone()[0] == 1219
    await load(conn)  # idempotent
    assert conn.execute("SELECT COUNT(*) FROM puzzles").fetchone()[0] == 3


async def test_streaming_decompression():
    import zstandard

    text = "\n".join([HEADER, *ROWS]) + "\n"
    half = len(text) // 2
    # Two concatenated frames, like the real file, split mid-line.
    c = zstandard.ZstdCompressor()
    blob = c.compress(text[:half].encode()) + c.compress(text[half:].encode())

    async def chunks():
        for i in range(0, len(blob), 37):
            yield blob[i : i + 37]

    lines = [line async for line in puzzles._lines(chunks())]
    assert lines[0] == HEADER and len(lines) == 5


async def _start(conn, mode="standard", live=None):
    s = Solver(conn, live)
    s.start(mode, random.Random(1))
    return s


async def _solve_current(s, wrong=False):
    """Play the stored solution (or a wrong move) through the public API."""
    nxt = s.next()
    item = s.session.current.item
    board = chess.Board(nxt["fen"])
    if nxt["lead_uci"]:
        board.push_uci(nxt["lead_uci"])
    sol = item["solution"].split()
    if wrong:
        bad = next(m.uci() for m in board.legal_moves if m.uci() != sol[0] and not _mates(board, m))
        return await s.move(item["id"], bad, "sure", "", 5000)
    res = None
    for i in range(0, len(sol), 2):
        res = await s.move(item["id"], sol[i], "sure", "the line", 5000)
        if res["done"]:
            break
        assert res["reply_uci"] == sol[i + 1]
    return res


def _mates(board, m):
    board.push(m)
    try:
        return board.is_checkmate()
    finally:
        board.pop()


async def test_payload_never_leaks_the_answer(conn):
    await load(conn)
    s = await _start(conn)
    p = s.next()
    blob = json.dumps(p)
    for key in ("solution", "themes", "rating", "source"):
        assert key not in p
    for row in ROWS[:3]:
        moves = row.split(",")[2].split()
        assert " ".join(moves[1:]) not in blob


async def test_correct_multi_move_and_fsrs(conn):
    await load(conn)
    s = await _start(conn)
    res = await _solve_current(s)
    assert res["result"] == "solved" and res["done"]
    rev = res["reveal"]
    assert rev["solution_san"] and rev["themes"] and rev["source"]["kind"] == "puzzle"
    assert rev["next_review_days"] is not None
    card = conn.execute("SELECT * FROM cards").fetchone()
    assert card is not None and card["due"] > time.time()
    r = conn.execute("SELECT * FROM reviews").fetchone()
    assert (r["correct"], r["confidence"], r["first_seen"], r["grade"]) == (1, "sure", 1, 4)  # sure + fast = Easy
    assert solve.solve_rating(conn)["n"] == 1


async def test_wrong_answer_is_again_and_confident_miss(conn):
    await load(conn)
    s = await _start(conn)
    res = await _solve_current(s, wrong=True)
    assert res["result"] == "wrong" and res["confident_miss"]
    assert conn.execute("SELECT grade FROM reviews").fetchone()[0] == 1
    # Relearning: due again in about ten minutes, not instantly.
    due = conn.execute("SELECT due FROM cards").fetchone()[0]
    assert 5 * 60 < due - time.time() < 20 * 60


async def test_illegal_and_stale_moves_are_rejected(conn):
    await load(conn)
    s = await _start(conn)
    p = s.next()
    with pytest.raises(ValueError):
        await s.move(p["item_id"], "a1a8")
    with pytest.raises(ValueError):
        await s.move(p["item_id"] + 999, "e2e4")


async def test_any_mate_solves_a_mate_puzzle(conn):
    with db.tx(conn):
        conn.execute(
            "INSERT INTO items (kind, ref, fen, lead_uci, solution, themes, rating, created_at) "
            "VALUES ('puzzle', 'M2', '6k1/5ppp/8/8/8/8/5PPP/RR4K1 w - - 0 1', NULL, 'a1a8', '[\"mateIn1\"]', 900, 0)")
    s = Solver(conn)
    s.start("standard", random.Random(0))
    p = s.next()
    res = await s.move(p["item_id"], "b1b8", "unsure")  # a different back-rank mate
    assert res["result"] == "solved"


async def test_speed_mode_keeps_cards_and_rating_untouched(conn):
    await load(conn)
    s = await _start(conn, "speed")
    await _solve_current(s)
    assert conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 0
    assert conn.execute("SELECT mode, grade FROM reviews").fetchone()[:] == ("speed", None)
    assert solve.solve_rating(conn)["n"] == 0


async def test_timebox_ends_the_set(conn):
    await load(conn)
    s = await _start(conn)
    s.session.started_at -= (config.SOLVE_TIMEBOX_MIN + 1) * 60
    out = s.next()
    assert out["done"] and out["reason"] == "timebox" and s.session is None


def test_interleave_avoids_repeats():
    items = [{"id": i, "theme": "fork" if i < 5 else "pin", "turn": "white"} for i in range(10)]
    out = solve.interleave(items, random.Random(3))
    assert all(out[i]["theme"] != out[i + 1]["theme"] for i in range(len(out) - 1))


def test_grade_mapping():
    assert solve.grade(False, "sure", 1000) == solve.Rating.Again
    assert solve.grade(True, "guess", 1000) == solve.Rating.Hard
    assert solve.grade(True, "unsure", 1000) == solve.Rating.Good
    assert solve.grade(True, "sure", 60_000) == solve.Rating.Good
    assert solve.grade(True, "sure", 3_000) == solve.Rating.Easy


def _seed_own_blunder(conn):
    """The test game's 5. Qb3?? marked as a deep-checked blunder with an engine best move."""
    gid = games.store(conn, importers.chesscom_meta(chesscom_game(), "me"))
    m = conn.execute("SELECT * FROM moves WHERE game_id = ? AND ply = 9", (gid,)).fetchone()
    conn.execute(
        "UPDATE moves SET class = 'blunder', motifs = '[\"hung_piece\"]' WHERE game_id = ? AND ply = 9", (gid,))
    conn.execute("UPDATE games SET analysed_at = 1, deep_at = 1 WHERE id = ?", (gid,))
    conn.execute("INSERT INTO evals (epd, cp, best_uci, pv, nodes, source, updated_at) "
                 "VALUES (?, 50, 'f3e2', 'f3e2 d4c2', 1000000, 'sf', 0)", (m["epd_before"],))
    return gid, m


async def test_own_items_with_mirror_and_live_check(conn):
    gid, m = _seed_own_blunder(conn)
    assert solve.sync_own_items(conn) == 2
    assert solve.sync_own_items(conn) == 0
    own = conn.execute("SELECT * FROM items WHERE kind = 'own' ORDER BY ref").fetchall()
    assert [o["ref"] for o in own] == [f"{gid}:9", f"{gid}:9:m"]
    # The lead-in is the opponent's previous move; the mirrored twin has Black to move.
    assert own[0]["lead_uci"] == "g8f6" and solve._turn_after_lead(own[1]["fen"], own[1]["lead_uci"]) == "black"
    assert own[1]["solution"] == "f6e7"

    checked = []

    async def live(fen, uci):
        checked.append(uci)
        return 30  # within the acceptance margin

    s = Solver(conn, live)
    s.start("standard", random.Random(0))
    p = s.next()
    item = s.session.current.item
    board = chess.Board(p["fen"])
    board.push_uci(p["lead_uci"])
    alt = next(mv.uci() for mv in board.legal_moves if mv.uci() != item["solution"])
    res = await s.move(p["item_id"], alt, "unsure")
    assert res["result"] == "solved" and checked == [alt]
    assert res["reveal"]["source"]["kind"] == "own" and res["reveal"]["source"]["move_number"] == 5
