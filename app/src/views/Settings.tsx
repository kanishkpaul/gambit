import { AnimatePresence, motion } from 'motion/react'
import { useEffect, useState } from 'react'
import { Notice, Segmented } from '../components/ui'
import { brain } from '../lib/brain'
import { num } from '../lib/format'
import { setSecret } from '../lib/native'
import type { CoachStatus, Settings as S } from '../lib/types'

const toDateInput = (unix: number | null) => (unix ? new Date(unix * 1000).toISOString().slice(0, 10) : '')

export function SettingsSheet({ open, onClose, settings, onSaved }: { open: boolean; onClose: () => void; settings: S | null; onSaved: (s: S) => void }) {
  const [chesscom, setChesscom] = useState('')
  const [lichess, setLichess] = useState('')
  const [start, setStart] = useState('')
  const [hours, setHours] = useState(20)
  const [rest, setRest] = useState<number[]>([6])
  const [stageOverride, setStageOverride] = useState<number | null>(null)
  const [token, setToken] = useState('')
  const [model, setModel] = useState('')
  const [ollama, setOllama] = useState<CoachStatus | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!open || !settings) return
    setChesscom(settings.chesscom_username)
    setLichess(settings.lichess_username)
    setStart(toDateInput(settings.training_start))
    setHours(settings.weekly_hours ?? 20)
    setRest(settings.rest_days ?? [6])
    setStageOverride(settings.stage_override ?? null)
    setToken('')
    setModel(settings.coach_model ?? '')
    setErr(null)
  }, [open, settings])

  useEffect(() => {
    if (!open) return
    let live = true
    brain.call<CoachStatus>('coach.status').then((st) => live && setOllama(st), () => live && setOllama(null))
    return () => {
      live = false
    }
  }, [open])

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  const save = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setErr(null)
    try {
      if (token.trim()) await setSecret('lichess_token', token)
      const s = await brain.call<S>('settings.set', {
        chesscom_username: chesscom.trim(),
        lichess_username: lichess.trim(),
        training_start: start ? Math.floor(new Date(`${start}T00:00:00`).getTime() / 1000) : settings?.training_start,
        weekly_hours: Math.max(1, Math.min(60, hours)),
        rest_days: rest,
        stage_override: stageOverride,
        coach_model: model,
      })
      onSaved(s)
      onClose()
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const removeSecret = async (name: 'lichess_token') => {
    setErr(null)
    try {
      await setSecret(name, '')
      onSaved(await brain.call<S>('settings.get'))
    } catch (e) {
      setErr((e as Error).message)
    }
  }

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-40 flex items-start justify-center bg-[rgb(0_0_0/0.18)] pt-[8vh]"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.18 }}
          onMouseDown={(e) => e.target === e.currentTarget && onClose()}
        >
          <motion.form
            onSubmit={save}
            role="dialog"
            aria-label="Settings"
            initial={{ opacity: 0, y: -12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
            className="sheet flex max-h-[84vh] w-[580px] flex-col overflow-hidden"
          >
            <div className="flex h-[48px] shrink-0 items-center justify-center border-b hairline">
              <h2 className="m-0 text-sm font-semibold">Settings</h2>
            </div>

            <div className="grid gap-6 overflow-y-auto px-6 pt-5 pb-6">
              <Group title="Accounts">
                <Row label="Chess.com username">
                  <input className="field w-[240px]" value={chesscom} onChange={(e) => setChesscom(e.target.value)} autoComplete="off" spellCheck={false} autoFocus placeholder="None" />
                </Row>
                <Row label="Lichess username">
                  <input className="field w-[240px]" value={lichess} onChange={(e) => setLichess(e.target.value)} autoComplete="off" spellCheck={false} placeholder="None" />
                </Row>
                <SecretRow
                  label="Lichess token"
                  hint="Optional: faster imports and puzzle history. Create one at lichess.org/account/oauth/token with “Read puzzle activity”. Kept in the macOS Keychain."
                  saved={settings?.has_lichess_token ?? false}
                  value={token}
                  onChange={setToken}
                  onRemove={() => removeSecret('lichess_token')}
                />
              </Group>

              <Group title="Coach" note="A local model, run by Ollama on this Mac. Free, and nothing leaves the machine.">
                <ModelPicker status={ollama} value={model} onChange={setModel} />
              </Group>

              <Group
                title="Training"
                note={settings ? `Analysis runs ${settings.engine.workers} Stockfish workers at ${num(settings.engine.nodes)} nodes a position, and re-checks your blunders at ${num(settings.engine.deep_nodes)}.` : undefined}
              >
                <Row label="Training started" hint="Gate 0 measures your progress from this date.">
                  <input type="date" className="field tabular w-[160px]" value={start} onChange={(e) => setStart(e.target.value)} />
                </Row>
                <Row label="Hours a week" hint="Spread over your training days.">
                  <input type="number" min={1} max={60} className="field tabular w-[72px] text-right" value={hours} onChange={(e) => setHours(Number(e.target.value))} />
                </Row>
                <Row label="Rest days" as="div">
                  <div className="inline-flex rounded-[8px] bg-[var(--active)] p-[2px]" role="group" aria-label="Rest days">
                    {['M', 'T', 'W', 'T', 'F', 'S', 'S'].map((d, i) => (
                      <button
                        type="button"
                        key={i}
                        aria-pressed={rest.includes(i)}
                        aria-label={['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'][i]}
                        onClick={() => setRest((r) => (r.includes(i) ? r.filter((x) => x !== i) : [...r, i].sort()))}
                        className={`h-6 w-7 rounded-[6px] text-sm ${rest.includes(i) ? 'bg-accent font-medium text-white' : 'text-muted hover:text-text'}`}
                      >
                        {d}
                      </button>
                    ))}
                  </div>
                </Row>
                <Row label="Stage" as="div">
                  <Segmented
                    label="Stage"
                    value={stageOverride == null ? 'auto' : String(stageOverride)}
                    options={[{ value: 'auto', label: 'Auto' }, ...[1, 2, 3, 4].map((n) => ({ value: String(n), label: String(n) }))]}
                    onChange={(v) => setStageOverride(v === 'auto' ? null : Number(v))}
                  />
                </Row>
              </Group>
            </div>

            <div className="flex shrink-0 items-center justify-between gap-4 border-t hairline px-6 py-3">
              <div className="min-w-0">{err && <Notice tone="bad">{err}</Notice>}</div>
              <div className="flex shrink-0 gap-2">
                <button type="button" className="btn" onClick={onClose}>
                  Cancel
                </button>
                <button className="btn btn-primary" disabled={busy}>
                  {busy ? 'Saving…' : 'Save settings'}
                </button>
              </div>
            </div>
          </motion.form>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

/** An inset group box with a title above and a footnote below, like System Settings. */
function Group({ title, note, children }: { title: string; note?: string; children: React.ReactNode }) {
  return (
    <section className="grid gap-1.5">
      <h3 className="m-0 px-1 text-sm font-semibold">{title}</h3>
      <div className="group-box divide-y divide-[var(--line)] px-3">{children}</div>
      {note && <p className="m-0 px-1 text-2xs text-muted">{note}</p>}
    </section>
  )
}

/** One form row: label (and hint) on the left, the control on the right. */
function Row({ label, hint, children, as = 'label' }: { label: string; hint?: string; children: React.ReactNode; as?: 'label' | 'div' }) {
  const Tag = as
  return (
    <Tag className="flex min-h-[44px] items-center justify-between gap-6 py-2">
      <span className="grid min-w-0">
        <span className="text-sm">{label}</span>
        {hint && <span className="text-2xs text-muted">{hint}</span>}
      </span>
      <span className="shrink-0">{children}</span>
    </Tag>
  )
}

const gb = (bytes: number | null) => (bytes ? `${(bytes / 1e9).toFixed(1)} GB` : null)

function ModelPicker({ status, value, onChange }: { status: CoachStatus | null; value: string; onChange: (v: string) => void }) {
  if (!status) return <p className="m-0 py-3 text-sm text-muted">Checking Ollama…</p>
  if (!status.running)
    return (
      <p className="m-0 py-3 text-sm text-muted">
        Ollama isn’t running. Open the Ollama app, or run <code className="font-mono">ollama serve</code>, then reopen Settings.
        {value && ` The coach is set to ${value}.`}
      </p>
    )
  const names = status.models.map((m) => m.name)
  const options = [{ name: '', size: null, params: null, quant: null }, ...status.models]
  return (
    <div className="grid">
      <div role="radiogroup" aria-label="Coach model" className="grid divide-y divide-[var(--line)]">
        {options.map((m) => {
          const on = value === m.name
          return (
            <button
              type="button"
              role="radio"
              aria-checked={on}
              key={m.name || 'off'}
              onClick={() => onChange(m.name)}
              className="flex h-9 items-center justify-between gap-4 text-left"
            >
              <span className="flex items-center gap-2.5">
                <span
                  className={`grid size-4 place-items-center rounded-full ${on ? 'bg-accent' : 'bg-[var(--control)] shadow-[var(--control-edge)]'}`}
                  aria-hidden
                >
                  {on && <span className="size-1.5 rounded-full bg-white" />}
                </span>
                <span className={m.name ? 'font-mono text-sm' : 'text-sm'}>{m.name || 'No coach'}</span>
              </span>
              <span className="tabular text-2xs text-faint">{[m.params, m.quant, gb(m.size)].filter(Boolean).join(' · ')}</span>
            </button>
          )
        })}
      </div>
      <span className="border-t hairline py-2 text-2xs text-muted">
        {status.models.length === 0
          ? 'Ollama has no models yet. Download one with ollama pull <name>, then reopen Settings.'
          : value && !names.includes(value)
            ? `${value} is no longer installed in Ollama. Choose another.`
            : 'Models of about 8B parameters fit alongside Stockfish and Maia in 16 GB.'}
      </span>
    </div>
  )
}

function SecretRow({ label, hint, saved, value, onChange, onRemove }: { label: string; hint: string; saved: boolean; value: string; onChange: (v: string) => void; onRemove: () => void }) {
  return (
    <div className="grid gap-1.5 py-2.5">
      <div className="flex items-center justify-between gap-6">
        <span className="text-sm">{label}</span>
        <span className="flex items-center gap-2">
          {saved && (
            <>
              <span className="text-2xs text-good">In Keychain</span>
              <button type="button" className="btn h-6 px-2.5 text-2xs" onClick={onRemove}>
                Remove
              </button>
            </>
          )}
          <input type="password" className="field w-[240px]" value={value} onChange={(e) => onChange(e.target.value)} placeholder={saved ? 'Paste to replace' : 'Paste it here'} autoComplete="off" aria-label={label} />
        </span>
      </div>
      <span className="text-2xs text-muted">{hint}</span>
    </div>
  )
}
