"""Maia-3: how humans at a given rating play a position.

Called through the model code (not `maia3-uci`), as the bake-off validated: Maia-3 23M matched
57.2% of real moves, in line with the paper. torch and the weights load lazily on first use, off
the event loop, so the brain still starts in about a second.
"""

from __future__ import annotations

import math
import threading
from collections import deque
from dataclasses import dataclass
from typing import Any

import chess

from . import config


@dataclass
class MoveProfile:
    ply: int
    played: str
    probs: list[float]  # probability of the played move at each level in config.MAIA_LEVELS
    tops: list[str]  # Maia's most likely move at each level


class Maia:
    def __init__(self, alias: str = config.MAIA_ANALYSIS_MODEL, device: str = "cpu"):
        self.alias, self.device = alias, device
        self._lock = threading.Lock()
        self._model: Any = None
        self._cfg: Any = None

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        """Heavy: imports torch and loads weights (from the Hugging Face cache, downloading once)."""
        with self._lock:
            if self._model is not None:
                return
            from maia3.model_registry import resolve_checkpoint_path
            from maia3.uci import get_all_possible_moves, load_model, parse_args

            cfg = parse_args(["--model", self.alias, "--device", self.device])
            cfg.checkpoint_path = resolve_checkpoint_path(
                cfg.model_spec, checkpoint_filename=cfg.checkpoint_filename, cache_dir=cfg.cache_dir,
                revision=cfg.revision, local_files_only=False, force_download=False, token=None)
            self._model = load_model(cfg)
            self._model.eval()
            self._cfg = cfg
            self._moves = get_all_possible_moves()
            self._index = {m: i for i, m in enumerate(self._moves)}

    def unload(self) -> None:
        """Free the weights (the fair-play lock suspends Maia, not just its panels)."""
        with self._lock:
            self._model = None

    def profile_game(self, start_fen: str, ucis: list[str], my_plies: set[int], self_elo_hint: int | None,
                     opp_elo: int, levels: list[int] | None = None) -> list[MoveProfile]:
        """For each of your moves (1-based plies), the probability Maia gives it at every level."""
        import torch
        from maia3.dataset import get_historical_tokens, get_legal_moves_mask, tokenize_board
        from maia3.utils import mirror_move

        self.load()
        levels = levels or list(config.MAIA_LEVELS)
        cfg, model = self._cfg, self._model
        board = chess.Board(start_fen)
        history: deque = deque(maxlen=cfg.history)
        rows: list[tuple[int, str, Any, Any, bool]] = []
        for ply, uci in enumerate(ucis, start=1):
            history.append(tokenize_board(board))
            if ply in my_plies:
                x = get_historical_tokens(deque(history, maxlen=cfg.history), cfg, base=0.0, inc=0.0,
                                          clk_left_before=0.0, clk_ponder=0.0)
                mask = get_legal_moves_mask(board, self._index)
                rows.append((ply, uci, x, mask, board.turn == chess.BLACK))
            board.push_uci(uci)

        out: list[MoveProfile] = []
        n = len(levels)
        per_batch = max(1, config.MAIA_BATCH // n)
        with torch.no_grad():
            for i in range(0, len(rows), per_batch):
                chunk = rows[i : i + per_batch]
                x = torch.stack([r[2] for r in chunk for _ in levels]).to(self.device)
                self_elo = torch.tensor([lv for _ in chunk for lv in levels], dtype=torch.long, device=self.device)
                oppo = torch.full((len(chunk) * n,), opp_elo, dtype=torch.long, device=self.device)
                logits = model(x, self_elo, oppo)[0].float().cpu()
                for j, (ply, uci, _, mask, black) in enumerate(chunk):
                    block = logits[j * n : (j + 1) * n].masked_fill(~mask, float("-inf"))
                    probs = torch.softmax(block, dim=-1)
                    key = mirror_move(uci) if black else uci
                    idx = self._index.get(key)
                    played = [float(probs[k, idx]) if idx is not None else 0.0 for k in range(n)]
                    tops = []
                    for k in range(n):
                        t = self._moves[int(probs[k].argmax())]
                        tops.append(mirror_move(t) if black else t)
                    out.append(MoveProfile(ply, uci, played, tops))
        return out


def sample_move(maia: Maia, start_fen: str, ucis: list[str], self_elo: int, opp_elo: int,
                temperature: float = 1.0, rng: Any = None) -> str:
    """A human-like move, sampled from Maia's policy at `self_elo`. Always playing the single most
    likely move makes a bot stronger than its label (report 07); sampling keeps the human mistakes."""
    import random as _random

    import torch
    from maia3.dataset import get_historical_tokens, get_legal_moves_mask, tokenize_board
    from maia3.utils import mirror_move

    maia.load()
    cfg, model = maia._cfg, maia._model
    board = chess.Board(start_fen)
    history: deque = deque(maxlen=cfg.history)
    for uci in ucis:
        history.append(tokenize_board(board))
        board.push_uci(uci)
    history.append(tokenize_board(board))
    x = get_historical_tokens(history, cfg, base=0.0, inc=0.0, clk_left_before=0.0, clk_ponder=0.0)
    with torch.no_grad():
        logits = model(x.unsqueeze(0).to(maia.device), torch.tensor([self_elo], device=maia.device),
                       torch.tensor([opp_elo], device=maia.device))[0][0].float().cpu()
    logits = logits.masked_fill(~get_legal_moves_mask(board, maia._index), float("-inf"))
    probs = torch.softmax(logits / max(temperature, 1e-3), dim=-1).tolist()
    r = (rng or _random).random()
    acc = 0.0
    pick = max(range(len(probs)), key=lambda i: probs[i])
    for i, p in enumerate(probs):
        acc += p
        if p > 0 and acc >= r:
            pick = i
            break
    uci = maia._moves[pick]
    return mirror_move(uci) if board.turn == chess.BLACK else uci


def band_fit(profiles: list[MoveProfile], levels: list[int] | None = None) -> dict[str, Any] | None:
    """The rating level whose Maia best explains a player's moves (highest log-likelihood).

    Report 02's inference, not a validated diagnostic: show it as a resemblance, never as a rating.
    """
    levels = levels or list(config.MAIA_LEVELS)
    totals = [sum(math.log(max(p.probs[k], 1e-6)) for p in profiles) for k in range(len(levels))]
    return fit_from_totals(totals, len(profiles), levels)


def fit_from_totals(totals: list[float], moves: int, levels: list[int] | None = None) -> dict[str, Any] | None:
    """Best level plus a likelihood interval: every level whose total log-likelihood is within
    config.MAIA_LL_INTERVAL of the best (2.0 ≈ a 95% interval for one parameter). Totals add across
    games, so pooling many games narrows the range honestly."""
    levels = levels or list(config.MAIA_LEVELS)
    if moves < config.MAIA_MIN_MOVES:
        return None
    best = max(range(len(levels)), key=lambda k: totals[k])
    inside = [k for k in range(len(levels)) if totals[k] >= totals[best] - config.MAIA_LL_INTERVAL]
    edge = "low" if best == 0 else "high" if best == len(levels) - 1 else None
    return {"level": levels[best], "lo": levels[min(inside)], "hi": levels[max(inside)], "levels": levels,
            "mean_logp": [round(t / moves, 4) for t in totals], "moves": moves, "edge": edge}


def nearest_level(elo: int, levels: list[int] | None = None) -> int:
    levels = levels or list(config.MAIA_LEVELS)
    return min(range(len(levels)), key=lambda k: abs(levels[k] - elo))
