import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

/**
 * The light-theme migration was mechanical and produced text that collides with
 * its own background: a dark hero left with near-black text, a selected tab
 * painted white on white. These rules catch that class of defect statically,
 * in both directions, so a colour edit cannot ship an unreadable surface again.
 */

const SRC = join(fileURLToPath(new URL('../src', import.meta.url)))

const DARK_BACKGROUND = /\bbg-(\[#[0-7][0-9a-fA-F]{5}\]|slate-(700|800|900|950)|(?:emerald|sky|rose|red|amber|violet|indigo|cyan|teal|purple)-(900|950))(?![-\w])/
const DARK_TEXT = /\btext-(dashem-strong|brand-ink|slate-(700|800|900|950))(?![-\w])/
const LIGHT_BACKGROUND = /\bbg-(white|dashem-surface|dashem-surface-elevated|dashem-bg|brand-soft|slate-(50|100))(?![-\w])/
const LIGHT_TEXT = /\btext-(white|dashem-bg|slate-(100|200))(?![-\w])/
const BRAND_FILL = /\bbg-(brand|dashem-red)(?![-\w/])/
const LIGHT_GRADIENT_STOP = /\b(from|via|to)-(white|dashem-surface|dashem-surface-elevated|dashem-bg|slate-(50|100))(?![-\w])/
const DARK_GRADIENT_STOP = /\b(from|via|to)-(\[#[0-7][0-9a-fA-F]{5}\]|slate-(700|800|900|950))(?![-\w])/

/** Every quoted string in the file, with template holes removed. */
function classStrings(source: string): string[] {
  const found: string[] = []
  const pattern = /"([^"\n]*)"|'([^'\n]*)'|`([^`]*)`/g
  let match: RegExpExecArray | null
  while ((match = pattern.exec(source)) !== null) {
    const raw = match[1] ?? match[2] ?? match[3] ?? ''
    if (!raw.includes(' ') && !raw.includes('-')) continue
    // A template hole splits the literal: classes on either side never combine.
    for (const chunk of raw.split(/\$\{[^}]*\}/)) {
      // Only the base state is comparable. A variant such as group-hover:text-white
      // pairs with its own group-hover background and is not a collision.
      const base = chunk.split(/\s+/).filter((cls) => cls && !cls.includes(':')).join(' ')
      if (/\b(bg|text|from|via|to)-/.test(base)) found.push(base)
    }
  }
  return found
}

function tsxFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) return tsxFiles(full)
    return full.endsWith('.tsx') ? [full] : []
  })
}

function violations(check: (chunk: string) => boolean): string[] {
  const hits: string[] = []
  for (const file of tsxFiles(SRC)) {
    const source = readFileSync(file, 'utf8')
    for (const chunk of classStrings(source)) {
      if (check(chunk)) hits.push(`${file.slice(SRC.length + 1)}: ${chunk.trim().slice(0, 90)}`)
    }
  }
  return hits
}

test('dark surfaces never carry dark text', () => {
  const hits = violations((chunk) => DARK_BACKGROUND.test(chunk) && DARK_TEXT.test(chunk))
  assert.deepEqual(hits, [], `Texto escuro sobre fundo escuro:\n${hits.join('\n')}`)
})

test('light surfaces never carry light text', () => {
  const hits = violations((chunk) => LIGHT_BACKGROUND.test(chunk) && LIGHT_TEXT.test(chunk))
  assert.deepEqual(hits, [], `Texto claro sobre fundo claro:\n${hits.join('\n')}`)
})

test('a brand fill states its own contrast colour', () => {
  // text-white breaks the amber identity; brand-contrast follows the niche.
  const hits = violations((chunk) => BRAND_FILL.test(chunk) && /\btext-white\b/.test(chunk))
  assert.deepEqual(hits, [], `Use text-brand-contrast sobre preenchimento de marca:\n${hits.join('\n')}`)
})

test('no gradient runs from a light stop to a dark one', () => {
  // Text cannot stay readable across both ends, which is how the plan card
  // faded its own copy into the background.
  const hits = violations((chunk) => LIGHT_GRADIENT_STOP.test(chunk) && DARK_GRADIENT_STOP.test(chunk))
  assert.deepEqual(hits, [], `Gradiente atravessa claro e escuro:\n${hits.join('\n')}`)
})
