/**
 * Clipboard and file-download helpers for CiteButton and FigureFrame.
 *
 * Data source: text the caller already built (a citation, a CSV string);
 * nothing is fetched or computed here.
 *
 * Rules: never throw. Every browser API is feature-checked and wrapped,
 * because clipboard access is refused on insecure origins, in some iframes
 * and when the document is not focused, and a Blob URL can fail under
 * strict privacy settings. Callers get a boolean (or a promise of one) and
 * show a fallback (e.g. selectable text) when it is false.
 *
 * Limitations: `downloadText` writes UTF-8; pass a BOM in the text itself
 * when a spreadsheet program needs one (src/lib/csv.js `{bom: true}`).
 */

/** Legacy synchronous copy through a temporary off-screen textarea. */
function execCommandCopy(text) {
  if (typeof document === 'undefined' || typeof document.execCommand !== 'function' || !document.body) return false
  let area = null
  try {
    area = document.createElement('textarea')
    area.value = text
    area.setAttribute('readonly', '')
    area.style.position = 'fixed'
    area.style.top = '-1000px'
    area.style.opacity = '0'
    document.body.appendChild(area)
    area.select()
    return document.execCommand('copy') === true
  } catch {
    return false
  } finally {
    if (area && area.parentNode) area.parentNode.removeChild(area)
  }
}

/** Copy text; resolves true when the browser reports success. */
export async function copyText(text) {
  if (typeof text !== 'string' || text === '') return false
  try {
    if (typeof navigator !== 'undefined' && navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    // Refused (permissions, insecure origin, unfocused document): try the legacy path.
  }
  return execCommandCopy(text)
}

/** Offer `text` as a file download; true when the download was started. */
export function downloadText(filename, text, type = 'text/csv;charset=utf-8') {
  if (typeof document === 'undefined' || typeof URL === 'undefined' || typeof Blob === 'undefined') return false
  if (typeof text !== 'string') return false
  let url = null
  try {
    url = URL.createObjectURL(new Blob([text], { type }))
    const link = document.createElement('a')
    link.href = url
    link.download = typeof filename === 'string' && filename ? filename : 'download.csv'
    link.rel = 'noopener'
    document.body.appendChild(link)
    link.click()
    link.remove()
    return true
  } catch {
    return false
  } finally {
    // Revoke on the next tick so the browser has read the Blob.
    if (url) setTimeout(() => URL.revokeObjectURL(url), 0)
  }
}
