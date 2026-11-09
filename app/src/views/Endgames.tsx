import { useState } from 'react'
import { Board } from '../components/Board'
import { Header, Notice, Section, View } from '../components/ui'
import { brain } from '../lib/brain'
import { Line, uciFromBoard, uciFromSan } from '../lib/chess'
import { days } from '../lib/format'
import { useRpc } from '../lib/hooks'
import type { EndgameAttempt, EndgameLesson, EndgameMoveResult } from '../lib/types'

const GOAL: Record<EndgameLesson['goal'], string> = {
  mate: 'Mate. The defence is perfect.',
  promote: 'Promote the pawn. The defence is perfect.',
  capture: 'Win the pawn and keep the win. The defence is perfect.',
  hold: 'Hold the draw against perfect play.',
}

export function Endgames() {
  const { data, reload } = useRpc<{ lessons: EndgameLesson[]; due: number; attempt: EndgameAttempt | null }>('endgames.overview')
  const [attempt, setAttempt] = useState<EndgameAttempt | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const start = (key?: string) => {
    setErr(null)
    brain
      .call<EndgameAttempt>('endgames.start', key ? { key } : {})
      .then(setAttempt)
      .catch((e: Error) => setErr(e.message))
  }
  const current = attempt ?? data?.attempt ?? null
  if (current)
    return (
      <Practice
        key={current.fen + current.moves.join()}
        a={current}
        onNext={() => start()}
        onLeave={() => {
          brain.call('endgames.abandon')
          setAttempt(null)
          reload()
        }}
      />
    )

  const stages = [1, 2, 3]
  return (
    <View>
      <Header
        eyebrow="Endgames"
        title={data?.due ? `${data.due} endgame${data.due === 1 ? ' is' : 's are'} due.` : 'The positions every player must know.'}
        sub="Each one is played against perfect tablebase defence, on squares and colours that change every time, and comes back on a spaced schedule."
      />
      <div className="flex items-center gap-3">
        <button className="btn btn-primary" onClick={() => start()}>
          {data?.due ? 'Start the next one due' : 'Start the next one'}
        </button>
        <span className="text-2xs text-muted">Needs an internet connection: the Lichess tablebase plays the defence.</span>
      </div>
      {err && (
        <div className="mt-4">
          <Notice tone="bad">{err}</Notice>
        </div>
      )}
      {stages.map((s) => (
        <Section key={s} title={`Stage ${s}`}>
          <ul className="m-0 grid list-none gap-0 p-0">
            {data?.lessons
              .filter((l) => l.stage === s)
              .map((l) => (
                <li key={l.key} className="flex h-11 items-center justify-between gap-4 border-b hairline text-sm">
                  <span>{l.title}</span>
                  <span className="flex items-center gap-4 text-2xs text-muted">
                    <span>{l.goal === 'hold' ? 'defend' : l.goal}</span>
                    <span className="tabular w-[110px] text-right">
                      {l.status === 'new' ? 'new' : l.status === 'due' ? 'due now' : `back ${days(Math.max(0, ((l.due ?? 0) - Date.now() / 1000) / 86400))}`}
                    </span>
                    <button className="btn btn-quiet" onClick={() => start(l.key)}>
                      Practise
                    </button>
                  </span>
                </li>
              ))}
          </ul>
        </Section>
      ))}
    </View>
  )
}

function Practice({ a, onNext, onLeave }: { a: EndgameAttempt; onNext: () => void; onLeave: () => void }) {
  const [line, setLine] = useState(() => new Line(a.fen, a.moves))
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState<Extract<EndgameMoveResult, { done: true }> | null>(null)
  const [count, setCount] = useState(a.user_moves)
  const [san, setSan] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const v = line.view()
  const yourTurn = v.turn === a.side && !busy && !done

  const play = (uci: string) => {
    if (!yourTurn) return
    setErr(null)
    setBusy(true)
    const withMove = line.push(uci)
    setLine(withMove)
    brain
      .call<EndgameMoveResult>('endgames.move', { uci })
      .then((r) => {
        setCount(r.user_moves)
        const reply = r.reply_uci
        const finish = () => {
          if (r.done) setDone(r)
          setBusy(false)
        }
        if (reply) setTimeout(() => (setLine(withMove.push(reply)), finish()), 380)
        else finish()
      })
      .catch((e: Error) => {
        setLine(line)
        setErr(e.message)
        setBusy(false)
      })
  }

  return (
    <div className="grid h-full min-h-[640px] grid-cols-[1fr_360px]">
      <div className="grid place-items-center px-10 pt-12 pb-8" data-tauri-drag-region>
        <div className="aspect-square w-[min(calc(100vh-112px),100%)] rounded-[6px] bg-surface p-2.5 shadow-[0_0_0_0.5px_var(--line),0_12px_32px_-12px_rgb(0_0_0/0.35)]">
          <Board fen={v.fen} orientation={a.side} turnColor={v.turn} movable={yourTurn ? a.side : null} dests={v.dests} lastMove={v.lastMove} check={v.check} onMove={(o, d) => play(uciFromBoard(line.pos(), o, d))} />
        </div>
      </div>
      <aside className="flex min-h-0 flex-col gap-6 border-l hairline bg-surface px-7 pt-[52px] pb-6">
        <div className="flex items-baseline justify-between">
          <div className="eyebrow">Endgames · stage {a.stage}</div>
          <div className="tabular text-xs text-muted">
            {count} of {a.move_limit} moves
          </div>
        </div>
        <div>
          <h2 className="display m-0 text-xl">{a.title}</h2>
          <p className="mt-2 mb-0 text-xs text-muted">
            You play {a.side}. {GOAL[a.goal]}
          </p>
        </div>

        {!done && (
          <form
            className="grid gap-1.5"
            onSubmit={(e) => {
              e.preventDefault()
              const u = uciFromSan(line.pos(), san)
              if (!u) return setErr(`“${san.trim()}” isn’t a legal move here.`)
              setSan('')
              play(u)
            }}
          >
            <label htmlFor="eg-san" className="text-xs text-muted">
              Or type your move
            </label>
            <input id="eg-san" className="field font-mono" value={san} onChange={(e) => setSan(e.target.value)} placeholder="Kd2, Rh5+" autoComplete="off" spellCheck={false} disabled={!yourTurn} />
          </form>
        )}

        {done && (
          <div className="grid gap-4">
            <h3 className={`display m-0 text-lg ${done.result === 'success' ? 'text-good' : ''}`}>
              {done.result === 'success' ? (done.optimal_moves ? `Done in ${done.user_moves} moves. Best is ${done.optimal_moves}.` : `Done in ${done.user_moves} moves.`) : done.reason ?? 'Not this time.'}
            </h3>
            {done.keeping_moves.length > 0 && (
              <p className="m-0 text-xs text-muted">
                Moves that kept the result: <span className="font-mono text-text">{done.keeping_moves.join(', ')}</span>
              </p>
            )}
            <p className="m-0 text-md leading-snug">{done.idea}</p>
            <p className="m-0 text-2xs text-muted">Back {days(done.next_review_days)}.</p>
            <button className="btn btn-primary justify-self-end" onClick={onNext} autoFocus>
              Next endgame
            </button>
          </div>
        )}
        {err && <Notice tone="bad">{err}</Notice>}
        <div className="mt-auto">
          <button className="btn btn-quiet -ml-3" onClick={onLeave}>
            ← All endgames
          </button>
        </div>
      </aside>
    </div>
  )
}
