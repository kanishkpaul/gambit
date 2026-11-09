import { AnimatePresence, motion } from 'motion/react'
import { useEffect, useState } from 'react'
import { Notice } from '../components/ui'
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
          className="fixed inset-0 z-40 flex items-start justify-center bg-[rgb(0_0_0/0.32)] pt-[10vh]"
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
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 4 }}
            transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}
            className="card max-h-[80vh] w-[560px] overflow-y-auto"
          >
            <div className="flex items-baseline justify-between border-b hairline px-7 pt-6 pb-4">
              <h2 className="display m-0 text-lg">Settings</h2>
              <kbd>esc</kbd>
            </div>

            <Group title="Accounts">
              <Row label="Chess.com username">
                <input className="field" value={chesscom} onChange={(e) => setChesscom(e.target.value)} autoComplete="off" spellCheck={false} autoFocus />
              </Row>
              <Row label="Lichess username">
                <input className="field" value={lichess} onChange={(e) => setLichess(e.target.value)} autoComplete="off" spellCheck={false} />
              </Row>
              <SecretRow
                label="Lichess token"
                hint="Optional: faster imports and puzzle history. Create one at lichess.org/account/oauth/token with “Read puzzle activity”. Kept in the macOS Keychain; it never appears on screen again."
                saved={settings?.has_lichess_token ?? false}
                value={token}
                onChange={setToken}
                onRemove={() => removeSecret('lichess_token')}
              />
            </Group>

            <Group title="Coach" note="A local model, run by Ollama on this Mac. Free, and nothing leaves the machine.">
              <ModelPicker status={ollama} value={model} onChange={setModel} />
            </Group>

            <Group title="Training">
              <Row label="Training started" hint="Gate 0 measures your progress from this date.">
                <input type="date" className="field tabular" value={start} onChange={(e) => setStart(e.target.value)} />
              </Row>
              <Row label="Hours a week" hint="The plan spreads these over your training days.">
                <input type="number" min={1} max={60} className="field tabular w-28" value={hours} onChange={(e) => setHours(Number(e.target.value))} />
              </Row>
              <div className="grid gap-1.5">
                <span className="text-xs text-muted">Rest days</span>
                <div className="flex gap-1.5">
                  {['M', 'T', 'W', 'T', 'F', 'S', 'S'].map((d, i) => (
                    <button
                      type="button"
                      key={i}
                      aria-pressed={rest.includes(i)}
                      onClick={() => setRest((r) => (r.includes(i) ? r.filter((x) => x !== i) : [...r, i].sort()))}
                      className={`size-8 rounded-md border text-xs ${rest.includes(i) ? 'border-[var(--text)] bg-surface-2 text-text' : 'hairline text-muted'}`}
                    >
                      {d}
                    </button>
                  ))}
                </div>
              </div>
              <div className="grid gap-1.5">
                <span className="text-xs text-muted">Stage</span>
                <div className="flex gap-1.5">
                  {[null, 1, 2, 3, 4].map((st) => (
                    <button
                      type="button"
                      key={String(st)}
                      aria-pressed={stageOverride === st}
                      onClick={() => setStageOverride(st)}
                      className={`h-8 rounded-md border px-3 text-xs ${stageOverride === st ? 'border-[var(--text)] bg-surface-2 text-text' : 'hairline text-muted'}`}
                    >
                      {st ?? 'From my rating'}
                    </button>
                  ))}
                </div>
              </div>
              {settings && (
                <p className="m-0 text-2xs text-faint">
                  Analysis runs {settings.engine.workers} Stockfish workers at {num(settings.engine.nodes)} nodes a position, and re-checks your blunders at{' '}
                  {num(settings.engine.deep_nodes)}.
                </p>
              )}
            </Group>

            <div className="flex items-center justify-between gap-4 border-t hairline px-7 py-4">
              <div className="min-w-0">{err && <Notice tone="bad">{err}</Notice>}</div>
              <div className="flex shrink-0 gap-2">
                <button type="button" className="btn btn-quiet" onClick={onClose}>
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

function Group({ title, note, children }: { title: string; note?: string; children: React.ReactNode }) {
  return (
    <section className="grid gap-4 px-7 py-5">
      <div>
        <h3 className="eyebrow m-0">{title}</h3>
        {note && <p className="mt-1 mb-0 text-2xs text-faint">{note}</p>}
      </div>
      {children}
    </section>
  )
}

function Row({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="grid gap-1.5">
      <span className="text-xs text-muted">{label}</span>
      {children}
      {hint && <span className="text-2xs text-faint">{hint}</span>}
    </label>
  )
}

const gb = (bytes: number | null) => (bytes ? `${(bytes / 1e9).toFixed(1)} GB` : null)

function ModelPicker({ status, value, onChange }: { status: CoachStatus | null; value: string; onChange: (v: string) => void }) {
  if (!status) return <span className="text-2xs text-faint">Checking Ollama…</span>
  if (!status.running)
    return (
      <span className="text-2xs text-muted">
        Ollama isn’t running. Open the Ollama app, or run <code className="font-mono">ollama serve</code>, then reopen Settings.
        {value && ` The coach is set to ${value}.`}
      </span>
    )
  const names = status.models.map((m) => m.name)
  const options = [{ name: '', size: null, params: null, quant: null }, ...status.models]
  return (
    <div className="grid gap-1.5">
      <div role="radiogroup" aria-label="Coach model" className="grid overflow-hidden rounded-lg border hairline">
        {options.map((m) => {
          const on = value === m.name
          return (
            <button
              type="button"
              role="radio"
              aria-checked={on}
              key={m.name || 'off'}
              onClick={() => onChange(m.name)}
              className={`flex items-baseline justify-between gap-4 border-b hairline px-3 py-2 text-left last:border-b-0 ${on ? 'bg-surface-2 text-text' : 'text-muted hover:text-text'}`}
            >
              <span className="flex items-center gap-2.5">
                <span className={`size-1.5 rounded-full ${on ? 'bg-[var(--text)]' : 'bg-transparent'}`} aria-hidden />
                <span className={m.name ? 'font-mono text-xs' : 'text-xs'}>{m.name || 'No coach'}</span>
              </span>
              <span className="tabular text-2xs text-faint">{[m.params, m.quant, gb(m.size)].filter(Boolean).join(' · ')}</span>
            </button>
          )
        })}
      </div>
      <span className="text-2xs text-faint">
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
    <div className="grid gap-1.5">
      <div className="flex items-baseline justify-between">
        <span className="text-xs text-muted">{label}</span>
        {saved && (
          <span className="flex items-center gap-3 text-2xs">
            <span className="text-good">Saved in Keychain</span>
            <button type="button" className="text-faint hover:text-text" onClick={onRemove}>
              Remove
            </button>
          </span>
        )}
      </div>
      <input type="password" className="field" value={value} onChange={(e) => onChange(e.target.value)} placeholder={saved ? 'Paste a new one to replace it' : 'Paste it here'} autoComplete="off" />
      <span className="text-2xs text-faint">{hint}</span>
    </div>
  )
}
