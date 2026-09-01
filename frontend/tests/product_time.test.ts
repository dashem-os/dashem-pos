import assert from 'node:assert/strict'
import test from 'node:test'

import { formatProductDateTime, PRODUCT_TIME_OFFSET } from '../src/utils/format.ts'

test('interprets offset-less backend timestamps as UTC and displays UTC minus three', () => {
  assert.equal(
    formatProductDateTime('2026-09-01T15:16:58'),
    `01/09/2026, 12:16:58 (${PRODUCT_TIME_OFFSET})`,
  )
})

test('preserves the instant when the API timestamp declares an offset', () => {
  assert.equal(formatProductDateTime('2026-09-01T12:16:58-03:00'), `01/09/2026, 12:16:58 (${PRODUCT_TIME_OFFSET})`)
  assert.equal(formatProductDateTime('2026-09-01T15:16:58Z'), `01/09/2026, 12:16:58 (${PRODUCT_TIME_OFFSET})`)
})

test('does not invent a date for missing or invalid evidence', () => {
  assert.equal(formatProductDateTime(undefined), '—')
  assert.equal(formatProductDateTime('invalid'), '—')
})
