"""Maia-3 latency: batch 1 and 64, CPU vs MPS, per model size."""
import sys, time, json, statistics as st, os, resource
import torch, chess, chess.pgn
from collections import deque
from maia3.uci import parse_args, load_model
from maia3.model_registry import resolve_checkpoint_path
from maia3.dataset import tokenize_board, get_historical_tokens

def fens(n):
    out = []
    with open("results/sample.pgn") as f:
        while (g := chess.pgn.read_game(f)) and len(out) < n:
            b = g.board()
            for m in g.mainline_moves():
                b.push(m)
                if not b.is_game_over(): out.append(b.fen())
    return out[:n]

def setup(alias, device):
    cfg = parse_args(["--model", alias, "--device", device])
    cfg.checkpoint_path = resolve_checkpoint_path(cfg.model_spec, checkpoint_filename=cfg.checkpoint_filename,
        cache_dir=cfg.cache_dir, revision=cfg.revision, local_files_only=False, force_download=False, token=None)
    t = time.perf_counter(); model = load_model(cfg); load_s = time.perf_counter() - t
    return cfg, model, load_s

def tokens_for(cfg, fen):
    h = deque([tokenize_board(chess.Board(fen))], maxlen=cfg.history)
    return get_historical_tokens(h, cfg, base=0.0, inc=0.0, clk_left_before=0.0, clk_ponder=0.0)

@torch.no_grad()
def bench(alias, device, positions):
    cfg, model, load_s = setup(alias, device)
    toks = [tokens_for(cfg, f) for f in positions]
    def run(batch):
        x = torch.stack(batch).to(device)
        e = torch.full((len(batch),), 1500, dtype=torch.long, device=device)
        out = model(x, e, e)[0]
        if device == "mps": torch.mps.synchronize()
        return out
    for _ in range(5): run(toks[:1])  # warm-up
    lat1 = []
    for t in toks[:200]:
        s = time.perf_counter(); run([t]); lat1.append((time.perf_counter() - s) * 1000)
    run(toks[:64])
    lat64 = []
    for i in range(0, 640, 64):
        s = time.perf_counter(); run(toks[i:i+64]); lat64.append((time.perf_counter() - s) * 1000)
    q = lambda xs, p: sorted(xs)[int(p * (len(xs) - 1))]
    return {"model": alias, "device": device, "load_s": round(load_s, 2),
            "b1_p50_ms": round(st.median(lat1), 2), "b1_p95_ms": round(q(lat1, .95), 2),
            "b64_p50_ms": round(st.median(lat64), 1), "pos_per_s_b64": round(64000 / st.median(lat64), 0),
            "maxrss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6, 0)}

if __name__ == "__main__":
    os.environ.pop("PYTORCH_ENABLE_MPS_FALLBACK", None)
    alias, device = sys.argv[1], sys.argv[2]
    try:
        print(json.dumps(bench(alias, device, fens(700))), flush=True)
    except Exception as e:
        print(json.dumps({"model": alias, "device": device, "error": repr(e)[:300]}), flush=True)
