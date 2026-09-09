# UX-10 — Contas a pagar: contrato antes do modelo

Data: 08/09/2026 · trilha: [sprints da experiência](ui-ux-implementation-sprints.md) ·
depende de: [UX-09](../quality/ux-09-fornecedores-2026-09-08.md).

Este documento existe porque o enunciado da UX-10 manda inventariar antes de
criar modelos, e porque dinheiro a pagar é o tipo de domínio em que uma decisão
tomada "para desbloquear a sprint" vira número errado no bolso de alguém.

## O inventário

| Procurado | Encontrado |
|---|---|
| Conta a pagar, obrigação, favorecido | **nada** — nenhum modelo, tabela, rota ou tela |
| `payable` no código | duas ocorrências, ambas sobre *provedor de pagamento*, sem relação |
| Contas a **receber** | domínio completo: `receivables`, razão com lançamentos, acordos, alocações, estorno |

O achado que importa: **contas a receber já existe e está inteiro.** Ele tem
razão de lançamentos (`receivable_ledger_entries`), chave de idempotência por
emissão e por lançamento, `version` para concorrência otimista, `Numeric(14,4)`
para dinheiro, e estorno com data própria. Contas a pagar é o espelho dessa
forma, e não há motivo para inventar uma segunda gramática de dinheiro no mesmo
produto.

## O contrato

Curto e explícito, como o dono pediu.

### Entra na primeira entrega

1. **Lançamento manual.** Uma pessoa registra que a loja deve. Nada cria dívida
   sozinho.
2. **Favorecido**, obrigatório, em uma de duas formas: um fornecedor do cadastro
   da UX-09, ou um nome livre. As duas são de primeira classe — a conta de luz
   não tem fornecedor cadastrado e nem deveria precisar de um.
3. **Vencimento** e **valor**, obrigatórios. Valor maior que zero.
4. **Descrição** livre, para o lojista reconhecer a conta na lista.
5. **Consulta por vencimento**: o que vence hoje, o que já venceu, o que vem.
6. **Baixa manual**, total ou **parcial**, com data e forma de pagamento
   registradas — ver a decisão sobre parcial abaixo.
7. **Reversão auditada** de uma baixa: desfazer o pagamento registrado por
   engano, com motivo obrigatório, sem apagar nada. O saldo volta.
8. **Arquivar** uma conta lançada por engano — que é diferente de reverter
   pagamento e não pode ser confundido com ela.

### Fica expressamente fora da primeira entrega

| Fora | Por quê | O que a pessoa faz enquanto isso |
|---|---|---|
| **Parcelas** | Um parcelamento é *N* obrigações com *N* vencimentos; embutir isso numa conta só esconde as datas que a operação precisa ver | Lançar as parcelas como contas separadas — o que é o que elas de fato são |
| **Juros e multa** | É regra de cálculo, e regra de cálculo não se escolhe para desbloquear sprint. Mesma classe da UX-11 | Lançar o acréscimo como ajuste da conta, com motivo |
| **Desconto calculado** | Espelho do anterior | Lançar o abatimento como ajuste, com motivo |
| **Integração bancária e pagamento automático** | O enunciado proíbe assumir | Nada: baixa é registro do que a pessoa fez fora do sistema |
| **Recorrência** | Aluguel todo mês é conveniência, não obrigação do primeiro corte | Lançar a cada mês |

O ajuste citado nas duas linhas do meio **não calcula nada**: é um lançamento de
uma decisão humana, com valor digitado e motivo obrigatório, na razão da conta.
É a mesma disciplina do ajuste técnico de estoque, que já existe no produto.

### Decisão sobre pagamento parcial: entra

O dono pediu que parcial fosse definido ou ficasse fora. **Entra**, por uma
razão de operação, não de arquitetura: pagar metade de uma conta é comum, e um
sistema que só aceita baixa total obriga a pessoa a mentir — a registrar como
paga uma conta que não está. O dado passa a valer menos que o caderno que ele
substituiu.

A forma já está provada no espelho: `principal_amount`, `paid_amount`, `balance`
e a razão de lançamentos que os concilia.

## A fronteira que o dono nomeou

> Receber mercadoria não deve gerar automaticamente uma dívida.

Ela vale nos dois sentidos, e o segundo é o que costuma ser esquecido:

- Registrar um recebimento **não** cria conta a pagar. A mercadoria pode ter sido
  paga à vista, ser consignada, ser bonificação, ou ser troca de avaria.
- Dar baixa numa conta **não** movimenta estoque. Pagar a fatura de setembro não
  faz mercadoria entrar na prateleira.

O elo entre os dois é opcional e humano: ao lançar a conta, quem lança pode
apontar o fornecedor — e é só isso. Um teste vai reprovar se um recebimento
criar obrigação.

## Números, concorrência e registro

Herdados do espelho, sem invenção:

- Dinheiro em `Numeric(14, 4)`. Nunca float.
- `Idempotency-Key` no lançamento e em cada baixa: reenvio depois de erro de rede
  não vira segunda conta nem segundo pagamento.
- `version` na conta, para duas pessoas dando baixa ao mesmo tempo não gravarem
  duas — quem perde a corrida é recusado com o saldo atual à vista.
- Restrições no banco: valor positivo, saldo não negativo, pago não negativo.
- Auditoria e outbox em lançar, baixar, ajustar, reverter e arquivar.
- RLS forçada, como toda tabela de tenant.

## Permissões

| Chave | Para quê |
|---|---|
| `payable.read` | Ver contas e vencimentos |
| `payable.manage` | Lançar, editar e arquivar |
| `payable.settle` | Dar baixa |
| `payable.reverse` | Reverter uma baixa |

Reverter fica separado de dar baixa de propósito: quem registra o dia a dia não
precisa poder desfazer o de ontem.

**Uma pergunta que é do dono, não minha:** reverter baixa deve exigir duas
pessoas, como cancelar venda e aplicar desconto (ADR-028)? O ADR-030 decidiu que
o estorno em conta aberta **não** exige, por ter permissão própria. Sigo o
ADR-030 — permissão própria, sem segunda pessoa — e registro aqui para ser
contrariado se for o caso.

## Aceite

Lançamento → consulta por vencimento → baixa → conferência, incluindo falha e
concorrência, percorrido na tela com evidência. Mais:

- reenviar o lançamento depois de um erro não cria a segunda conta;
- baixa parcial deixa a conta aberta pelo saldo certo;
- reverter devolve o saldo e o histórico mostra as duas coisas;
- registrar recebimento não cria conta a pagar;
- a conta de um tenant não aparece no outro.
