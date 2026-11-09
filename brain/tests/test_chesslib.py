import chess

from gambit_brain import chesslib
from gambit_brain.chesslib import Eval

from .conftest import BLUNDER_PGN


def test_parse_pgn_clocks_spent_and_trouble():
    g = chesslib.parse_pgn(BLUNDER_PGN, 600, 0)
    assert g is not None and len(g.moves) == 16
    first = g.moves[0]
    assert (first.san, first.uci, first.color, first.clock_ms, first.spent_ms) == ("e4", "e2e4", "white", 598000, 2000)
    # 5. Qb3 with 50 s left of 600 s is time trouble (< 10 %).
    qb3 = g.moves[8]
    assert qb3.san == "Qb3" and qb3.time_trouble and not g.moves[7].time_trouble
    assert g.moves[0].phase == "opening"


def test_parse_pgn_embedded_lichess_evals():
    pgn = '[Event "x"]\n[Result "*"]\n\n1. e4 { [%eval 0.3] [%clk 0:05:00] } 1... e5 { [%eval #-2] } *'
    g = chesslib.parse_pgn(pgn, 300, 3)
    b = chess.Board()
    b.push_san("e4")
    assert g.embedded[chesslib.epd(b)] == Eval(cp=30)
    b.push_san("e5")
    assert g.embedded[chesslib.epd(b)] == Eval(mate=-2)


def test_parse_rejects_custom_setups():
    assert chesslib.parse_pgn('[SetUp "1"]\n[FEN "8/8/8/8/8/8/8/K6k w - - 0 1"]\n\n*') is None


def test_eval_clamping_and_terminal():
    assert Eval(cp=2500).clamped() == 1000
    assert Eval(mate=-3).clamped() == -1000
    mated = chess.Board("rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3")
    assert chesslib.terminal_eval(mated) == Eval(mate=-1)


def test_phase_and_time_control():
    assert chesslib.phase(chess.Board(), 1) == "opening"
    assert chesslib.phase(chess.Board("4k3/8/8/8/8/8/4P3/R3K3 w - - 0 40"), 79) == "endgame"
    assert chesslib.parse_time_control("180+2") == (180, 2)
    assert chesslib.parse_time_control("1/259200") == (None, None)
