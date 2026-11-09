import { useState } from 'react'
import { BarList, Header, Notice, Section, View } from '../components/ui'
import { brain } from '../lib/brain'
import { dateLong } from '../lib/format'
import { useRpc } from '../lib/hooks'
import type { CoachWeekly, Settings } from '../lib/types'

const LABEL: Record<string, string> = {
  solving: 'Solve', analysis: 'Game Lab', endgames: 'Endgames', master_games: 'Master games', openings: 'Openings', play: 'Serious play',
}

export function Coach({ settings, onSettings }: { settings: Settings | null; onSettings: () => void }) {
  const { data: latest, setData } = useRpc<CoachWeekly | null>('coach.latest')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const write = () => {
    setBusy(true)
    setErr(null)
    brain
      .call<CoachWeekly>('coach.weekly')
      .then(setData)
      .catch((e: Error) => setErr(e.message))
      .finally(() => setBusy(false))
  }
  const hasKey = settings?.has_anthropic_key
  return (
    <View>
      <Header
        eyebrow="Coach"
        title={latest ? latest.headline : 'A weekly review, grounded in your numbers.'}
        sub={
          latest
            ? `Written ${dateLong(latest.created_at)} from your last seven days.`
            : 'Claude reads a summary of your week that gambit computes (ratings, blunders, sets, post-mortems, time against the plan) and proposes next week’s split. Any statement with a number that isn’t in your data is removed before you see it.'
        }
      />
      <div className="flex items-center gap-3">
        {hasKey ? (
          <button className="btn btn-primary" onClick={write} disabled={busy}>
            {busy ? 'Writing…' : latest ? 'Write this week’s review' : 'Write the first review'}
          </button>
        ) : (
          <button className="btn" onClick={onSettings}>
            Add a Claude API key in Settings
          </button>
        )}
        <span className="text-2xs text-muted">Uses Claude Opus 5.5 through your API key. Off during a live game.</span>
      </div>
      {err && (
        <div className="mt-4">
          <Notice tone="bad">{err}</Notice>
        </div>
      )}

      {latest && (
        <>
          <Section title="What the numbers say">
            <ul className="m-0 grid list-none gap-4 p-0">
              {latest.observations.map((o, i) => (
                <li key={i} className="grid gap-1">
                  <span className="font-serif text-md leading-snug font-light">{o.text}</span>
                  <span className="text-2xs text-faint">from {o.evidence.map((e) => e.replaceAll('_', ' ')).join(', ')}</span>
                </li>
              ))}
            </ul>
            {latest.removed > 0 && (
              <p className="mt-4 mb-0 text-2xs text-faint">
                {latest.removed} statement{latest.removed === 1 ? ' was' : 's were'} removed because {latest.removed === 1 ? 'it' : 'they'} cited numbers that aren’t in your data.
              </p>
            )}
          </Section>
          <div className="grid grid-cols-[1.3fr_1fr] gap-12">
            <Section title="Proposed split for next week" note="Change it in Settings if you agree">
              <BarList rows={Object.entries(latest.next_week).map(([k, v]) => ({ label: LABEL[k] ?? k, value: v }))} format={(v) => `${v}%`} empty="No split proposed." />
            </Section>
            <Section title="Focus">
              <ul className="m-0 grid list-none gap-2 p-0 text-sm">
                {latest.focus.map((f, i) => (
                  <li key={i}>{f}</li>
                ))}
              </ul>
            </Section>
          </div>
          <details className="mt-12 text-2xs text-muted">
            <summary className="cursor-default">Exactly what Claude was given</summary>
            <pre className="mt-3 overflow-x-auto rounded-lg border hairline bg-bg p-4 font-mono text-2xs leading-relaxed">{JSON.stringify(latest.facts, null, 2)}</pre>
          </details>
        </>
      )}
    </View>
  )
}
