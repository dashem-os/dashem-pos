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

/**
 * Date fields the server puts on the wire whose name does not end in `_at` or
 * `_until`. The suffix convention was the whole rule until 4 September 2026,
 * when an audit found `reserved_for` rendered with `new Date` on four screens:
 * a reservation booked for 19:00 announced itself to the room as 22:00.
 *
 * This list is derived from the OpenAPI schema — the wire contract itself — and
 * the backend test `test_frontend_names_every_server_date_field` fails when the
 * contract grows a name this list does not carry, or keeps one it no longer
 * has. A hand-kept list nobody checks is exactly how the first rule went stale.
 */
const SERVER_DATE_FIELDS = [
  'as_of', 'competence', 'competence_date', 'discount_ends_on', 'discount_review_on',
  'discount_starts_on', 'due_date', 'end_date', 'ends_on', 'hire_date', 'metric_date',
  'period_end', 'period_start', 'promised_for', 'reserved_for', 'review_on',
  'source_watermark', 'start_date', 'starts_on', 'watermark',
]

/**
 * Values the person typed into the browser. A `datetime-local` input is already
 * local time, so `new Date` on it is correct and must stay. Each entry is a
 * deliberate exception, not a silenced defect.
 */
const TYPED_IN_THE_BROWSER = new Set([
  'components/management/ServiceSetupManager.tsx:reservationForm.reserved_for',
])

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) return sourceFiles(full)
    return full.endsWith('.tsx') || full.endsWith('.ts') ? [full] : []
  })
}

test('no screen builds a Date straight from a server timestamp', () => {
  // A dotted path ending in a server date field. The person's own typed values
  // are named one by one above; everything else must go through parseApiDate.
  const names = ['_at', '_until', ...SERVER_DATE_FIELDS].join('|')
  const offender = new RegExp(`new Date\\(\\s*([A-Za-z_$][\\w$.?]*(?:${names}))\\b`, 'g')
  const hits: string[] = []
  for (const file of sourceFiles(SRC)) {
    const relative = file.slice(SRC.length + 1).split('\\').join('/')
    readFileSync(file, 'utf8').split('\n').forEach((line, index) => {
      for (const match of line.matchAll(offender)) {
        if (TYPED_IN_THE_BROWSER.has(`${relative}:${match[1]}`)) continue
        hits.push(`${relative}:${index + 1}  new Date(${match[1]})`)
      }
    })
  }
  assert.deepEqual(hits, [], `Use parseApiDate/formatApiDateTime nestes pontos:\n${hits.join('\n')}`)
})
