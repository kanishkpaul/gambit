import type { AnalysisStatus, Settings } from '../lib/types'
import { num } from '../lib/format'
import { Progress } from './ui'

export type ViewId =
  | 'today' | 'solve' | 'calc' | 'lab' | 'endgames' | 'openings' | 'masters' | 'sparring'
  | 'mirror' | 'slope' | 'coach' | 'audit'

export const VIEWS: { id: ViewId; label: string; hint: string; group: 'train' | 'review' }[] = [
  { id: 'today', label: 'Today', hint: '⌘1', group: 'train' },
  { id: 'solve', label: 'Solve', hint: '⌘2', group: 'train' },
  { id: 'calc', label: 'Calculation', hint: '⌘3', group: 'train' },
  { id: 'lab', label: 'Game Lab', hint: '⌘4', group: 'train' },
  { id: 'endgames', label: 'Endgames', hint: '⌘5', group: 'train' },
  { id: 'openings', label: 'Openings', hint: '⌘6', group: 'train' },
  { id: 'masters', label: 'Master games', hint: '⌘7', group: 'train' },
  { id: 'sparring', label: 'Sparring', hint: '⌘8', group: 'train' },
  { id: 'mirror', label: 'Mirror', hint: '⌘9', group: 'review' },
  { id: 'slope', label: 'Slope', hint: '', group: 'review' },
  { id: 'coach', label: 'Coach', hint: '', group: 'review' },
  { id: 'audit', label: 'Audit', hint: '', group: 'review' },
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
        {VIEWS.map((v, i) => (
          <button
            style={i > 0 && VIEWS[i - 1].group !== v.group ? { marginTop: 14 } : undefined}
            key={v.id}
            onClick={() => onView(v.id)}
            aria-current={view === v.id ? 'page' : undefined}
            className={`group flex h-8 items-center justify-between rounded-[7px] px-2.5 text-left text-xs transition-colors duration-150 ${
              view === v.id ? 'bg-[var(--active)] text-text' : 'text-muted hover:bg-[var(--hover)] hover:text-text'
            }`}
          >
            {v.label}
            {v.hint && <kbd className="border-transparent opacity-0 transition-opacity group-hover:opacity-100">{v.hint}</kbd>}
          </button>
        ))}
      </nav>

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
            <span className="text-2xs text-muted">
              {locked ? (settings?.fairplay_reason === 'lichess' ? 'On · Lichess game in progress' : 'On · engines stopped') : 'Off'}
            </span>
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
