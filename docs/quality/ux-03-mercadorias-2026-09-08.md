# UX-03 — categorizar deixou de ser privilégio do banco

Data: 08/09/2026 · base: [UX-02](ux-02-fundacao-visual-2026-09-08.md) ·
trilha: [sprints da experiência](../product/ui-ux-implementation-sprints.md).

A UX-03 tem aceite por jornada: *cadastrar sem foto → categorizar → definir onde
vender → conferir publicação*, e depois *editar preço → salvar → retornar ao
filtro*. Ao tentar percorrê-la, a segunda etapa não existia.

## Categorizar não tinha onde acontecer

`Product.category_id` existe no modelo desde sempre. `CategoryManager` cria
categorias. O cliente de API aceita `category_id` em cadastro e em edição. E o
formulário de produto **não tinha campo de categoria** — de modo que a tela de
Categorias criava categorias que nenhum produto podia usar, e a única forma de
categorizar era escrever no banco.

O formulário ganhou o campo, num bloco próprio: categorizar é organizar o
acervo, publicar é decidir onde se vende, e são duas perguntas diferentes. Quem
tem `catalog.update` pode criar a categoria ali mesmo — "no fluxo pertinente,
respeitando autorização", como o enunciado pede — e a nova já fica escolhida. A
referência de integração vem de `referenciaDoNome`, o mesmo cálculo que a tela
de Categorias usa; não há um segundo jeito de gerar slug.

## A contagem que mentia, e o que ela destrancava

A UX-02 deixou registrado: Categorias mostrava **0 itens** para uma categoria com
2 produtos no banco. A contagem vinha de `products` do `usePos()` — o catálogo
**vendável**, só o que está publicado num cardápio.

O efeito não era só informar errado. A tela desabilita "Arquivar" quando a
contagem é maior que zero, com o aviso "Mova os produtos antes de arquivar".
Com a contagem em zero, **o botão ficava habilitado numa categoria que tinha dois
produtos dentro**: a informação errada destrancava a ação destrutiva.

A correção mudou de lado. `list_categories_with_usage` responde a contagem no
servidor, numa consulta agrupada, e `GET /catalog/categories` passa a devolver
`product_count`. O navegador não junta mais duas listas para descobrir um número
que uma consulta responde — é a mesma regra que o resto do backoffice já segue.

Quatro testes fixam o comportamento: produto que ninguém publicou conta; categoria
vazia conta zero e continua aparecendo, para poder ser arquivada; produto
arquivado não conta, porque quem saiu do acervo não deve impedir o arquivamento;
e a contagem não atravessa a fronteira do tenant.

## A jornada, percorrida

`frontend/e2e/presentation/ux03_mercadorias.cjs` percorre o aceite e mede o que
afirma. Evidência em [`evidence/ux-03/`](evidence/ux-03/).

| Etapa | O que a medida devolve |
|---|---|
| Cadastrar sem foto, categorizando ali mesmo | a categoria criada no formulário fica escolhida |
| Salvar sem escolher cardápio | *"Produto cadastrado no acervo. Publique-o em um sortimento para vender no PDV."* |
| Conferir em Categorias | a categoria nova conta **1** produto |
| Editar preço, salvar, voltar | o filtro `CAM-737469` continua no campo, e o preço novo aparece na lista |

**Cadastrar não é publicar**, e o roteiro reprova se a tela disser que é. O
controle: troquei o aviso por "Produto publicado com sucesso." e ele acusou duas
vezes — que não diz "acervo", e que anuncia publicação sem que se tenha
publicado. Restaurado, volta a passar.

## Portões executados

| Portão | Resultado |
|---|---|
| `ux03_mercadorias.cjs` | 3 etapas medidas, 4 telas, 0 falhas — e reprova com a mentira de publicação |
| `ux02_foundation.cjs` | 12 medições, 0 falhas (sem regressão da sprint anterior) |
| `npm test` · `npm run build` | 183 passando · limpo |
| `pytest` do backend | suíte completa com os dois servidores no ar |

## O que ficou de fora, e por quê

O enunciado também pede "edição longa em página/seções com salvar acessível" e
"substituir linguagem técnica". O formulário continua em diálogo único: mexer na
sua estrutura toca o fluxo de mídia, de preço e de publicação ao mesmo tempo, e
isso é reescrita de lógica — o que a trilha reservou para depois da fundação.
Fica nomeado aqui como pendência da UX-03, não como entrega silenciosa: o que
esta sprint entregou foi a jornada que não existia e a contagem que mentia.
