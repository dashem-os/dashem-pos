# ADR-033 — Estado de risco da mercadoria

**Status:** proposto — pendente de aceite do dono do SaaS
**Data:** 2026-09-07
**Origem:** "15 un com mínimo 14 aparecer como Regular é enganoso", 07/09/2026
**Relacionado:** [ADR-032](adr-032-available-to-promise.md), [ADR-031](adr-031-capability-readiness.md), [plano corretivo](../product/inventory-operational-correction-plan.md)

## Contexto

A classificação atual tem dois estados úteis e uma comparação só:

```
quantity <= minimum_stock  →  "Abaixo do mínimo"
caso contrário             →  "Regular"
```

Com 15 unidades e mínimo 14, ela diz **Regular**. Há uma unidade de folga. O
rótulo não está errado por engano de cálculo: está errado por ser binário
quando a realidade é gradual, e por olhar o número errado — saldo em vez de
disponível.

## Decisão

### Seis estados, calculados no servidor

| Estado | Condição | Olha |
|---|---|---|
| `RUPTURA` | `atp <= 0` | ATP |
| `CRITICO` | `atp <= safety_stock` | ATP |
| `REPOR` | `inventory_position <= rop` | posição |
| `ATENCAO` | `inventory_position <= rop * (1 + faixa)` ou cobertura abaixo do alvo | posição/cobertura |
| `SAUDAVEL` | folga confortável acima do ROP | posição |
| `REPOSICAO_A_CAMINHO` | está baixo **e** há `on_order` confirmado que cobre | posição |

O estado é derivado, nunca declarado — mesma disciplina do ADR-031: o servidor
calcula, a tela mostra, ninguém grava "saudável" numa coluna.

### Enquanto não houver ROP, o mínimo manual ganha faixa

Sem histórico não há previsão, e o mínimo cadastrado continua sendo o piso. Mas
deixa de ser um degrau:

```
margem      = disponivel - minimo
margem_pct  = margem / minimo
```

| Condição | Estado |
|---|---|
| `disponivel <= 0` | `RUPTURA` |
| `disponivel <= minimo` | `CRITICO` |
| `margem_pct <= 0,25` | `ATENCAO` — "próximo do mínimo" |
| acima disso | `SAUDAVEL` |

No caso relatado: 15 disponíveis, mínimo 14, margem 1 = 7,1% → **Atenção**, com
a margem dita em unidade ("apenas 1 un de folga"), não em porcentagem.

Quando o ROP existir para aquele SKU, ele domina, e o mínimo manual passa a ser
**piso operacional**: nunca sugerir menos do que o comerciante pediu.

### O painel obedece ao pior risco, não à média

Hoje o cabeçalho conta "1 abaixo do mínimo" ao lado de dois números tranquilos.
Passa a resumir por severidade, e **nunca** anuncia normalidade havendo risco:

```
3 mercadorias monitoradas
1 saudável · 1 atenção · 1 repor · 0 rupturas
```

Com uma ruptura entre cem mercadorias saudáveis, o cabeçalho diz *"1 item exige
ação"*, e não "tudo regular".

### Uma linha por mercadoria, detalhe sob demanda

A lista mostra **um estado e um número**. O cálculo — venda média, cobertura,
lead time, estoque de segurança, ROP — vive no detalhe da mercadoria, aberto por
quem quiser. A tela não explica a conta enquanto a pessoa só quer saber se
precisa comprar.

## Consequências

* `is_low_stock` e `is_out_of_stock` do `StockHolding` são substituídos por
  `risk_state` mais os números que o sustentam; as telas param de recalcular
  regra própria;
* "Regular" deixa de existir como palavra: o estado saudável se chama
  **Saudável**, e ele passa a exigir folga, não apenas empate;
* enquanto faltar dado para ROP, o sistema **pede o dado que falta** — lead time
  do fornecedor — em vez de inventar recomendação.

## Alternativa recusada

**Manter dois estados e só ajustar a cor.** Trocaria o rótulo sem trocar a
informação: continuaria comparando o número errado (saldo, não disponível) e
continuaria dizendo que empatar com o mínimo é estar bem.
