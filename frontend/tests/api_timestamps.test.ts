import assert from 'node:assert/strict'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import test from 'node:test'

import { formatApiDateTime, millisecondsSince, parseApiDate } from '../src/utils/format.ts'

/**
 * The backend serializes naive UTC, with no offset on the wire. `new Date` on
 * such a string is parsed as local time, so every server timestamp rendered
 * that way was off by the browser's offset. The visible symptom during OA-4 was
 * a fifteen minute credential lock announcing itself three hours away; the
 * quieter ones were a terminal seen a second ago never counting as online and a
 * due date in the small hours of UTC showing the previous day.
 */

const SRC = join(import.meta.dirname, '..', 'src')

test('a timestamp without an offset is read as UTC, not as local time', () => {
  const parsed = parseApiDate('2026-09-04T00:48:00')
  assert.ok(parsed)
  assert.equal(parsed.toISOString(), '2026-09-04T00:48:00.000Z')
})

test('an offset already on the wire is respected', () => {
  assert.equal(parseApiDate('2026-09-04T00:48:00Z')?.toISOString(), '2026-09-04T00:48:00.000Z')
  assert.equal(parseApiDate('2026-09-03T21:48:00-03:00')?.toISOString(), '2026-09-04T00:48:00.000Z')
})

test('absent and unparseable values do not become Invalid Date on screen', () => {
  assert.equal(parseApiDate(null), null)
  assert.equal(parseApiDate(''), null)
  assert.equal(parseApiDate('não é data'), null)
  assert.equal(formatApiDateTime(undefined), '—')
  assert.equal(formatApiDateTime('não é data', 'time'), '—')
})

test('elapsed time is measured from the UTC instant', () => {
  const thirtySecondsAgo = new Date(Date.now() - 30_000).toISOString().replace('Z', '')
  const elapsed = millisecondsSince(thirtySecondsAgo)
  assert.ok(elapsed !== null && elapsed >= 29_000 && elapsed < 40_000, `medido ${elapsed}ms`)
  assert.equal(millisecondsSince(undefined), null)
})

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) return sourceFiles(full)
    return full.endsWith('.tsx') || full.endsWith('.ts') ? [full] : []
  })
}

test('no screen builds a Date straight from a server timestamp', () => {
  // Fields named *_at or *_until are produced by the server. Values the person
  // typed into the browser are already local and stay on `new Date`.
  const offender = /new Date\(\s*[A-Za-z_$][\w$.?]*(?:_at|_until)\b/
  const hits: string[] = []
  for (const file of sourceFiles(SRC)) {
    const source = readFileSync(file, 'utf8')
    source.split('\n').forEach((line, index) => {
      if (offender.test(line)) hits.push(`${file.slice(SRC.length + 1)}:${index + 1}`)
    })
  }
  assert.deepEqual(hits, [], `Use parseApiDate/formatApiDateTime nestes pontos:\n${hits.join('\n')}`)
})
