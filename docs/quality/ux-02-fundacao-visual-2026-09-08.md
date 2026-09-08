# UX-02 — a fundação visual, e um lugar para mudar a cor

Data: 08/09/2026 · base: [UX-01](ux-01-navegacao-2026-09-08.md) ·
trilha: [sprints da experiência](../product/ui-ux-implementation-sprints.md).

O sistema já tinha tokens de marca por nicho e uma escala de neutros. Não tinha
nenhum canal para **situação** — e o efeito era que cada tela escolhia a sua cor
crua do Tailwind: `emerald-700` numa, `emerald-800` na outra, um `violet-700` em
Categorias sem motivo nenhum. Eram 36 escolhas soltas só nas quatro telas de
Mercadorias, mais 38 nos componentes de fundação. Nenhuma acompanhava o nicho, e
corrigir o verde de "em dia" exigia achar as seis grafias dele.

## A escala de estados

Quatro estados — sucesso, atenção, perigo, informação — com seis degraus cada,
em `frontend/src/index.css`. Cada degrau existe porque uma tela precisava dele:

| Degrau | Onde aparece |
|---|---|
| `state-*` | o texto e o preenchimento sobre fundo claro |
| `state-*-soft` | o fundo da faixa |
| `state-*-border` | a moldura da faixa |
| `state-*-strong` | a superfície escura das mensagens |
| `state-*-on-strong` | o texto que se lê sobre ela |
| `state-*-accent` | o ícone que ainda precisa saltar no escuro |

**Os canais de estado não mudam por nicho.** "Em falta" é vermelho na padaria e
na revendedora de beleza; quem troca por nicho é a marca. As duas famílias ficam
separadas de propósito, e um teste reprova se um bloco `[data-niche]` tentar
redefinir cor de situação.

## O que passou a falar em token

Zero cor crua da paleta em:

- as quatro telas de Mercadorias — `CatalogManager`, `CategoryManager`,
  `AssortmentManager`, `InventoryManager`;
- o conteúdo da entrada — `DashboardBI`;
- os dois estados novos da UX-01 — `AreaHub` e `ManagementLayout`;
- e a fundação que todas usam: `Badge`, `Button`, `EmptyState`, `Field`,
  `RowActions`, `StatCard`, `Toast`.

`design_tokens.test.ts` reprova cor crua nesses arquivos, exige os 24 canais em
`index.css` e proíbe um nicho redefinir estado. Ele já acusou duas vezes durante
a própria sprint: `amber` e `red` que o meu levantamento inicial não tinha visto,
porque eu só tinha procurado por seis famílias de cor.

## Um título por tela

A UX-01 introduziu o defeito que esta sprint tira: no estado de módulo havia
**dois** `h1` — o do módulo e um que a casca acrescentava para ter onde pousar o
foco. E o topo repetia o nome do destino que o título logo abaixo já dizia.

Agora:

- o topo mostra **a área** e a unidade, que é o que o contrato admite como texto
  de contexto — no hub ele nem isso, porque ali o título da tela já é o nome da
  área;
- o módulo traz o próprio título, e é ele que recebe o foco;
- `CatalogManager` era a única das quatro sem `h1`: usava `h2` para o título da
  própria página.

## O que a medida encontrou, e o que o olho encontrou

`ux02_foundation.cjs` mede, em 1366×640 e 390×844, nas seis telas: quantos
títulos de página existem, se o topo repete o título, se há cartão dentro de
cartão, e se a busca e o começo da lista aparecem sem rolar.

Ele acusou seis coisas na primeira rodada. Três eram defeito real:

1. **Cartão dentro de cartão na entrada** — os oito quadros de operação viviam
   dentro de um `Card`, cada um com a sua moldura. Moldura sobre moldura não
   agrupa melhor: o preenchimento agrupa, e a tela perde oito bordas
   concorrendo com a do painel.
2. **O topo repetindo o título** no hub.
3. **Categorias sem lista** — e essa não era da tela: o semeador não criava
   categoria nenhuma, então a tela media vazio. Ganhou quatro categorias, uma
   dentro da outra, e cinco dos seis produtos classificados. O sexto fica sem
   categoria de propósito: a tela tem de aguentar o produto que ninguém
   classificou, que é o caso comum de quem cadastra correndo.

As outras três eram **erro do meu detector**, e valem registro porque é fácil
repetir: ele chamava de cartão um seletor de período (uma caixa com moldura cujos
filhos são todos botões — isso é um controle) e um estado vazio de moldura
tracejada dentro de um painel, que é o padrão reconhecido de "aqui ainda não há
nada". O detector passou a excluir os dois.

**E o olho encontrou o que a medida não sabia perguntar:** ao focar o `h1` do
módulo por programa, o navegador desenhava uma moldura de foco em volta do
título inteiro — um retângulo preto atravessando o painel. O título não é
alcançável por Tab; ele só recebe foco por programa, para o leitor de tela
anunciar a tela nova. A moldura saiu dali e continua onde importa, nos controles.

### O controle

Devolvi o título duplicado de propósito. O roteiro reprovou nas seis telas,
nomeando os dois títulos de cada uma. Removido, volta a passar. Uma medida que
nunca acusa não prova nada.

## Portões executados

| Portão | Resultado |
|---|---|
| `ux02_foundation.cjs` | 12 medições, 0 falhas — e reprova com o título duplicado de volta |
| `responsive_audit.cjs` | 20 de 20 medições, 0 achados, agora com categorias no acervo |
| `npm test` | 183 passando, 0 falhas — 3 novos em `design_tokens.test.ts` |
| `npm run build` | limpo |

## Achado entregue à UX-03

A tela de Categorias mostra **0 itens** para "Materiais elétricos e de
instalação", e o banco tem 2. A contagem vem de `products` do `usePos()`, que é
o catálogo **vendável** — só o que está publicado num cardápio. É o mesmo defeito
que o Estoque já teve e corrigiu: publicação decide onde o item pode ser vendido,
não se ele existe.

Não corrigi aqui porque `CategoryManager` é alvo da UX-03, que tem o aceite por
jornada para provar a correção. Fica registrado com o número que o expõe: 0 na
tela, 2 no banco.
