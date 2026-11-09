# Design language

gambit should feel like a premium instrument: quiet, precise and expensive. You'll spend 20–40 hours a week in it, so every screen is design work, not decoration added afterwards.

## North star

- **A real Mac app.** gambit looks and behaves like Apple's own apps (changed 2026-11-09 from an editorial look): system type, system colours, your accent colour, native-feeling controls. Nothing should look like a website.
- **Calm focus.** One thing on screen at a time. The board is the hero, and everything else gets out of its way.
- **Craft you can feel.** Exact alignment, the macOS type scale, motion that has weight. No component-library look.
- **Light and dark** follow the system appearance; both are first-class.

## Colour (tokens in `app/src/index.css`)

macOS system colours, light / dark:

| Token | Light | Dark | Use |
|---|---|---|---|
| `--bg` | `#FFFFFF` | `#1E1E1E` | Content pane (text background) |
| `--window` | `#ECECEC` | `#282828` | Sheets; sidebar fallback outside the app |
| `--surface` | `#F5F5F7` | `#262628` | Inset group boxes, inspector panels |
| `--line` | black 10% | white 10% | Separators |
| `--text` / `--muted` / `--faint` | label / secondary / tertiary label | | Text |
| `--accent` | the user's accent (`-apple-system-control-accent`), blue fallback | | Default button, selection, sidebar icons, focus ring |
| `--good` / `--bad` | system green / red, darkened for text contrast | | Correct / blunder |

The accent marks the one default action per view (the filled button). Sidebar icons and selections use it too, as macOS does. `--gold` remains as an alias of `--accent` in code.

## Typography

- **SF Pro only** (system font). The macOS scale: 11 / 12 / 13 (body) / 15 / 17 / 22 / 26 (large title, bold).
- Headings are SF Pro bold or semibold; no serif display face.
- **Notation and numbers:** SF Mono and tabular figures, so moves and evaluations align in columns.

## Chrome and controls

- **Window:** translucent sidebar (vibrancy) with traffic lights; a unified toolbar strip along the top of the content with the search field (⌘K).
- **Sidebar:** section headers ("Train", "Review"), 16 px line icons in the accent colour, 28 px rows, gray selection.
- **Controls:** AppKit-sized push buttons (28 px), the accent default button, segmented controls with a raised selected segment, switches with an accent track, text fields with the accent focus ring.
- **Settings:** a sheet laid out like System Settings: grouped inset boxes, label left and control right, footnotes under the group.
- **Command palette:** Spotlight-like: large search field, accent-filled selection.

## The board

- A custom board theme: muted walnut on dark slate, low contrast, no gradients on the squares.
- An elegant piece set, either a refined Staunton or a crisp modern set; never the default.
- Last-move and check highlights as soft inner glows, not flat fills. Arrows are thin, rounded and partly transparent.
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
- Native macOS feel throughout: translucent sidebar, traffic lights, ⌘, for settings, full-screen focus mode.
- **No gamification.** No streaks, confetti, quotas or shaming red badges. Progress shows up as honest charts.

## Data visualisation

- Charts are thin-lined with no chart junk. The ±40 noise band is a soft fill, and a trend line is drawn only when it's real.
- Follow the `dataviz` skill when building any chart.

## Quality bar (every screen)

- [ ] Works in dark and light and looks like a Mac app in both
- [ ] One clear default action (accent-filled button)
- [ ] Alignment checked on a 4 px grid; no orphaned elements
- [ ] Every interaction reachable by keyboard
- [ ] Empty, loading and error states designed, not left as defaults
- [ ] Screenshot reviewed at 100% and at full screen before it ships
