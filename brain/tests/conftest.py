import os
import shutil

import pytest

from gambit_brain import db

HAS_STOCKFISH = shutil.which(os.environ.get("GAMBIT_STOCKFISH", "stockfish")) is not None


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("GAMBIT_DATA_DIR", str(tmp_path))
    c = db.connect(tmp_path / "test.sqlite")
    yield c
    c.close()


# A short Chess.com-style game with clocks: White (me) hangs the queen on move 4.
BLUNDER_PGN = """[Event "Live Chess"]
[Site "Chess.com"]
[White "me"]
[Black "opp"]
[Result "0-1"]
[ECO "C20"]
[TimeControl "600"]

1. e4 {[%clk 0:09:58]} 1... e5 {[%clk 0:09:57]} 2. Qh5 {[%clk 0:09:50]} 2... Nc6 {[%clk 0:09:49]}
3. Bc4 {[%clk 0:09:40]} 3... g6 {[%clk 0:09:30]} 4. Qf3 {[%clk 0:09:20]} 4... Nf6 {[%clk 0:09:10]}
5. Qb3 {[%clk 0:00:50]} 5... Nd4 {[%clk 0:09:00]} 6. Bxf7+ {[%clk 0:00:40]} 6... Ke7 {[%clk 0:08:50]}
7. Qc4 {[%clk 0:00:30]} 7... b5 {[%clk 0:08:40]} 8. Qxc7 {[%clk 0:00:20]} 8... Qxc7 {[%clk 0:08:30]} 0-1
"""


def chesscom_game(pgn=BLUNDER_PGN, uuid="g1", end_time=1_700_000_000, my="me", result="resigned",
                  rating=800, opp_rating=820, time_class="rapid", rated=True):
    win = {"resigned": "win", "win": "resigned", "agreed": "agreed"}[result]
    return {
        "url": f"https://www.chess.com/game/live/{uuid}", "pgn": pgn, "time_control": "600",
        "end_time": end_time, "rated": rated, "uuid": uuid, "initial_setup": "", "time_class": time_class,
        "rules": "chess", "eco": "https://www.chess.com/openings/Kings-Pawn-Opening-Wayward-Queen-Attack-2...Nc6",
        "white": {"username": my, "rating": rating, "result": result},
        "black": {"username": "opp", "rating": opp_rating, "result": win},
    }
