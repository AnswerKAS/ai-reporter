type VisibilityTarget = EventTarget & { visibilityState: string }

/** Refresh dataset permissions when an already open workspace becomes active again. */
export function watchDatasetAccess(
  refresh: () => void,
  tab: EventTarget = window,
  page: VisibilityTarget = document,
): () => void {
  /** Ignore visibility changes while the workspace remains in the background. */
  function onVisibilityChange(): void {
    if (page.visibilityState === 'visible') refresh()
  }

  tab.addEventListener('focus', refresh)
  page.addEventListener('visibilitychange', onVisibilityChange)
  return () => {
    tab.removeEventListener('focus', refresh)
    page.removeEventListener('visibilitychange', onVisibilityChange)
  }
}
