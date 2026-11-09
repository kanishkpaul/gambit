"""Batch-analysis throughput: N single-thread Stockfish workers, node-limited."""
import asyncio, sys, time, json, chess, chess.pgn, chess.engine

def positions(path, limit):
    out = []
    with open(path) as f:
        while (g := chess.pgn.read_game(f)) is not None:
            b = g.board()
            for m in g.mainline_moves():
                b.push(m)
                if not b.is_game_over():
                    out.append(b.fen())
            if len(out) >= limit:
                break
    return out[:limit]

async def worker(q, nodes, done):
    _, eng = await chess.engine.popen_uci("stockfish")
    await eng.configure({"Threads": 1, "Hash": 64})
    while True:
        try:
            fen = q.get_nowait()
        except asyncio.QueueEmpty:
            break
        info = await eng.analyse(chess.Board(fen), chess.engine.Limit(nodes=nodes), info=chess.engine.INFO_SCORE)
        done.append((time.perf_counter(), info.get("nodes", nodes)))
    await eng.quit()

async def run(workers, nodes, n):
    fens = positions("results/sample.pgn", n)
    q = asyncio.Queue()
    for f in fens: q.put_nowait(f)
    done = []
    t0 = time.perf_counter()
    await asyncio.gather(*(worker(q, nodes, done) for _ in range(workers)))
    dt = time.perf_counter() - t0
    pps = len(fens) / dt
    res = {"workers": workers, "nodes": nodes, "positions": len(fens), "seconds": round(dt, 1),
           "pos_per_s": round(pps, 2), "est_hours_160k": round(160_000 / pps / 3600, 2)}
    print(json.dumps(res), flush=True)
    return res

if __name__ == "__main__":
    w, nodes, n = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])
    asyncio.run(run(w, nodes, n))
