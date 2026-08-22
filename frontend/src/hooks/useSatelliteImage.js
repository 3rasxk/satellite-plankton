import { useCallback, useEffect, useRef, useState } from 'react'
import client from '../api/client.js'

/**
 * Fetches a satellite PNG (from GET /satellite-image or
 * GET /risk-map/{site_id}/image) as a blob and exposes it as an object
 * URL, rather than pointing a plain <img src> straight at the backend
 * route. Two reasons this needs the extra step:
 *
 *  1. Loading state: these renders are genuinely multi-second (live GEE
 *     render, ~4-8s per backend/src/routers/satellite_image.py's own
 *     docstring) and a bare <img> gives no loading signal beyond the
 *     browser's own broken-image icon while it waits.
 *  2. Honest error text: on a 404/502/503 the backend returns a real,
 *     specific reason in the JSON body (FastAPI's HTTPException `detail`)
 *     — a plain <img onError> only fires a generic event with no access
 *     to that body. Fetching as a blob via the shared axios client lets a
 *     failed response's body be read and shown verbatim instead of
 *     inventing a generic message (CLAUDE.md: never fabricate, always
 *     show the real reason when there is one to show).
 *
 * `url` is a relative backend path (e.g. from `detect()`'s
 * `true_color_image_url`) or null/undefined — passing a falsy url is a
 * no-op (loading stays false, nothing fetched), which lets call sites
 * just pass whatever the API response gave them without an extra guard.
 *
 * Returns `{ loading, error, objectUrl }`. The object URL is revoked on
 * unmount/url change so repeated site-panel opens don't leak memory.
 *
 * Mirrors hooks/useApi.js's own load-via-indirection shape (a
 * useCallback fetch function invoked as a single-expression effect body)
 * rather than setting state directly inside the effect block.
 */
export function useSatelliteImage(url) {
  const [state, setState] = useState({ loading: !!url, error: null, objectUrl: null })
  const urlRef = useRef(null)

  const load = useCallback(() => {
    if (!url) {
      setState({ loading: false, error: null, objectUrl: null })
      return () => {}
    }

    let cancelled = false
    setState({ loading: true, error: null, objectUrl: null })

    client
      .get(url, { responseType: 'blob' })
      .then((res) => {
        if (cancelled) return
        const objUrl = URL.createObjectURL(res.data)
        urlRef.current = objUrl
        setState({ loading: false, error: null, objectUrl: objUrl })
      })
      .catch(async (err) => {
        if (cancelled) return
        let message = 'Image unavailable.'
        const data = err?.response?.data
        if (data instanceof Blob) {
          try {
            const text = await data.text()
            const parsed = JSON.parse(text)
            if (parsed && typeof parsed.detail === 'string') message = parsed.detail
          } catch {
            // Body wasn't JSON (or wasn't readable) — keep the generic
            // fallback rather than showing raw/garbled bytes.
          }
        } else if (err?.message) {
          message = err.message
        }
        setState({ loading: false, error: message, objectUrl: null })
      })

    return () => {
      cancelled = true
      if (urlRef.current) {
        URL.revokeObjectURL(urlRef.current)
        urlRef.current = null
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url])

  useEffect(() => load(), [load])

  return state
}
