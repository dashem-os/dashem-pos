# ADR-034 — A complexidade pertence ao sistema, não ao operador

**Status:** aceito — decisão do dono do SaaS em 07/09/2026
**Data:** 2026-09-07
**Origem:** revisão das telas publicadas de Produtos, Estoque, Sortimentos e Categorias
**Relacionado:** [ADR-032](adr-032-available-to-promise.md), [ADR-033](adr-033-stock-risk-state.md), [identidade visual](dashem-visual-identity.md), [plano corretivo](../product/inventory-operational-correction-plan.md)

## Contexto

As telas publicadas expõem a mecânica interna a quem só quer trabalhar. Três
sintomas do mesmo problema:

* **contadores no lugar de conclusão** — três cartões dizendo "3 controladas, 0
  sem estoque, 2 abaixo do mínimo" ocupam um terço da área e não dizem o que
  fazer;
* **vocabulário do modelo de dados** na tela do cliente — *sortimento*,
  *contextos operacionais habilitados*, *atividade de negócio*, *versão
  esperada*, *publicados por contexto*;
* **onboarding virou mobiliário** — a faixa "1 cadastre, 2 publique, 3 venda"
  aparece todo dia para quem já cadastrou.

E, com a chegada do ATP, o risco aumenta: `on_hand`, `reserved`,
`inventory_position`, `ROP`, `safety stock` e cobertura são seis conceitos
internos com vontade de virar seis colunas.

## Decisão

### A regra

**Algoritmos calculam. Serviços decidem o estado. A interface comunica situação,
impacto e próxima ação.** Se o sistema sabe que 13 unidades são risco, ele não
pede que a pessoa compare 13 com 14, entenda reserva e chegue sozinha à
conclusão — ele conclui.

### Regra da decisão única

**Cada superfície operacional tem uma ação dominante.** Informação técnica,
configuração e explicação nunca competem visualmente com ela. O sistema
interpreta a complexidade; a pessoa recebe situação, consequência e próxima
ação.

| Superfície | A ação dominante |
|---|---|
| Frente de caixa | **Receber R$ 134,00** |
| Estoque | **2 produtos precisam de reposição** |
| Comanda | **Mesa 08 · R$ 186,00** |
| Produtos | encontrar e corrigir um item |

No PDV o operador faz quatro coisas: **encontrar produto → adicionar → conferir
→ receber**. O que não serve diretamente a uma delas sai da frente de caixa ou
fica subordinado.

### Regra da ausência silenciosa

**Nenhuma ausência de configuração vira mensagem permanente na operação**, salvo
quando ela impede a ação atual. Some por esta regra: "vitrine não configurada",
"sem categoria", "acesso rápido (0)", instruções permanentes, cartões vazios e
rótulos internos.

### Três níveis que não competem na mesma jornada

| Nível | O que é | Onde vive |
|---|---|---|
| **Operação** | vender, receber, contar | ação direta na linha |
| **Gestão** | o que está acabando, quanto repor, histórico | resumo no topo e detalhe |
| **Configuração** | estoque de referência, catálogo, onde vender, publicação | detalhe → "Configurações avançadas" |

### Um número operacional por linha

A linha responde três perguntas, e só: **o que é**, **quanto posso vender
agora**, **preciso fazer algo**.

| Produto | Disponível | Situação | Ação |
|---|---|---|---|
| Coca-Cola Lata | 40 un | Saudável | ⋯ |
| Coca-Cola Sem Açúcar | 4 un | 🔴 Repor | Receber |
| Hambúrguer Bacon | 13 un | 🟠 Atenção | Receber |

`on_hand`, `reserved`, `ATP`, `inventory_position`, `ROP` e `safety stock`
**não aparecem na lista**. Havendo reserva ativa, a composição fica no detalhe:

```
Coca-Cola Sem Açúcar
Disponível agora: 4 un
⚠️ Reposição recomendada

Físico: 6 · Em vendas abertas: 2 · Mínimo atual: 10
[Receber mercadoria]  [Contar estoque]
Configurações avançadas →
```

Sinal contextual discreto na linha — "2 em vendas" — é permitido **quando houver
razão operacional**, nunca disputando hierarquia com o número principal.

### Um resumo que conclui, não que conta

```
⚠️ 2 produtos precisam de atenção
3 produtos acompanhados · nenhum sem estoque
```

e, quando não há risco:

```
✓ Estoque saudável — nenhum item requer ação agora
```

O resumo obedece ao pior risco relevante ([ADR-033](adr-033-stock-risk-state.md)).

### Vocabulário: a tela fala a língua de quem vende

| Interno | Na tela |
|---|---|
| Contextos operacionais habilitados | Onde este produto é vendido? — Balcão · Mesa/Comanda · Delivery |
| Sortimentos e cardápios | Catálogos e cardápios |
| Publicados por contexto | Onde cada item aparece |
| Atividade de negócio | Tipo de negócio |
| Versão esperada / v4 | não aparece na jornada diária |
| Mínimo desejado | **Estoque de referência** — usado enquanto não há histórico para calcular a reposição |

Com o ROP ([3.2](../product/inventory-operational-correction-plan.md)), a
configuração vira escolha de regime, não de número:

```
Reposição
○ Automática — recomendada
● Manual — mínimo de 10 un
```

O comerciante não precisa aprender o que é ROP para se beneficiar dele.

### Onboarding não é mobiliário

Orientação de primeira vez aparece enquanto ela é primeira vez: fechada por
padrão, e ausente depois que a pessoa já fez aquilo uma vez.

### Homologação

Nenhuma tela é dada por pronta olhando componente isolado ou captura de um
tamanho só: **navegação real, na resolução real, com dados reais**.

### A frente de caixa segue a mesma regra

O PDV é o lugar onde a regra pesa mais, porque ali o tempo é do cliente na
frente do balcão:

| Hoje | Decisão |
|---|---|
| Sete linhas iguais para sete Coca-Colas | Uma linha, `7×` |
| "A vitrine desta unidade ainda não foi montada. A gerência define os itens que aparecem primeiro" + dois botões *Personalizar* | Montar vitrine é Gestão. Na venda, ou a vitrine existe, ou o espaço é da busca |
| "SEM CATEGORIA" em cada cartão | Ausência de categoria não vira etiqueta |
| "Acesso Rápido (0)" | Aba vazia não se anuncia |

## Consequências

* colunas somem: `Mínimo desejado` sai da lista de Estoque e vai para o detalhe;
* a lista de Produtos perde a coluna de estoque dupla e mantém um número;
* os três cartões do topo viram uma faixa;
* renomear termos exige uma passada de vocabulário nas quatro superfícies;
* qualquer número interno novo — ATP, ROP, cobertura — nasce no detalhe, e só
  sobe para a linha se substituir outro.

## Alternativa recusada

**Mostrar tudo e deixar a pessoa filtrar.** É o desenho atual: transfere ao
operador o trabalho que o sistema já tem condição de fazer, e foi exatamente o
que produziu "muita informação poluindo a tela, nada intuitivo".
