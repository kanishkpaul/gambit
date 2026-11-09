"""Chess helpers shared by importers, analysis and metrics: PGN walking, keys, phases, scores."""

from __future__ import annotations

import io
import math
from dataclasses import dataclass, field

import chess
import chess.engine
import chess.pgn

from . import config

PIECE_VALUE = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}


def epd(board: chess.Board) -> str:
    """Position key without move counters; en passant only when a capture is actually legal."""
    return board.epd(en_passant="legal")


def majors_minors(board: chess.Board) -> int:
    return sum(
        len(board.pieces(pt, color))
        for pt in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN)
        for color in chess.COLORS
    )


def _backrank_sparse(board: chess.Board) -> bool:
    white = sum(1 for sq in chess.SquareSet(chess.BB_RANK_1) if board.color_at(sq) == chess.WHITE)
    black = sum(1 for sq in chess.SquareSet(chess.BB_RANK_8) if board.color_at(sq) == chess.BLACK)
    return white < 4 or black < 4


def phase(board: chess.Board, ply: int) -> str:
    """Simplified Lichess Divider: material decides the endgame, development the middlegame."""
    mm = majors_minors(board)
    if mm <= config.ENDGAME_MAJORS_MINORS:
        return "endgame"
    if mm <= config.MIDDLEGAME_MAJORS_MINORS or _backrank_sparse(board) or ply > config.OPENING_MAX_PLY:
        return "middlegame"
    return "opening"


def material(board: chess.Board, color: chess.Color) -> int:
    return sum(PIECE_VALUE[p.piece_type] for p in board.piece_map().values() if p.color == color)


# ── Scores ───────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Eval:
    """White-POV evaluation: exactly one of cp / mate is set."""

    cp: int | None = None
    mate: int | None = None

    def clamped(self) -> int:
        if self.mate is not None:
            # Mate in 0 means the side to move is mated; sign carries who wins.
            return config.MATE_CP if self.mate > 0 else -config.MATE_CP
        assert self.cp is not None
        return max(-config.EVAL_CLAMP_CP, min(config.EVAL_CLAMP_CP, self.cp))

    @staticmethod
    def from_pov(score: chess.engine.PovScore) -> Eval:
        w = score.white()
        return Eval(mate=w.mate()) if w.is_mate() else Eval(cp=w.score())


def winning_chance(cp: int) -> float:
    """Lichess's logistic mapping of centipawns to [-1, 1] winning chances."""
    return 2 / (1 + math.exp(-0.00368208 * cp)) - 1


def terminal_eval(board: chess.Board) -> Eval | None:
    if board.is_checkmate():
        # Side to move is mated; only the sign matters (positive = White mates).
        return Eval(mate=-1 if board.turn == chess.WHITE else 1)
    if board.is_stalemate() or board.is_insufficient_material():
        return Eval(cp=0)
    return None


# ── PGN walking ──────────────────────────────────────────────────────────────────────────────────


@dataclass
class ParsedMove:
    ply: int
    color: str
    san: str
    uci: str
    fen_before: str
    epd_before: str
    epd_after: str
    phase: str
    clock_ms: int | None
    spent_ms: int | None
    time_trouble: bool


@dataclass
class ParsedGame:
    headers: dict[str, str]
    moves: list[ParsedMove] = field(default_factory=list)
    # Evaluations embedded by the platform (Lichess server analysis), keyed by EPD after each move.
    embedded: dict[str, Eval] = field(default_factory=dict)
    final_epd: str = ""
    final_terminal: Eval | None = None


def parse_pgn(text: str, base_s: int | None = None, inc_s: int | None = None) -> ParsedGame | None:
    game = chess.pgn.read_game(io.StringIO(text))
    if game is None or game.errors:
        return None
    headers = dict(game.headers)
    if headers.get("SetUp") == "1" or headers.get("Variant", "Standard").lower() not in ("standard", "chess"):
        return None
    out = ParsedGame(headers=headers)
    board = game.board()
    last_clock: dict[bool, float | None] = {chess.WHITE: base_s, chess.BLACK: base_s}
    ply = 0
    for node in game.mainline():
        move = node.move
        ply += 1
        mover = board.turn
        fen_before, epd_before, ph = board.fen(), epd(board), phase(board, ply)
        san = board.san(move)
        board.push(move)
        clock = node.clock()
        spent = None
        if clock is not None and last_clock[mover] is not None:
            spent = max(0.0, last_clock[mover] - clock + (inc_s or 0))
        trouble = clock is not None and bool(base_s) and clock < base_s * config.TIME_TROUBLE_SHARE
        last_clock[mover] = clock if clock is not None else last_clock[mover]
        after = epd(board)
        if (score := node.eval()) is not None:
            out.embedded[after] = Eval.from_pov(score)
        out.moves.append(
            ParsedMove(
                ply=ply,
                color="white" if mover == chess.WHITE else "black",
                san=san,
                uci=move.uci(),
                fen_before=fen_before,
                epd_before=epd_before,
                epd_after=after,
                phase=ph,
                clock_ms=None if clock is None else round(clock * 1000),
                spent_ms=None if spent is None else round(spent * 1000),
                time_trouble=trouble,
            )
        )
    out.final_epd = epd(board)
    out.final_terminal = terminal_eval(board)
    return out


def parse_time_control(tc: str | None) -> tuple[int | None, int | None]:
    """'600+5' → (600, 5); '1/259200' (daily) → (None, None); '-' → (None, None)."""
    if not tc or "/" in tc or tc == "-":
        return None, None
    base, _, inc = tc.partition("+")
    try:
        return int(base), int(inc or 0)
    except ValueError:
        return None, None
