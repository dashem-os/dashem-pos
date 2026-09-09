# UX-09 — de quem veio a mercadoria

Data: 08/09/2026 · trilha: [sprints da experiência](../product/ui-ux-implementation-sprints.md) ·
evidência: [`evidence/ux-09/`](evidence/ux-09/).

O card de Fornecedores era um **destino ausente** no mapa das sete áreas: o
inventário não achou nada — nem tabela, nem rota, nem tela. A pergunta "de quem
veio esta mercadoria?" não tinha onde ser respondida.

Esta sprint cria o domínio inteiro e liga o recebimento a ele. **Não há pedido
de compra**, que o enunciado proíbe entregar, e nenhuma rota, coluna ou botão
finge que existe — há um teste que reprova se aparecer.

## O que existe agora

| Peça | Onde |
|---|---|
| `suppliers` e `supplier_contacts`, com RLS forçada | `092_who_supplies_the_goods` |
| `inventory_movements.supplier_id` | mesma migração |
| Um contato principal por fornecedor, garantido pelo banco | `093_one_primary_contact_only` |
| Cadastro, busca, contatos, arquivamento | `/api/v1/suppliers` |
| A tela, no card de Relacionamento | `SupplierManager.tsx` |
| **"De quem veio"** no recebimento | `InventoryManager.tsx` |

## As cinco correções da revisão

A primeira entrega foi lida pelo dono do produto antes de ser considerada
concluída, e cinco defeitos voltaram. Todos eram reais. Cada correção abaixo tem
uma prova que reprova se o defeito voltar, e cada prova foi verificada
**desfazendo a correção de propósito**.

### 1. O CNPJ alfanumérico perdia as letras

A normalização guardava só dígitos. O CNPJ alfanumérico entrou em operação em
julho de 2026: as doze primeiras posições podem ser letras, e só os dois dígitos
verificadores são numéricos. Um documento válido chegava, perdia metade dos
caracteres e era **gravado como outro documento** — sem erro e sem aviso, porque
o que sobrava ainda parecia um número.

Agora se remove apenas a máscara e o resto vai em maiúsculas, o que mantém CPF e
CNPJ numérico pelo mesmo caminho e faz `12abc…` e `12ABC…` serem o mesmo
documento na comparação.

> Controle: com `isdigit()` de volta, a prova reprova mostrando a corrupção —
> `12ABC34501DE35` virava `123450135`.

### 2. "Um principal" não resistia a dois acessos

A rota desmarcava os anteriores antes de inserir o novo, e isso basta em fila
única. Em duas requisições ao mesmo tempo as duas leem, as duas desmarcam e as
duas inserem: o fornecedor termina com dois contatos principais, que é o mesmo
que ficar sem nenhum — a tela deixa de responder a quem ligar.

A garantia passou para o banco: índice único parcial por fornecedor onde
`is_primary`. Quem perde a corrida recebe 409 com a frase do caso, não um 500. E
a rota passou a gravar a desmarcação **antes** da inserção, porque deixar a
ordem por conta do unit of work do SQLAlchemy faria a própria operação bater no
índice.

> Controle: sem o índice, quatro de cinco rodadas gravaram dois principais. Com
> ele, cinco de cinco rodadas verdes.

### 3. Apagar um campo não apagava o cadastro

A tela mandava `undefined`, que some do JSON. O servidor lia "não mexeu neste
campo" e mantinha o valor antigo: o lojista apagava o CNPJ errado, salvava, e
ele voltava. O mesmo valia para razão social e observações.

Agora a tela manda `null` — a intenção de apagar viaja — e o servidor trata
string vazia e espaço em branco como a mesma intenção, porque `""` gravado seria
uma razão social que existe e não diz nada.

### 4. A edição não checava documento duplicado

Cadastrar recusava com o nome de quem já tem o documento; editar não checava
nada. Trocar o documento de um fornecedor para o de outro passava direto até o
banco recusar, e a tela recebia um erro que não sabia explicar.

A edição ganhou a mesma checagem, excluindo o próprio registro — regravar o
próprio documento não é conflito consigo mesmo. E os dois caminhos passaram a
capturar o `IntegrityError` da corrida: a restrição `uq_tenant_supplier_document`
já existia, e o que faltava era transformar sua recusa em 409 com explicação.

> Controle: sem a checagem, a recusa ainda acontece — pelo banco — mas perde o
> nome de quem tem o documento. A prova acusa exatamente essa perda.

### 5. O vínculo com o recebimento não tinha por onde ser informado

Este era o mais grave, porque era a promessa da sprint. A coluna existia, a API
aceitava `supplier_id`, e **nenhuma tela o preenchia**: toda entrada nascia com o
campo nulo e o histórico continuava sem responder de quem veio.

O formulário de receber mercadoria ganhou **De quem veio**, opcional, só na
entrada — perda não vem de fornecedor. E o histórico devolve o vínculo, porque
guardar sem mostrar de volta é o mesmo que não guardar.

O seletor oferece os ativos; a lista carrega também os arquivados, para que o
histórico saiba nomear quem entregou antes de ser arquivado.

## A travessia na tela

`frontend/e2e/presentation/ux09_fornecedores.cjs` — 11 etapas, 12 telas, 0 falhas.

| Etapa | Evidência |
|---|---|
| O card existe em Relacionamento, com a frase de tarefa do mapa | `1-card-em-relacionamento.png` |
| Cadastrar, e a lista dizer "Nenhum ainda" nos recebimentos | `3-fornecedor-cadastrado.png` |
| Achar pelo documento **com máscara** | — |
| Guardar contato com função e marcá-lo principal | `4-contatos.png` |
| Nada promete pedido de compra | `5-lista-final.png` |
| CNPJ alfanumérico volta inteiro e mascarado | `6-cnpj-alfanumerico.png` |
| Apagar o documento e ele ficar apagado | `7-documento-apagado.png` |
| Editar para o documento de outro e ouvir **de quem é** | `8-documento-de-outro-recusado.png` |
| Receber informando de quem veio | `10-recebimento-com-fornecedor.png` |
| O histórico dizer "de Distribuidora Aurora …" | `11-historico-de-quem-veio.png` |
| O fornecedor deixar de dizer "Nenhum ainda" | `12-fornecedor-com-recebimento.png` |

### Os controles da travessia

- Fixado `supplier_id: null` no contexto, a travessia reprova nas **duas** pontas
  do vínculo: o histórico não nomeia e o fornecedor volta a "Nenhum ainda".
- Três reprovações da primeira rodada foram erro de medida, não do produto: os
  3 s fixos fotografavam a tela antes de carregar; a aba de Movimentações tem
  `role="tab"` e eu procurava `button` — com um `.count()` que engolia isso em
  silêncio; e os itens do menu de linha são `menuitem`, não `button`. A espera
  virou portão de conteúdo, e o `.count()` silencioso saiu.
- A travessia passou a ser re-executável: o documento carrega a marca da rodada.
  Antes, a segunda execução esbarrava no cadastro da primeira e a recusa por
  documento repetido — comportamento correto — aparecia como falha.

## Portões executados

| Portão | Resultado |
|---|---|
| `pytest tests/test_who_supplies_the_goods.py` | 13 provas, 5 rodadas seguidas verdes |
| `pytest` completo | **571 passando**, 15 pulados, 1 xfailed, 0 falhas |
| `npm test` | 198 passando |
| `npm run build` | limpo |
| `alembic check` | sem operações novas |
| `ux09_fornecedores.cjs` | 11 etapas, 12 telas, 0 falhas — e reprova sem o vínculo |

Dois testes de arquitetura reprovaram enquanto o domínio era novo e sem dono
declarado: `supplier` entrou no mapa de módulos como **catalog** — quem fornece
fica com a mercadoria, e finanças pode ler catálogo quando precisar do
favorecido, o que já é a direção de que a UX-10 vai precisar.

Um teste do frontend também reprovou, e a regra dele estava certa: a chamada de
movimentação passou a ocupar mais de uma linha porque leva o fornecedor junto, e
a expressão que guardava o carimbo de idempotência era de uma linha só. A regra
foi ajustada à chamada nova e continua acusando quando o carimbo sai.

## O que fica de fora

- **Pedido de compra**, por decisão do enunciado. Receber mercadoria não gera
  dívida, e essa fronteira é o ponto de partida do contrato da UX-10.
- **Catálogo por fornecedor** (o que cada um fornece, a que preço).
- **Concorrência de duas estações na tela**: a corrida do contato principal foi
  provada por requisições simultâneas contra a API, não por duas pessoas em duas
  máquinas. Fica com as demais lacunas de homologação da UX-08.
