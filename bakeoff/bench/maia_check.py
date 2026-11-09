"""Sanity check: Maia-3-23M top-1 match vs moves actually played (uses PGN Elo)."""
import json, time, torch, chess, chess.pgn
from collections import deque
from maia_bench import setup, tokens_for
from maia3.uci import get_all_possible_moves, mirror_move
from maia3.dataset import get_legal_moves_mask
cfg, model, _ = setup("maia3-23m", "cpu")
moves = get_all_possible_moves(); idx = {m: i for i, m in enumerate(moves)}
hit = n = 0
with torch.no_grad(), open("results/sample.pgn") as f:
    while (g := chess.pgn.read_game(f)) and n < 1500:
        we, be = int(g.headers.get("WhiteElo", 1500)), int(g.headers.get("BlackElo", 1500))
        b = g.board()
        for mv in g.mainline_moves():
            se, oe = (we, be) if b.turn else (be, we)
            x = tokens_for(cfg, b.fen()).unsqueeze(0)
            logits = model(x, torch.tensor([se]), torch.tensor([oe]))[0][0]
            logits = logits.masked_fill(~get_legal_moves_mask(b, idx), float("-inf"))
            u = moves[int(logits.argmax())]
            if b.turn == chess.BLACK: u = mirror_move(u)
            hit += (u == mv.uci()); n += 1
            b.push(mv)
print(json.dumps({"model": "maia3-23m", "positions": n, "top1_match": round(hit / n, 3)}))
