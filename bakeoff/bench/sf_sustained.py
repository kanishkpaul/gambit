"""Sustained throughput: 4 single-thread workers at 300k nodes for 10 minutes, logged per minute."""
import asyncio, time, json, itertools, chess, chess.engine
from sf_batch import positions
DURATION, WORKERS, NODES = 600, 4, 300_000
fens = itertools.cycle(positions("results/sample.pgn", 3000))
done = []
async def worker(stop):
    _, eng = await chess.engine.popen_uci("stockfish"); await eng.configure({"Threads": 1, "Hash": 64})
    while time.perf_counter() < stop:
        await eng.analyse(chess.Board(next(fens)), chess.engine.Limit(nodes=NODES)); done.append(time.perf_counter())
    await eng.quit()
async def main():
    t0 = time.perf_counter(); await asyncio.gather(*(worker(t0 + DURATION) for _ in range(WORKERS)))
    per_min = [sum(1 for t in done if t0 + 60*m <= t < t0 + 60*(m+1)) / 60 for m in range(DURATION // 60)]
    out = {"workers": WORKERS, "nodes": NODES, "pos_per_s_by_minute": [round(x, 2) for x in per_min]}
    print(json.dumps(out)); open("results/sf_sustained.json", "w").write(json.dumps(out, indent=2))
asyncio.run(main())
