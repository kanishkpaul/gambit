# Stack bake-off results

Measured on the owner's MacBook Air (Apple M5, 4 performance + 6 efficiency cores, 16 GB, fanless, 60 Hz Retina display), macOS 27, 9 November 2026. Raw numbers are in `bench/results/`.

**Verdict: Tauri 2 + React + Python brain passes every test that could be run without the owner.** The stack stays locked. Three items still need the owner (see the end).

## 1 · Stockfish 19 (Homebrew, official arm64 build)

| Test | Result |
|---|---|
| `bench` (depth 15) | 0.80M nps on 1 thread · 2.75M on 4 · 4.41M on 10 |
| Real game positions, 1 thread | ~0.45M nps (game positions are slower than the bench set) |
| Batch, 4 single-thread workers, 300k nodes | 5.1 positions/s → **~8.6 h for 2,000 games** (~160k positions) |
| Batch, 6 / 10 workers, 300k nodes | 5.0 / 5.6 positions/s (efficiency cores add almost nothing) |
| Batch, 4 workers, 100k nodes | 11.1 positions/s → **~4 h for 2,000 games** |
| Batch, 4 workers, 1.5M nodes (Lichess's budget) | 0.61 positions/s → ~72 h for 2,000 games |
| Sustained 10 min, 4 workers, 300k nodes | 4.7–6.0 positions/s every minute, no downward trend: **no progressive thermal throttling** on the fanless Air |

**Finding:** throughput is roughly 3–10× below the research estimates (which assumed 15–25M nps). The plan must change:

- First pass at **~100k nodes**, 4 workers on the performance cores, overnight. Re-search only critical moments (eval swings, the moments you flag) at 1M+.
- **Skip positions that already have an eval**: Lichess game exports include server analysis when it exists, and the CC0 Lichess eval database covers common positions (especially openings).
- Live analysis (one position, 3 threads) stays interactive: ~1.3M nps.

## 2 · Maia-3 and Maia-2 (PyTorch 2.8, called through model code)

| Model | CPU batch 1 p50 / p95 | GPU (MPS) batch 1 p50 | GPU batch 64 | Memory |
|---|---|---|---|---|
| Maia-3 5M | 3.1 / 3.6 ms | 7.7 ms | 1,616 positions/s | ~290 MB |
| Maia-3 23M | 6.9 / 7.6 ms | 13.3 ms | 564 positions/s | ~390–460 MB |
| Maia-3 79M | 16.9 / 17.2 ms | 33.1 ms | 208 positions/s | ~550 MB (MPS) – 1.1 GB (CPU) |
| Maia-2 rapid | 3.9 / 4.3 ms | 5.3 ms | — | — |

- **Correctness check:** Maia-3 23M matched **57.2%** of 1,502 played moves (sample players averaging ~1736), in line with the paper's 56.6%. The encoding and side-to-move mirroring are right.
- **Sparring:** every model is far under the 150 ms budget. Use **CPU for single moves** (faster than the GPU at batch 1) and **79M for sparring**.
- **Rating-band sweep** (2,000 games × ~40 of your moves × 22 rating levels ≈ 1.8M passes): ~52 min with 23M on the GPU, ~2.4 h with 79M. Fine overnight.
- Python + torch + Maia cold start: ~1.1 s. Models load in under 0.5 s once cached.
- ONNX Runtime was not benchmarked: PyTorch already beats every bar by 10×, so the extra backend isn't worth carrying.
- Maia-2's `device="gpu"` means CUDA; on this Mac pass `device="mps"`.

## 3 · Brain round trip (WebSocket JSON-RPC, "position → legal moves + SAN")

| Condition | p50 | p99 | max |
|---|---|---|---|
| Idle | 0.24 ms | 0.46 ms | 0.81 ms |
| 4 Stockfish workers at 100% | 0.41 ms | 0.73 ms | 1.13 ms |

Pass bar was p99 < 16 ms. **Passes by 20×.**

## 4 · Tauri board spike (`tauri-spike/`)

Tauri 2.12.5, React 19, `@lichess-org/chessground` 10.5.0, chessops, translucent sidebar via `window-vibrancy`, walnut-on-slate board, inner-glow highlights, gold arrows, typed SAN input, 220 ms spring easing. Scripted replay of the Opera Game (33 moves, arrows redrawn each move), rAF frame times:

| Condition | fps | p50 | p95 | p99 | frames > 25 ms |
|---|---|---|---|---|---|
| Idle | 59.9 | 17 ms | 18 ms | 21 ms | 1 of 636 |
| 4 Stockfish workers at 100% | 59.9 | 17 ms | 18 ms | 21 ms | 2 of 635 (max 31 ms) |

- **Passes**: a locked 60 fps under full engine load.
- Shell binary: 8.7 MB (release).
- **chessground motion:** its easing is hard-coded. A 10-line Vite transform swaps in a spring curve (`vite.config.ts`). "Overshoot only on captures" from `DESIGN.md` needs a deeper patch (anim.js would have to know which moves capture); recommend dropping overshoot from the spec.

## 5 · Quit paths (zero orphans required)

| Path | Shell gone | Brain left | Stockfish left |
|---|---|---|---|
| ⌘Q (×3) | yes | 0 | 0 |
| Close window (×3) | yes | 0 | 0 |
| SIGTERM to shell | yes | 0 | 0 |
| `kill -9` on shell | yes | 0 | 0 |

The stdin lifeline works: when the shell dies for any reason, the brain sees EOF, kills its engines and exits within 2 s.

Not tested: Dock "Quit" (needs a bundled `.app`; the unbundled binary didn't receive the AppleScript quit event), sleep/wake (would sleep this Mac), and a forced Rust panic.

## 6 · Native-feel notes from the spike

- Sidebar vibrancy, inset traffic lights and the overlay title bar work.
- The menu bar shows "app" because the Rust package is named `app`; rename it to `gambit` in the real project.
- Board contrast: walnut squares read brighter than `DESIGN.md`'s "low contrast" intent in screenshots; tune the two square colours in the design pass.

## Still needs the owner

1. **Look and feel:** open the spike (`npm run tauri dev` in `tauri-spike/`) and judge the board, sidebar and motion against `DESIGN.md`. A SwiftUI board spike is only worth building if this one feels wrong.
2. **Keychain:** needs a stable code-signing identity and a person to click "Always Allow"; test when the real app reads the Lichess token.
3. **120 Hz:** irrelevant on this 60 Hz display; re-test only if training moves to an external high-refresh monitor.
