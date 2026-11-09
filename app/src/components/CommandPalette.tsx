import { Command } from 'cmdk'
import { Search } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useEffect } from 'react'

export interface PaletteAction {
  id: string
  label: string
  group: 'Go to' | 'Actions'
  hint?: string
  run: () => void
}

export function CommandPalette({ open, onOpenChange, actions }: { open: boolean; onOpenChange: (o: boolean) => void; actions: PaletteAction[] }) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onOpenChange(false)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onOpenChange])

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-start justify-center bg-[rgb(0_0_0/0.12)] pt-[16vh]"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.16 }}
          onMouseDown={(e) => e.target === e.currentTarget && onOpenChange(false)}
        >
          <motion.div
            initial={{ opacity: 0, y: 8, scale: 0.99 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 4 }}
            transition={{ duration: 0.18, ease: [0.22, 1, 0.36, 1] }}
            className="w-[600px] overflow-hidden rounded-[16px] bg-[color-mix(in_srgb,var(--bg)_82%,transparent)] shadow-[var(--shadow)] backdrop-blur-2xl backdrop-saturate-150"
          >
            <Command label="Command palette" loop>
              <div className="flex h-[52px] items-center gap-2.5 border-b hairline px-4">
                <Search size={20} strokeWidth={1.75} className="shrink-0 text-muted" aria-hidden />
                <Command.Input autoFocus placeholder="Go to a view or run a command" className="h-full w-full bg-transparent text-xl font-light outline-none placeholder:text-faint focus-visible:outline-none" />
              </div>
              <Command.List className="max-h-[340px] overflow-y-auto p-1.5">
                <Command.Empty className="px-3 py-6 text-center text-xs text-muted">No matching command.</Command.Empty>
                {(['Go to', 'Actions'] as const).map((g) => (
                  <Command.Group key={g} heading={g}>
                    {actions
                      .filter((a) => a.group === g)
                      .map((a) => (
                        <Command.Item
                          key={a.id}
                          value={`${g} ${a.label}`}
                          onSelect={() => {
                            onOpenChange(false)
                            a.run()
                          }}
                          className="flex h-8 items-center justify-between rounded-[7px] px-2.5 text-sm text-text data-[selected=true]:bg-accent data-[selected=true]:text-white [&[data-selected=true]_kbd]:text-white/75"
                        >
                          {a.label}
                          {a.hint && <kbd>{a.hint}</kbd>}
                        </Command.Item>
                      ))}
                  </Command.Group>
                ))}
              </Command.List>
            </Command>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
