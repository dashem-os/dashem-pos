# OA-4 — Cenários credenciados no deploy publicado

Data de início: 3 de setembro de 2026
Commit: `bf5a1dd`
Deploy do app: `https://dashem-pos.vercel.app`
API de produção: `https://dashem-pos-api.onrender.com`
Tenant: Tenant de Homologação · unidade Matriz Homologação
Executor: Marcelo (gestor e colaboradores), com condução do agente Claude (Opus 5)
Decisão: **em execução**

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
| 10 | Sessão expirada ou revogada | JWT antigo recusado; volta ao portão operacional | — | pendente |
| 11 | Terminal pausado ou revogado | sessão interrompida e nova entrada bloqueada | — | pendente |
| 12 | Função ou permissão alterada | autoridade antiga deixa de operar | — | pendente |
| 13 | Operador tenta `/manage` | acesso negado | — | pendente |
| 14 | Autoridade sobre o turno | toda mutação de caixa responde a uma pessoa nomeada, e ninguém opera sob identidade alheia | **Cenário reescrito em 4/9/2026 por decisão do dono do SaaS.** O critério anterior — "gestor não muta sem assunção operacional" — contradizia a matriz da migração 017, que concede `cash.open` e `cash.close` a OWNER, TENANT_OWNER, ADMIN e MANAGER, e inviabilizava a revendedora que trabalha sozinha. A fronteira passa a ser a **superfície**: na sessão web do próprio gestor, ele abre e fecha o caixa sob a própria identidade, rastreado no perfil dele; no terminal de balcão compartilhado, código e PIN identificam quem assume, para qualquer pessoa. Invariantes verificados em `tests/test_cash_shift_authority.py`: turno sem principal autenticado é recusado; ator declarado diferente do autenticado é recusado (Gate A); a permissão continua exigida por rota. ADR-024 revisto, ADR-028 conciliado | **A reexecutar no deploy com o critério novo** |

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

## Evidência de estados (exigida pelo gate do OA-3)

| Estado | Captura | Observação |
|---|---|---|
| Terminal não autorizado | — | pendente |
| Ativação inicial do colaborador | 03/09/2026 20:02 e 20:08 | confirmação de ativação e recusa da reutilização. **A captura de 20:08 exibe o código temporário e não pode ser anexada ao dossiê sem tarja** |
| Entrada por código e PIN | 03/09/2026 20:09 | `/pos` com identidade Atendente OP · Operador e caixa fechado |
| Erro de credencial | — | pendente |
| Offline preservando autoridade | — | pendente |
| Sessão expirada ou revogada | — | pendente |

## Decisão do Gate B

Preenchida ao final, somando esta rodada à rodada não credenciada. Enquanto
qualquer cenário permanecer pendente ou reprovado, o Gate B continua `REOPENED`
e o piloto continua `NO-GO`.
