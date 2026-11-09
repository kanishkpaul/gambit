"""Spike brain: JSON-RPC over a localhost WebSocket, with a stdin lifeline.

Init: one JSON line on stdin {"port": int, "token": str}. stdin EOF or a
changed parent PID shuts the brain down, Stockfish children included.
"""
import asyncio, json, os, sys, time, threading, signal
from pathlib import Path
import chess, chess.engine
import websockets

RESULTS = Path(__file__).resolve().parents[2] / "bench" / "results"
engines: list[chess.engine.UciProtocol] = []
load_tasks: list[asyncio.Task] = []


def legal(fen: str) -> dict:
    b = chess.Board(fen)
    dests: dict[str, list[str]] = {}
    san: dict[str, str] = {}
    for m in b.legal_moves:
        dests.setdefault(chess.square_name(m.from_square), []).append(chess.square_name(m.to_square))
        san[m.uci()] = b.san(m)
    return {"dests": dests, "san": san, "turn": "white" if b.turn else "black"}


async def spin(engine: chess.engine.UciProtocol):
    board = chess.Board("r1bq1rk1/pp2bppp/2n1pn2/3p4/2PP4/2N2N2/PP2BPPP/R2QKB1R w KQ - 0 9")
    while True:
        await engine.analyse(board, chess.engine.Limit(nodes=2_000_000))


async def start_load(n: int) -> dict:
    for _ in range(n):
        _, eng = await chess.engine.popen_uci("stockfish")
        await eng.configure({"Threads": 1, "Hash": 64})
        engines.append(eng)
        load_tasks.append(asyncio.create_task(spin(eng)))
    return {"engines": len(engines)}


async def handle(ws, token: str):
    if ws.request.path != f"/?t={token}":
        await ws.close(code=4401, reason="bad token")
        return
    async for raw in ws:
        msg = json.loads(raw)
        method, params, mid = msg["method"], msg.get("params", {}), msg.get("id")
        if method == "ping":
            result = {"t": time.time()}
        elif method == "legal":
            result = legal(params["fen"])
        elif method == "load":
            result = await start_load(params.get("engines", 4))
        elif method == "report":
            RESULTS.mkdir(parents=True, exist_ok=True)
            (RESULTS / params["name"]).write_text(json.dumps(params["data"], indent=2))
            result = {"saved": params["name"]}
        else:
            result = {"error": f"unknown method {method}"}
        await ws.send(json.dumps({"id": mid, "result": result}))


def shutdown(reason: str):
    print(f"brain: shutting down ({reason})", file=sys.stderr, flush=True)
    for eng in engines:
        try:
            eng.transport.kill()
        except Exception:
            pass
    os._exit(0)


def lifelines():
    parent = os.getppid()
    def stdin_watch():
        for _ in sys.stdin:
            pass
        shutdown("stdin EOF")
    def ppid_watch():
        while True:
            if os.getppid() != parent:
                shutdown("parent changed")
            time.sleep(0.5)
    threading.Thread(target=stdin_watch, daemon=True).start()
    threading.Thread(target=ppid_watch, daemon=True).start()


async def main():
    init = json.loads(sys.stdin.readline())
    lifelines()
    signal.signal(signal.SIGTERM, lambda *_: shutdown("SIGTERM"))
    async with websockets.serve(lambda ws: handle(ws, init["token"]), "127.0.0.1", init["port"]):
        print(f"brain: ready on {init['port']}", file=sys.stderr, flush=True)
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
