# Homologação — o acervo grande, no balcão e na Gestão

Data: 09/09/2026 · trilha: [sprints da experiência](../product/ui-ux-implementation-sprints.md) ·
evidência: [`evidence/hom-05-catalogo-volumoso/`](evidence/hom-05-catalogo-volumoso/) ·
roteiro: `frontend/e2e/presentation/hom05_catalogo_volumoso.cjs`.

A [UX-08](ux-08-homologacao-2026-09-08.md) deixou a lacuna escrita: *"catálogo
volumoso não exercitado: seis produtos no acervo. Busca e grade não foram
medidas sob carga"*. Seis produtos cabem em qualquer tela.

O acervo desta travessia tem **1.203 produtos vendáveis** — `--volume 1200` na
semeadura das duas estações. Os nomes se espalham pelo alfabeto de propósito, e
um produto fica no fim dele: **"Zimbro Desidratado 5kg"**. Ele é o pente-fino.
Qualquer corte por ordem de nome o deixa de fora, e é por ele que as duas telas
são cobradas.

## O que a travessia achou

Duas coisas, e só uma era a que eu esperava.

| Achado | Onde |
|---|---|
| A página da grade custava **4,5 segundos** | balcão, servidor |
| O seletor de produtos do sortimento parava na **letra D**, calado | Gestão |

## O primeiro: 4,5 segundos para virar a página da grade

A medida não veio da tela — veio do servidor, e é reprodutível:

| Situação | Página 1 da grade |
|---|---|
| Antes | **4.996ms** (e a última janela, 4.569ms) |
| Depois | **168ms** (última janela, 213ms) |

O caminho até a causa, porque o meio dele importa:

1. a primeira medida, logo depois de semear, deu 4,5s — e minutos depois, 0,12s.
   Isso **parecia** cache frio, e teria fechado o assunto errado;
2. com o acervo repetido em vários tenants (40 mil produtos na tabela), os 4,5s
   voltaram e **não saíram mais**. Não era cache;
3. `resolve_effective_product_ids` custa 13–250ms. A montagem do item, as
   reservas e as imagens custam menos de 10ms. **A consulta paginada custava
   4.563ms sozinha**;
4. removendo uma junção de cada vez: sem a junção de `inventory_balances`, os
   mesmos 4.563ms viram **36ms**. Sem as de preço, nada muda.

O plano diz o resto:

```
Nested Loop Left Join  (actual time=0.215..4448.239 rows=1203)
      Join Filter: ((inventory_balances_1.tenant_id = products.tenant_id)
                AND (inventory_balances_1.product_id = products.id))
      Rows Removed by Join Filter: 723003
      Buffers: shared hit=2201635
```

**Não é índice faltando.** `ix_inventory_balances_product_id` existe. É a
política de RLS da tabela, que carrega um `EXISTS` sobre `stores`. Um predicado
assim não é *leakproof*, então o PostgreSQL o aplica **antes** das condições de
junção — a junção perde o índice, vira laço aninhado com filtro, e descarta
723.003 linhas para entregar 50.

### A correção

O saldo saiu da consulta paginada. Ele é buscado depois do `LIMIT`, para as
linhas da página — **o mesmo caminho que as reservas e as imagens já usavam
naquela função**, com o comentário de origem explicando por quê. Nem o saldo nem
o preço filtram ou ordenam a grade: são enfeite da página, e enfeite se resolve
para 50 linhas, não para mil.

Isso não é ajuste de número mágico: tira do caminho da página a junção que o
plano apontou como causa.

**O que está medido, e só isso.** Nas condições desta travessia — 1.203 produtos
vendáveis num tenant, 40 mil na tabela, 50 por página — a primeira e a última
janela da grade custam o mesmo (168ms e 213ms), e antes custavam 4.996ms e
4.569ms. Duas janelas medidas não são uma curva: **não** foi medido como a
página se comporta com dez mil produtos, com mais tenants, ou com outra
distribuição de saldos. Dizer que o custo ficou "independente do tamanho do
acervo" seria conclusão maior que a medida.

> O preço ficou onde está. Tirando **só** as junções de preço, a consulta
> continua em 5.632ms — o laço do saldo segue lá. Tirando só o saldo, ela cai a
> 36ms **com** as de preço no lugar. O preço era carona, não causa, e mexer nele
> agora seria mudar o que a medida não acusou. (São batidas únicas, tomadas para
> separar as junções, não medidas de regime.)

## O segundo: o seletor parava na letra D, sem dizer

Na Gestão, vincular um produto a um sortimento passava por um `<select>` com o
catálogo mestre inteiro. `GET /catalog/products` cortava em 200 linhas — em
silêncio. Com 1.203 produtos:

> devolvidos: **200** de 1.203 · último: **"Detergente Tipo 034"** ·
> "Zimbro Desidratado 5kg": **ausente**

Na tela, 183 opções (as já vinculadas saem da lista) numa caixa que termina no D
— `00-antes-o-seletor-parava-na-letra-d.png`, a foto da execução que reprovou.
Quem procurasse qualquer produto de E a Z concluiria que **ele não existe**. Não
havia busca, não havia aviso, não havia página seguinte.

### A correção

Duas metades, porque só a segunda não bastaria:

1. **o teto deixou de ser escondido**: `limit` é parâmetro da rota, com padrão
   200 e máximo 500, e o cliente passa o número que pediu. Quem recebe
   exatamente `limit` linhas sabe que pode haver mais;
2. **o seletor virou busca**: o campo consulta o servidor a cada 300ms de
   silêncio, como o Hub de Canais já fazia — não é padrão inventado aqui. E
   quando a resposta vem no teto, a tela **diz**:

> ⚠ Há mais produtos do que cabe nesta resposta (200). Refine a busca para
> alcançar o que procura.

O aviso está em `04-seletor-avisa-que-ha-mais-do-que-cabe.png`, e o produto do
fim do alfabeto, achado pela busca, em `05-seletor-acha-o-fim-do-alfabeto.png`.
A travessia reprova se o aviso sumir com o acervo maior que o teto.

Aumentar o corte de 200 para 500 só moveria a parede: o seletor voltaria a
depender de o acervo caber na resposta. Buscar no servidor tira essa dependência
do caminho — **medido aqui com 1.203 produtos**, e não além disso.

## O que ficou medido

| Medida | Valor | Alcance |
|---|---|---|
| Grade, página 1 (servidor) | **168ms** | mediana de três, descartada a primeira batida; cruas: 332/221/142/168 |
| Grade, última janela (24ª) | **213ms** | cruas: 284/186/213/236 |
| Acervo medido | 1.203 vendáveis no tenant, 40.830 na tabela | é o cenário a que estes números se referem |
| Busca no balcão, até o cartão | **831ms** | digitar → produto na tela |
| Catálogo mestre sem busca | **131ms** | 200 linhas, o teto declarado |
| Tela do PDV, recarregar → 1º cartão | 1.315ms | **não é medida do produto** |

A última linha não é prova de desempenho, e está aqui só como sinal de que a
tela subiu. Ela inclui o servidor de desenvolvimento do Vite, que entrega
centenas de módulos soltos a cada recarregamento: duas execuções seguidas com o
**mesmo** acervo deram 1.299ms e 5.520ms. Cronometrar isso mediria a máquina do
dia. O que fala sobre o catálogo é o tempo do servidor, e é ele que a travessia
cobra.

## As provas, e o controle de cada uma

A travessia é rodada à mão. As duas correções também viraram portão da suíte,
em `test_the_counter_grid_under_a_big_catalogue.py`:

| Prova | O que guarda | Quebrando de propósito |
|---|---|---|
| `test_a_pagina_da_grade_nao_junta_a_tabela_de_saldos` | a junção não volta | devolvendo o `outerjoin`, reprova |
| `test_o_saldo_da_grade_sobrevive_a_saida_da_juncao` | quantidade, mínimo e "estoque baixo" continuam certos | esvaziando `_balances_by_product`, reprova com `0 == 2` |

A primeira é estrutural de propósito. Cronometrar no CI mediria a máquina do
dia, e uma prova que oscila com a máquina não acusa regressão nenhuma.

A própria travessia serviu de controle da correção de desempenho: **o mesmo
roteiro, com o mesmo limite de 1 segundo, reprovou com 4.996ms antes e passou
com 168ms depois.**

## Alcance desta evidência

Percorrido: 1.203 produtos vendáveis num tenant, com 40 mil na tabela de
produtos; grade paginada da primeira à última janela; busca no balcão achando e
vendendo o produto do fim do alfabeto; e o seletor da Gestão alcançando o mesmo
produto pela busca.

**Não** percorrido: dez mil produtos ou mais; acervo grande com imagens de
verdade em cada cartão (aqui os produtos não têm imagem, e a resolução de
imagens custou menos de 10ms — com mídia real esse número muda); catálogo grande
em mesa e delivery, que passam por outro sortimento; e a grade em aparelho
lento, que é outra medida e outro assunto.

Isto é travessia de navegador contra a API local, com semeadura própria. Não é
simulação de tela, e não envolve serviço externo.

## Lacunas de homologação, depois desta

| Lacuna | Estado |
|---|---|
| Dois destinos nunca percorridos | fechada em 09/09/2026 |
| Duas estações, a segunda achando a unidade já reservada | fechada em 09/09/2026 |
| Conceder e retirar autoridade, com sessão aberta | fechada em 09/09/2026 |
| **Catálogo volumoso não exercitado** | **fechada em 09/09/2026** |
| Duas inclusões simultâneas disputando a última unidade | aberta, pendência específica |
| Estado "em processamento" do TEF | aberta — próxima |
| Propagação da mudança de autoridade para sessão aberta | aberta |
| Transação real com provedor | aberta, pendência separada |
| Vínculo de maquininha | aberta, pendência separada |
