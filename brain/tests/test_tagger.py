import chess

from gambit_brain.analysis import classify
from gambit_brain.chesslib import Eval
from gambit_brain.tagger import tag


def test_classify_thresholds():
    assert classify(Eval(cp=20), Eval(cp=-250), True, False)[2] == "blunder"
    assert classify(Eval(cp=20), Eval(cp=-100), True, False)[2] == "mistake"
    assert classify(Eval(cp=20), Eval(cp=-40), True, False)[2] == "inaccuracy"
    assert classify(Eval(cp=20), Eval(cp=0), True, False)[2] == "ok"
    # Black's point of view: White-POV eval rising is Black's loss.
    assert classify(Eval(cp=0), Eval(cp=300), False, False)[2] == "blunder"
    # Still clearly winning after the move: never an error.
    assert classify(Eval(cp=900), Eval(cp=500), True, False)[2] == "ok"
    assert classify(Eval(cp=10), Eval(cp=-500), True, True)[2] == "best"
    # Allowing mate from equality is a blunder.
    cp_loss, wc, cls = classify(Eval(cp=0), Eval(mate=-2), True, False)
    assert cls == "blunder" and cp_loss == 1000 and 0 < wc <= 1


def test_hung_piece():
    # Ba6?? drops the bishop to the b7 pawn.
    board = chess.Board("rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2")
    move = chess.Move.from_uci("f1a6")
    tags = tag(board, move, Eval(cp=30), [], Eval(cp=-300), ["b7a6"])
    assert "hung_piece" in tags


def test_fork():
    # ...b6?? lets the d5 knight jump to c7 with check, forking king and rook.
    board = chess.Board("r3k3/1p6/8/3N4/8/8/8/4K3 b - - 0 1")
    tags = tag(board, chess.Move.from_uci("b7b6"), Eval(cp=-300), [], Eval(cp=-800), ["d5c7"])
    assert "fork" in tags


def test_allowed_mate_back_rank():
    # White's king is boxed in on g1; Rc2?? gives up the first rank and ...Rd1 is mate.
    board = chess.Board("3r2k1/5ppp/8/8/8/8/P4PPP/2R3K1 w - - 0 1")
    move = chess.Move.from_uci("c1c2")
    tags = tag(board, move, Eval(cp=0), [], Eval(mate=-1), ["d8d1"])
    assert "allowed_mate" in tags and "back_rank" in tags


def test_missed_mate_and_missed_capture():
    board = chess.Board("6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1")
    tags = tag(board, chess.Move.from_uci("g1f1"), Eval(mate=1), ["a1a8"], Eval(cp=50), [])
    assert "missed_mate" in tags
    board = chess.Board("4k3/8/8/3q4/8/8/3R4/4K3 w - - 0 1")
    tags = tag(board, chess.Move.from_uci("e1f1"), Eval(cp=900), ["d2d5"], Eval(cp=-400), [])
    assert "missed_capture" in tags


def test_positional_fallback():
    assert tag(chess.Board(), chess.Move.from_uci("g2g4"), Eval(cp=20), [], Eval(cp=-110), []) == ["positional"]
