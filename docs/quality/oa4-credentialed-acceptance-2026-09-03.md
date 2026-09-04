# OA-4 — Cenários credenciados no deploy publicado

Data de início: 3 de setembro de 2026
Commit: `bf5a1dd`
Deploy do app: `https://dashem-pos.vercel.app`
API de produção: `https://dashem-pos-api.onrender.com`
Tenant: Tenant de Homologação · unidade Matriz Homologação
Executor: Marcelo (gestor e colaboradores), com condução do agente Claude (Opus 5)
Decisão: **concluída em 4/9/2026 — 14/14 cenários. Gate B promovido para `PASSED` por decisão do dono do SaaS**

Complementa a rodada não credenciada registrada em
[`oa4-deploy-acceptance-2026-09-03.md`](oa4-deploy-acceptance-2026-09-03.md),
que aprovou os cinco cenários alcançáveis sem credencial.

## Identidades usadas

| Papel | Referência | Observação |
|---|---|---|
| Administrador contratual | acesso por e-mail | entra por `/login` |
| Colaborador A | Supervisor Homologação · matrícula 0020 | função Supervisor |
| Colaborador B | Atendente OP · matrícula 0040 | função Atendente |
| Terminal | criado na unidade Matriz Homologação | autorizado pelo gestor |

Nenhum PIN, token, código de ativação ou identificador completo é registrado
neste documento. Identificadores aparecem truncados quando necessários.

## Resultado por cenário

| # | Cenário | Resultado obrigatório | Observado | Veredito |
|---|---|---|---|---|
| 1 | Gestor entra por e-mail | chega a `/manage`, nunca ao PDV automaticamente | janela anônima em `/login`; após autenticar parou em `/manage`, sem desvio para o PDV | PASS |
| 2 | Gestor autoriza POS | contexto persistido e auditado no servidor | `Validar no PDV` abriu `/pos?access=management` com contexto Matriz Homologação · Caixa 01 · gestor identificado, faixa de acesso gerencial e caixa fechado. O terminal já existia de execução anterior, então o caminho de provisionamento confirmado não foi exercitado aqui; ele foi verificado contra a pilha local no commit `bf5a1dd` | PASS |
| 3 | Colaborador ativa credencial | define o próprio PIN; ativação torna-se inutilizável | Gestão emitiu nova ativação para o Atendente OP com o aviso de revogação das sessões vigentes. Na janela anônima, `Primeiro acesso / novo PIN` com matrícula 0040, código temporário e PIN escolhido pelo colaborador devolveu "PIN pessoal ativado. Informe o mesmo código e PIN para assumir a operação" e voltou ao modo de entrada. A segunda tentativa com o mesmo código temporário foi recusada com "Código de ativação inválido ou expirado. Solicite um novo código à Gestão". A Gestão em momento algum viu o PIN | PASS |
| 4 | Código + PIN válidos | cria sessão e abre `/pos` no contexto do terminal | `Entrar no turno` com matrícula 0040 e o PIN recém-definido abriu `/pos` no contexto Matriz Homologação, com a faixa "Identidade reconhecida: Atendente OP · Operador" e o caixa em estado fechado. Sem botão de Gestão e sem controles de caixa no cabeçalho, coerente com a função Atendente, que só carrega `cash.read` | PASS |
| 5 | Código ou PIN inválido | mensagem neutra, sem enumeração, com rate limit | Matrícula válida com PIN errado, `ZZ-9999` e `CC-2026` devolveram todas a mesma frase, "Código ou PIN inválido para esta unidade". Cinco erros seguidos **na mesma matrícula** bloquearam o acesso com "Acesso temporariamente bloqueado após tentativas inválidas", e o PIN correto continuou recusado durante a janela — a trava por credencial funciona. | **FAIL na primeira execução**, por dois furos que a varredura por códigos diferentes escondeu. (a) O contador vivia só na credencial: uma matrícula que não resolve saía antes de incrementar qualquer coisa, então varrer códigos no terminal era ilimitado. (b) A neutralidade valia só para as saídas 401 — matrícula existente sem PIN ativado devolvia 409 e suspensa devolvia 403, confirmando a existência do código a custo zero. Corrigido no commit `9c3dacf`: contador por terminal (10 falhas em 10 minutos, teto de 1 tentativa por minuto), recusa única para toda falha de identidade, orientação de primeiro acesso fixa na tela e limpeza do portão por ociosidade de 60 segundos. Ficou também a liberação auditada do bloqueio na Gestão, porque a única saída existente era reemitir a ativação e destruir o PIN do colaborador. **A reexecutar no deploy** |
| 6 | Operador de outro tenant/unidade | acesso negado sem seletor de contexto | Conduzido pelo agente contra a API, já que a interface nunca oferece o tenant ou a unidade errados. Uma matrícula válida no tenant vizinho foi recusada no terminal deste tenant, e uma matrícula válida na Unidade 2 foi recusada no terminal da Unidade 1 do mesmo tenant. As duas recusas usam **a mesma frase** de um código que não existe em lugar nenhum, então o terminal não confirma que a pessoa é real do outro lado do muro. Nenhum seletor de contexto foi oferecido em momento algum, e a credencial da própria unidade continuou entrando, o que separa isolamento de terminal quebrado. Provado em `tests/test_oa4_cross_context_isolation.py` | PASS |
| 7 | Contexto adulterado | backend recusa antes da mutação | Com uma sessão operacional legítima da Unidade 1: pedir o contexto declarando a Unidade 2 devolveu 403, e declarando outro tenant devolveu 403 — a autoridade persistida no servidor vence o cabeçalho enviado pelo cliente. Restando o ataque de contexto autêntico com **corpo adulterado**, abrir caixa apontando para o caixa da unidade vizinha foi recusado e, lido fora da transação recusada, **nenhuma sessão de caixa ficou para trás**. Provado em `tests/test_oa4_cross_context_isolation.py` | PASS |
| 8 | Saída do turno | sessão encerra; terminal permanece autorizado | O ícone de sair devolveu o portão de **código e PIN**, não a tela de terminal não autorizado, com o campo de matrícula vazio. A autorização do terminal sobreviveu à saída da pessoa | PASS |
| 9 | Segundo colaborador | assume o mesmo terminal com sessão e autoria próprias | Sem reautorizar nada, `SP-0020` assumiu o mesmo terminal: o cabeçalho passou a identificar "Supervisor Homologação · Supervisor" e a tela de caixa fechado trocou de conteúdo — o Supervisor recebeu o campo de fundo de troco e **Abrir caixa e iniciar vendas**, ausentes para o Atendente, que só via "Seu perfil pode operar vendas depois que um Caixa ou Supervisor abrir este caixa". A matriz de permissão é aplicada por sessão, não por terminal | PASS |
| 10 | Sessão expirada ou revogada | JWT antigo recusado; volta ao portão operacional | Executado em 4/9/2026. Com o Supervisor no turno, **Suspender** na Gestão derrubou o PDV para o portão de código e PIN. Tentar assumir o turno com `SP-0020` e o PIN correto foi recusado com "Código ou PIN inválido para esta unidade" — a **mesma** frase de um código inexistente, sem revelar que o acesso está suspenso, que é a recusa uniforme corrigida no commit `9c3dacf` funcionando em produção. Após **Reativar**, o mesmo código e o mesmo PIN voltaram a entrar, sem exigir nova ativação, e o controle de caixa reapareceu no cabeçalho | PASS |
| 11 | Terminal pausado ou revogado | sessão interrompida e nova entrada bloqueada | Executado em 4/9/2026. **Pausar** o `Caixa 01` com motivo registrado interrompeu a sessão em curso e o terminal passou a exibir "TERMINAL NÃO AUTORIZADO · Ative este ponto de operação", com a explicação "Este terminal foi pausado, revogado, reativado ou alterado pelo gestor". A mensagem fala do **terminal**, nunca do PIN, que é o ponto do cenário: o colaborador não é levado a culpar a própria credencial por um problema do estabelecimento. O portão de código e PIN não é oferecido enquanto o terminal estiver sem autorização | PASS |
| 12 | Função ou permissão alterada | autoridade antiga deixa de operar | Executado em 4/9/2026. Com o Supervisor no turno e o controle de caixa visível no cabeçalho, a Gestão alterou a função para Atendente com motivo registrado. A sessão caiu e o terminal voltou ao portão de código e PIN. Ao reentrar com o **mesmo** código e PIN, o cabeçalho passou a `Supervisor Homologação · Operador` **sem o controle de caixa**, mantendo a barra de venda — que é o esperado, porque `sale.create` também é do Atendente. Devolvida a função para Supervisor, o controle de caixa voltou. A revogação é feita na mesma transação do salvamento (`revoke_credential_sessions` em `team.py`), então a autoridade acaba no instante do salvamento; a tela reflete no próximo contato, em até 15s pela inspeção do `PosContext` ou 30s pelo heartbeat do `AuthContext`, ou imediatamente na primeira ação — nenhuma operação é aceita nesse intervalo | PASS |
| 13 | Operador tenta `/manage` | acesso negado | Reexecutado em 4/9/2026 com isolamento correto de perfis — a primeira tentativa foi inválida porque as duas janelas eram anônimas do **mesmo** perfil e compartilhavam a sessão gerencial. Com a Gestão no perfil normal e o terminal em janela anônima, o Atendente no turno digitou `/manage` e o navegador voltou para `/pos` sem exibir a Gestão. O cabeçalho do operador não traz o botão Gestão | PASS |
| 14 | Autoridade sobre o turno | toda mutação de caixa responde a uma pessoa nomeada, e ninguém opera sob identidade alheia | **Cenário reescrito em 4/9/2026 por decisão do dono do SaaS.** O critério anterior — "gestor não muta sem assunção operacional" — contradizia a matriz da migração 017, que concede `cash.open` e `cash.close` a OWNER, TENANT_OWNER, ADMIN e MANAGER, e inviabilizava a revendedora que trabalha sozinha. A fronteira passa a ser a **superfície**: na sessão web do próprio gestor, ele abre e fecha o caixa sob a própria identidade, rastreado no perfil dele; no terminal de balcão compartilhado, código e PIN identificam quem assume, para qualquer pessoa. Invariantes verificados em `tests/test_cash_shift_authority.py`: turno sem principal autenticado é recusado; ator declarado diferente do autenticado é recusado (Gate A); a permissão continua exigida por rota. ADR-024 revisto, ADR-028 conciliado | **PASS**. Reexecutado no deploy em 4/9/2026: com identidade administrativa, informar R$ 100,00 abriu o turno ("Caixa aberto com saldo inicial de R$ 100,00"), o cabeçalho passou a `Caixa Aberto (R$ 100,00)` e o Atendente no terminal compartilhado, que não tem `cash.open`, passou a poder vender no caixa que o gestor abriu. O fechamento pelo cabeçalho devolveu "Caixa fechado! Saldo apurado: R$ 100,00 · Divergência: R$ 0,00". Defeito encontrado na reexecução e corrigido: o valor do fundo de troco sobrevivia ao próprio turno e reaparecia preenchido, com o botão habilitado, na abertura seguinte |

## Reexecução do cenário 5 no deploy (commit `9c3dacf`)

Executada em 3 de setembro de 2026, entre 21:10 e 21:18.

| Bloco | Observado | Veredito |
|---|---|---|
| Teto do terminal | Errando com matrículas diferentes (`HH-8888` entre elas), o portão passou a recusar com "Terminal temporariamente bloqueado após tentativas inválidas. Aguarde um instante e tente de novo.", mensagem distinta da recusa de identidade e que não fala de nenhuma pessoa | PASS |
| Limpeza por ociosidade | O portão apagou sozinho matrícula, PIN e mensagem após um minuto parado, voltando ao estado inicial | PASS |
| Recusa uniforme | Não exercitado nesta rodada. Coberto por teste automatizado em `tests/test_oa4_terminal_credential_throttle.py` | a observar |
| Bloqueio da credencial e liberação pela Gestão | Na segunda tentativa, com a janela do terminal já limpa, cinco erros seguidos em `AT-0040` bloquearam o acesso: o PDV passou a recusar com "Acesso temporariamente bloqueado após tentativas inválidas" e a Gestão passou a mostrar `Bloqueado até` em âmbar, com a ação **Liberar bloqueio**. Liberado, o colaborador entrou no PDV com o **mesmo PIN anterior** e chegou a `/pos` com "Identidade reconhecida: Atendente OP · Operador" | PASS |

**Nota sobre a ordem das travas.** A verificação do teto do terminal acontece
antes da busca da credencial, então enquanto o terminal está em ritmo limitado
uma tentativa devolve 429 sem tocar no contador da credencial. É o comportamento
pretendido — a trava mais ampla protege a mais estreita e evita escrita
desnecessária —, mas significa que as cinco falhas de PIN sobre a mesma
matrícula precisam caber abaixo do teto para bloquear o acesso. A janela de dez
minutos zera o contador do terminal na falha seguinte, então a sequência
correta é aguardar a janela e então errar cinco vezes seguidas na mesma
matrícula. Foi assim que o bloco foi concluído com sucesso na segunda tentativa.

**Defeito encontrado na própria evidência.** O distintivo do bloqueio anunciou
"Bloqueado até 00:48" às 21:34, o que se lê como três horas de castigo por cinco
erros de digitação. A trava é de quinze minutos; o que estava errado era a
exibição. A API serializa UTC ingênuo, sem fuso — `2026-09-04T00:48:00` — e
`new Date` sobre uma string sem fuso é interpretada como hora local, deslocando
todo carimbo de tempo vindo do servidor. O mesmo defeito mantinha um terminal
visto há um segundo fora do indicador "online agora" (janela de 90 segundos
comparada contra um instante três horas no passado) e antecipava o vencimento de
títulos com `due_at` na madrugada UTC. Corrigido em toda a interface pelos
auxiliares `parseApiDate`/`formatApiDateTime`, com regra de repositório em
`tests/api_timestamps.test.ts`.

### Nota do cenário 11 — reativar não devolve o navegador

Reativar o dispositivo **não** restabelece a autorização daquele navegador. Foi
preciso entrar como gestor no próprio terminal, abrir Terminais e dispositivos e
usar **Autorizar este navegador**; só então o portão de código e PIN voltou.

A causa está em [`device_service.py:112-116`](../../backend/app/services/device_service.py#L112-L116):
**qualquer** troca de status incrementa `authorization_version` e zera
`authorized_at`, `authorized_by` e `authorization_expires_at`. Pausar queima a
autorização, e a reativação queima de novo.

Isso não reprova o cenário — a entrada ficou bloqueada, que é o exigido. Mas
levanta uma decisão de produto ainda **pendente**: na prática, pausar equivale a
desparear. A diferença que resta entre **Pausar** e **Revogar** é que revogar é
irreversível (`Dispositivo revogado não pode ser reativado; faça novo
pareamento`), enquanto pausar permite voltar ao status ACTIVE — mas os dois
exigem alguém fisicamente no terminal, entrando por e-mail, para reautorizar.
Um PDV pausado por engano numa terça de manhã custa uma ida do gerente ao
balcão, e deixa a sessão gerencial aberta naquele navegador.

## Evidência de estados (exigida pelo gate do OA-3)

| Estado | Captura | Observação |
|---|---|---|
| Terminal não autorizado | 04/09/2026 10:25 a 10:30 | "TERMINAL NÃO AUTORIZADO · Ative este ponto de operação", com a razão do terminal e sem oferecer o portão de código e PIN |
| Ativação inicial do colaborador | 03/09/2026 20:02 e 20:08 | confirmação de ativação e recusa da reutilização. **A captura de 20:08 exibe o código temporário e não pode ser anexada ao dossiê sem tarja** |
| Entrada por código e PIN | 03/09/2026 20:09 | `/pos` com identidade Atendente OP · Operador e caixa fechado |
| Erro de credencial | 03/09/2026 e 04/09/2026 10:17 | "Código ou PIN inválido para esta unidade", idêntica para matrícula inexistente, PIN errado e acesso suspenso |
| Offline preservando autoridade | não exercitado à mão | coberto pela suíte de aceitação em `frontend/e2e/operational_access.cjs`, cenário "offline preserva autorização do terminal", verde no CI a cada commit. Sem captura manual nesta rodada |
| Sessão expirada ou revogada | 04/09/2026 10:00 e 10:16 | queda ao portão após troca de função (cenário 12) e após suspensão do acesso (cenário 10) |

## Decisão do Gate B

Execução concluída em 4 de setembro de 2026. **14 de 14 cenários executados
contra o deploy publicado**, somados aos cinco não credenciados da rodada de 3
de setembro.

O Gate B exige, além do núcleo já implementado, "o novo job verde no CI e a
repetição assistida contra o deploy publicado". As duas condições estão
cumpridas: o job `Operational access E2E` está verde, e esta é a repetição
assistida.

**Gate B promovido de `REOPENED` para `PASSED` em 4 de setembro de 2026**, por
decisão do dono do SaaS, tomada depois de ler as ressalvas abaixo.

### Ressalvas que acompanham a recomendação

1. **O cenário 14 foi reescrito durante a execução.** O critério original —
   "gestor não muta sem assunção operacional" — foi substituído por decisão do
   dono do SaaS em 4/9/2026, porque contradizia a matriz de permissões e
   inviabilizava a revendedora que trabalha sozinha. O gate está sendo avaliado
   pelo critério revisado, não pelo original. Quem ler depois precisa saber
   disso.
2. **Cenários 6 e 7 não foram executados contra o banco de produção.** A
   interface nunca oferece o tenant ou a unidade errados, então foram
   conduzidos pelo agente contra a API, com o mesmo código do deploy, e ficaram
   como testes em `tests/test_oa4_cross_context_isolation.py`. O agente não tem
   credenciais de produção.
3. **O estado offline não foi exercitado à mão.** Está coberto pela suíte de
   aceitação, verde no CI a cada commit.
4. **A comparação direta das três mensagens de recusa do cenário 5** não foi
   refeita à mão após a correção; foi observada indiretamente no cenário 6
   (outro tenant e outra unidade) e no cenário 10 (acesso suspenso), os dois
   devolvendo a frase genérica.

### Achados abertos que não bloqueiam este gate

Pertencem a outros escopos e estão registrados nos seus lugares:

- reativar um terminal não devolve a autorização do navegador (nota do cenário
  11, decisão de produto pendente);
- mesa e comanda operam sem turno de caixa (roadmap, seção 9, decisão pendente);
- comanda não pode ser transferida nem a conta dividida por pessoa (roadmap,
  seção 9, dívidas abertas);
- responsividade e UI/UX em redesenho por outro agente.
