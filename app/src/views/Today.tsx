import { Header, Notice, Progress, View } from '../components/ui'
import { PLATFORM, num } from '../lib/format'
import { useRpc } from '../lib/hooks'
import type { TodayPlan } from '../lib/types'
import type { ViewId } from '../components/Sidebar'

const DAY = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

const hm = (m: number) => (m >= 60 ? `${Math.floor(m / 60)} h${m % 60 ? ` ${m % 60} min` : ''}` : `${m} min`)

export function Today({ onGo }: { onGo: (v: ViewId) => void }) {
  const { data: p, error } = useRpc<TodayPlan>('planner.today', {}, ['import', 'analysis', 'settings'])
  if (!p)
    return (
      <View>
        <Header eyebrow="Today" title={<span className="text-faint">Planning your day…</span>} />
        {error && <Notice tone="bad">{error}</Notice>}
      </View>
    )
  const st = p.stage
  const basis = st.basis
  return (
    <View>
      <Header
        eyebrow={`Today · Stage ${st.stage}`}
        title={p.rest_day ? 'Rest day.' : `${hm(p.planned)} of training today.`}
        sub={
          p.rest_day
            ? 'Nothing is planned. Memories consolidate on rest days; a walk does more for your chess today than another set.'
            : 'The split follows your stage. Do the blocks in this order: study first, then play, because games are tests of what you studied.'
        }
      />

      {!p.rest_day && (
        <ol className="m-0 grid list-none gap-0 border-t hairline p-0">
          {p.blocks.map((b, i) => (
            <li key={b.activity} className="grid grid-cols-[28px_1fr_160px_auto] items-center gap-6 border-b hairline py-5">
              <span className="tabular font-serif text-lg font-light text-faint">{i + 1}</span>
              <div className="min-w-0">
                <div className="text-md">{b.label}</div>
                <div className="mt-0.5 text-xs text-muted">{b.why}</div>
              </div>
              <div className="grid gap-1.5">
                <div className="tabular flex justify-between text-2xs text-muted">
                  <span>{hm(b.done)} done</span>
                  <span>{hm(b.minutes)}</span>
                </div>
                <Progress value={b.minutes ? b.done / b.minutes : 0} />
              </div>
              {b.view ? (
                <button className="btn" onClick={() => onGo(b.view as ViewId)}>
                  {b.activity === 'play' ? 'Spar with Maia' : 'Open'}
                </button>
              ) : (
                <span />
              )}
            </li>
          ))}
        </ol>
      )}

      <section className="mt-12">
        <div className="mb-4 flex items-baseline justify-between border-b hairline pb-2">
          <h2 className="m-0 text-xs font-medium">This week</h2>
          <span className="text-2xs text-muted">
            {p.weekly_hours} h planned · set the hours and rest days in Settings
          </span>
        </div>
        <div className="grid grid-cols-7 gap-3">
          {p.week.map((d) => {
            const max = Math.max(...p.week.map((w) => Math.max(w.planned, w.done ?? 0)), 1)
            return (
              <div key={d.date} className="grid gap-2" title={d.planned ? `${hm(d.done ?? 0)} of ${hm(d.planned)}` : 'Rest day'}>
                <div className="relative h-24 rounded-md bg-[var(--grid)]">
                  {d.planned > 0 && <div className="absolute inset-x-0 bottom-0 rounded-md border border-[var(--line)]" style={{ height: `${(d.planned / max) * 100}%` }} />}
                  {d.done != null && d.done > 0 && <div className="absolute inset-x-[5px] bottom-[3px] rounded-[4px] bg-[var(--muted)]" style={{ height: `calc(${(d.done / max) * 100}% - 6px)` }} />}
                </div>
                <div className={`text-center text-2xs ${d.today ? 'text-text' : 'text-faint'}`}>{d.planned ? DAY[d.weekday] : `${DAY[d.weekday]} · rest`}</div>
              </div>
            )
          })}
        </div>
        <p className="mt-3 mb-0 text-2xs text-faint">Outlines are the plan; filled bars are time you actually spent, measured from your sets, post-mortems, endgames and games.</p>
      </section>

      <section className="mt-12 text-xs text-muted">
        {basis ? (
          <>
            Stage {st.stage}{st.override ? ' (set by you)' : ''}: your {PLATFORM[basis.platform]} {basis.time_class} average is <span className="tabular text-text">{num(basis.rating)}</span> over {basis.games} games.
            {basis.next_at && !st.override ? ` Stage ${st.stage + 1} starts at ${num(basis.next_at)}; the split shifts on its own.` : ''}
          </>
        ) : (
          'Stage 1 until your games are imported; the split then follows your rating.'
        )}
      </section>
    </View>
  )
}
