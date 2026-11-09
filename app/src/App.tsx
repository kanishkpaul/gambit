import { AnimatePresence } from 'motion/react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { CommandPalette, type PaletteAction } from './components/CommandPalette'
import { Sidebar, VIEWS, type ViewId } from './components/Sidebar'
import { Transition } from './components/ui'
import { brain } from './lib/brain'
import { useConnection, useEvent, useRpc } from './lib/hooks'
import { onMenu } from './lib/native'
import type { AnalysisStatus, GuardStatus, ImportState, Settings } from './lib/types'
import { Audit } from './views/Audit'
import { Mirror } from './views/Mirror'
import { SettingsSheet } from './views/Settings'
import { Slope } from './views/Slope'
import { Solve } from './views/Solve'
import { GameLab } from './views/GameLab'
import { Today } from './views/Today'
import { Endgames } from './views/Endgames'
import { Sparring } from './views/Sparring'

const loadView = (): ViewId => {
  try {
    const v = localStorage.getItem('gambit.view') as ViewId | null
    return v && VIEWS.some((x) => x.id === v) ? v : 'today'
  } catch {
    return 'today'
  }
}

export default function App() {
  const [view, setViewState] = useState<ViewId>(loadView)
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const conn = useConnection()

  const { data: settings, setData: setSettings } = useRpc<Settings>('settings.get')
  const pushedSettings = useEvent<Settings>('settings')
  useEffect(() => {
    if (pushedSettings) setSettings(pushedSettings)
  }, [pushedSettings, setSettings])

  const { data: initialAnalysis } = useRpc<AnalysisStatus>('analysis.status')
  const analysis = useEvent<AnalysisStatus>('analysis', initialAnalysis)
  const { data: initialImport } = useRpc<ImportState>('import.status')
  const imp = useEvent<ImportState>('import', initialImport)

  const { data: guard, setData: setGuard } = useRpc<GuardStatus>('guard.status', {}, ['import', 'settings'])
  const pushedGuard = useEvent<GuardStatus>('guard')
  useEffect(() => {
    if (pushedGuard) setGuard(pushedGuard)
  }, [pushedGuard, setGuard])
  const stopForToday = useCallback(() => {
    brain.call<GuardStatus>('guard.tilt', { on: true }).then(setGuard)
  }, [setGuard])

  const setView = useCallback((v: ViewId) => {
    setViewState(v)
    try {
      localStorage.setItem('gambit.view', v)
    } catch {
      /* per-viewer convenience only */
    }
  }, [])

  const toggleLock = useCallback(() => {
    brain.call<Settings>('fairplay.set', { locked: !settings?.fairplay_lock }).then(setSettings)
  }, [settings, setSettings])

  // Keyboard: ⌘K palette, ⌘, settings, ⌘1–8 views.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!e.metaKey) return
      if (e.key === 'k') {
        e.preventDefault()
        setPaletteOpen((o) => !o)
      } else if (e.key === ',') {
        e.preventDefault()
        setSettingsOpen(true)
      } else if (/^[1-8]$/.test(e.key)) {
        e.preventDefault()
        setView(VIEWS[Number(e.key) - 1].id)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [setView])

  useEffect(() => {
    let off: (() => void) | undefined
    onMenu((id) => (id === 'settings' ? setSettingsOpen(true) : id === 'palette' && setPaletteOpen(true))).then((f) => (off = f))
    return () => off?.()
  }, [])

  const actions = useMemo<PaletteAction[]>(() => {
    const running = analysis?.state === 'running'
    return [
      ...VIEWS.map((v) => ({ id: `go-${v.id}`, label: v.label, group: 'Go to' as const, hint: v.hint, run: () => setView(v.id) })),
      { id: 'settings', label: 'Settings', group: 'Go to', hint: '⌘,', run: () => setSettingsOpen(true) },
      { id: 'import', label: 'Check for new games', group: 'Actions', run: () => void brain.call('import.start').catch(() => {}) },
      running
        ? { id: 'pause', label: 'Pause analysis', group: 'Actions', run: () => void brain.call('analysis.pause') }
        : { id: 'analyse', label: 'Resume analysis', group: 'Actions', run: () => void brain.call('analysis.start').catch(() => {}) },
      { id: 'lock', label: settings?.fairplay_lock ? 'Turn the fair-play lock off' : 'Turn the fair-play lock on', group: 'Actions', run: toggleLock },
      { id: 'tilt', label: 'That loss made me angry: stop playing for today', group: 'Actions', run: stopForToday },
    ]
  }, [analysis?.state, settings?.fairplay_lock, setView, toggleLock, stopForToday])

  return (
    <div className="grid h-full grid-cols-[224px_1fr]">
      <Sidebar view={view} onView={setView} settings={settings} analysis={analysis} onToggleLock={toggleLock} onSettings={() => setSettingsOpen(true)} />
      <main className="relative min-h-0 overflow-y-auto bg-bg">
        <div className="absolute inset-x-0 top-0 h-[38px]" data-tauri-drag-region />
        {conn === 'down' && (
          <div className="sticky top-0 z-10 border-b hairline bg-surface px-12 py-2.5 text-xs text-bad">
            The brain isn't responding. gambit keeps retrying; if this stays, quit and reopen the app.
          </div>
        )}
        {guard && guard.stop_loss.level !== 'clear' && ['today', 'mirror', 'slope'].includes(view) && <StopLoss g={guard} />}
        <AnimatePresence mode="wait">
          <Transition key={view} id={view} fill={['solve', 'lab', 'endgames', 'sparring'].includes(view)}>
            {view === 'mirror' && <Mirror settings={settings} analysis={analysis} imp={imp} onSettingsChange={setSettings} />}
            {view === 'solve' && <Solve />}
            {view === 'lab' && <GameLab />}
            {view === 'today' && <Today onGo={setView} />}
            {view === 'endgames' && <Endgames />}
            {view === 'sparring' && <Sparring onGo={setView} />}
            {view === 'slope' && <Slope />}
            {view === 'audit' && <Audit />}
          </Transition>
        </AnimatePresence>
      </main>
      <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} actions={actions} />
      <SettingsSheet open={settingsOpen} onClose={() => setSettingsOpen(false)} settings={settings} onSaved={setSettings} />
    </div>
  )
}

/** The stop-loss: honest and plain, never a scold. Study is always open. */
function StopLoss({ g }: { g: GuardStatus }) {
  const s = g.stop_loss
  const text = s.tilted
    ? 'You flagged a loss that made you angry. No more games today; solving and post-mortems are still open.'
    : s.level === 'stop'
      ? `${s.streak} straight losses today. Stop playing for today; a post-mortem of the last one is a better use of the evening.`
      : `${s.streak} losses in a row today. One more and it's time to stop for the day.`
  return (
    <div className="mx-auto w-full max-w-[1040px] px-12 pt-12">
      <div className={`rounded-lg border px-4 py-3 text-xs ${s.level === 'stop' ? 'border-[var(--bad)] text-text' : 'hairline text-muted'}`} role="status">
        {text}
      </div>
    </div>
  )
}
