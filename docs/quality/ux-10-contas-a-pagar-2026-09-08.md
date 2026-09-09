# UX-10 — o que a loja deve, e o que continua não acontecendo

Data: 08/09/2026 · trilha: [sprints da experiência](../product/ui-ux-implementation-sprints.md) ·
contrato: [UX-10](../product/ux-10-contas-a-pagar-contrato.md) ·
evidência: [`evidence/ux-10/`](evidence/ux-10/).

O inventário não achou nada de contas a pagar — nenhum modelo, nenhuma tabela,
nenhuma rota. Achou o espelho inteiro: `receivables`, com razão de lançamentos,
chave de idempotência, `version` e estorno. Contas a pagar segue a mesma
gramática, porque um produto não precisa de duas formas de escrever dinheiro.

Metade desta entrega é a fronteira que o dono nomeou, e ela vale nos dois
sentidos: **receber mercadoria não cria conta a pagar**, e **dar baixa não
movimenta estoque**.

## O que existe agora

| Peça | Onde |
|---|---|
| `payables` e `payable_ledger_entries`, com RLS forçada | `094_what_the_shop_owes` |
| Lançar, consultar por vencimento, baixar, ajustar, reverter, arquivar | `/api/v1/payables` |
| A tela, no card de Financeiro | `PayablesManager.tsx` |
| Quatro permissões, com reverter separada de baixar | mesma migração |

## Cinco decisões que o contrato obrigou a tomar por escrito

### "Vencida" não é situação gravada

Ela é derivada de `due_on` contra hoje. Uma coluna gravada exigiria alguém — ou
algum processo — virando linhas à meia-noite, e esse processo não existe: a
lista mentiria por um dia inteiro toda vez que uma conta vencesse. O servidor
devolve `is_overdue` e `days_to_due`, e a tela mostra "venceu há 3 dias".

### Baixa parcial entra; parcelamento, não

Pagar metade de uma conta é comum. Um sistema que só aceita baixa total obriga a
pessoa a registrar como paga uma conta que não está, e o dado passa a valer
menos que o caderno que ele substituiu.

Parcelamento fica fora porque um parcelamento é *N* obrigações com *N*
vencimentos, e embutir isso numa conta só esconderia as datas que a operação
precisa ver. Quem parcela lança as parcelas — que é o que elas são.

### Juros, multa e desconto são registrados, nunca calculados

O ajuste é valor **digitado**, com motivo obrigatório, e a tela diz isso na
própria tela: *"O sistema não calcula juros nem desconto: o valor é o que você
combinou."* Escolher uma regra de cálculo para desbloquear a sprint é
exatamente como o número fica errado no bolso de alguém — a mesma razão pela
qual a UX-11 continua parada esperando os exemplos do dono.

### O saldo vem da razão, não de uma variável

`_recalcular` relê os lançamentos vivos a cada operação. Somar e subtrair no
objeto funciona até o dia em que um caminho esquece de somar; e um saldo errado
que ninguém consegue reconstruir é pior do que um saldo ausente.

### Reverter não apaga

A reversão é outro lançamento, apontando para o primeiro. A tela mostra os dois
— a baixa riscada e marcada "Desfeito", e a reversão com o motivo. Quem confere
precisa ver que houve um engano e que ele foi desfeito, não uma conta que sempre
esteve certa.

E uma baixa só se desfaz **uma vez**: o índice `uq_payable_reversal_once`
garante no banco. Sem ele, dois cliques em "Desfazer" devolveriam o saldo duas
vezes, e a conta passaria a dever mais do que devia — em silêncio, porque cada
lançamento é válido sozinho.

## Os três pontos da revisão do dono

A entrega foi lida antes de ser considerada concluída, e os três apontamentos
eram reais. Nenhum deles aparecia nos testes que eu tinha escrito.

### 1. A concorrência não estava garantida pelo banco

`_exigir_versao` conferia `version` em Python: ler, decidir, e só então gravar.
Duas requisições leem a mesma versão, as duas passam pela conferência, e as duas
gravam — cada lançamento válido sozinho, ninguém percebe.

As rotas que mexem em dinheiro passaram a travar a linha (`FOR UPDATE`) antes de
conferir, como o `receivable_service` — o espelho que este módulo diz seguir —
já fazia em sete pontos. Eu tinha copiado a forma da tabela e deixado a garantia
para trás.

**A prova antiga não servia.** As dez baixas simultâneas passavam com e sem a
trava, porque a pilha local escalona as requisições uma depois da outra por
acidente — um teste que passa nos dois casos mede o escalonador, não a regra.
A prova nova constrói a corrida: abre a própria transação, trava a linha da
conta e segura. Sem `FOR UPDATE`, a rota decide sobre a versão antiga, espera
só para gravar, e **grava** — paga uma conta cujo estado mudou debaixo dela e
apaga a alteração de quem chegou antes. Com a trava, ela lê depois da liberação,
vê a versão nova e recusa.

### 2. A autorização não era consistente por unidade

A listagem escondia a conta de outra unidade; as rotas de baixa, ajuste e
reversão a aceitavam mesmo assim. Quem tivesse o identificador pagava a conta de
uma loja estando em outra, e o dinheiro saía do lugar errado.

Agora as duas usam a mesma regra, num só lugar (`_alcanca`): conta sem unidade é
da empresa e todo mundo alcança; conta atribuída a uma unidade só é alcançada de
dentro dela.

### 3. A idempotência não estava vinculada à conta

O nome da operação era `POST /api/v1/payables/baixas`, sem o identificador. A
mesma `Idempotency-Key` usada numa **segunda** conta batia no registro da
primeira e devolvia a resposta dela: a segunda baixa não era gravada, e a tela
mostrava sucesso.

Perda silenciosa de pagamento — o pior defeito possível neste domínio. A
operação e a chave gravada na razão passaram a carregar a conta, e o reenvio
continua sendo reconhecido onde deve ser.

## O defeito que a primeira execução encontrou

`scope_tenant_query` — o ajudante padrão de escopo — casa `store_id` com a
unidade aberta. Contas a pagar usa `store_id` **opcional**, porque a conta de
luz é da empresa e não de uma unidade. Resultado: assim que alguém entrava na
Gestão com uma unidade selecionada, **a conta mais comum de todas desaparecia
da lista**.

A regra certa é inclusiva: conta sem unidade é de todo mundo; conta atribuída a
uma unidade aparece nela. Está escrita à mão na rota, com o porquê ao lado, para
ninguém "simplificar" de volta para o ajudante.

## A travessia na tela

`frontend/e2e/presentation/ux10_contas_a_pagar.cjs` — 8 etapas, 10 telas, 0 falhas.

| Etapa | Evidência |
|---|---|
| O card existe em Financeiro, com a frase de tarefa do mapa | `1-card-em-financeiro.png` |
| Lançar duas contas, uma delas já vencida | `3-contas-lancadas.png` |
| "Venceu há 3 dias", o resumo de vencidas, e a ordem por vencimento | idem |
| Dinheiro em português: `R$ 2.500,00` | idem |
| Baixa parcial: 1.000 de 2.500, e a conta segue aberta por 1.500 | `4-` e `5-` |
| Reverter: saldo de volta, a baixa riscada e a reversão com o motivo | `6-baixa-desfeita.png` |
| Ajustar: valor digitado, motivo obrigatório, e o aviso de que nada é calculado | `7-` e `8-` |
| **Receber mercadoria e voltar: nenhuma conta nova** | `9-` e `10-` |

### Os controles

Oito guardas desfeitas de propósito, oito reprovações:

| O que foi desfeito | O que reprovou |
|---|---|
| A exigência de `version` na baixa | as três baixas simultâneas passaram, e a conta foi paga mais de uma vez |
| O escopo inclusivo (voltando a casar unidade) | a lista ficou vazia com a conta lançada |
| O vínculo da reversão (`reverses_entry_id`) | a baixa deixou de saber que foi desfeita, e pôde ser desfeita duas vezes |
| A exigência de `Idempotency-Key` | dinheiro passou a poder ser registrado sem carimbo |
| **O gatilho proibido, criado de propósito** no recebimento | a travessia acusou com o número: *"eram 4 contas em aberto e passaram a ser 5"* |
| O `FOR UPDATE` das rotas de dinheiro | a baixa passou sobre versão antiga e pagou uma conta que estava sendo alterada |
| A regra de unidade (`_alcanca`) | a conta da matriz foi paga de dentro da filial |
| A idempotência vinculada à conta | a baixa na segunda conta devolveu a resposta da primeira, e o pagamento sumiu |

O último é o que importa: a fronteira do dono é provada **pelo caminho de quem
usa**, não só por uma prova de API.

Três reprovações da primeira rodada foram erro de medida, não do produto: o
portão de carga olhava só para `main`, e o painel de pagamento é irmão dele;
esperar o título da lista de estoque lia a tela antes das linhas; e `.first()`
clicava na conta de uma execução anterior, cujo saldo estava certo para
*aquela* conta.

## Portões executados

| Portão | Resultado |
|---|---|
| `pytest tests/test_what_the_shop_owes.py` | 20 provas, incluindo as seis dos três pontos da revisão |
| `pytest` completo | **571 passando**, 15 pulados, 1 xfailed, 0 falhas |
| `npm test` | 198 passando |
| `npm run build` | limpo |
| `alembic check` | sem operações novas |
| `ux10_contas_a_pagar.cjs` | 8 etapas, 10 telas, 0 falhas — e reprova com o gatilho proibido |

Dois guardas do próprio repositório pegaram erros meus antes de mim.

`test_frontend_names_every_server_date_field` reprovou porque `due_on` e
`occurred_on` não estavam na convenção de datas do frontend. Não é burocracia:
`new Date("2026-09-20")` é meia-noite **UTC**, e num fuso negativo — o nosso —
ela é exibida como o dia 19. Uma conta apareceria vencendo um dia antes. Os dois
campos entraram na lista, e a proteção foi verificada quebrando-a de propósito.

E `test_no_new_client_function_is_orphaned` reprovou porque
`adjustPayable` e `updatePayable` existiam no cliente e nenhuma tela as chamava. O cliente tinha
andado na frente da interface — e o ajuste, que o contrato define como a única
forma de registrar juros e desconto, não estava ao alcance do lojista. As duas
ações foram para a tela.

## O que fica de fora, por decisão

Parcelas, cálculo de juros e multa, desconto calculado, integração bancária,
pagamento automático e recorrência. Cada um com a alternativa que a pessoa tem
enquanto isso, na tabela do [contrato](../product/ux-10-contas-a-pagar-contrato.md).

## A pergunta que era do dono

Reverter baixa deve exigir duas pessoas, como cancelar venda e aplicar desconto
(ADR-028)? **Respondida em 08/09/2026: não.** Permissão própria, motivo
obrigatório e auditoria, sem segunda pessoa, e MANAGER continua sem a permissão
por padrão — que é exatamente o que está implementado e o que a migração 094
concede a OWNER, TENANT_OWNER e ADMIN.
