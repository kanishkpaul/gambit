import type { LucideIcon } from 'lucide-react'
import {
  BookOpen, Brain, CalendarDays, ChartColumn, Crown, FlaskConical, ListChecks, Lock, MessageCircle, Puzzle, Settings as Gear, Swords, TrendingUp, Trophy,
} from 'lucide-react'
import type { AnalysisStatus, Settings } from '../lib/types'
import { num } from '../lib/format'
import { Progress } from './ui'

export type ViewId =
  | 'today' | 'solve' | 'calc' | 'lab' | 'endgames' | 'openings' | 'masters' | 'sparring'
  | 'mirror' | 'slope' | 'coach' | 'audit'

export const VIEWS: { id: ViewId; label: string; hint: string; group: 'train' | 'review'; icon: LucideIcon }[] = [
  { id: 'today', label: 'Today', hint: '⌘1', group: 'train', icon: CalendarDays },
  { id: 'solve', label: 'Solve', hint: '⌘2', group: 'train', icon: Puzzle },
  { id: 'calc', label: 'Calculation', hint: '⌘3', group: 'train', icon: Brain },
  { id: 'lab', label: 'Game Lab', hint: '⌘4', group: 'train', icon: FlaskConical },
  { id: 'endgames', label: 'Endgames', hint: '⌘5', group: 'train', icon: Crown },
  { id: 'openings', label: 'Openings', hint: '⌘6', group: 'train', icon: BookOpen },
  { id: 'masters', label: 'Master games', hint: '⌘7', group: 'train', icon: Trophy },
  { id: 'sparring', label: 'Sparring', hint: '⌘8', group: 'train', icon: Swords },
  { id: 'mirror', label: 'Mirror', hint: '⌘9', group: 'review', icon: ChartColumn },
  { id: 'slope', label: 'Slope', hint: '', group: 'review', icon: TrendingUp },
  { id: 'coach', label: 'Coach', hint: '', group: 'review', icon: MessageCircle },
  { id: 'audit', label: 'Audit', hint: '', group: 'review', icon: ListChecks },
]

const GROUP_LABEL = { train: 'Train', review: 'Review' } as const

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
    <aside className="flex min-h-0 flex-col px-2.5 pt-[52px] pb-3" data-tauri-drag-region>
      <nav aria-label="Views" className="flex flex-col">
        {VIEWS.map((v, i) => {
          const Icon = v.icon
          const on = view === v.id
          return (
            <div key={v.id} className="contents">
              {(i === 0 || VIEWS[i - 1].group !== v.group) && (
                <div className={`px-2 pb-1 text-2xs font-semibold text-faint ${i === 0 ? 'pt-1' : 'pt-4'}`} data-tauri-drag-region>
                  {GROUP_LABEL[v.group]}
                </div>
              )}
              <button
                onClick={() => onView(v.id)}
                aria-current={on ? 'page' : undefined}
                title={v.hint ? `${v.label}  ${v.hint}` : v.label}
                className={`flex h-7 items-center gap-2 rounded-[7px] px-2 text-left text-sm ${on ? 'bg-[var(--active)] text-text' : 'text-text hover:bg-[var(--hover)]'}`}
              >
                <Icon size={16} strokeWidth={1.75} className="shrink-0 text-accent" aria-hidden />
                <span className="truncate">{v.label}</span>
              </button>
            </div>
          )
        })}
      </nav>

      <div className="mt-auto grid gap-3 px-2">
        {running && analysis && analysis.games > 0 && (
          <div className="grid gap-1.5" aria-live="polite">
            <div className="flex justify-between text-2xs text-muted">
              <span>{analysis.phase === 'deep' ? 'Re-checking blunders' : 'Analysing'}</span>
              <span className="tabular">
                {num(analysis.phase === 'deep' ? analysis.deep : analysis.analysed)} / {num(analysis.games)}
              </span>
            </div>
            <Progress value={(analysis.phase === 'deep' ? analysis.deep : analysis.analysed) / analysis.games} tone="gold" />
          </div>
        )}

        <button
          onClick={onToggleLock}
          role="switch"
          aria-checked={locked}
          className="flex items-center justify-between gap-3 rounded-[7px] text-left"
          title="Turn on while you play a live game. It stops every engine until you turn it off."
        >
          <span className="flex min-w-0 items-center gap-2">
            <Lock size={16} strokeWidth={1.75} className={`shrink-0 ${locked ? 'text-accent' : 'text-muted'}`} aria-hidden />
            <span className="grid min-w-0">
              <span className="text-sm text-text">Fair-play lock</span>
              <span className="truncate text-2xs text-muted">
                {locked ? (settings?.fairplay_reason === 'lichess' ? 'On · Lichess game in progress' : 'On · engines stopped') : 'Off'}
              </span>
            </span>
          </span>
          <Switch on={locked} />
        </button>

        <button onClick={onSettings} className="-mx-2 flex h-7 items-center gap-2 rounded-[7px] px-2 text-sm text-text hover:bg-[var(--hover)]" title="Settings  ⌘,">
          <Gear size={16} strokeWidth={1.75} className="shrink-0 text-muted" aria-hidden />
          Settings
        </button>
      </div>
    </aside>
  )
}

/** The macOS switch: accent track when on, white knob with a soft shadow. */
export function Switch({ on }: { on: boolean }) {
  return (
    <span
      className={`relative h-[18px] w-[30px] shrink-0 rounded-full transition-colors duration-200 ${on ? 'bg-accent' : 'bg-[var(--active)]'}`}
      style={{ boxShadow: 'inset 0 0 0 0.5px rgb(0 0 0 / 0.08)' }}
      aria-hidden
    >
      <span
        className={`absolute top-[1px] size-4 rounded-full bg-white transition-[left] duration-200 ${on ? 'left-[13px]' : 'left-[1px]'}`}
        style={{ boxShadow: '0 0 0 0.5px rgb(0 0 0 / 0.12), 0 1px 2px rgb(0 0 0 / 0.25)' }}
      />
    </span>
  )
}
