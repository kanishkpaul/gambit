/** The few things only the shell can do. Each degrades gracefully in a plain browser (dev mode). */

const inTauri = () => '__TAURI_INTERNALS__' in window

export async function setSecret(name: 'lichess_token' | 'anthropic_key', value: string): Promise<void> {
  if (!inTauri()) throw new Error('Secrets are stored in the Keychain by the app. In browser dev mode, set them as environment variables for the brain.')
  const { invoke } = await import('@tauri-apps/api/core')
  await invoke('set_secret', { name, value })
}

export async function openExternal(url: string): Promise<void> {
  if (!inTauri()) {
    window.open(url, '_blank', 'noopener')
    return
  }
  const { invoke } = await import('@tauri-apps/api/core')
  await invoke('plugin:opener|open_url', { url })
}

/** Native menu items (Settings…, Command Palette…) arrive as events. */
export async function onMenu(fn: (id: string) => void): Promise<() => void> {
  if (!inTauri()) return () => {}
  const { listen } = await import('@tauri-apps/api/event')
  return listen<string>('menu', (e) => fn(e.payload))
}
