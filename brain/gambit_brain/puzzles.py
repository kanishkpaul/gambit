"""One-time import of the Lichess puzzle library (CC0), streamed and filtered straight into SQLite.

The 310 MB zstd CSV is decompressed on the fly; nothing is written to disk but the kept rows.
"""

from __future__ import annotations

import asyncio
import csv
import io
import sqlite3
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from typing import Any

import httpx
import zstandard

from . import config
from .db import get_setting, set_setting, tx

Emit = Callable[[dict[str, Any]], Awaitable[None]]
BATCH = 5000


def keep(row: dict[str, str]) -> bool:
    try:
        return (
            int(row["Popularity"]) >= config.PUZZLE_MIN_POPULARITY
            and int(row["NbPlays"]) >= config.PUZZLE_MIN_PLAYS
            and int(row["RatingDeviation"]) <= config.PUZZLE_MAX_RD
            and len(row["Moves"].split()) >= 2
        )
    except (KeyError, ValueError):
        return False


def to_row(r: dict[str, str]) -> tuple:
    return (r["PuzzleId"], r["FEN"], r["Moves"], int(r["Rating"]), int(r["RatingDeviation"]), int(r["Popularity"]),
            int(r["NbPlays"]), r["Themes"], r.get("GameUrl") or None, r.get("OpeningTags") or None)


def insert_rows(conn: sqlite3.Connection, rows: list[tuple]) -> None:
    with tx(conn):
        conn.executemany(
            """INSERT INTO puzzles (id, fen, moves, rating, rd, popularity, plays, themes, game_url, opening)
               VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET rating = excluded.rating, rd = excluded.rd,
                 popularity = excluded.popularity, plays = excluded.plays, themes = excluded.themes""",
            rows,
        )


async def _lines(chunks: AsyncIterator[bytes]) -> AsyncIterator[str]:
    """Decompress a zstd byte stream (possibly several concatenated frames) and yield complete lines."""
    dctx = zstandard.ZstdDecompressor()
    d = dctx.decompressobj()
    raw = b""
    tail = ""
    async for chunk in chunks:
        while chunk:
            raw += d.decompress(chunk)
            chunk = b""
            if d.eof:  # frame boundary: the rest belongs to the next frame
                chunk = d.unused_data
                d = dctx.decompressobj()
        # Split on bytes so a multi-byte character cut across chunks is never mangled.
        cut = raw.rfind(b"\n")
        if cut < 0:
            continue
        text, raw = tail + raw[:cut].decode("utf-8", errors="replace"), raw[cut + 1 :]
        tail = ""
        for line in text.split("\n"):
            yield line
    rest = tail + raw.decode("utf-8", errors="replace")
    if rest:
        yield rest
    if tail:
        yield tail


async def import_rows(conn: sqlite3.Connection, lines: AsyncIterator[str] | Iterable[str],
                      on_batch: Callable[[int, int], Awaitable[None]] | None = None) -> tuple[int, int]:
    """Parse CSV lines (header first), keep the good puzzles, insert in batches. Returns (seen, kept)."""
    header: list[str] | None = None
    seen = kept = 0
    batch: list[tuple] = []

    async def aiter(src):
        if hasattr(src, "__aiter__"):
            async for x in src:
                yield x
        else:
            for x in src:
                yield x

    async for line in aiter(lines):
        if not line.strip():
            continue
        values = next(csv.reader(io.StringIO(line)))
        if header is None:
            header = values
            continue
        seen += 1
        row = dict(zip(header, values, strict=False))
        if keep(row):
            batch.append(to_row(row))
        if len(batch) >= BATCH:
            insert_rows(conn, batch)
            kept += len(batch)
            batch.clear()
            if on_batch:
                await on_batch(seen, kept)
            await asyncio.sleep(0)
    if batch:
        insert_rows(conn, batch)
        kept += len(batch)
    return seen, kept


class PuzzleImport:
    """Background download-and-import with progress events."""

    def __init__(self, conn: sqlite3.Connection, emit: Emit):
        self.conn, self.emit = conn, emit
        self.task: asyncio.Task | None = None
        self.state: dict[str, Any] = {"state": "idle"}

    def status(self) -> dict[str, Any]:
        count = self.conn.execute("SELECT COUNT(*) FROM puzzles").fetchone()[0]
        meta = get_setting(self.conn, "puzzle_library", {}) or {}
        return {**self.state, "count": count, "imported_at": meta.get("imported_at"),
                "download_mb": round(meta.get("bytes", 310_000_000) / 1e6)}

    def start(self, url: str = config.PUZZLE_DB_URL) -> dict[str, Any]:
        if self.task and not self.task.done():
            return self.status()
        self.state = {"state": "running", "received": 0, "total": None, "seen": 0, "kept": 0}
        self.task = asyncio.create_task(self._run(url))
        return self.status()

    async def _run(self, url: str) -> None:
        last = 0.0
        try:
            async with httpx.AsyncClient(headers={"User-Agent": config.USER_AGENT}, timeout=httpx.Timeout(30, read=120),
                                         follow_redirects=True) as http, http.stream("GET", url) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get("Content-Length", 0)) or None
                self.state["total"] = total

                async def chunks() -> AsyncIterator[bytes]:
                    async for c in resp.aiter_bytes(1 << 20):
                        self.state["received"] += len(c)
                        yield c

                async def on_batch(seen: int, kept: int) -> None:
                    nonlocal last
                    self.state.update(seen=seen, kept=kept)
                    if time.monotonic() - last > 1:
                        last = time.monotonic()
                        await self.emit(self.status())

                seen, kept = await import_rows(self.conn, _lines(chunks()), on_batch)
            with tx(self.conn):
                set_setting(self.conn, "puzzle_library", {"imported_at": int(time.time()), "seen": seen, "kept": kept,
                                                          "bytes": total, "etag": resp.headers.get("ETag")})
            self.state = {"state": "done", "seen": seen, "kept": kept}
        except Exception as e:  # network trouble: what was imported stays, and the import can be rerun
            self.state = {**self.state, "state": "error", "error": f"{e.__class__.__name__}: {e}"}
        await self.emit(self.status())
