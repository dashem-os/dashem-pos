# OA-4 — Execução assistida contra o deploy publicado

Data: 3 de setembro de 2026
Commit: `a6cab8e`
Deploy do app: `https://dashem-pos.vercel.app` (bundle `index-Kx0mBv_U.js`)
API de produção: `https://dashem-pos-api.onrender.com` (`environment: production`)
Navegador: Chromium headless (Playwright)
Viewport base: 1366×768; larguras adicionais 1280, 1024, 768, 390 e 360
Responsável pela execução: agente Claude (Opus 5), sob condução de Marcelo
Decisão desta execução: **PASS parcial — não promove o Gate B**

## Por que parcial

A matriz mínima de aceitação do OA-4 exige cenários com credencial operacional:
terminal autorizado, colaborador com código ativado e PIN pessoal definido pelo
próprio colaborador. O ambiente de produção fica no Supabase e na Render, e o
executor não possui credencial nem acesso ao banco. Os cenários credenciados
**não foram executados** e não são presumidos aprovados.

O que segue é a parte da matriz alcançável sem credencial, executada contra o
deploy publicado, e não contra o ambiente local.

## Cenários executados

| Cenário da matriz | Resultado esperado | Observado | Veredito |
|---|---|---|---|
| Login público | não anuncia nem navega para `/operate` | título gerencial presente; "Entrar como operador" = 0; "Entrar com PIN" = 0; links para `/operate` = 0 | PASS |
| Navegador sem autorização | não recebe formulário de código + PIN | portão "Ative este ponto de operação"; campo de código = 0; campo de PIN = 0; campos de senha = 0 | PASS |
| Avisos e erros: leitura clara | superfície utilizável nas larguras de validação | sem rolagem horizontal em 1366, 1280, 1024, 768, 390 e 360 px | PASS |
| Avisos e erros: foco visível | indicador de foco presente e destacável | anel de foco presente; melhor contraste 21,00:1 contra o fundo | PASS |
| Avisos e erros: contraste AA | texto principal ≥ 4,5:1 | título da entrada operacional 20,17:1 sobre o próprio fundo | PASS |

Nenhum cenário falhou, portanto não há trace nem screenshot de falha a anexar.

## Cenários NÃO executados nesta rodada

Todos dependem de credencial operacional em produção e permanecem pendentes
para a decisão do Gate B:

- gestor entra por e-mail e chega a `/manage`;
- gestor autoriza o POS e o contexto é persistido e auditado;
- colaborador ativa credencial e define o próprio PIN; ativação torna-se inutilizável;
- código + PIN válidos criam sessão e abrem `/pos` no contexto do terminal;
- código ou PIN inválido devolve mensagem neutra com rate limit;
- operador de outro tenant/unidade é negado sem seletor de contexto;
- contexto adulterado é recusado antes da mutação;
- saída do turno encerra a sessão e preserva a autorização do terminal;
- segundo colaborador assume o mesmo terminal com autoria própria;
- sessão expirada ou revogada tem o JWT antigo recusado;
- terminal pausado ou revogado interrompe a sessão;
- alteração de função ou permissão derruba a autoridade anterior;
- operador tenta `/manage` e é negado;
- gestor tenta mutação no POS sem assunção e é negado.

Esses catorze cenários passam verdes no CI contra a pilha efêmera, no job
`Operational access E2E`. O que falta é a repetição no deploy, que o plano exige
explicitamente e que CI verde não substitui.

## Identificadores

A execução foi inteiramente não autenticada. Nenhum identificador de tenant,
unidade, terminal ou sessão foi utilizado ou capturado, portanto não há o que
sanitizar. As capturas cobrem apenas telas públicas, sem dado pessoal, PIN,
token ou código de colaborador.

## O que falta para promover o Gate B

1. Executar em produção os catorze cenários credenciados, com um terminal e um
   colaborador de homologação criados para esse fim.
2. Registrar a evidência sanitizada de cada um neste mesmo formato.
3. Submeter a decisão do Gate B com base nas duas execuções somadas.

*(Cumprido em 04/09/2026: a rodada credenciada fechou `14/14` e o Gate B foi promovido a `PASSED`.)* Até ali, o Gate B permanecia `REOPENED` e o piloto permanecia
`NO-GO`.
