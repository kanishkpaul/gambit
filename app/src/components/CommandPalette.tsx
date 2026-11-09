import { Command } from 'cmdk'
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
          className="fixed inset-0 z-50 flex items-start justify-center bg-[rgb(0_0_0/0.28)] pt-[18vh]"
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
            className="card w-[560px] overflow-hidden"
          >
            <Command label="Command palette" loop>
              <Command.Input autoFocus placeholder="Type a command" className="h-12 w-full border-b hairline bg-transparent px-4 text-md outline-none placeholder:text-faint" />
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
                          className="flex h-9 items-center justify-between rounded-[7px] px-2.5 text-sm text-muted data-[selected=true]:bg-[var(--active)] data-[selected=true]:text-text"
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
