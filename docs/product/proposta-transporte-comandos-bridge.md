# Proposta — transporte de comandos ao bridge TEF (frente A)

Status: **contrato corrigido; implementação incremental autorizada, condicionada
a estas correções** · revisão 3.1 em 10/09/2026 (revisões 1, 2 e 3 em 10/09/2026,
todas corrigidas por revisão dirigida do dono).
Base: `518e79a` em `main`. Cabeça de migração conferida nesta revisão no código
**e** no banco publicado: `096_the_grant_keeps_its_history`. CI remoto do
candidato: [run 34420801772](https://github.com/dashem-os/dashem-pos/actions/runs/34420801772),
quatro jobs verdes. Verde no repositório não é homologação.

Esta revisão foi autorizada como revisão documental; **não aprova o desenho
anterior**. Nada foi implementado. Não escolhe provedor, adquirente, preço,
capability produtiva, canal, regra da UX-11 nem canal da UX-12.

## 0.1 O que mudou da revisão 3 para a 3.1

Correções dirigidas no contrato, sem reformulação geral.

| # | Revisão 3 dizia | Correção |
|---|---|---|
| 1 | Consulta "não executada" libera a ocupação | **Não basta.** Processo antigo suspenso pode retomar e executar depois. Liberar exige **neutralizar o executor anterior** (N1/N2/N3) ou garantia equivalente do provedor (§3.2, I1b) |
| 2 | Resposta da instalação substituta é autoritativa "porque a credencial é nova" | Credencial autentica **quem respondeu**. Resolver exige origem confiável, correlação e ambiente recuperado. E extrato sem lançamento **não** prova ausência (§3.7, I10b) |
| 3 | Autenticar com a credencial nova prova que foi persistida | **Não prova** — pode estar só em memória. Persistir antes de confirmar, confirmação idempotente, rota de estado para a resposta perdida (§3.8, I11b) |
| — | Ocupação com terminal como chave primária | `released_at` não removia o bloqueio. Índice parcial sobre `released_at IS NULL`, e liberação que **confere a operação proprietária** (§3.1, I14) |
| — | Correlação ambígua só entre classes diferentes | Múltiplos candidatos **da mesma classe** também são ambíguos (§3.6) |
| — | "Cancelada" tratada como não execução | Não é universal; mapeamento **declarado por provedor**. Cobrança e estorno resolvem separado (§3.5) |
| — | "As permissões novas existem" | **Estão propostas.** Nada implementado (§8) |
| — | D1 tornaria exatamente-uma-vez alcançável | Vale no escopo e janela da chave; durabilidade local vale para aquela instalação e condições testadas (§4) |

## 0. O que mudou da revisão 2 para a 3

| # | Revisão 2 dizia | Correção |
|---|---|---|
| 1 | Índice parcial sobre `PENDING/LEASED/ACKED` | **Contradição medida.** Excluía `UNRESOLVED`, liberando nova cobrança com desfecho incerto. Ocupação passa a ser da **operação financeira**, não do comando (§3.1) |
| 2 | `SKIP LOCKED` + lease como proteção contra duplo consumidor | **Insuficiente.** Não impede processo antigo com armazenamento local próprio de acionar o SDK após expiração (§3.2) |
| 3 | "Gravar antes de tocar o pinpad" | Incompleto: faltava a **intenção** persistida e o caso de a chamada nunca ter ocorrido. E prometia exatamente-uma-vez com armazenamento local (§3.3) |
| 4 | Corridas descritas em prosa | Vira **tabela de transições**, com ACK tardio sem regressão e `QUERY` que não encerra a operação consultada (§3.5) |
| 5 | Revogação aceitando resultado de comando `ACKED` | **Perigoso.** Credencial comprometida passaria a afirmar fatos financeiros. E limitar a `ACKED` ignora execução com ACK perdido (§3.7) |
| 6 | "Guarda só hash, entrega depois uma vez" | **Impossível como escrito.** Protocolo de rotação completo em §3.8 |
| 7 | Ações da fila em `provider.configure` | `CONTROL` é classe de transporte, não autorização. Permissões por ação em §3.9 |
| 8 | "Gestão → Operação → Provedores" | **Errado.** A migração `090` moveu a tela para **FINANCEIRO** (§3.10) |
| 8 | "Latência da venda local inalterada" | Não é mensurável. Vira limite de degradação com baseline e critério (§3.11) |

## 1. Invariantes

Tudo abaixo existe para sustentar estas treze afirmações. Cada teste de §5 se
liga a pelo menos uma.

| # | Invariante |
|---|---|
| **I1** | Um terminal nunca tem duas operações financeiras de execução sem resolução provada |
| **I1b** | Enquanto um executor anterior puder acionar o SDK, o terminal não libera execução nova — nem com consulta dizendo "não executada" (§3.2) |
| **I2** | Tempo não prova ausência: expiração, tentativas esgotadas e `UNKNOWN` nunca liberam ocupação nem reserva |
| **I3** | Reenvio reusa o mesmo `command_id`; reenviar nunca cria comando novo |
| **I4** | Nenhuma chamada ao SDK sem registro durável de **intenção** gravado antes |
| **I5** | Retomada após interrupção consulta; nunca reexecuta por suposição |
| **I6** | Estado concluído não regride: ACK tardio ou resposta repetida não reabrem operação fechada |
| **I7** | Concluir um comando `QUERY` não resolve a operação financeira consultada |
| **I8** | Resultado sem correlação comprovável é evidência não atribuída, não desfecho |
| **I9** | Só a instalação ativa recebe comandos; assumir o terminal não libera ocupação pendente |
| **I10** | Credencial revogada por suspeita de comprometimento nunca afirma fato financeiro |
| **I10b** | Credencial autentica **quem respondeu**, nunca torna a resposta verdade financeira (§3.7) |
| **I11** | Credencial existe em claro apenas na resposta que a criou; nunca em log, auditoria, payload de domínio ou documento |
| **I11b** | O bridge persiste a credencial nova **antes** de confirmar; confirmar é idempotente e nunca exige receber o segredo de novo (§3.8) |
| **I14** | Liberar ocupação confere a **operação proprietária**: resultado tardio de outra operação não libera a ocupação vigente (§3.1) |
| **I12** | Ação financeira tem permissão própria; cancelar e reconciliar não herdam de configurar |
| **I13** | Limitação do provedor vira pendência explícita; nunca sucesso presumido |

## 2. O que a revisão do código confirmou

`BridgeQueuedAdapter.start` ([adapter.py:51](../../backend/app/providers/adapter.py#L51))
devolve `PROCESSING` e grava `sanitized_payload = {"bridge_command": "START"}`.
Ninguém lê. As quatro rotas em [providers.py](../../backend/app/api/v1/endpoints/providers.py)
param em parear, listar, heartbeat e receber resultado.

Achados que seguem valendo das revisões anteriores: não há guarda de ocupação por
`bridge_terminal_id` (A2); `ONLINE` só é rebaixado por `list_terminals`, e só se
alguém abrir a tela (A3); o segredo é derivado da `Idempotency-Key` e não
rotaciona (A4); `heartbeat_terminal` e `report_bridge_result` chamam
`set_tenant_db_context` com o `tenant_id` do corpo antes de autenticar (A5);
nenhuma tela mostra a fila (A6).

Corrigido na revisão 2 e mantido: a `Session` **não** retém conexão pela
requisição — faz checkout no primeiro comando e devolve no commit (medido); e
já existem três rotas `async def`, então esta não seria a primeira. O risco real
é transação aberta durante a espera, com dez conexões no pool e `psycopg2`
síncrono.

Ainda vale: **engenharia interna e testes controlados não dependem da definição
dos planos produtivos.** A frente A se exercita com tenant de teste, sem semear
`tef` em plano nenhum.

## 3. A proposta

### 3.1 Ocupação: o estado da operação, não o do comando

A revisão 2 confundiu dois eixos. Separá-los é o que resolve a contradição.

| Eixo | Valores | Do que fala |
|---|---|---|
| **Entrega do comando** | `PENDING` · `LEASED` · `ACKED` · `CLOSED` | onde o comando está no fio |
| **Resolução financeira** | `NAO_INICIADA` · `INCERTA` · `PROVADA_EXECUTADA` · `PROVADA_NAO_EXECUTADA` | o que aconteceu com o dinheiro |

Ocupação é do **eixo financeiro**. Enquanto uma operação de execução não tiver
resolução provada, o terminal está ocupado — inclusive, e principalmente,
quando o comando já morreu no fio.

**Garantia transacional: linha de ocupação, não status enumerado.**

```sql
CREATE TABLE tef_terminal_occupancy (
    id                      uuid PRIMARY KEY,
    bridge_terminal_id      uuid NOT NULL REFERENCES tef_bridge_terminals(id),
    provider_transaction_id uuid NOT NULL,
    tenant_id uuid NOT NULL, store_id uuid NOT NULL,
    acquired_at timestamptz NOT NULL, released_at timestamptz,
    released_reason text, released_by uuid
);

CREATE UNIQUE INDEX uq_terminal_occupied
    ON tef_terminal_occupancy (bridge_terminal_id)
 WHERE released_at IS NULL;
```

**Correção:** a revisão anterior punha o terminal como chave primária, e assim
preencher `released_at` **não** removia o bloqueio — a linha liberada continuava
ocupando a chave, e o terminal ficava travado para sempre. O cadeado é o índice
parcial sobre `released_at IS NULL`: uma ocupação viva por terminal, com o
histórico preservado.

**A liberação confere a operação proprietária** (I14). Nunca "libere o terminal",
sempre "libere esta operação neste terminal":

```sql
UPDATE tef_terminal_occupancy
   SET released_at = now(), released_reason = :motivo, released_by = :autor
 WHERE bridge_terminal_id = :terminal
   AND provider_transaction_id = :operacao
   AND released_at IS NULL;
```

Zero linhas afetadas significa que a ocupação vigente é de **outra** operação — e
aí não se libera nada. Sem essa conferência, um resultado tardio da cobrança
antiga soltaria o terminal que já está ocupado pela cobrança seguinte.

**Medi a propriedade de concorrência** no Postgres do projeto, em banco de
rascunho descartado depois. Com uma cobrança `UNRESOLVED` no terminal, o índice
da revisão 2 **aceitou** nova cobrança; o critério da revisão 3 **recusou**. Com
8 processos disputando ao mesmo tempo: 1 aceito, 7 recusados, uma linha ativa.
*Limite:* isso demonstra semântica de restrição única sob concorrência no
PostgreSQL. Não demonstra nada sobre o bridge, o SDK ou cobrança física. A linha
de ocupação usa a mesma primitiva — uma chave única — e herda a propriedade; a
forma exata da tabela não foi medida.

**O que libera a ocupação** (I1, I1b, I2) — e cada item tem uma condição que a
revisão anterior não tinha:

1. Resultado que **prova** o desfecho, com evidência do provedor. A tradução de
   status do provedor para resolução é **por provedor e declarada**: `CANCELED`
   **não** significa universalmente "nunca executou" — pode ser desfazimento
   depois de autorizada, que é dinheiro que saiu e voltou (§3.5);
2. Resposta de consulta que prova que a operação não executou **e** que nenhum
   executor anterior pode mais executá-la (§3.2). Isoladamente, "não executou até
   agora" não libera nada;
3. Reconciliação humana registrada, com autoridade nomeada e evidência anexada,
   sujeita aos critérios de suficiência de §3.7.

Expiração de lease, tentativas esgotadas e `UNKNOWN` **não estão nesta lista**, e
nunca estarão. A reserva da parcela segue a ocupação: não é liberada por tempo.

### 3.2 Dois processos, duas instalações — e o limite honesto

`FOR UPDATE SKIP LOCKED` protege a reivindicação simultânea. Não protege o caso
real: um processo antigo que recebeu o comando, ficou mudo, teve o lease vencido,
e volta a si com armazenamento local próprio — podendo acionar o SDK enquanto
outro processo já assumiu o terminal.

**Digo sem rodeio: nenhum lease ou fencing no servidor impede isso.** O recurso
disputado é o pinpad, e o servidor não tem alcance sobre ele. O desenho tem que
assumir que o processo antigo pode agir.

**Identidade da instalação.** `installation_id`, gerado na primeira instalação e
gravado no armazenamento durável do bridge; enviado em toda requisição. É
distinto do terminal (posição lógica no caixa) e da credencial.

**Autoridade da instância ativa.** O servidor guarda `active_installation_id` e
um `installation_epoch` monotônico por terminal. Só a instalação ativa recebe
comandos. Outra instalação com credencial válida **não** é aceita em silêncio:
passa por *assunção de terminal*, ato explícito e auditado.

**Fencing com honestidade sobre o que ele faz.** O comando carrega o epoch. Um
resultado com epoch velho **não é descartado** — pode ser a verdade sobre
dinheiro que saiu. Ele é aceito como **evidência**, registrado, e força
reconciliação; o que ele não faz é liberar ocupação nem autorizar a instância
nova a seguir (I9).

**Consultar não neutraliza — a correção central desta revisão.** Existe esta
sequência, e o desenho anterior caía nela:

1. o processo antigo recebe o comando e fica suspenso;
2. a nova instalação consulta: a cobrança ainda não aconteceu;
3. a ocupação é liberada;
4. o processo antigo retoma e **executa**.

**"Não executou até agora" não é "não poderá mais executar".** A evidência
financeira, sozinha, não resolve isto: ela descreve o passado, e o executor
suspenso é um fato do futuro. Liberar execução nova depois de troca de instalação
exige **neutralizar o executor anterior**, ou garantia equivalente do provedor.

Três formas de neutralização, e a ocupação só é liberada com pelo menos uma
registrada:

| # | Neutralização | Vale porque |
|---|---|---|
| **N1** | Provedor deduplica pela referência estável da operação (D1) | a execução tardia do processo antigo não vira segunda cobrança |
| **N2** | Provedor invalida/cancela a operação pendente por referência, e foi invalidada | o comando velho deixa de ter efeito no provedor |
| **N3** | Executor anterior atestadamente neutralizado por procedimento controlado — serviço desinstalado, máquina desativada, pinpad fisicamente repareado — com autoria registrada | não há mais quem chame o SDK |

**Autofencing do bridge é mitigação, não garantia.** O bridge deve conferir seu
epoch contra o servidor antes de chamar o SDK, e desistir se estiver velho. Isso
ajuda no caso comum e **não conta como neutralização**: um processo que retoma
sem rede pode executar assim mesmo, e é exatamente o caso que preocupa.

**Assunção de terminal.** Nova instalação pareada → terminal em
`TAKEOVER_PENDING`. Se houver ocupação sem resolução, a instalação nova recebe
**apenas** comandos de recuperação (`QUERY`), nunca `START`, até a operação
pendente ser resolvida **e** a neutralização registrada. É exatamente a regra
pedida: se a execução anterior não puder ser descartada com segurança, a
operação permanece bloqueada para
reconciliação.

**Reinstalação, troca de equipamento, perda do armazenamento local.** O bridge
sobe sem estado local, com credencial válida e `installation_id` novo. Ele
**declara ao servidor que subiu sem armazenamento**. Perder o armazenamento local
não é começar limpo — é **perder a prova**, e é tratado como tal: o servidor
bloqueia execução naquele terminal até que a ocupação pendente seja resolvida por
consulta ou reconciliação. Um bridge que se reinstala não ganha o direito de
cobrar de novo.

### 3.3 Persistência antes da chamada externa — sequência exata

| Passo | Ato | Durável antes de seguir? |
|---|---|---|
| 1 | **Recebimento**: `{command_id, provider_transaction_id, epoch}` | sim, com `fsync` |
| 2 | **Intenção de acionar**: referência exata da chamada que será feita ao SDK | sim, com `fsync` — **antes** do passo 3 |
| 3 | Chamada ao SDK | — |
| 4 | **Resultado** devolvido pelo SDK | sim, com `fsync` |
| 5 | Comunicação ao servidor | — |

**A janela de incerteza é entre 2 e 4**, e ela inclui a possibilidade de a
chamada **nunca ter ocorrido** — queda entre gravar a intenção e o SDK receber
qualquer coisa. Do lado de fora, "intenção gravada sem resultado" e "cobrança
feita sem resposta" são indistinguíveis localmente.

Na retomada, o bridge encontra intenção sem resultado e **não reexecuta** (I5).
Ele consulta o provedor pela referência estável gravada no passo 2. Se o provedor
responder, relata a verdade. Se não puder responder, relata `UNKNOWN`, e a
operação permanece bloqueada para reconciliação.

**Não prometo execução financeira exatamente uma vez com armazenamento local.**
O que o armazenamento local garante é: no máximo uma *intenção* por `command_id`,
e evidência durável da incerteza. Exatamente-uma-vez depende do provedor — §4.

### 3.4 As rotas

| Rota | Quem chama | O que faz |
|---|---|---|
| `GET .../terminals/{id}/commands` | bridge | espera até ~25 s; entrega um comando em lease |
| `POST .../commands/{cmd}/ack` | bridge | `PENDING/LEASED` → `ACKED` |
| `POST .../commands/{cmd}/result` | bridge | resultado do comando, inclusive de `QUERY` |
| `POST .../transactions/{tx}/result` | bridge | **legado**; correlação em §3.6 |
| `POST .../secret/rotate` e `.../confirm` | bridge | rotação (§3.8) |

Autenticadas pelo segredo de pareamento em cabeçalho, sem
`Depends(get_tenant_context)` — que é como as rotas de bridge atuais já ficam
fora do RBAC de usuário. Tenant e loja saem do **terminal autenticado**, nunca do
corpo (corrigindo A5).

### 3.5 Tabela de transições

Duas máquinas. A de entrega fala do fio; a financeira fala do dinheiro. Nenhuma
transição da primeira resolve a segunda (I7).

**Entrega do comando**

| Estado atual | Evento | Novo estado | Observação |
|---|---|---|---|
| `PENDING` | reivindicado | `LEASED` | lease de ~30 s |
| `LEASED` | ACK | `ACKED` | — |
| `LEASED` | **resultado antes do ACK** | `CLOSED` | resultado implica recebimento; ACK deixa de importar |
| `LEASED` | lease vence | `PENDING` | reentrega com **o mesmo `command_id`** (I3) |
| `ACKED` | resultado | `CLOSED` | — |
| `PENDING`/`LEASED`/`ACKED` | tentativas esgotadas | `CLOSED` | fecha **o comando**; a operação **não** se resolve (I2) |
| `CLOSED` | **ACK após conclusão** | `CLOSED` | aceito, registrado em auditoria, **sem efeito** (I6) |
| `CLOSED` | **ACK após expiração** | `CLOSED` | idem; se ainda não estava `CLOSED`, cancela reentrega |
| `CLOSED` | resultado repetido | `CLOSED` | idempotente |

**Resolução financeira**

| Estado atual | Evento | Novo estado | Ocupação |
|---|---|---|---|
| `NAO_INICIADA` | comando emitido | `INCERTA` | **adquirida** |
| `INCERTA` | resultado prova execução | `PROVADA_EXECUTADA` | liberada |
| `INCERTA` | resultado prova recusa | `PROVADA_NAO_EXECUTADA` | liberada |
| `INCERTA` | resultado diz "cancelada" | **depende do provedor** — ver abaixo | só se provar não execução |
| `INCERTA` | consulta prova não execução | `PROVADA_NAO_EXECUTADA` | liberada |
| `INCERTA` | **consulta concluída, financeiro ainda `UNKNOWN`** | `INCERTA` | **mantida** (I7) |
| `INCERTA` | expiração / tentativas esgotadas | `INCERTA` | **mantida** (I2) |
| `INCERTA` | **resultado após comando não resolvido** | conforme a prova | liberada só se provar |
| `PROVADA_EXECUTADA` | resposta contraditória | `PROVADA_EXECUTADA` | mantida liberada; vira divergência, sem regredir (I6) |
| `INCERTA` | reconciliação humana com evidência | conforme decisão registrada | liberada, com autoria |

`_apply_result` já trata tardia, repetida e contraditória, e não deixa a
transação andar para trás; a novidade é que a **ocupação** passa a ter regra
própria, separada do status da transação.

**Cobrança e estorno resolvem separado.** São operações distintas, com resolução
própria cada uma: um estorno provado não resolve a cobrança que o originou, e uma
cobrança confirmada não diz nada sobre o estorno pedido depois. Cada uma tem sua
linha de ocupação quando ocupa o terminal, e sua própria correlação (§3.6).

**"Cancelada" não é universalmente "nunca executou".** Em parte dos provedores
significa desfazimento *antes* da captura — não saiu dinheiro. Em outros
significa desfazimento *depois* de autorizada — o dinheiro saiu e voltou, o que
é movimento, não ausência dele. **O mapeamento de status do provedor para
resolução financeira é declarado por provedor**, junto com o adapter, e revisado
contra a documentação dele. Enquanto não estiver declarado, "cancelada" mantém a
operação `INCERTA` e a ocupação de pé.

### 3.6 Correlação de resultados

**Rota nova, por comando:** o resultado referencia `command_id`. É a via
preferencial e não tem ambiguidade.

**Rota legada, por transação** (`/transactions/{tx}/result`): precisa descobrir a
qual comando responde. Regra:

1. Candidatos = comandos daquele `provider_transaction_id`, naquele terminal, não
   `CLOSED`.
2. Exatamente um candidato → correlaciona.
3. Nenhum, ou **mais de um, inclusive da mesma classe** — duas consultas abertas
   sobre a mesma transação são tão ambíguas quanto uma cobrança e um
   estorno abertos) → **não adivinha**: registra como evidência não atribuída,
   mantém a ocupação e força reconciliação (I8).
4. Resultado de estorno correlaciona ao comando `REFUND`, nunca ao `START`
   original, e sem `refunded_amount` não há baixa — [ADR-030](../architecture/adr-030-open-account-parcel-reversal.md)
   já vale, e estorno parcial é exatamente onde adivinhar sai caro.

**"Última operação do pinpad"** só pode ser usada quando o SDK devolver uma
referência **comprovadamente igual** à gravada na intenção (§3.3, passo 2). Sem
essa igualdade, a última operação pode ser de outro caixa, de outro turno ou de
outro sistema: preserva-se o resultado desconhecido (I8).

### 3.7 Pausa, rotação e revogação — três coisas diferentes

A revisão 2 tratou como uma só, e errou no caso que mais importa.

| Situação | Entrega de comandos | Resultado financeiro pela credencial | Autoridade |
|---|---|---|---|
| **Pausa operacional do vínculo** | suspensa | **aceito** — a credencial está íntegra | `provider.configure` |
| **Rotação normal** | continua | aceito (as duas credenciais na janela) | `provider.terminal.rotate` |
| **Revogação por suspeita de comprometimento** | cortada | **recusado** (I10) | `provider.terminal.revoke` |

Na revogação por segurança, quem tem a credencial pode ser um atacante — e uma
credencial comprometida autorizada a afirmar "confirmado" ou "estornado" é pior
que a cobrança perdida. Ela deixa de valer para afirmar fato financeiro.
Requisições que chegarem com ela são **registradas como evidência suspeita**, não
descartadas em silêncio, e nunca liberam ocupação.

**A recuperação não se limita a comandos `ACKED`.** Pode ter havido execução com
ACK perdido em `LEASED`, ou operação já dada como não resolvida. O escopo de
recuperação é **toda operação sem resolução provada**, qualquer que seja o estado
de entrega.

**Credencial não é verdade financeira** (I10b). A revisão anterior dizia que a
resposta da instalação substituta é autoritativa "porque a credencial é nova".
Está errado: a credencial autentica **quem respondeu**, e nada além disso. Um
bridge novo pode responder de boa-fé com um palpite local.

Resolver exige as três coisas juntas:

| Requisito | O que significa |
|---|---|
| **Origem confiável do resultado** | o fato veio do SDK/provedor, não da memória local do bridge; a resposta declara sua procedência |
| **Correlação com a operação** | referência comprovadamente igual à gravada na intenção (I8) — nada de "última operação" |
| **Ambiente recuperado** | o ambiente comprometido foi efetivamente recuperado, não apenas recredenciado |

Três caminhos de recuperação, em ordem de preferência:

1. **Credencial substituta** em instalação nova, com uma pessoa presente na loja.
   A resposta dela vale se — e só se — cumprir os três requisitos acima.
2. **Canal confiável**: extrato do adquirente, portal do provedor ou arquivo de
   liquidação — evidência que não passa pelo caminho comprometido. **Ressalva que
   a revisão anterior não fazia: extrato sem lançamento não prova ausência de
   cobrança.** Pode ser atraso de atualização ou de liquidação. Só vale como
   prova de ausência depois da janela de liquidação declarada pelo provedor, ou
   com declaração de finalidade dele.
3. **Procedimento controlado**: reconciliação humana registrada, com autoridade
   nomeada e evidência anexada, quando os dois anteriores não resolverem.

**Os critérios técnicos de suficiência da evidência são definidos por quem
implementa, conforme o provedor escolhido** — variam com o que cada adquirente
oferece de consulta, finalidade e janela. O que é seu é dizer **quem tem
autoridade para aplicá-los** (§8).

Até existir evidência suficiente, a operação **permanece bloqueada** e a
ocupação, mantida.

Comandos permitidos em cada situação:

| Situação | `START` | `QUERY` | `CANCEL` |
|---|---|---|---|
| Pausa operacional | bloqueado | permitido | permitido, se o provedor suportar (§3.9) |
| Rotação normal | permitido | permitido | permitido |
| Revogação por segurança | bloqueado | **só pela instalação substituta** | bloqueado |
| Assunção pendente com ocupação | bloqueado | permitido à instalação nova | bloqueado |

### 3.8 Rotação recuperável — protocolo completo

A revisão 2 dizia guardar só o hash e entregar o segredo depois, uma vez. **Não
dá para entregar o que não se tem.** Protocolo:

**Disponibilidade protegida.** A rotação é iniciada pelo bridge, que gera e
persiste um `rotation_id` antes de pedir. O servidor cria a credencial nova e
guarda: o **hash** (permanente) e um **registro de rotação pendente** com o valor
cifrado por chave que não está no banco, com TTL curto (proposta: 15 minutos) e
teto de recuperações. O valor em claro existe apenas ali e na resposta.

**Persistir antes de confirmar** (I11b). A revisão anterior dizia que autenticar
com a credencial nova *é* a prova de que foi persistida. **Não é:** o bridge pode
autenticar com o segredo ainda em memória e cair antes de gravá-lo — ficando sem
a credencial nova e com a antiga já vencida. Obrigação explícita do bridge:
gravar a credencial nova com `fsync` **antes** de chamar confirmar. O servidor
não consegue verificar isso; é obrigação contratual, e é assim que está escrito.

**Confirmação idempotente.** `POST .../secret/rotate/{rotation_id}/confirm`,
autenticado com a credencial nova. Repetir a chamada com o mesmo `rotation_id`
devolve o mesmo desfecho, sem efeito colateral e sem gerar credencial nova.

**Confirmação processada com resposta perdida.** É o caso que faltava: o servidor
já confirmou e **já destruiu o valor cifrado**, e o bridge não soube. A
recuperação **não depende de receber o segredo de novo** — ele já está gravado
localmente, porque gravar veio antes de confirmar. O bridge consulta
`GET .../secret/rotation/{rotation_id}`, autenticado **com a credencial nova**, e
lê o estado (`PENDENTE`, `CONFIRMADA`, `ABANDONADA`). Essa rota **nunca** devolve
segredo, só estado. Se autenticar e ler `CONFIRMADA`, a transição terminou.

**Perda da resposta da emissão** (antes de persistir). O bridge repete com o
**mesmo `rotation_id`** e recebe **a mesma credencial**, dentro do TTL e do teto.
É o que impede emissão sucessiva de segredos diferentes numa repetição: um
`rotation_id` produz uma credencial, e só uma. Restrição única garante **uma
rotação pendente por terminal**.

**Recuperação segura durante a transição.** Enquanto a rotação está pendente, as
duas credenciais autenticam. O bridge que caiu no meio tem sempre uma saída: se
gravou a nova, usa a nova; se não gravou, ainda tem a antiga válida.

**Quando a anterior deixa de valer.** Ela permanece válida até a confirmação,
mais uma janela de carência curta. Se a rotação não for confirmada dentro do TTL,
ela é **abandonada** e a credencial antiga segue sendo a única válida — falha
segura, sem tranca do lado de fora.

**Nunca em log, auditoria, payload de domínio ou documento** (I11). A auditoria
registra `rotation_id`, terminal, autor e desfecho. Nenhum valor de credencial
entra em `sanitized_payload`, outbox, evidência ou neste documento.

### 3.9 Permissões, cancelamento e capacidade do provedor

`CONTROL` classifica **transporte**, não autoridade. Cancelar afeta operação
financeira, e o repositório já tem o precedente: `checkout.payment.cancel` e
`checkout.payment.refund` foram separadas de `checkout.payment` justamente porque
devolver dinheiro não é a mesma autoridade que recebê-lo.

| Ação | Permissão | Nova? |
|---|---|---|
| Ver fila e pendências | `provider.read` | existente |
| Emitir consulta (`QUERY`) | `provider.transaction.query` | **nova** |
| Cancelar operação em voo | `provider.transaction.cancel` | **nova** |
| Registrar reconciliação humana | `provider.transaction.reconcile` | **nova** |
| Rotacionar credencial | `provider.terminal.rotate` | **nova** |
| Revogar por comprometimento | `provider.terminal.revoke` | **nova** |
| Configurar provider e parear | `provider.configure` | existente, inalterada |

Todas com escopo de unidade, como o resto da cadeia. Toda ação grava
`ProviderTransactionEvent` mais outbox com autor; a reconciliação grava também a
**evidência em que se apoiou** (I12).

**Receber comando ≠ chamar o SDK.** O bridge mantém o long-poll aberto enquanto
executa — senão um `CANCEL` nunca chega a tempo — mas **serializa as chamadas ao
SDK**. Recepção concorrente, invocação serial.

**Sem sucesso presumido** (I13). Se o SDK não aceita cancelamento com operação em
curso, o `CANCEL` **não** vira sucesso por ter sido entregue: o comando fecha como
*não executado por limitação do provedor*, a operação segue em voo, a ocupação é
mantida e a tela diz isso com essas palavras. Entregar não é cancelar.

### 3.10 Interface

Reuso de `PaymentProviderManager`, na localização que a migração `090` já lhe
deu: **FINANCEIRO** — "Configure como você recebe pagamentos". Sem área nova. A
revisão 2 disse "Gestão → Operação" e estava errada.

Nova seção *Fila e pendências*: comando parado, operação sem resolução, evidência
não atribuída e resultado que não pôde ser aplicado — em linguagem de operação,
não traceback. Dela saem apenas **consultar**, **cancelar** (quando o provedor
suportar) e **encaminhar para reconciliação**.

**A tela de pendências não inicia cobrança.** Nenhum botão ali cria movimento de
dinheiro novo.

E, no caminho de venda: **novo `START` é recusado quando o pinpad está ocupado ou
quando há operação incerta**, com mensagem que nomeia a operação em voo e oferece
as ações autorizadas de consulta e tratamento. Com a linha de ocupação (§3.1), a
recusa é o desfecho natural do banco.

### 3.11 Métricas — meta de laboratório, não SLA

**p95 ≤ 2 s** entre emissão e disponibilidade ao bridge, como **meta inicial de
laboratório**. Não é SLA, não é compromisso comercial, e não vira um sem decisão
sua e separada.

| Condição | Definição proposta |
|---|---|
| **Carga** | 20 terminais com long-poll aberto; 60 comandos/min distribuídos |
| **Ambiente** | laboratório local: um processo `uvicorn`, pool 5+5, Postgres do compose. **Não é produção** |
| **Amostra** | mínimo 500 comandos numa janela contínua declarada |
| **Pontos de medição** | `created_at` (commit da emissão) → `delivered_at` (commit da reivindicação), **ambos do relógio do servidor** — o relógio do bridge não entra |

**Duas métricas, sempre reportadas juntas:** (a) tempo total observado, sem
exclusão nenhuma; (b) tempo excluindo períodos sem bridge conectado. A (b) nunca
aparece sozinha — sozinha, ela esconde exatamente o caso em que o operador
esperou.

**Degradação da venda local**, substituindo o "inalterada" da revisão 2, que não
é mensurável:

- **Baseline**: p95 do caminho de venda local, mesma amostra, **sem** long-polls abertos.
- **Critério de aprovação proposto**: sob a carga acima, p95 da venda local
  **≤ baseline × 1,20** (degradação ≤ 20%) e **zero** erros de esgotamento de pool.

### 3.12 Execução assíncrona e banco

1. Nenhuma transação aberta e nenhuma conexão retida durante a espera: cada
   sondagem abre transação → tenta reivindicar → **commit** (devolve a conexão,
   conforme medido) → `await` sem nada na mão.
2. Nenhuma chamada bloqueante no event loop: `psycopg2` é síncrono, então toda
   sondagem vai para thread; a espera é `await asyncio.sleep(...)`.
3. Sem `Depends(get_session)` nesta rota; sessão curta por sondagem.
4. Contexto RLS dentro de cada sondagem — `set_config(..., true)` é
   *transaction-local*.
5. Desconexão do cliente encerra a espera.
6. Teto de esperadores por processo; acima dele, resposta imediata com recuo,
   degradando para polling curto em vez de derrubar a API.

### 3.13 Carga e migração

`tef_bridge_commands` (identidade estável, classe, sequência, entrega, lease,
tentativas, carga saneada), `tef_terminal_occupancy` (§3.1), registro de rotação
pendente (§3.8), e colunas novas em `tef_bridge_terminals`: `last_seen_at`,
`device_state`, `active_installation_id`, `installation_epoch`.

**Migração nova `097`** sobre `096_the_grant_keeps_its_history` — cabeça conferida
nesta revisão no código e no `alembic_version` do banco publicado. Nenhuma
migração publicada é alterada. RLS igual à da `024`; `EnumString` vira
`String(50)`; `alembic check` é o juiz.

Carga do comando: identificador, tipo, valor, método, rota, epoch. Nunca PAN,
trilha, senha ou credencial. `credentials_ref` segue apontando para o cofre e não
viaja no comando.

## 4. Dependências reais do SDK e do provedor

O que a frente A **não** consegue garantir sozinha, e de que depende cada
garantia. Isto precisa ser conferido contra a documentação do adquirente escolhido
— não escolho adquirente aqui, e a ausência de qualquer item abaixo não é defeito
nosso, mas muda o que podemos prometer.

| # | Dependência | Se existir | Se não existir |
|---|---|---|---|
| **D1** | **Idempotência na cobrança** por chave da operação | reenvio ao SDK deixa de duplicar **dentro do escopo e da janela de retenção da chave** — não é exatamente-uma-vez por si só | exatamente-uma-vez **impossível**; só resta consultar |
| **D2** | **Consulta por referência estável** da operação | a janela de incerteza (§3.3) fecha sozinha | incerteza persiste até reconciliação humana |
| **D3** | **Confirmação/desfazimento** explícito (padrão comum em TEF) | operação em dúvida é resolvida pelo protocolo | resolução depende de D2 ou de extrato |
| **D4** | **Cancelamento durante operação em curso** | `CANCEL` executa | `CANCEL` vira pendência explícita (I13) |
| **D5** | **Estorno com valor revertido declarado** | baixa financeira acontece (ADR-030) | estorno fica pendente; nada é baixado por palavra |
| **D6** | **Referência correlacionável** da última operação | retomada identifica a operação certa | "última operação" é inutilizável; preserva `UNKNOWN` (I8) |

**Sem D1 e sem D2, nenhum desenho de transporte entrega exatamente-uma-vez.** O
que entregamos nesse caso é: no máximo uma intenção por comando, incerteza sempre
visível, e nenhuma cobrança nova sobre operação não resolvida. É menos do que se
gostaria de prometer, e é o que é verdade.

**E com D1 também não prometemos exatamente-uma-vez de saída.** A idempotência do
provedor vale dentro do escopo da chave, da janela de retenção dela e do canal em
que foi apresentada — e nada disso é nosso. A durabilidade local, por sua vez, é
garantia **daquela instalação e das condições testadas**: não atravessa perda de
armazenamento, troca de equipamento nem um segundo executor. Somadas, as duas
reduzem a chance de duplicidade; declará-las como exatamente-uma-vez seria
prometer com recurso alheio.

## 5. Matriz de testes

Bridge de referência é **processo de verdade**: HTTP real pela rede,
armazenamento local durável com `fsync`, morrível e reiniciável, e capaz de rodar
em **duas instalações com bancos locais separados**.

**Real nestas provas:** transporte, rede, persistência, concorrência, reinício,
expiração, deduplicação, ocupação.
**Simulado, e declarado:** **toda resposta do adquirente** — aprovação, recusa,
NSU, código de autorização, tempo, bandeira, valor de estorno. Nenhuma prova
desta frente diz coisa alguma sobre dinheiro real.

| # | Teste | Garante |
|---|---|---|
| T1 | Perda de ACK: recebe, grava, executa, derruba o ACK; reentrega deduplicada | I3, I5 |
| T2 | Dois processos, **bancos locais separados**, lease expira e o **antigo retoma** | I1, I9 |
| T3 | Execução anterior indescartável → operação permanece bloqueada para reconciliação | I1, I2, I9 |
| T4 | Queda entre intenção persistida e retorno do SDK; retomada consulta, não reexecuta | I4, I5 |
| T5 | Queda **antes** de o SDK receber qualquer coisa; retomada trata como incerta | I4, I5 |
| T6 | Resultado antes do ACK | I6 |
| T7 | ACK após `CLOSED` e ACK após expiração: sem regressão | I6 |
| T8 | Resultado após comando não resolvido | I2, I6 |
| T9 | Respostas repetidas e contraditórias | I6 |
| T10 | `QUERY` concluída com financeiro ainda `UNKNOWN`: ocupação **mantida** | I7 |
| T11 | Correlação ambígua na rota legada → evidência não atribuída | I8 |
| T12 | Estorno parcial correlaciona ao `REFUND`, não ao `START` | I8 |
| T13 | Expiração e tentativas esgotadas não liberam ocupação nem reserva | I2 |
| T14 | Reinstalação sem armazenamento local não libera cobrança nova | I1, I9 |
| T15 | Assunção de terminal com ocupação pendente: só `QUERY` | I9 |
| T16 | Pausa do vínculo durante cobrança em voo: resultado ainda aceito | — |
| T17 | Revogação por segurança: credencial revogada **não** afirma resultado | I10 |
| T18 | Recuperação por credencial substituta resolve a operação pendente | I10 |
| T19 | Rotação: resposta perdida, repetição com mesmo `rotation_id` devolve a mesma credencial | I11 |
| T20 | Rotação não confirmada dentro do TTL é abandonada; credencial antiga segue válida | I11 |
| T21 | Rotação com operação em voo não derruba a cobrança | I11 |
| T22 | Nenhuma credencial aparece em log, auditoria ou payload | I11 |
| T23 | `CANCEL` não suportado pelo provedor vira pendência, não sucesso | I13 |
| T24 | Cancelamento em voo entregue sem esperar o `START` terminar | I13 |
| T25 | Permissões por ação: `configure` não cancela nem reconcilia | I12 |
| T26 | Carga concorrente: venda local **≤ baseline × 1,20**, zero esgotamento de pool | — |
| T27 | **Processo antigo suspenso, consulta diz "não executou", retomada executa**: sem neutralização registrada, a ocupação **não** é liberada | I1b |
| T28 | Neutralização N1/N2/N3 registrada libera; nenhuma delas mantém bloqueado | I1b |
| T29 | Autofencing do bridge (epoch velho) não conta como neutralização | I1b |
| T30 | Resultado tardio da operação A **não** libera ocupação da operação B | I14 |
| T31 | `released_at` preenchido não trava o terminal: ocupação nova é aceita | I14 |
| T32 | Correlação legada com **dois candidatos da mesma classe** → não atribuída | I8 |
| T33 | Estorno resolvido não resolve a cobrança de origem, e vice-versa | I8 |
| T34 | "Cancelada" sem mapeamento declarado mantém `INCERTA` e ocupação | I2 |
| T35 | Resposta de instalação substituta sem origem confiável **não** resolve | I10b |
| T36 | Extrato sem lançamento, dentro da janela de liquidação, **não** prova ausência | I10b |
| T37 | Bridge cai após autenticar e antes de gravar: rotação recuperável, sem tranca | I11b |
| T38 | Confirmação processada com resposta perdida: estado lido pela credencial nova, sem reenvio do segredo | I11b |
| T39 | Confirmação repetida é idempotente e não gera credencial nova | I11b |

## 6. Ordem de implementação, depois do aceite

1. Migração `097`: comandos, ocupação, rotação pendente, colunas de instalação, RLS. `alembic check` verde.
2. Ocupação adquirida na mesma transação que cria a `ProviderTransaction`.
3. Rota de entrega assíncrona, ACK e resultado por comando.
4. `QUERY` como comando; `adapter.query()` deixa de fingir consulta síncrona e passa a enfileirar, devolvendo estado conhecido rotulado como *consulta emitida*.
5. Máquinas de transição de §3.5 e correlação de §3.6.
6. Identidade de instalação, epoch e assunção de terminal (§3.2).
7. Rotação e revogação (§3.7, §3.8) com as permissões novas (§3.9).
8. Bridge de referência e a matriz T1–T26.
9. Seção *Fila e pendências* em `PaymentProviderManager`.

Os itens 1 a 7 sem o 8 são código sem prova.

## 7. Fronteira com o Channel Hub

Esta implementação **não executa o Channel Hub e não será ampliada para isso**.
[S10.1 e S13.2](channel-hub-fundacoes-2026-09-10.md) avançam independentemente,
sem TEF, sem SDK de adquirente e sem credenciais produtivas. Os problemas se
parecem — inbox durável, deduplicação, executor com tentativa e reconciliação,
persistir antes de responder — e as lições atravessam; o mecanismo, não.

Vocabulário de estado aplicado ao TEF:

| Estado | TEF hoje |
|---|---|
| Estrutura existente | Pareamento, heartbeat, callback, vínculo e telas — **é o que existe** |
| Fundação validada | **Não.** É o que a frente A entrega, com efeitos do adquirente simulados |
| Conector implementado | **Não.** Frente B, por provedor |
| Homologado | **Não.** Frente C, externa |
| Ativo por cliente | **Não.** Depende de tudo acima mais configuração da unidade |

Contratação de plano pode financiar desenvolvimento, infraestrutura e
homologação, mas não substitui nenhuma dessas entregas. Entre contratar e a
primeira cobrança real existem as frentes A, B e C.

## 8. Decisões que ainda dependem de você

Os pontos técnicos foram resolvidos com recomendação concreta, não devolvidos
como pergunta. Restam duas decisões que são de autoridade operacional, não de
engenharia — e **nenhuma das duas bloqueia** começar pelos itens 1 a 8 de §6.

**1. Quem pode cancelar uma cobrança em voo e quem pode fechar uma operação
incerta.** As permissões novas de §3.9 estão **propostas**, não implementadas —
nada foi construído ainda. Recomendo que `provider.transaction.query` acompanhe
quem já opera o caixa, e que `provider.transaction.cancel` e `.reconcile` fiquem
com quem responde pela unidade. **Ressalva que importa:** numa operação de uma
pessoa só, essa pessoa é as duas coisas — a regra não pode exigir uma segunda
pessoa que não existe.

**2. Quem tem autoridade para aplicar os critérios de suficiência da evidência**
numa reconciliação humana. Os critérios **técnicos** são de quem implementa,
conforme o provedor (§3.7); o que é seu é dizer quem pode aplicá-los.

**Enquanto as duas seguirem pendentes** — e podem seguir: `cancel` e `reconcile`
ficam **sem concessão produtiva a perfil nenhum**, e **não existe caminho manual
de desbloqueio**. A consequência é deliberada e precisa estar dita: uma operação
bloqueada permanece bloqueada até que você decida quem desbloqueia. Nada no
código vai contornar isso por conveniência.

Segue **fora do meu alcance e não perguntado aqui**: adquirente, preços,
capabilities produtivas, canais, regra da UX-11 e canal da UX-12. E segue valendo
que planos comerciais **não bloqueiam** engenharia nem teste controlado.
