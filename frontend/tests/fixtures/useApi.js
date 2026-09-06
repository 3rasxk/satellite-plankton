let responses = {}

export function setResponses(next) {
  responses = next
}

export function useApi(fetchFn, deps, { enabled = true } = {}) {
  return {
    loading: false, error: null, data: null, refetch() {},
    ...(enabled ? responses[fetchFn.name] : {}),
  }
}
