import * as Plot from '@observablehq/plot'
import { useCallback, useMemo, useState } from 'react'
import { BarList, Figure, Header, Notice, Section, Segmented, View } from '../components/ui'
import { PlotFigure, tok } from '../components/Plot'
import { MOTIF, num, pct, poolName, signed } from '../lib/format'
import { useRpc } from '../lib/hooks'
import type { SlopeData } from '../lib/types'

export function Slope() {
  const [pool, setPool] = useState<string | null>(null)
  const params = pool ? { platform: pool.split(':')[0], time_class: pool.split(':')[1] } : {}
  const { data, error } = useRpc<SlopeData>('slope.get', params, ['analysis', 'import'])

  if (!data)
    return (
      <View>
        <Header eyebrow="Slope" title={<span className="text-faint">Reading the slope…</span>} />
        {error && <Notice tone="bad">{error}</Notice>}
      </View>
    )
  if (!data.pool || !data.rating?.length)
    return (
      <View>
        <Header eyebrow="Slope" title="No rated games yet." sub="Import your games in Mirror. The slope appears once rated games are in." />
      </View>
    )

  const key = `${data.pool.platform}:${data.pool.time_class}`
  const options = data.pools.filter((p) => p.rated > 0).slice(0, 5).map((p) => ({ value: `${p.platform}:${p.time_class}`, label: poolName(p) }))
  const verdict = readVerdict(data)

  return (
    <View>
      <Header eyebrow={`Slope · ${poolName(data.pool)}`} title={verdict.title} sub={verdict.sub} />
      {options.length > 1 && (
        <div className="mb-4 flex justify-end">
          <Segmented label="Rating pool" value={key} options={options} onChange={setPool} />
        </div>
      )}
      <RatingChart data={data} />

      <div className="mt-14 grid grid-cols-[1.35fr_1fr] gap-12">
        <Section title="Blunders per game" note={`Rolling ${data.noise!.window} · your moves losing 2+ pawns`} className="mt-0">
          <ErrorChart data={data} />
        </Section>
        <Section title="Clock" note="Your 30th move" className="mt-0">
          <div className="grid grid-cols-2 gap-x-6 gap-y-7 pt-1">
            <Figure label="Clock left at move 30" value={pct(data.clock?.median_share_at_30)} note={`median of ${num(data.clock?.games_reaching_30)} games`} />
            <Figure label="Losses on time" value={pct(data.clock?.loss_on_time_share)} note="of all losses" />
            <Figure label="Blunders in time trouble" value={pct(data.clock?.time_trouble_blunder_share)} note="under 10% of base time left" />
            <Figure label="Games analysed" value={num(data.counts?.analysed)} note={`of ${num(data.counts?.games)}`} />
          </div>
        </Section>
      </div>

      <div className="grid grid-cols-[1.35fr_1fr] gap-12">
        <Section title="What the blunders were">
          <BarList
            rows={(data.motifs ?? []).slice(0, 7).map((m) => ({ label: MOTIF[m.motif] ?? m.motif, value: m.count }))}
            empty="Motifs appear once games are analysed."
          />
        </Section>
        <Section title="Where they happen" note="Blunders per game">
          <BarList
            rows={(['opening', 'middlegame', 'endgame'] as const).map((p) => ({ label: p[0].toUpperCase() + p.slice(1), value: data.phases?.[p] ?? 0 }))}
            format={(v) => v.toFixed(2)}
            empty="Phases appear once games are analysed."
          />
        </Section>
      </div>

      <Gate0 data={data} />
    </View>
  )
}

function readVerdict(d: SlopeData): { title: string; sub: string } {
  const n = d.rating!.length
  const band = d.noise!.band
  const w = d.noise!.window
  const t = d.trend
  if (!t)
    return {
      title: 'Too few games to read a slope.',
      sub: `${num(n)} rated games so far. A rolling ${w}-game average needs about ${w + 50} before its direction means anything.`,
    }
  const span = t.to_i - t.from_i
  if (t.real)
    return {
      title: t.per_100 > 0 ? `Rising, ${signed(t.per_100)} per 100 games.` : `Falling, ${signed(t.per_100)} per 100 games.`,
      sub: `Your ${w}-game average moved from ${num(Math.round(t.from))} to ${num(Math.round(t.to))} over the last ${span} games, more than the ±${band} band that ordinary fluctuation fills.`,
    }
  return {
    title: 'Inside the noise.',
    sub: `Your ${w}-game average moved ${signed(t.to - t.from)} over the last ${span} games. Anything within ±${band} is ordinary fluctuation, so this isn't a trend yet in either direction.`,
  }
}

function RatingChart({ data }: { data: SlopeData }) {
  const rows = data.rating!
  const trend = data.trend
  const make = useCallback(
    (): Plot.PlotOptions => {
      const text = tok('text')
      const marks: Plot.Markish[] = [
        Plot.gridY({ stroke: tok('grid'), strokeOpacity: 1 }),
        Plot.areaY(rows, { x: 'i', y1: 'lo', y2: 'hi', fill: tok('band'), fillOpacity: 1, curve: 'monotone-x' }),
        Plot.dot(rows, { x: 'i', y: 'rating', r: 2.2, fill: tok('dot'), stroke: 'none' }),
        Plot.lineY(rows, { x: 'i', y: 'mean', stroke: text, strokeWidth: 2, curve: 'monotone-x' }),
      ]
      if (trend?.real) {
        marks.push(
          Plot.link([trend], { x1: 'from_i', y1: 'from', x2: 'to_i', y2: 'to', stroke: tok('gold'), strokeWidth: 2, strokeLinecap: 'round' }),
          Plot.dot([trend], { x: 'to_i', y: 'to', r: 4, fill: tok('gold'), stroke: tok('bg'), strokeWidth: 2 }),
        )
      }
      const last = rows[rows.length - 1]
      marks.push(
        Plot.text([last], { x: 'i', y: 'mean', text: (d: { mean: number }) => num(Math.round(d.mean)), dx: 10, textAnchor: 'start', fill: text, fontSize: 13, fontVariant: 'tabular-nums' }),
        Plot.ruleX(rows, Plot.pointerX({ x: 'i', stroke: tok('line') })),
        Plot.dot(rows, Plot.pointerX({ x: 'i', y: 'mean', r: 4, fill: text, stroke: tok('bg'), strokeWidth: 2 })),
        Plot.tip(
          rows,
          Plot.pointerX({
            x: 'i',
            y: 'mean',
            title: (d: { i: number; rating: number; mean: number; t: number }) =>
              `Game ${num(d.i)} · ${new Date(d.t * 1000).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })}\nRating ${num(d.rating)}\nRolling average ${num(Math.round(d.mean))}`,
          }),
        ),
      )
      return {
        marginLeft: 44,
        marginRight: 52,
        marginBottom: 32,
        x: { label: 'Rated games played →', labelAnchor: 'right', tickFormat: (v: number) => num(v), ticks: 8 },
        y: { label: null, nice: true, ticks: 5, tickFormat: (v: number) => num(v), zero: false },
        style: { color: tok('muted') },
        marks,
      }
    },
    [rows, trend],
  )
  return (
    <figure className="m-0">
      <PlotFigure make={make} height={340} label={`Rating against games played with a ±${data.noise!.band} noise band`} />
      <figcaption className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-2xs text-muted">
        <Key swatch={<span className="h-[2px] w-4 rounded bg-[var(--text)]" />}>Rolling {data.noise!.window}-game average</Key>
        <Key swatch={<span className="h-2.5 w-4 rounded-[2px] bg-[var(--band)] outline outline-1 outline-[var(--line)]" />}>±{data.noise!.band} ordinary fluctuation</Key>
        <Key swatch={<span className="size-[5px] rounded-full bg-[var(--dot)]" />}>Each game's rating</Key>
        {trend?.real && <Key swatch={<span className="h-[2px] w-4 rounded bg-[var(--gold)]" />}>Trend beyond the noise</Key>}
      </figcaption>
    </figure>
  )
}

function Key({ swatch, children }: { swatch: React.ReactNode; children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center gap-2">
      {swatch}
      {children}
    </span>
  )
}

function ErrorChart({ data }: { data: SlopeData }) {
  const rows = useMemo(() => data.errors ?? [], [data.errors])
  const make = useCallback(
    (): Plot.PlotOptions => ({
      marginLeft: 36,
      marginRight: 40,
      marginBottom: 28,
      x: { label: null, tickFormat: (v: number) => num(v), ticks: 5 },
      y: { label: null, nice: true, ticks: 4, zero: true },
      style: { color: tok('muted') },
      marks: [
        Plot.gridY({ stroke: tok('grid'), strokeOpacity: 1 }),
        Plot.areaY(rows, { x: 'i', y: 'blunders_mean', fill: tok('bad'), fillOpacity: 0.1, curve: 'monotone-x' }),
        Plot.lineY(rows, { x: 'i', y: 'blunders_mean', stroke: tok('bad'), strokeWidth: 2, curve: 'monotone-x' }),
        Plot.text(rows.slice(-1), { x: 'i', y: 'blunders_mean', text: (d: { blunders_mean: number }) => d.blunders_mean.toFixed(2), dx: 8, textAnchor: 'start', fill: tok('text'), fontVariant: 'tabular-nums' }),
        Plot.ruleX(rows, Plot.pointerX({ x: 'i', stroke: tok('line') })),
        Plot.tip(
          rows,
          Plot.pointerX({ x: 'i', y: 'blunders_mean', title: (d: { i: number; blunders_mean: number; blunders: number }) => `Analysed game ${num(d.i)}\nRolling ${d.blunders_mean.toFixed(2)} a game\nThis game ${d.blunders}` }),
        ),
      ],
    }),
    [rows],
  )
  if (rows.length < 2) return <p className="m-0 text-xs text-muted">The line appears once a few games are analysed.</p>
  const w = data.noise!.window
  const last = rows[rows.length - 1].blunders_mean
  const first = rows.length >= 2 * w ? rows[w - 1].blunders_mean : null
  return (
    <>
      <PlotFigure make={make} height={180} label="Rolling blunders per game" />
      <p className="mt-3 mb-0 text-2xs text-muted">
        {first != null ? (
          <>
            <span className="tabular">{first.toFixed(2)}</span> a game over your first {w} analysed games, <span className="tabular">{last.toFixed(2)}</span> over the last {w}.
          </>
        ) : (
          <>
            <span className="tabular">{last.toFixed(2)}</span> a game across your {rows.length} analysed games.
          </>
        )}{' '}
        Players about 600 points stronger make roughly half as many.
      </p>
    </>
  )
}

function Gate0({ data }: { data: SlopeData }) {
  const g = data.gate0
  if (!g || g.state === 'no_data') return null
  const rate = g.rate_per_year
  const text =
    g.state === 'early'
      ? `Day ${num(g.days)} of ${num(g.due_days)}. ${rate != null ? `So far your average is moving at ${signed(rate)} a year against the ${signed(g.target_per_year)} an ordinary adult manages; too early to judge.` : 'There aren’t enough games since you started training to measure a rate yet.'}`
      : g.state === 'beating'
        ? `Your average is moving at ${signed(rate!)} a year, ahead of the ${signed(g.target_per_year)} an ordinary adult manages. The method is working; keep the content.`
        : `Your average is moving at ${signed(rate!)} a year, not clearly ahead of the ${signed(g.target_per_year)} an ordinary adult manages. Change the content, not the volume.`
  return (
    <Section title="Gate 0 · method check at six months" note={g.start ? `Training since ${new Date(g.start * 1000).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })}` : undefined}>
      <p className="m-0 max-w-[70ch] text-sm text-muted">{text}</p>
    </Section>
  )
}
