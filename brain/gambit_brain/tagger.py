"""Motif tagging for your errors: why a move lost material or the game.

A starter tagger for the error tail (hung pieces, forks, pins, mates). It reads the engine's
refutation line after the move and the best line before it. The fuller lichess-puzzler tagger
is vendored with Solve (v0.2), where puzzle themes need to match Lichess's.
"""

from __future__ import annotations

import chess

from .chesslib import PIECE_VALUE, Eval, material

MOTIFS = {
    "allowed_mate": "Allowed a forced mate",
    "back_rank": "Back-rank weakness",
    "missed_mate": "Missed a forced mate",
    "hung_piece": "Left a piece hanging",
    "fork": "Walked into a fork",
    "pin": "Walked into a pin",
    "discovered_attack": "Missed a discovered attack",
    "missed_capture": "Missed a free capture",
    "lost_material": "Lost material to a combination",
    "positional": "Error with no quick tactic",
}


def _mover_pov(e: Eval | None, mover: chess.Color) -> Eval | None:
    if e is None:
        return None
    sign = 1 if mover == chess.WHITE else -1
    return Eval(cp=None if e.cp is None else sign * e.cp, mate=None if e.mate is None else sign * e.mate)


def _wins_material(board: chess.Board, move: chess.Move) -> bool:
    """Does `move` capture something that isn't adequately defended? (A one-step exchange check.)"""
    if not board.is_capture(move):
        return False
    victim = board.piece_at(move.to_square)
    if victim is None:  # en passant
        return False
    attacker = board.piece_at(move.from_square)
    assert attacker is not None
    gain = PIECE_VALUE[victim.piece_type]
    if gain == 0:
        return False
    after = board.copy(stack=False)
    after.push(move)
    defended = bool(after.attackers(after.turn, move.to_square))
    return not defended or gain > PIECE_VALUE[attacker.piece_type]


def _forks(board: chess.Board, move: chess.Move) -> bool:
    """After `move`, does the moved piece attack two targets worth more than itself (or king + piece)?"""
    piece = board.piece_at(move.from_square)
    if piece is None:
        return False
    after = board.copy(stack=False)
    after.push(move)
    victim_color = after.turn
    own = PIECE_VALUE[piece.piece_type] or 100
    targets = 0
    for sq in after.attacks(move.to_square):
        p = after.piece_at(sq)
        if p is None or p.color != victim_color:
            continue
        if p.piece_type == chess.KING:
            targets += 1
        elif PIECE_VALUE[p.piece_type] > own or not after.attackers(victim_color, sq):
            if PIECE_VALUE[p.piece_type] >= 3:
                targets += 1
    # The forking piece must not simply be lost for free.
    safe = not after.attackers(victim_color, move.to_square) or own <= 3
    return targets >= 2 and safe


def _new_pin(before: chess.Board, after: chess.Board, victim: chess.Color) -> bool:
    for sq in chess.SquareSet(after.occupied_co[victim]):
        p = after.piece_at(sq)
        if p is None or p.piece_type in (chess.KING, chess.PAWN):
            continue
        if after.is_pinned(victim, sq) and not before.is_pinned(victim, sq):
            return True
    return False


def _discovered(board: chess.Board, move: chess.Move) -> bool:
    """Does `move` uncover a slider attack (by another piece) on a king or a piece worth ≥ 3?"""
    attacker_color = board.turn
    victim_color = not attacker_color
    after = board.copy(stack=False)
    after.push(move)
    for sq in chess.SquareSet(after.occupied_co[victim_color]):
        p = after.piece_at(sq)
        if p is None or (p.piece_type != chess.KING and PIECE_VALUE[p.piece_type] < 3):
            continue
        new = after.attackers(attacker_color, sq) & ~board.attackers(attacker_color, sq)
        new &= ~chess.BB_SQUARES[move.to_square]
        if new:
            return True
    return False


def _play(board: chess.Board, pv: list[str], plies: int) -> chess.Board:
    b = board.copy(stack=False)
    for uci in pv[:plies]:
        mv = chess.Move.from_uci(uci)
        if mv not in b.legal_moves:
            break
        b.push(mv)
    return b


def tag(
    board_before: chess.Board,
    move: chess.Move,
    eval_before: Eval | None,
    pv_before: list[str],
    eval_after: Eval | None,
    pv_after: list[str],
) -> list[str]:
    """Motifs for one erroneous move. `pv_after` is the opponent's best line after the move."""
    mover = board_before.turn
    eb, ea = _mover_pov(eval_before, mover), _mover_pov(eval_after, mover)
    tags: list[str] = []

    if ea is not None and ea.mate is not None and ea.mate < 0 and not (eb and eb.mate is not None and eb.mate < 0):
        tags.append("allowed_mate")
        end = _play(_play(board_before, [move.uci()], 1), pv_after, 12)
        if end.is_checkmate():
            king = end.king(end.turn)
            back = chess.BB_RANK_1 if end.turn == chess.WHITE else chess.BB_RANK_8
            checkers = [end.piece_at(s) for s in end.checkers()]
            if king is not None and chess.BB_SQUARES[king] & back and any(
                c and c.piece_type in (chess.ROOK, chess.QUEEN) for c in checkers
            ):
                tags.append("back_rank")
    if eb is not None and eb.mate is not None and eb.mate > 0 and not (ea and ea.mate is not None and ea.mate > 0):
        tags.append("missed_mate")

    after = board_before.copy(stack=False)
    after.push(move)
    if pv_after:
        reply = chess.Move.from_uci(pv_after[0])
        if reply in after.legal_moves:
            if _wins_material(after, reply):
                tags.append("hung_piece")
            if _forks(after, reply):
                tags.append("fork")
            if _discovered(after, reply):
                tags.append("discovered_attack")
            replied = after.copy(stack=False)
            replied.push(reply)
            if _new_pin(after, replied, mover):
                tags.append("pin")
        # Material lost over the next few plies, from the mover's side.
        line_end = _play(after, pv_after, 5)
        swing = (material(after, mover) - material(after, not mover)) - (
            material(line_end, mover) - material(line_end, not mover)
        )
        if swing >= 2 and not {"hung_piece", "fork", "pin", "discovered_attack"} & set(tags):
            tags.append("lost_material")

    if pv_before:
        best = chess.Move.from_uci(pv_before[0])
        if best != move and best in board_before.legal_moves and _wins_material(board_before, best):
            tags.append("missed_capture")

    return tags or ["positional"]
