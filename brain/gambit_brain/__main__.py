"""Entry point.

Shell mode (default): the first stdin line is {"port", "ws_token", "lichess_token"?}.
Dev mode (`--dev`): port 8765, token "dev", Lichess token from $GAMBIT_LICHESS_TOKEN, so the UI can
run in a normal browser against `npm run dev`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys

from .server import serve

DEV_PORT = 8765


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="brain %(levelname)s %(name)s: %(message)s", stream=sys.stderr)
    if "--dev" in sys.argv:
        secrets = {k: v for k, v in {"lichess_token": os.environ.get("GAMBIT_LICHESS_TOKEN")}.items() if v}
        asyncio.run(serve(DEV_PORT, "dev", secrets, watch_stdin=False))
        return
    init = json.loads(sys.stdin.readline())
    secrets = {k: init[k] for k in ("lichess_token",) if init.get(k)}
    asyncio.run(serve(int(init["port"]), init["ws_token"], secrets, watch_stdin=True))


if __name__ == "__main__":
    main()
