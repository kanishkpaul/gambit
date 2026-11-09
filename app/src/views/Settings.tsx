import { AnimatePresence, motion } from 'motion/react'
import { useEffect, useState } from 'react'
import { Notice } from '../components/ui'
import { brain } from '../lib/brain'
import { num } from '../lib/format'
import { setSecret } from '../lib/native'
import type { Settings as S } from '../lib/types'

const toDateInput = (unix: number | null) => (unix ? new Date(unix * 1000).toISOString().slice(0, 10) : '')

export function SettingsSheet({ open, onClose, settings, onSaved }: { open: boolean; onClose: () => void; settings: S | null; onSaved: (s: S) => void }) {
  const [chesscom, setChesscom] = useState('')
  const [lichess, setLichess] = useState('')
  const [start, setStart] = useState('')
  const [token, setToken] = useState('')
  const [key, setKey] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!open || !settings) return
    setChesscom(settings.chesscom_username)
    setLichess(settings.lichess_username)
    setStart(toDateInput(settings.training_start))
    setToken('')
    setKey('')
    setErr(null)
  }, [open, settings])

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
      if (key.trim()) await setSecret('anthropic_key', key)
      const s = await brain.call<S>('settings.set', {
        chesscom_username: chesscom.trim(),
        lichess_username: lichess.trim(),
        training_start: start ? Math.floor(new Date(`${start}T00:00:00`).getTime() / 1000) : settings?.training_start,
      })
      onSaved(s)
      onClose()
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const removeSecret = async (name: 'lichess_token' | 'anthropic_key') => {
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
            </Group>

            <Group title="Keys" note="Stored in the macOS Keychain. They never appear on screen again.">
              <SecretRow
                label="Lichess token"
                hint="Faster imports and puzzle history. Create one at lichess.org/account/oauth/token with “Read puzzle activity”."
                saved={settings?.has_lichess_token ?? false}
                value={token}
                onChange={setToken}
                onRemove={() => removeSecret('lichess_token')}
              />
              <SecretRow
                label="Claude API key"
                hint="For the coach, which arrives in v0.5."
                saved={settings?.has_anthropic_key ?? false}
                value={key}
                onChange={setKey}
                onRemove={() => removeSecret('anthropic_key')}
              />
            </Group>

            <Group title="Training">
              <Row label="Training started" hint="Gate 0 measures your progress from this date.">
                <input type="date" className="field tabular" value={start} onChange={(e) => setStart(e.target.value)} />
              </Row>
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
