import assert from 'node:assert/strict'
import test from 'node:test'

import { withoutRecoveryMode } from '../src/utils/authUrl.ts'

test('removes the recovery mode after a cancelled password reset', () => {
  assert.equal(
    withoutRecoveryMode('https://dashem-pos.vercel.app/login?mode=recovery'),
    '/login',
  )
})

test('preserves unrelated query parameters and the URL fragment', () => {
  assert.equal(
    withoutRecoveryMode('https://dashem-pos.vercel.app/login?mode=recovery&source=email#complete'),
    '/login?source=email#complete',
  )
})

test('does not remove other authentication modes', () => {
  assert.equal(
    withoutRecoveryMode('https://dashem-pos.vercel.app/login?mode=invite'),
    '/login?mode=invite',
  )
})
