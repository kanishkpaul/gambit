# Product plan

gambit is a personal Mac chess tutor for one player. Its design follows research on accelerated skill acquisition and chess expertise (kept outside this repository).

## Core model

1. **Rating below master level mostly measures the error tail.** Large errors fall roughly by half for every ~600 Elo, so the fastest early gains come from eliminating hung pieces and missed threats.
2. **Recognition carries most of the strength.** Blitz performance reproduces up to ~81% of rating variance, so most hours should build a library of patterns you recognise instantly. Chess patterns are tied to particular squares, so each one needs varied instances across board sectors and both colours.
3. **Solving is retrieval practice** (g ≈ 0.6 over restudy). Spacing (d ≈ 0.46) and mixing visually similar categories (g ≈ 0.67) make it stick.
4. **Study beats play per hour** (~3.6× on Chess.com data). Games are tests and raw material for analysis.
5. **Rating is noisy.** ±40 points of standard deviation at fixed skill, and 90-point swings within 50 games are normal. Steer by rolling averages per games played and by leading indicators.

## Stack (locked 2026-11-09)

Decided by the stack evaluation (research report 06). Native SwiftUI is the runner-up and replaces only the UI layer if the bake-off triggers it (see below).

| Layer | Owner | Choice |
|---|---|---|
| UI | TypeScript + React | `@lichess-org/chessground` 10.5 (thin in-house React wrapper), `chessops` 0.15 for client-side legality/SAN/mirroring, Tailwind 4 + shadcn source restyled to `DESIGN.md`, Motion, cmdk (⌘K), Observable Plot (visx/D3 where bespoke) |
| Shell | Rust (thin) | Tauri 2.12: windows, menus, settings, `window-vibrancy`, Keychain via `keyring`, supervises the brain. Plain `std::process`/tokio spawning, no bundled sidecar |
| Brain | Python 3.12 (pinned), run with `uv run` | One long-lived asyncio process that owns everything below |
| Chess logic | Python | python-chess 1.11.x; vendored, adapted lichess-puzzler tagger |
| Engines | Python | Pool of Stockfish 19 processes via `chess.engine`: N × Threads=1 for batch, 1 × Threads=3 for live. Validate FENs first (SF19 exits on invalid input) |
| ML | Python | Maia-3 (CSSLab, pinned commit) called through its model code, not `maia3-uci`; Maia-2 Rapid alongside for rapid play; ONNX Runtime export as a benchmarked alternative backend |
| Review | Python | py-fsrs (FSRS-6) with optimizer |
| Storage | Python, single writer | stdlib `sqlite3`, WAL, one file; Lichess puzzle CSV imported once |
| APIs | Python | berserk for Lichess (personal token with `puzzle:read`; explorer needs the token); `httpx` for Chess.com PubAPI (serial, generic User-Agent, ETag) |
| Coach | Python | Official `anthropic` SDK, `claude-opus-5-5`, structured outputs, no prefill or temperature; grounded in Stockfish output |

### Process architecture

```
gambit.app (Tauri, Rust) ── reads Keychain, spawns brain, owns windows/menus
   │  spawn: uv run --frozen --project brain python -m gambit_brain
   │  stdin: init {lichess_token, anthropic_key, ws_token}; EOF = brain exits
   ▼
WKWebView (React) ── JSON-RPC over ws://127.0.0.1:<port>?t=<ws_token>
   ▼
gambit_brain (Python 3.12) ── SQLite · Maia (warm) · FSRS · tagger · coach · Stockfish pool
```

- The brain also polls its parent PID and exits if the shell dies. Every quit path must leave zero orphans.
- Secrets flow Rust → brain over stdin; they never enter the WebView and Python never touches the Keychain.
- The WebSocket lets the full stack run in a normal browser during development (`uv run gambit_brain --dev` + Vite), so UI work can be verified with browser tooling.
- Batch analysis defaults to 300k nodes per position at background priority, with deeper re-search only on critical positions.
- The fair-play lock suspends the Stockfish pool and Maia, not just the panels.
- Never fine-tune a model on Chess.com games (User Agreement §4(D)); use Lichess CC0 data.
- Sign dev builds with one stable identity so the Keychain doesn't re-prompt.

### Runner-up trigger

Switch the UI layer to native SwiftUI (keeping the brain and protocol unchanged) if any of these happens: the board can't meet the motion spec without heavy patching; the native-feel audit fails on things CSS can't fix; or the owner prefers a SwiftUI board spike in a side-by-side comparison. Also re-test if training moves to a 120 Hz+ display.

## Modules

| Module | What it does |
|---|---|
| **Mirror** | Imports all games, runs batch analysis and tags each move: blunder ≥ 2 pawns, mistake, motif, phase, time spent, clock left. Includes a one-time history audit that is time-boxed, then filed and closed. |
| **Solve** | Draws positions from your own blunders, Lichess puzzles on the themes you miss, and positions where Maia predicts players at your level go wrong. You commit to a move, line and confidence before anything is revealed. Sets are mixed and unlabelled, with varied instances of each motif, FSRS review, and a timed speed mode. |
| **Calculation** | The pieces stay frozen while you list candidates and type the main line, then the engine verifies it. Includes a visualization mode and a "scan one different area once" step. |
| **Game Lab** | The engine stays locked until you've annotated the game and logged 1–3 critical moments. Then come Stockfish, Maia at your level versus a higher level, and time use plotted against criticality. Sessions are time-boxed and end with lessons logged into review. |
| **Endgames** | A curriculum of theoretical positions played against tablebase defence, with spaced review. |
| **Openings** | A narrow repertoire built from your own games. Flags where you left your preparation and reviews only critical lines; its share of time is capped by stage. |
| **Sparring** | Local Maia-3 set slightly above your level at long time controls, plus an optional "good-enough move" drill. |
| **Master games** | Guess-the-move through games in the pawn structures your repertoire leads to. |
| **Planner** | Daily sessions split by stage allocations, which advance automatically with rating. Rest days and variety are built in. |
| **Slope** | Rolling 50–100-game rating against games played with the noise band shaded, blunders per game, clock profile, Maia band resemblance, hours logged against the plan, and progress gates. |
| **Calibration** | Every 6–8 weeks, a fresh difficulty-matched set solved cold and timed. |
| **Coach** | A weekly review of your metrics, a proposed mix for the next week, and plain-language explanations of engine-confirmed lines. |

### Stage allocations (starting point, untested)

| Activity | Stage 1 | Stage 2 | Stage 3 | Stage 4 |
|---|---|---|---|---|
| Solving (tactics → calculation) | 35% | 30% | 25% | 20% |
| Own-game analysis | 20% | 20% | 20% | 15% |
| Endgames | 15% | 15% | 15% | 10% |
| Master games, structures | 5% | 15% | 15% | 15% |
| Openings | 5% | 5% | 10% | 20% |
| Serious play | 20% | 15% | 15% | 20% |

### Gates

| Gate | Target | Meaning |
|---|---|---|
| 0 · ~6 months | Rolling average clearly beating the ordinary-adult rate (~+95/yr) | Method check: if it isn't, change the content, not the volume |
| 1 · year 3–4 | FIDE ~2000 | Key checkpoint |
| 2 · year 6 | FIDE ~2200 | Key checkpoint |

## Guardrails

- **Fair-play lock:** all assistance is off while a live game is in progress. Lichess games are detected through the API; Chess.com uses a manual toggle.
- **Time-boxes** on every session, with a soft warning and then a hard stop.
- **Stop-loss:** stop playing after 2–3 straight losses, or after any loss that leaves you angry.
- **Engine-reassurance limiter:** a nudge after repeated engine checks of the same position.
- **Post-mortem stopping rule:** 1–3 lessons, then the file closes.
- **Diminishing returns warning:** flags when time on an activity grows while measured benefit shrinks.
- **No streaks, quotas or daily shame mechanics.**

## Build order

1. **v0.1 · Mirror:** import, batch analysis, Slope dashboard, one-time audit.
2. **v0.2 · Solve:** positions from your own blunders + Lichess puzzle library, solve-first, FSRS.
3. **v0.3 · Game Lab:** engine-locked post-mortems, Maia comparison, fair-play lock, guardrails.
4. **v0.4 · Train:** planner, endgames, Maia sparring.
5. **v0.5 · Deepen:** calculation, openings, master games, Claude coach, calibration.
