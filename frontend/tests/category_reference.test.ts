import assert from 'node:assert/strict'
import test from 'node:test'
import {
  referenciaAoRenomear, referenciaDoNome,
} from '../src/domain/categoryReference.ts'

/**
 * Uma referência de integração que muda sozinha quebra o outro lado sem avisar.
 *
 * Derivar o slug do nome resolveu um problema real — ninguém deveria decidir
 * formato de identificador para cadastrar "Bebidas geladas". Mas aplicar a
 * mesma derivação ao renomear uma categoria que já existe trocava, em silêncio,
 * o nome pelo qual um sistema de fora se refere a ela. O defeito não aparece
 * nesta tela: aparece na integração, depois.
 */

test('categoria nova: a referência nasce do nome', () => {
  assert.equal(referenciaAoRenomear({
    nome: 'Bebidas geladas', referenciaAtual: 'bebidas',
    categoriaExistente: false, edicaoManual: false,
  }), 'bebidas-geladas')
})

test('categoria existente: renomear não mexe na referência', () => {
  // Este é o defeito relatado: abrir a edição, corrigir o nome, e a referência
  // seguir junto sem que ninguém tenha pedido.
  assert.equal(referenciaAoRenomear({
    nome: 'Bebidas geladas e sucos', referenciaAtual: 'bebidas',
    categoriaExistente: true, edicaoManual: false,
  }), 'bebidas')
})

test('quem assume a referência à mão fica com ela, nova ou existente', () => {
  for (const categoriaExistente of [false, true]) {
    assert.equal(referenciaAoRenomear({
      nome: 'Bebidas geladas', referenciaAtual: 'bebidas-linha-2024',
      categoriaExistente, edicaoManual: true,
    }), 'bebidas-linha-2024')
  }
})

test('a derivação tira acento, espaço e pontuação sem deixar traço solto', () => {
  assert.equal(referenciaDoNome('Bebidas Geladas'), 'bebidas-geladas')
  assert.equal(referenciaDoNome('Açaí & Sorvetes'), 'acai-sorvetes')
  assert.equal(referenciaDoNome('  Pães / Bolos  '), 'paes-bolos')
  assert.equal(referenciaDoNome('—'), '')
})
