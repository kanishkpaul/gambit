# gambit

A personal macOS chess tutor for one player. It is not distributed, so optimise for this player's training, not for general users.

The name is always lowercase, **gambit** (repo, app, bundle and window title), including at the start of a sentence.

- Product plan and build order: `docs/PLAN.md`
- Design language and quality bar: `docs/DESIGN.md`

## Non-negotiables

1. **The UI/UX must be premium.** Treat every screen as design work, follow `docs/DESIGN.md`, and run its quality-bar checklist before calling UI done. No default component-library look. Load the `frontend-design` and `ui-ux-pro-max` skills before building UI, and `dataviz` before any chart.
2. **Fair play.** No engine, Maia or coach assistance while a live game is in progress. Analysis runs on finished games only.
3. **Solve first, reveal later.** Training boards never show evaluations, best moves or hints before the user commits to an answer.
4. **Guardrails stay on.** Time-boxes, stopping rules, stop-loss, no streaks or quotas. Don't add gamification.
5. **The coach is grounded.** The Claude coach may only state evaluations and lines confirmed by Stockfish output passed into its prompt.
6. **Local first.** Data lives in SQLite on the Mac. Secrets (Lichess token, Claude API key) go in the macOS Keychain, never in files or the repository.

## Stack (locked; details in `docs/PLAN.md`)

- Tauri 2 shell (Rust, kept thin: windows, menus, Keychain, brain supervision)
- React + TypeScript UI with `@lichess-org/chessground` and chessops
- Python 3.12 brain, run with `uv run`, the single owner of chess logic, Stockfish 19 pool, Maia-3 / Maia-2, FSRS, SQLite (single writer), Lichess/Chess.com clients and the Claude coach
- UI ↔ brain: JSON-RPC over a localhost WebSocket with a per-launch token; stdin is the brain's lifeline
- Don't use Homebrew's default Python (3.15); Maia-2 needs 3.10–3.12

## Conventions

- Don't commit engine binaries, model weights, puzzle databases or user data (see `.gitignore`).
- Keep rating conversions, thresholds and stage allocations in one config module, not scattered constants.
