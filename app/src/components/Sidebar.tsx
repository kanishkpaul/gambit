import type { AnalysisStatus, Settings } from '../lib/types'
import { num } from '../lib/format'
import { Progress } from './ui'

export type ViewId = 'mirror' | 'slope' | 'audit'

export const VIEWS: { id: ViewId; label: string; hint: string }[] = [
  { id: 'mirror', label: 'Mirror', hint: '⌘1' },
  { id: 'slope', label: 'Slope', hint: '⌘2' },
  { id: 'audit', label: 'Audit', hint: '⌘3' },
]

// The rest of the plan, shown honestly as what's next rather than as dead buttons.
const LATER: [string, string][] = [
  ['Solve', '0.2'],
  ['Game Lab', '0.3'],
  ['Endgames', '0.4'],
  ['Sparring', '0.4'],
  ['Planner', '0.4'],
  ['Calculation', '0.5'],
  ['Openings', '0.5'],
  ['Coach', '0.5'],
]

export function Sidebar({
  view,
  onView,
  settings,
  analysis,
  onToggleLock,
  onSettings,
}: {
  view: ViewId
  onView: (v: ViewId) => void
  settings: Settings | null
  analysis: AnalysisStatus | null
  onToggleLock: () => void
  onSettings: () => void
}) {
  const locked = settings?.fairplay_lock ?? false
  const running = analysis && (analysis.state === 'running' || analysis.state === 'pausing')
  return (
    <aside className="flex min-h-0 flex-col border-r border-[rgb(127_127_127/0.12)] px-3 pt-[52px] pb-4" data-tauri-drag-region>
      <div className="display px-2.5 pb-7 text-[26px] tracking-[0.02em]" data-tauri-drag-region>
        gambit
      </div>

      <nav aria-label="Views" className="flex flex-col gap-px">
        {VIEWS.map((v) => (
          <button
            key={v.id}
            onClick={() => onView(v.id)}
            aria-current={view === v.id ? 'page' : undefined}
            className={`group flex h-8 items-center justify-between rounded-[7px] px-2.5 text-left text-xs transition-colors duration-150 ${
              view === v.id ? 'bg-[var(--active)] text-text' : 'text-muted hover:bg-[var(--hover)] hover:text-text'
            }`}
          >
            {v.label}
            <kbd className="border-transparent opacity-0 transition-opacity group-hover:opacity-100">{v.hint}</kbd>
          </button>
        ))}
      </nav>

      <div className="mt-8 px-2.5">
        <div className="eyebrow mb-2 text-[10px] text-faint">Later</div>
        <ul className="m-0 grid list-none gap-1 p-0">
          {LATER.map(([name, v]) => (
            <li key={name} className="flex justify-between text-2xs text-faint">
              <span>{name}</span>
              <span className="tabular">v{v}</span>
            </li>
          ))}
        </ul>
      </div>

      <div className="mt-auto grid gap-4 px-2.5">
        {running && analysis && analysis.games > 0 && (
          <div className="grid gap-1.5" aria-live="polite">
            <div className="flex justify-between text-2xs text-muted">
              <span>{analysis.phase === 'deep' ? 'Re-checking blunders' : 'Analysing'}</span>
              <span className="tabular">
                {num(analysis.phase === 'deep' ? analysis.deep : analysis.analysed)} / {num(analysis.games)}
              </span>
            </div>
            <Progress value={(analysis.phase === 'deep' ? analysis.deep : analysis.analysed) / analysis.games} />
          </div>
        )}

        <button
          onClick={onToggleLock}
          role="switch"
          aria-checked={locked}
          className="flex items-center justify-between gap-3 rounded-[7px] text-left"
          title="Turn on while you play a live game. It stops every engine until you turn it off."
        >
          <span className="grid">
            <span className="text-xs text-text">Fair-play lock</span>
            <span className="text-2xs text-muted">{locked ? 'On · engines stopped' : 'Off'}</span>
          </span>
          <span className={`relative h-[18px] w-[30px] shrink-0 rounded-full transition-colors duration-200 ${locked ? 'bg-[var(--text)]' : 'bg-[var(--line)]'}`}>
            <span
              className={`absolute top-[2px] size-[14px] rounded-full bg-[var(--bg)] shadow transition-[left] duration-200 ${locked ? 'left-[14px]' : 'left-[2px]'}`}
            />
          </span>
        </button>

        <button onClick={onSettings} className="flex h-7 items-center justify-between rounded-[7px] text-xs text-muted hover:text-text">
          Settings <kbd>⌘,</kbd>
        </button>
      </div>
    </aside>
  )
}
