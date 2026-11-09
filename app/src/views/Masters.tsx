import { useState } from 'react'
import { Board } from '../components/Board'
import { Figure, Header, Notice, Section, View } from '../components/ui'
import { brain } from '../lib/brain'
import { Line, arrow, uciFromBoard } from '../lib/chess'
import { num } from '../lib/format'
import { useEvent, useRpc } from '../lib/hooks'
import type { GuessResult, GuessView, MastersOverview } from '../lib/types'

const START = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'

export function Masters() {
  const { data: ov, reload } = useRpc<MastersOverview>('masters.overview', {}, ['masters'])
  const progress = useEvent<{ stage: string; done?: number; total?: number; added?: number; error?: string }>('masters')
  const [game, setGame] = useState<GuessView | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const start = () => {
    setErr(null)
    brain
      .call<GuessView>('masters.start')
      .then(setGame)
      .catch((e: Error) => setErr(e.message))
  }
  const current = game ?? ov?.current ?? null
  if (current) return <Guess key={current.session_id} g={current} onNext={start} onLeave={() => (setGame(null), reload())} />
  const importing = progress && progress.stage === 'import'
  return (
    <View>
      <Header
        eyebrow="Master games"
        title="Guess the master’s move."
        sub="Classical games from over-the-board events, picked from the ones that pass through your own openings. You play one side after the opening; a move the engine rates as good as the master’s counts too."
      />
      <div className="grid grid-cols-3 gap-6 border-y hairline py-6">
        <Figure label="Master games on this Mac" value={num(ov?.games ?? 0)} note="both players 2300+" />
        <Figure label="Through your openings" value={num(ov?.matching ?? 0)} />
        <Figure label="Moves to guess per game" value={num(ov?.moves_per_game ?? 20)} />
      </div>
      <div className="mt-8 flex items-center gap-3">
        <button className="btn btn-primary" onClick={start} disabled={!ov?.games}>
          Start a game
        </button>
        <button className="btn" onClick={() => brain.call('masters.import')} disabled={!!importing}>
          {importing ? `Fetching · ${progress.added ?? 0} games` : 'Fetch recent master games'}
        </button>
        <span className="text-2xs text-muted">From Lichess broadcasts of live events; no account needed.</span>
      </div>
      {progress?.stage === 'error' && (
        <div className="mt-4">
          <Notice tone="bad">The fetch stopped: {progress.error}. Games already fetched are kept.</Notice>
        </div>
      )}
      {err && (
        <div className="mt-4">
          <Notice tone="bad">{err}</Notice>
        </div>
      )}
      {!!ov?.history.length && (
        <Section title="Recent games">
          <ul className="m-0 grid list-none gap-0 p-0">
            {ov.history.map((h, i) => (
              <li key={i} className="flex justify-between gap-6 border-b hairline py-2.5 text-xs">
                <span>
                  {h.white} – {h.black} <span className="text-faint">· {h.event}</span>
                </span>
                <span className="tabular text-muted">
                  {h.matched} matched · {h.as_good} as good · of {h.guesses}
                </span>
              </li>
            ))}
          </ul>
        </Section>
      )}
    </View>
  )
}

function Guess({ g, onNext, onLeave }: { g: GuessView; onNext: () => void; onLeave: () => void }) {
  const [line, setLine] = useState(() => new Line(START, g.moves))
  const [last, setLast] = useState<GuessResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [stats, setStats] = useState({ guesses: g.guesses, matched: g.matched, as_good: g.as_good })
  const [err, setErr] = useState<string | null>(null)
  const v = line.view()
  const yourTurn = v.turn === g.side && !busy && !last?.done

  const play = (o: string, d: string) => {
    const uci = uciFromBoard(line.pos(), o, d)
    setBusy(true)
    setErr(null)
    const before = line
    setLine(before.push(uci))
    brain
      .call<GuessResult>('masters.guess', { uci })
      .then((r) => {
        setLast(r)
        setStats((s) => ({ guesses: s.guesses + 1, matched: s.matched + (r.matched ? 1 : 0), as_good: s.as_good + (r.as_good ? 1 : 0) }))
        // Replace your guess with the master's move, then the reply.
        const withMaster = before.push(r.master_uci)
        setTimeout(() => {
          setLine(withMaster)
          if (r.reply_uci) setTimeout(() => (setLine(withMaster.push(r.reply_uci!)), setBusy(false)), 450)
          else setBusy(false)
        }, r.matched ? 0 : 650)
      })
      .catch((e: Error) => {
        setLine(before)
        setErr(e.message)
        setBusy(false)
      })
  }

  return (
    <div className="grid h-full min-h-[640px] grid-cols-[1fr_360px]">
      <div className="grid place-items-center px-10 pt-12 pb-8">
        <div className="aspect-square w-[min(calc(100vh-112px),100%)] rounded-[6px] bg-surface p-2.5 shadow-[0_0_0_0.5px_var(--line),0_12px_32px_-12px_rgb(0_0_0/0.35)]">
          <Board fen={v.fen} orientation={g.side} turnColor={v.turn} movable={yourTurn ? g.side : null} dests={v.dests} lastMove={v.lastMove} check={v.check} shapes={last && !last.matched && busy ? [arrow(last.master_uci, 'good')] : []} onMove={play} />
        </div>
      </div>
      <aside className="flex flex-col gap-5 border-l hairline bg-surface px-7 pt-[52px] pb-6">
        <div className="eyebrow">Master games{g.why === 'repertoire' ? ' · from your openings' : ''}</div>
        <div>
          <div className="text-sm">
            {g.white} <span className="tabular text-faint">{g.white_elo}</span> – {g.black} <span className="tabular text-faint">{g.black_elo}</span>
          </div>
          <div className="mt-0.5 text-2xs text-muted">
            {g.event} {g.opening ? `· ${g.opening}` : ''}
          </div>
        </div>
        <h2 className="display m-0 text-xl">{last?.done ? 'Game over.' : `You play ${g.side}. Guess the next move.`}</h2>
        {last && (
          <p className={`m-0 text-sm ${last.matched ? 'text-good' : ''}`}>
            {last.matched ? `Yes: ${last.master_san}.` : last.as_good ? `The master played ${last.master_san}; yours was just as good.` : `The master played ${last.master_san}.`}
          </p>
        )}
        <div className="tabular text-xs text-muted">
          {stats.matched} matched · {stats.as_good} as good · {stats.guesses} guesses
        </div>
        {last?.done && (
          <button className="btn btn-primary justify-self-start" onClick={onNext} autoFocus>
            Another game
          </button>
        )}
        {err && <Notice tone="bad">{err}</Notice>}
        <div className="mt-auto">
          <button className="btn btn-quiet -ml-3" onClick={() => brain.call('masters.finish').then(onLeave)}>
            ← Stop here
          </button>
        </div>
      </aside>
    </div>
  )
}
