# Design language

gambit should feel like a premium instrument: quiet, precise and expensive. You'll spend 20–40 hours a week in it, so every screen is design work, not decoration added afterwards.

## North star

- **Calm focus.** One thing on screen at a time. The board is the hero, and everything else gets out of its way.
- **Craft you can feel.** Exact alignment, deliberate type, motion that has weight. No default component-library look.
- **Dark first, warm light.** A midnight theme by default; the light theme is warm ivory, not clinical white.

## Palette (tokens)

| Token | Dark | Light | Use |
|---|---|---|---|
| `--bg` | `#0B0B0E` | `#F7F3EA` | App background |
| `--surface` | `#141319` | `#FFFDF8` | Panels, cards |
| `--surface-2` | `#1C1A22` | `#F0EADD` | Raised / hover |
| `--line` | `#2A2731` | `#E2D9C6` | Hairlines, dividers |
| `--text` | `#ECE8DF` | `#1A1814` | Primary text |
| `--muted` | `#A7A196` | `#6E675B` | Secondary text |
| `--gold` | `#C9A86A` | `#9C7A3C` | Accent: one per view, sparingly |
| `--good` | `#7FB89A` | `#3F7D5E` | Correct, best move |
| `--bad` | `#D9826F` | `#B0503B` | Blunder, error |

Gold is a signature, not a fill colour. If two gold elements compete in one view, remove one.

## Typography

- **Display and headings:** New York (Apple's system serif), with Playfair Display as fallback. Light weights, generous tracking on small caps.
- **UI text:** SF Pro Text / Display. Sizes 13 / 15 / 17 / 22 / 28 / 40.
- **Notation and numbers:** SF Mono with tabular figures, so moves and evaluations align in columns.

## The board

- A custom board theme: muted walnut on dark slate, low contrast, no gradients on the squares.
- An elegant piece set, either a refined Staunton or a crisp modern set; never the default.
- Last-move and check highlights as soft inner glows, not flat fills. Arrows are thin, rounded, partly transparent, and gold for your own ideas.
- The evaluation bar is hidden by default and appears only after you commit (solve first, reveal later).

## Motion

- Spring physics for pieces, about 220 ms, slight overshoot only on capture.
- Panel transitions are 180–240 ms ease-out, combining opacity and an 8 px slide.
- Respect *Reduce Motion*: cross-fade only.
- Nothing bounces, pulses or wiggles to get attention.

## Sound

Optional, off by default. Wooden move and capture sounds, quiet, and never used as reward fanfare.

## Interaction

- **Keyboard-first.** A ⌘K command palette, arrow keys through moves, and typed SAN moves on every training board.
- Native macOS feel: translucent sidebar, traffic lights, ⌘, for settings, full-screen focus mode.
- **No gamification.** No streaks, confetti, quotas or shaming red badges. Progress shows up as honest charts.

## Data visualisation

- Charts are thin-lined with no chart junk. The ±40 noise band is a soft fill, and a trend line is drawn only when it's real.
- Follow the `dataviz` skill when building any chart.

## Quality bar (every screen)

- [ ] Works in dark and light and looks intentional in both
- [ ] One clear primary action; gold used at most once
- [ ] Alignment checked on a 4 px grid; no orphaned elements
- [ ] Every interaction reachable by keyboard
- [ ] Empty, loading and error states designed, not left as defaults
- [ ] Screenshot reviewed at 100% and at full screen before it ships
