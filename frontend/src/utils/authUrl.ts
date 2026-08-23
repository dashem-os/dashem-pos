export function withoutRecoveryMode(href: string): string {
  const url = new URL(href)
  if (url.searchParams.get('mode') === 'recovery') {
    url.searchParams.delete('mode')
  }
  return `${url.pathname}${url.search}${url.hash}`
}

export function clearRecoveryModeFromBrowser(): void {
  const currentPath = `${window.location.pathname}${window.location.search}${window.location.hash}`
  const nextPath = withoutRecoveryMode(window.location.href)
  if (nextPath !== currentPath) {
    window.history.replaceState({}, '', nextPath)
  }
}
