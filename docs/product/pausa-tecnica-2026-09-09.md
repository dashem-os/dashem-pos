# Pausa técnica — DASHEM POS

Data: 09/09/2026. Base de código conferida localmente: `e693284`, em `main`; árvore limpa antes desta atualização documental. Os quatro jobs verdes foram informados pelo executor; esta revisão não consultou o CI remoto nem reexecutou testes. Esta pausa não declara homologação TEF real nem liberação para operação financeira real.

## Estado para retomada

- Fornecedores e contas a pagar entregues; evidências e contratos na [trilha UX](ui-ux-implementation-sprints.md).
- Diagnóstico e acesso assistido nominal entregues, com histórico preservado pelos fluxos implementados. Não há garantia de imutabilidade no banco.
- Jornadas de Ambientes e Mesas, configuração de provedores e [vínculo de maquininha](../quality/homologacao-vinculo-de-maquininha-2026-09-09.md) percorridas.
- Última unidade: jornada sequencial em duas telas e prova concorrente no banco; autoridade: proteção do servidor e atualização periódica da tela a cada 30 segundos, sem prazo garantido sob falha de rede ou suspensão da aba.
- Catálogo validado no cenário documentado (1.203 vendáveis no tenant, 40.830 na tabela), sem extrapolar o desempenho para qualquer volume.
- Processamento parcial, resposta tardia/repetida/contraditória e varrimento de reconciliação demonstrados nos cenários simulados e testes documentados. Não equivalem a integração externa.

## Bloqueio da integração real

O bridge ainda não recebe comandos de cobrança por um caminho implementado. Há pareamento, listagem, heartbeat e relato de resultado; o comando START armazenado não é entregue ao bridge. Também faltam bridge instalado, integração efetiva com o provedor escolhido e credenciais/ambiente de homologação. Não marcar sessão de homologação externa como pronta apenas com base no CI.

Inventário, 14 cenários e limites: [preparação da homologação com provedor](../quality/preparacao-homologacao-provedor-2026-09-09.md).

## Decisões do dono — ainda não tomadas

| Decisão | Informação necessária / efeito |
|---|---|
| Provedor/adquirente | Escolher a integração e obter documentação e ambiente de homologação; credenciais ficam fora de documentos e repositório. |
| Entrega ao bridge | Aprovar proposta técnica de polling ou conexão persistente. A proposta deve definir autenticação por terminal, isolamento, identificação do comando, confirmação de recebimento, repetição segura e recuperação após desconexão. O transporte sozinho não resolve duplicação de cobrança. |
| Responsável pelo bridge | Definir quem fornece, instala, configura e opera o software e equipamento na homologação. |
| Classificação de divergências | Definir se cada classificação é requisito verificável com prova própria, além dos valores financeiros. |
| Débito | Definir inclusão na primeira homologação ou adiamento explícito. |
| Canal de suporte — UX-12 | Informar canal real, destino e responsável pelo atendimento. Sem isso, pedir ajuda permanece incompleto. |
| Cálculos — UX-11 | Aprovar exemplos de base, competência, elegibilidade, divisão de gorjetas, cancelamento, ajustes e fechamento; não inventar percentuais ou regras trabalhistas. |

Emergência e autorização de equipe continuam fora do escopo; não precisam de nova decisão para pausar ou concluir o escopo inicial já definido.

## Sequência de retomada

1. Ler este registro e conferir `git status`, HEAD e resultado remoto do CI do candidato. Não repetir suítes já concluídas sem mudança ou motivo concreto.
2. Com o dono, resolver as decisões acima; o agente pode preparar proposta técnica e levantar requisitos sem escolher provedor ou inventar regras de negócio.
3. Implementar o caminho de entrega e recuperação dos comandos ao bridge, com contrato explícito e testes de isolamento, reenvio e desconexão. Definir onde a integração específica do provedor reside (bridge, servidor ou ambos) conforme a documentação escolhida.
4. Exercitar os cenários sem equivalente atual: cancelamento antes da resposta, cancelamento fora de ordem, estorno fora de ordem e pausa do vínculo durante cobrança em voo. Preservar os demais limites da tabela de preparação, inclusive dois workers e várias parcelas.
5. Executar homologação externa com bridge e ambiente do provedor, distinguindo resultados reais dos simulados. Definir os critérios de aceite aplicáveis antes de liberar essa integração.
6. Concluir pedir ajuda após definição do canal; iniciar UX-11 somente após exemplos aprovados.

## Condições desta pausa

Pausa de desenvolvimento, sem tarefa implícita de monitoramento ou alteração de serviços. Não desligar containers, limpar dados, desfazer migrações nem trocar configurações apenas para pausar. O próximo executor pode trabalhar diretamente na main, conforme autorização do dono para DASHEM POS. Preservar migrações publicadas; eventual correção estrutural usa nova migração.