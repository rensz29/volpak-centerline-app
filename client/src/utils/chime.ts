import alertSound from '@/assets/sounds/popup-message-alert.mp3'

/**
 * The reason assistant's alert (ADR-0040): the plant's own sound, `popup-message-alert.mp3` (about 14 s). It stops at
 * the operator's first click, touch or key on the page: they've seen it. A new call starts it again from the top.
 * Browsers play sound only once the person has clicked or typed on the page, which signing in does; otherwise it stays
 * silent and nothing else changes. If the file can't be played, the two-note tone made in the browser instead.
 */
let audio: HTMLAudioElement | null = null
let unlisten = () => {}

export function chime(): void {
  try {
    audio ??= new Audio(alertSound)
    const sound = audio
    unlisten()
    sound.currentTime = 0
    sound.play().then(
      () => {
        const stop = () => {
          sound.pause()
          unlisten()
        }
        unlisten = () => {
          window.removeEventListener('pointerdown', stop, { capture: true })
          window.removeEventListener('keydown', stop, { capture: true })
          sound.removeEventListener('ended', unlisten)
        }
        window.addEventListener('pointerdown', stop, { capture: true })
        window.addEventListener('keydown', stop, { capture: true })
        sound.addEventListener('ended', unlisten)
      },
      (caught: unknown) => {
        // Not allowed yet (no click on the page): silent, as the tone would be. Anything else: the file can't play here
        if (!(caught instanceof DOMException && caught.name === 'NotAllowedError')) tone()
      },
    )
  } catch {
    tone()
  }
}

/** A short two-note alert, made in the browser */
function tone(): void {
  try {
    const ctx = new AudioContext()
    const start = ctx.currentTime
    ;[880, 660].forEach((frequency, i) => {
      const at = start + i * 0.18
      const note = ctx.createOscillator()
      const gain = ctx.createGain()
      note.type = 'sine'
      note.frequency.value = frequency
      gain.gain.setValueAtTime(0.0001, at)
      gain.gain.exponentialRampToValueAtTime(0.3, at + 0.02)
      gain.gain.exponentialRampToValueAtTime(0.0001, at + 0.16)
      note.connect(gain).connect(ctx.destination)
      note.start(at)
      note.stop(at + 0.17)
    })
    window.setTimeout(() => void ctx.close(), 800)
  } catch {
    /* no audio here: the panel still opens */
  }
}
