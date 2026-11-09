"""Round-trip latency for legal-move requests, idle and with 4 Stockfish workers busy."""
import asyncio, json, subprocess, sys, time, secrets, statistics as st, socket
from pathlib import Path
import websockets

HERE = Path(__file__).parent
FENS = ["r1bq1rk1/pp2bppp/2n1pn2/3p4/2PP4/2N2N2/PP2BPPP/R2QKB1R w KQ - 0 9",
        "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
        "8/5pk1/6p1/8/3R4/6P1/5PK1/3r4 w - - 0 40"]


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


async def measure(ws, n=500):
    lat = []
    for i in range(n):
        t = time.perf_counter()
        await ws.send(json.dumps({"id": i, "method": "legal", "params": {"fen": FENS[i % 3]}}))
        await ws.recv()
        lat.append((time.perf_counter() - t) * 1000)
    q = lambda p: round(sorted(lat)[int(p * (len(lat) - 1))], 2)
    return {"p50_ms": round(st.median(lat), 2), "p99_ms": q(0.99), "max_ms": round(max(lat), 2)}


async def main():
    port, token = free_port(), secrets.token_urlsafe(16)
    proc = subprocess.Popen([sys.executable, str(HERE / "brain.py")], stdin=subprocess.PIPE, text=True)
    proc.stdin.write(json.dumps({"port": port, "token": token}) + "\n"); proc.stdin.flush()
    await asyncio.sleep(1.0)
    async with websockets.connect(f"ws://127.0.0.1:{port}/?t={token}") as ws:
        idle = await measure(ws)
        await ws.send(json.dumps({"id": "l", "method": "load", "params": {"engines": 4}})); await ws.recv()
        await asyncio.sleep(2)
        busy = await measure(ws)
    proc.stdin.close(); proc.wait(timeout=5)
    out = {"idle": idle, "with_4_stockfish": busy}
    print(json.dumps(out))
    (HERE.parents[1] / "bench" / "results" / "brain_rtt.json").write_text(json.dumps(out, indent=2))


asyncio.run(main())
