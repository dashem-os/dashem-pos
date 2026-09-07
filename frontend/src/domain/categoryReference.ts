/**
 * A referência de integração de uma categoria, e quando ela pode mudar.
 *
 * O slug é o nome estável pelo qual um sistema de fora se refere à categoria.
 * Quem cadastra "Bebidas geladas" não deveria precisar decidir formato de
 * identificador, então em uma categoria **nova** a referência nasce do nome.
 *
 * Em uma categoria que **já existe** a conta se inverte: renomear é ato de
 * vitrine — trocar "Bebidas" por "Bebidas geladas" — e não pode arrastar junto
 * o identificador que alguém de fora já usa. Uma referência que muda sozinha
 * quebra integração sem avisar ninguém, e o defeito só aparece do outro lado.
 *
 * Por isso a regra tem três casos, e não dois: nova segue o nome; existente
 * preserva; e qualquer uma das duas passa a preservar assim que a pessoa
 * assume a referência à mão, porque aí a escolha é dela.
 */

/** O nome reduzido à forma que uma integração aceita. */
export function referenciaDoNome(nome: string): string {
  return nome
    .normalize('NFD').replace(/[\u0300-\u036f]/g, '')
    .toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
}

export interface RenomeacaoDeCategoria {
  /** O nome que a pessoa acabou de digitar. */
  nome: string
  /** A referência que o formulário tem agora. */
  referenciaAtual: string
  /** Verdadeiro quando se está editando uma categoria já cadastrada. */
  categoriaExistente: boolean
  /** Verdadeiro depois que a pessoa abriu o campo da referência. */
  edicaoManual: boolean
}

export function referenciaAoRenomear({
  nome, referenciaAtual, categoriaExistente, edicaoManual,
}: RenomeacaoDeCategoria): string {
  if (categoriaExistente || edicaoManual) return referenciaAtual
  return referenciaDoNome(nome)
}
