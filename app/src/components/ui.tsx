import { motion, useReducedMotion } from 'motion/react'
import type { ReactNode } from 'react'

/** The standard view column. */
export function View({ children }: { children: ReactNode }) {
  return <div className="mx-auto w-full max-w-[1000px] px-10 pt-[60px] pb-16">{children}</div>
}

/** View transitions: an 8 px slide plus fade, cross-fade only under Reduce Motion. */
export function Transition({ id, children, fill = false }: { id: string; children: ReactNode; fill?: boolean }) {
  const reduce = useReducedMotion()
  return (
    <motion.div
      key={id}
      initial={{ opacity: 0, y: reduce ? 0 : 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: reduce ? 0 : -4, transition: { duration: 0.12 } }}
      transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
      className={fill ? 'h-full' : undefined}
    >
      {children}
    </motion.div>
  )
}

export function Header({ eyebrow, title, sub, aside }: { eyebrow: string; title: ReactNode; sub?: ReactNode; aside?: ReactNode }) {
  return (
    <header className="mb-8 flex items-end justify-between gap-8">
      <div className="min-w-0">
        <div className="mb-1 text-sm font-medium text-muted">{eyebrow}</div>
        <h1 className="display m-0 text-2xl">{title}</h1>
        {sub && <p className="mt-2 mb-0 max-w-[64ch] text-sm leading-relaxed text-muted">{sub}</p>}
      </div>
      {aside && <div className="shrink-0">{aside}</div>}
    </header>
  )
}

export function Section({ title, note, children, className = '' }: { title: string; note?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`mt-10 ${className}`}>
      <div className="mb-3 flex items-baseline justify-between gap-6 border-b hairline pb-2">
        <h2 className="m-0 text-md font-semibold text-text">{title}</h2>
        {note && <div className="text-2xs text-muted">{note}</div>}
      </div>
      {children}
    </section>
  )
}

/** A label-over-value figure. Values are tabular so neighbours align. */
export function Figure({ label, value, note }: { label: string; value: ReactNode; note?: ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="text-2xs text-muted">{label}</div>
      <div className="tabular mt-1 text-xl font-semibold leading-tight tracking-[-0.01em]">{value}</div>
      {note && <div className="mt-1 text-2xs text-faint">{note}</div>}
    </div>
  )
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T
  options: { value: T; label: string }[]
  onChange: (v: T) => void
  label: string
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-[8px] bg-[var(--active)] p-[2px]">
      {options.map((o) => (
        <button
          key={o.value}
          role="radio"
          aria-checked={o.value === value}
          onClick={() => onChange(o.value)}
          className={`h-6 rounded-[6px] px-3 text-sm transition-colors duration-150 ${
            o.value === value ? 'bg-[var(--control)] text-text shadow-[var(--control-edge)] dark:bg-[rgb(255_255_255/0.2)]' : 'text-muted hover:text-text'
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

/** A thin determinate progress line. */
export function Progress({ value, tone = 'text' }: { value: number; tone?: 'text' | 'gold' }) {
  return (
    <div className="h-[4px] w-full overflow-hidden rounded-full bg-[var(--active)]" role="progressbar" aria-valuenow={Math.round(value * 100)} aria-valuemin={0} aria-valuemax={100}>
      <div
        className="h-full rounded-full transition-[width] duration-700 ease-out"
        style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%`, background: tone === 'gold' ? 'var(--accent)' : 'var(--muted)' }}
      />
    </div>
  )
}

/** Horizontal bars with labels on the left and values at the tip: for motifs and phases. */
export function BarList({ rows, format = (v) => String(v), empty }: { rows: { label: string; value: number }[]; format?: (v: number) => string; empty: string }) {
  const max = Math.max(...rows.map((r) => r.value), 0)
  if (!rows.length || max === 0) return <p className="m-0 text-xs text-muted">{empty}</p>
  return (
    <ul className="m-0 grid list-none gap-2.5 p-0">
      {rows.map((r) => (
        <li key={r.label} className="grid grid-cols-[minmax(150px,220px)_1fr] items-center gap-4 text-xs" title={`${r.label}: ${format(r.value)}`}>
          <span className="truncate text-muted">{r.label}</span>
          <span className="flex items-center gap-2.5">
            <span className="h-2.5 rounded-r-[4px] bg-[var(--muted)] opacity-70" style={{ width: `${(r.value / max) * 82}%`, minWidth: r.value > 0 ? 2 : 0 }} />
            <span className="tabular text-text">{format(r.value)}</span>
          </span>
        </li>
      ))}
    </ul>
  )
}

export function Notice({ tone = 'muted', children }: { tone?: 'muted' | 'bad' | 'gold'; children: ReactNode }) {
  const color = tone === 'bad' ? 'var(--bad)' : tone === 'gold' ? 'var(--gold)' : 'var(--muted)'
  return (
    <div className="flex items-start gap-2.5 text-xs leading-relaxed" style={{ color }}>
      <span className="mt-[7px] size-1.5 shrink-0 rounded-full" style={{ background: color }} aria-hidden />
      <div className="min-w-0">{children}</div>
    </div>
  )
}
