/**
 * Copy text. navigator.clipboard exists only on secure pages (HTTPS or localhost); over the Docker stack's plain
 * HTTP (ADR-0032) the older copy command still works. `within` is where the hidden text box goes: inside an open
 * dialog, whose focus trap would otherwise take the focus back before the copy.
 */
export function copyText(text: string, within: HTMLElement | null = null): Promise<void> {
  if (window.isSecureContext && navigator.clipboard) return navigator.clipboard.writeText(text)
  const area = document.createElement('textarea')
  area.value = text
  area.setAttribute('readonly', '')
  area.style.position = 'fixed'
  area.style.opacity = '0'
  ;(within ?? document.body).appendChild(area)
  area.select()
  // deprecated, but the only copy that works on a page served over HTTP
  const copied = document.execCommand('copy')
  area.remove()
  return copied ? Promise.resolve() : Promise.reject(new Error('The browser refused to copy'))
}
