import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * Loading/error/data fetch hook shared by every page. `fetchFn` should be
 * a stable-enough async function (wrap in useCallback at the call site
 * when it closes over changing args like lat/lng); `deps` controls when
 * it re-runs, same semantics as useEffect's dependency array.
 *
 * Kept intentionally small — no caching/retry policy beyond a manual
 * `refetch`, this app has ~5 call sites total.
 */
export function useApi(fetchFn, deps = [], { enabled = true } = {}) {
  const fetchRef = useRef(fetchFn)
  fetchRef.current = fetchFn

  const [state, setState] = useState({ data: null, loading: enabled, error: null })

  const refetch = useCallback(() => {
    if (!enabled) {
      setState({ data: null, loading: false, error: null })
      return () => {}
    }
    let cancelled = false
    setState((s) => ({ ...s, loading: true, error: null }))
    fetchRef
      .current()
      .then((data) => {
        if (!cancelled) setState({ data, loading: false, error: null })
      })
      .catch((error) => {
        if (!cancelled) setState({ data: null, loading: false, error })
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, ...deps])

  useEffect(() => refetch(), [refetch])

  return { ...state, refetch }
}
