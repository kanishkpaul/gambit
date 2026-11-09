import { useState } from 'react'
import { BarList, Figure, Header, Notice, Section, View } from '../components/ui'
import { brain } from '../lib/brain'
import { MOTIF, cap, dateLong, num, pct } from '../lib/format'
import { useNow, useRpc } from '../lib/hooks'
import type { AuditReport, AuditState } from '../lib/types'

export function Audit() {
  const { data, error, setData } = useRpc<AuditState>('audit.get')
  const [err, setErr] = useState<string | null>(null)
  const now = useNow(15_000)

  if (!data)
    return (
      <View>
        <Header eyebrow="Audit" title={<span className="text-faint">Opening the file…</span>} />
        {error && <Notice tone="bad">{error}</Notice>}
      </View>
    )

  const act = (method: string, params = {}) => {
    setErr(null)
    brain
      .call<AuditState>(method, params)
      .then(setData)
      .catch((e: Error) => setErr(e.message))
  }

  // The time-box is enforced by the brain too; this keeps the screen honest between refreshes.
  const elapsedMin = data.started_at ? Math.max(0, (now / 1000 - data.started_at) / 60) : 0
  const state = data.state === 'open' && elapsedMin > data.timebox_min ? 'expired' : data.state

  if (state === 'none')
    return (
      <View>
        <div className="mx-auto max-w-[560px] pt-[8vh]">
          <div className="eyebrow mb-3">Audit · once</div>
          <h1 className="display m-0 text-2xl">Look back once, then move on.</h1>
          <p className="mt-4 mb-3 text-sm text-muted">
            The audit reads your whole history: which errors repeat, when they happen, which openings cost you, and how you play after losses. You get{' '}
            {data.timebox_min} minutes with it. Then you write down at most {data.max_lessons} lessons and the file closes for good.
          </p>
          <p className="mt-0 mb-10 text-sm text-muted">Run it after most of your games are analysed, so the numbers are complete.</p>
          {err && (
            <div className="mb-5">
              <Notice tone="bad">{err}</Notice>
            </div>
          )}
          <button className="btn btn-primary" onClick={() => act('audit.start')}>
            Start the {data.timebox_min}-minute audit
          </button>
        </div>
      </View>
    )

  if (state === 'filed')
    return (
      <View>
        <Header eyebrow="Audit · filed" title="Filed and closed." sub={`You filed it on ${dateLong(data.filed_at!)}. These are the lessons you kept.`} />
        <ol className="m-0 grid list-none gap-6 p-0">
          {data.lessons!.map((l, i) => (
            <li key={i} className="grid grid-cols-[32px_1fr] items-baseline">
              <span className="tabular font-serif text-lg text-faint">{i + 1}</span>
              <span className="font-serif text-lg leading-snug font-light">{l}</span>
            </li>
          ))}
        </ol>
      </View>
    )

  const left = Math.max(0, Math.ceil(data.timebox_min - elapsedMin))
  const warn = elapsedMin >= data.warn_min
  return (
    <View>
      <Header
        eyebrow="Audit"
        title={state === 'expired' ? 'Time’s up. File your lessons.' : 'Your history, once.'}
        sub={
          state === 'expired'
            ? `The ${data.timebox_min} minutes are over and the report is closed. Write what you'll take forward, then file it.`
            : `Read it, decide what matters, and write at most ${data.max_lessons} lessons before the time runs out.`
        }
        aside={
          state === 'open' && (
            <div className="text-right" aria-live="polite">
              <div className={`tabular font-serif text-xl font-light ${warn ? 'text-bad' : ''}`}>{left} min</div>
              <div className="text-2xs text-muted">left of {data.timebox_min}</div>
            </div>
          )
        }
      />
      {state === 'open' && warn && (
        <div className="mb-8">
          <Notice tone="bad">A few minutes left. Start writing your lessons now; the report closes at {data.timebox_min} minutes.</Notice>
        </div>
      )}
      {state === 'open' && data.report && <Report r={data.report} />}
      <Lessons max={data.max_lessons} onFile={(lessons) => act('audit.file', { lessons })} err={err} />
    </View>
  )
}

const score = (s: number) => pct(s)

function Report({ r }: { r: AuditReport }) {
  const tcs = Object.entries(r.by_time_class).sort((a, b) => b[1].games - a[1].games)
  return (
    <>
      <p className="m-0 max-w-[70ch] text-md leading-relaxed">
        {num(r.games)} games from {dateLong(r.first)} to {dateLong(r.last)}, {num(r.analysed)} of them analysed, with {num(r.blunders)} blunders of yours among them.
      </p>

      <Section title="By time control">
        <table className="w-full border-collapse text-xs">
          <thead>
            <tr className="text-left text-2xs text-faint">
              <th className="pb-2 font-normal">Time control</th>
              <th className="pb-2 text-right font-normal">Games</th>
              <th className="pb-2 text-right font-normal">Score</th>
              <th className="pb-2 text-right font-normal">Blunders a game</th>
            </tr>
          </thead>
          <tbody className="tabular">
            {tcs.map(([tc, v]) => (
              <tr key={tc} className="h-9 border-t hairline">
                <td>{cap(tc)}</td>
                <td className="text-right">{num(v.games)}</td>
                <td className="text-right">{score(v.score)}</td>
                <td className="text-right">{v.blunders_per_game?.toFixed(2) ?? '–'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      <div className="grid grid-cols-[1.35fr_1fr] gap-12">
        <Section title="What the blunders were">
          <BarList rows={r.motifs.map((m) => ({ label: MOTIF[m.motif] ?? m.motif, value: m.count }))} empty="No analysed blunders yet." />
        </Section>
        <Section title="When they happen">
          <div className="grid grid-cols-2 gap-x-6 gap-y-7 pt-1">
            <Figure label="In the opening" value={num(r.phases.opening)} />
            <Figure label="In the middlegame" value={num(r.phases.middlegame)} />
            <Figure label="In the endgame" value={num(r.phases.endgame)} />
            <Figure label="In time trouble" value={pct(r.time_trouble_share)} />
            <Figure label="First blunder, typical move" value={r.first_blunder_move_median ?? '–'} note="median" />
            <Figure label="Losses on time" value={pct(r.losses_on_time)} />
          </div>
        </Section>
      </div>

      <Section title="Openings" note="Families with 8+ games, by your score">
        {r.openings_worst.length ? (
          <div className="grid grid-cols-2 gap-12">
            <OpeningList title="Costing you most" rows={r.openings_worst} />
            <OpeningList title="Working best" rows={r.openings_best} />
          </div>
        ) : (
          <p className="m-0 text-xs text-muted">No opening family has 8 games yet.</p>
        )}
      </Section>

      <Section title="After two straight losses" note="Games started within two hours">
        <p className="m-0 max-w-[70ch] text-sm text-muted">
          {r.tilt.after_two_losses == null
            ? 'You haven’t played on soon after two straight losses, so there’s nothing to compare.'
            : `You scored ${score(r.tilt.after_two_losses)} in the ${num(r.tilt.games_after_two_losses)} games you started soon after two straight losses, against ${score(r.tilt.overall)} overall. That gap is what the stop-loss rule is for.`}
        </p>
      </Section>
    </>
  )
}

function OpeningList({ title, rows }: { title: string; rows: AuditReport['openings_worst'] }) {
  return (
    <div>
      <div className="mb-2 text-2xs text-muted">{title}</div>
      <ul className="m-0 grid list-none gap-2 p-0 text-xs">
        {rows.map((o) => (
          <li key={`${o.name}-${o.color}`} className="flex justify-between gap-4 border-t hairline pt-2">
            <span className="truncate">
              {o.name} <span className="text-faint">as {o.color}</span>
            </span>
            <span className="tabular shrink-0 text-muted">
              {score(o.score)} · {num(o.games)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function Lessons({ max, onFile, err }: { max: number; onFile: (l: string[]) => void; err: string | null }) {
  const [lessons, setLessons] = useState<string[]>(Array(max).fill(''))
  const filled = lessons.filter((l) => l.trim()).length
  return (
    <Section title="Lessons" note={`1 to ${max}. Filing closes the audit for good.`}>
      <form
        className="grid gap-3"
        onSubmit={(e) => {
          e.preventDefault()
          onFile(lessons)
        }}
      >
        {lessons.map((l, i) => (
          <label key={i} className="grid grid-cols-[32px_1fr] items-start">
            <span className="tabular pt-2 font-serif text-md text-faint">{i + 1}</span>
            <textarea
              className="field"
              rows={2}
              value={l}
              placeholder={i === 0 ? 'Before every move, check what each capture and check leaves hanging.' : ''}
              onChange={(e) => setLessons((ls) => ls.map((x, j) => (j === i ? e.target.value : x)))}
            />
          </label>
        ))}
        {err && <Notice tone="bad">{err}</Notice>}
        <div className="mt-2 flex justify-end">
          <button className="btn btn-primary" disabled={!filled}>
            File and close
          </button>
        </div>
      </form>
    </Section>
  )
}
