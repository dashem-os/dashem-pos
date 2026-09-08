import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'

const ler = (caminho: string) => readFileSync(new URL(caminho, import.meta.url), 'utf8')

const dialogo = ler('../src/components/pos/SupervisorAuthorization.tsx')
const totais = ler('../src/components/pos/SaleTotals.tsx')
const contexto = ler('../src/context/PosContext.tsx')
const layout = ler('../src/layouts/PosLayout.tsx')

test('o operador continua vendo a ação que não pode fazer sozinho', () => {
  // Botão apagado empurrava o supervisor a operar no caixa alheio, e a venda
  // ficava registrada no nome errado.
  assert.ok(!/disabled=\{[^}]*!canCancel/.test(totais), 'cancelar ainda apaga por permissão')
  assert.ok(!/disabled=\{[^}]*!canDiscount/.test(totais), 'desconto ainda apaga por permissão')
  assert.match(totais, /canCancel \? 'Cancelar venda' : 'Precisa de autorização do supervisor'/)
  assert.match(totais, /canDiscount \? 'Aplicar desconto' : 'Precisa de autorização do supervisor'/)
})

test('o diálogo pede código e senha de quem autoriza, e diz o que está autorizando', () => {
  assert.match(dialogo, /Autorização do supervisor/)
  assert.match(dialogo, /Código do supervisor/)
  assert.match(dialogo, /Senha numérica/)
  assert.match(dialogo, /autorizacaoPendente\.acao/)
  // A senha não fica à mostra no balcão.
  assert.match(dialogo, /type="password"/)
  // O erro da recusa aparece para quem digitou, não vira toast que some.
  assert.match(dialogo, /role="alert"/)
})

test('a credencial viaja no cabeçalho da requisição e não fica guardada', () => {
  assert.match(contexto, /'X-Supervisor-Code': codigo, 'X-Supervisor-Pin': pin/)
  // Some da memória assim que a operação acontece ou o diálogo é fechado.
  assert.match(contexto, /pedidoDeAutorizacao\.current = null/)
  assert.ok(!/localStorage[^\n]*[Ss]upervisor/.test(contexto), 'PIN não pode ser persistido')
})

test('quem já tem autoridade não vê diálogo nenhum', () => {
  assert.match(contexto, /if \(permissions\.includes\(permissao\)\) \{\s*\n\s*await executar\(\{\}\)/)
})

test('cancelar e descontar passam pelo mesmo caminho', () => {
  assert.match(contexto, /comAutorizacao\(\s*\n?\s*'sale\.cancel', 'Cancelar a venda'/)
  assert.match(contexto, /comAutorizacao\(\s*\n?\s*'sale\.discount', 'Aplicar desconto'/)
})

test('o diálogo está montado no PDV', () => {
  assert.match(layout, /<SupervisorAuthorization \/>/)
  assert.match(layout, /import \{ SupervisorAuthorization \}/)
})
