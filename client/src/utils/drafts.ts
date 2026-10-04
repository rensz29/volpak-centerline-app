/**
 * What an operator has typed but not sent, kept only in this browser (guide §7.1). It's wiped
 * when the session ends (sign-out, the shift's end, a takeover) and when its request closes.
 * Storage can be unavailable (a private window): then nothing is kept, and nothing breaks.
 */

const PREFIX = 'centerline.draft.'

export function loadDraft(key: string): string {
  try {
    return window.localStorage.getItem(PREFIX + key) ?? ''
  } catch {
    return ''
  }
}

export function saveDraft(key: string, text: string): void {
  try {
    if (text) window.localStorage.setItem(PREFIX + key, text)
    else window.localStorage.removeItem(PREFIX + key)
  } catch {
    /* nothing kept */
  }
}

/** Every draft, or those whose key the test rejects (e.g. requests still open). */
export function clearDrafts(keep: (key: string) => boolean = () => false): void {
  try {
    const keys: string[] = []
    for (let i = 0; i < window.localStorage.length; i++) {
      const k = window.localStorage.key(i)
      if (k?.startsWith(PREFIX) && !keep(k.slice(PREFIX.length))) keys.push(k)
    }
    keys.forEach((k) => window.localStorage.removeItem(k))
  } catch {
    /* nothing to clear */
  }
}
