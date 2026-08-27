import assert from 'node:assert/strict'
import test from 'node:test'

import {
  formatBrazilianPhone,
  formatBrazilianPostalCode,
  formatCpfCnpj,
  isValidCpfCnpj,
  onlyDigits,
} from '../src/utils/brazil.ts'

test('formats Brazilian fixed and mobile telephone numbers with one adaptive mask', () => {
  assert.equal(formatBrazilianPhone('1133334444'), '(11) 3333-4444')
  assert.equal(formatBrazilianPhone('11999994444'), '(11) 99999-4444')
  assert.equal(onlyDigits('(11) 99999-4444', 11), '11999994444')
})

test('formats postal code and CPF/CNPJ according to the detected document length', () => {
  assert.equal(formatBrazilianPostalCode('22250040'), '22250-040')
  assert.equal(formatCpfCnpj('52998224725'), '529.982.247-25')
  assert.equal(formatCpfCnpj('18236120000158'), '18.236.120/0001-58')
})

test('validates CPF and CNPJ check digits locally', () => {
  assert.equal(isValidCpfCnpj('529.982.247-25'), true)
  assert.equal(isValidCpfCnpj('18.236.120/0001-58'), true)
  assert.equal(isValidCpfCnpj('000.000.000-00'), false)
  assert.equal(isValidCpfCnpj('18.236.120/0001-00'), false)
})
