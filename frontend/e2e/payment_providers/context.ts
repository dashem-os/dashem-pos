// Only the shell context is supplied by the test. Every API call uses real HTTP.
export function usePos() {
  return { ...window.__providerContext, showToast: (type, message) => { window.__toasts.push({ type, message }) } }
}
