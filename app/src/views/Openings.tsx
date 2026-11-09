import { useEffect, useState } from 'react'
import { Board } from '../components/Board'
import { Header, Notice, Section, Segmented, View } from '../components/ui'
import { brain } from '../lib/brain'
import { Line, arrow, uciFromBoard } from '../lib/chess'
import { cap, date, days } from '../lib/format'
import { useRpc } from '../lib/hooks'
import type { DrillPosition, OpeningsOverview } from '../lib/types'

const moveText = (moves: string[]) =>
  moves.map((m, i) => (i % 2 === 0 ? `${i / 2 + 1}. ${m}` : m)).join(' ')

export function Openings() {
  const { data: ov, reload } = useRpc<OpeningsOverview>('openings.overview', {}, ['import'])
  const [color, setColor] = useState<'white' | 'black'>('white')
  const [drilling, setDrilling] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  if (drilling) return <Drill onLeave={() => (setDrilling(false), reload())} />
  if (!ov)
    return (
      <View>
        <Header eyebrow="Openings" title={<span className="text-faint">Reading your openings…</span>} />
      </View>
    )
  const pin = (fen: string, san: string, c: string) =>
    brain
      .call('openings.pin', { color: c, fen, san })
      .then(() => brain.call('openings.rebuild'))
      .then(reload)
      .catch((e: Error) => setErr(e.message))
  const empty = ov.positions.white + ov.positions.black === 0
  return (
    <View>
      <Header
        eyebrow="Openings"
        title={empty ? 'Your repertoire builds itself from your games.' : 'A narrow repertoire, from your own games.'}
        sub={`Your repertoire move in each position is the one you play most in your first ${ov.plies / 2} moves. gambit flags moves the engine dislikes, shows where games left your preparation, and drills only the positions you’ve gone wrong in.`}
      />
      <div className="flex items-center gap-3">
        <button className="btn btn-primary" disabled={!ov.drill_due} onClick={() => setDrilling(true)}>
          {ov.drill_due ? `Drill ${ov.drill_due} position${ov.drill_due === 1 ? '' : 's'}` : 'Nothing to drill'}
        </button>
        <button className="btn btn-quiet" onClick={() => brain.call('openings.rebuild').then(reload)}>
          Rebuild from my games
        </button>
      </div>
      {err && (
        <div className="mt-4">
          <Notice tone="bad">{err}</Notice>
        </div>
      )}

      <Section title="Your main lines" note={<Segmented label="Colour" value={color} options={[{ value: 'white', label: `White · ${ov.positions.white}` }, { value: 'black', label: `Black · ${ov.positions.black}` }]} onChange={setColor} />}>
        {ov.lines[color].length ? (
          <ul className="m-0 grid list-none gap-0 p-0">
            {ov.lines[color].map((l, i) => (
              <li key={i} className="flex items-baseline justify-between gap-6 border-b hairline py-2.5">
                <span className="font-mono text-sm">{moveText(l.moves)}</span>
                <span className="tabular shrink-0 text-2xs text-faint">{l.games} games</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="m-0 text-xs text-muted">A line appears once you’ve played the same moves in at least two games as {color}.</p>
        )}
      </Section>

      <Section title="Repertoire moves the engine dislikes" note="From the batch analysis of your games">
        {ov.leaks.length ? (
          <ul className="m-0 grid list-none gap-0 p-0">
            {ov.leaks.map((l, i) => (
              <li key={i} className="flex items-center justify-between gap-6 border-b hairline py-2.5 text-sm">
                <span>
                  As {l.color}, move {Math.ceil(l.ply / 2)}: <span className="font-mono">{l.san}</span>
                  <span className="text-muted"> costs about {l.cost} pawns</span>
                  {l.engine && <span className="text-muted"> · the engine prefers <span className="font-mono text-text">{l.engine}</span></span>}
                </span>
                {l.engine && !l.pinned && (
                  <button className="btn btn-quiet shrink-0" onClick={() => pin(l.fen, l.engine!, l.color)}>
                    Switch to {l.engine}
                  </button>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <p className="m-0 text-xs text-muted">Nothing costly in your repertoire, as far as your analysed games show.</p>
        )}
      </Section>

      <Section title="Where recent games left your preparation">
        <ul className="m-0 grid list-none gap-0 p-0">
          {ov.departures.map((d) => (
            <li key={d.game_id} className="flex items-baseline justify-between gap-6 border-b hairline py-2.5 text-xs">
              <span>
                {date(d.played_at)} · as {d.color} against {d.opp_name ?? 'unknown'} · {cap(d.result)}
              </span>
              <span className="text-muted">
                {!d.event
                  ? 'stayed in your repertoire'
                  : d.event.kind === 'deviated'
                    ? `move ${Math.ceil(d.event.ply / 2)}: played ${d.event.played}, your usual is ${d.event.usual}`
                    : `move ${Math.ceil(d.event.ply / 2)}: new territory (${d.event.played})`}
              </span>
            </li>
          ))}
        </ul>
      </Section>
    </View>
  )
}

function Drill({ onLeave }: { onLeave: () => void }) {
  const [d, setD] = useState<DrillPosition | null>(null)
  const [line, setLine] = useState<Line | null>(null)
  const [result, setResult] = useState<{ correct: boolean; answer_san: string; answer_uci: string; next_review_days: number } | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [done, setDone] = useState(false)
  const load = () => {
    setResult(null)
    brain.call<DrillPosition | null>('openings.drill_next').then((n) => {
      if (!n) return setDone(true)
      setD(n)
      const base = new Line(n.fen)
      setLine(base)
      if (n.lead_uci) setTimeout(() => setLine(base.push(n.lead_uci!)), 420)
    })
  }
  useEffect(load, [])
  if (done)
    return (
      <View>
        <Header eyebrow="Openings" title="Drill done." sub="These positions come back on a spaced schedule; the ones you got wrong come back first." />
        <button className="btn" onClick={onLeave} autoFocus>
          Back to Openings
        </button>
      </View>
    )
  if (!d || !line) return null
  const v = line.view()
  const ready = !result && (!d.lead_uci || line.ucis.length > 0)
  const play = (o: string, dest: string) => {
    const uci = uciFromBoard(line.pos(), o, dest)
    setLine(line.push(uci))
    brain
      .call<typeof result>('openings.drill_answer', { item_id: d.item_id, uci })
      .then(setResult)
      .catch((e: Error) => setErr(e.message))
  }
  return (
    <div className="grid h-full min-h-[640px] grid-cols-[1fr_340px]">
      <div className="grid place-items-center px-10 pt-12 pb-8">
        <div className="aspect-square w-[min(calc(100vh-112px),100%)] rounded-[6px] bg-surface p-2.5 shadow-[0_0_0_1px_var(--line),0_30px_80px_-30px_rgb(0_0_0/0.8)]">
          <Board fen={v.fen} orientation={d.turn} turnColor={v.turn} movable={ready ? d.turn : null} dests={v.dests} lastMove={v.lastMove} shapes={result && !result.correct ? [arrow(result.answer_uci, 'good')] : []} onMove={play} />
        </div>
      </div>
      <aside className="flex flex-col gap-5 border-l hairline bg-surface px-7 pt-[52px] pb-6">
        <div className="eyebrow">Openings · drill · {d.remaining} left</div>
        <h2 className="display m-0 text-xl">Your move, from your repertoire.</h2>
        {result && (
          <div className="grid gap-3">
            <p className={`m-0 text-sm ${result.correct ? 'text-good' : ''}`}>
              {result.correct ? 'Yes, that’s your move.' : `Your repertoire move is ${result.answer_san}.`} <span className="text-muted">Back {days(result.next_review_days)}.</span>
            </p>
            <button className="btn btn-primary justify-self-end" onClick={load} autoFocus>
              Next
            </button>
          </div>
        )}
        {err && <Notice tone="bad">{err}</Notice>}
        <div className="mt-auto">
          <button className="btn btn-quiet -ml-3" onClick={onLeave}>
            ← Openings
          </button>
        </div>
      </aside>
    </div>
  )
}
