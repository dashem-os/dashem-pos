import { useEffect } from 'react'

/**
 * Business niches that carry their own visual identity.
 * The accent channels for each one live in src/index.css under [data-niche="..."].
 */
export const NICHE_THEMES = ['FOOD_SERVICE', 'RETAIL', 'BEAUTY_RESELLER'] as const

export type NicheTheme = typeof NICHE_THEMES[number]

/**
 * Deterministic precedence for tenants that contract more than one activity.
 * The operation with the heaviest visual footprint wins so the console does not
 * flip identity between page loads.
 */
const PRECEDENCE: readonly NicheTheme[] = ['FOOD_SERVICE', 'RETAIL', 'BEAUTY_RESELLER']

/**
 * Resolves which visual identity applies to a tenant.
 * Returns null when no themed activity is contracted, which keeps the primary
 * DASHEM identity (Akira red) declared on :root.
 */
export function resolveNicheTheme(activities: readonly string[] | null | undefined): NicheTheme | null {
  if (!activities || activities.length === 0) return null
  const contracted = new Set(activities)
  return PRECEDENCE.find((niche) => contracted.has(niche)) ?? null
}

/**
 * Writes the resolved identity onto the root element so every token-driven
 * surface picks up the accent. Removing the attribute restores the primary identity.
 */
export function applyNicheTheme(activities: readonly string[] | null | undefined): NicheTheme | null {
  if (typeof document === 'undefined') return null
  const niche = resolveNicheTheme(activities)
  if (niche) document.documentElement.dataset.niche = niche
  else delete document.documentElement.dataset.niche
  return niche
}

/** React binding for {@link applyNicheTheme}. */
export function useNicheTheme(activities: readonly string[] | null | undefined): void {
  const key = (activities ?? []).join(',')
  useEffect(() => {
    applyNicheTheme(activities)
  }, [key])
}
