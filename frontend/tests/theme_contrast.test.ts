import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

/**
 * The light-theme migration was mechanical and produced text that collides with
 * its own background: a dark hero left with near-black text, a selected tab
 * painted white on white, a white card inheriting the white text of the dark
 * shell around it. These rules catch that class of defect statically, in both
 * directions, so a colour edit cannot ship an unreadable surface again.
 */

const SRC = join(fileURLToPath(new URL('../src', import.meta.url)))

const DARK_BACKGROUND = /\bbg-(\[#[0-7][0-9a-fA-F]{5}\]|slate-(700|800|900|950)|(?:emerald|sky|rose|red|amber|violet|indigo|cyan|teal|purple)-(900|950))(?![-\w])/
const DARK_TEXT = /\btext-(dashem-strong|brand-ink|slate-(700|800|900|950))(?![-\w])/
const LIGHT_BACKGROUND = /\bbg-(white|dashem-surface|dashem-surface-elevated|dashem-bg|brand-soft|slate-(50|100))(?![-\w])/
const LIGHT_TEXT = /\btext-(white|dashem-bg|slate-(100|200))(?![-\w])/
const BRAND_FILL = /\bbg-(brand|dashem-red)(?![-\w/])/
const LIGHT_GRADIENT_STOP = /\b(from|via|to)-(white|dashem-surface|dashem-surface-elevated|dashem-bg|slate-(50|100))(?![-\w])/
const DARK_GRADIENT_STOP = /\b(from|via|to)-(\[#[0-7][0-9a-fA-F]{5}\]|slate-(700|800|900|950))(?![-\w])/

/**
 * A colour declared on the element itself for its base state. A variant such as
 * `placeholder:text-slate-400` does not colour the typed value, so it must not
 * satisfy the rule.
 */
const OWN_TEXT_COLOUR = /(^|[\s"'`{])text-[a-z]/

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

test('every credential input declares its own text colour', () => {
  // The first-access password field rendered white on white because it inherited
  // the dark shell's text colour into a white card. On a screen where someone
  // types a secret, an invisible character is a usability and security failure,
  // so these inputs never rely on inheritance.
  const folders = ['components/auth', 'components/context']
  const hits: string[] = []
  for (const folder of folders) {
    for (const file of tsxFiles(join(SRC, folder))) {
      const source = readFileSync(file, 'utf8')
      let index = source.indexOf('<input')
      while (index !== -1) {
        const close = source.indexOf('/>', index)
        const tag = source.slice(index, close === -1 ? index + 800 : close)
        if (!OWN_TEXT_COLOUR.test(tag)) {
          hits.push(`${file.slice(SRC.length + 1)}: ${tag.replace(/\s+/g, ' ').slice(0, 90)}`)
        }
        index = source.indexOf('<input', index + 1)
      }
    }
  }
  assert.deepEqual(hits, [], `Campo de credencial sem cor de texto própria:\n${hits.join('\n')}`)
})

test('no gradient runs from a light stop to a dark one', () => {
  // Text cannot stay readable across both ends, which is how the plan card
  // faded its own copy into the background.
  const hits = violations((chunk) => LIGHT_GRADIENT_STOP.test(chunk) && DARK_GRADIENT_STOP.test(chunk))
  assert.deepEqual(hits, [], `Gradiente atravessa claro e escuro:\n${hits.join('\n')}`)
})

test('the focus indicator is not animated into existence', () => {
  // `transition` animates box-shadow, so the ring only appears after the
  // animation ends. An accessibility indicator has to be there the instant
  // focus lands — and reading it synchronously is exactly what the acceptance
  // suite does, which is how this reached CI unnoticed.
  const hits: string[] = []
  for (const file of tsxFiles(SRC)) {
    for (const chunk of classStrings(readFileSync(file, 'utf8'))) {
      if (!/\bfocus-visible:ring-\d/.test(chunk) && !/\bfocus:ring-\d/.test(chunk)) continue
      if (!/\btransition(?![-\w])/.test(chunk)) continue
      hits.push(`${file.slice(SRC.length + 1)}: ${chunk.trim().slice(0, 90)}`)
    }
  }
  assert.deepEqual(hits, [], `Use transition-colors: 'transition' anima o anel de foco:\n${hits.join('\n')}`)
})
