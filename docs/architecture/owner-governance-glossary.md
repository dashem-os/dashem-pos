# Glossário canônico da governança Owner

Este vocabulário é normativo para backend, frontend, banco, testes e
documentação do Console do Owner.

| Termo | Definição | Autoridade | Pode ser editado no Owner? |
|---|---|---|---|
| Teto do plano | Máximo publicado por uma revisão do plano | Owner | Sim, somente em nova revisão do catálogo |
| Limite contratado | Direito do tenant no snapshot contratual vigente | Owner | Sim, por nova versão contratual |
| Configurado | Recurso cadastrado pelo administrador do tenant | Tenant | Não |
| Reservado | Capacidade ocupada por operação pendente, como convite ou upload | Sistema | Não |
| Utilizado | Consumo observado por medição confiável | Sistema | Não |
| Disponível | Saldo calculado pela policy: limite menos ocupação pertinente | Sistema | Não |
| Atividade comercial | Segmento contratado, como Retail ou Food Service; clientes possuem uma ou várias | Owner | Sim, por nova versão contratual |
| Capability proposta | Item resultante da combinação comercial ainda não aprovada | Catálogo | Não é autorização |
| Capability contratada | Direito explícito registrado no contrato | Owner | Sim, por nova versão contratual |
| Permission | Autorização pessoal/contextual para executar ação | Tenant/RBAC | Não é capability |
| Solicitação comercial | Pedido do tenant para alterar direito contratual | Tenant | Owner decide |
| Exceção | Direito ou limite fora do pacote padrão, com motivo e vigência | Owner | Sim, com auditoria |
| Não medido | Não existe instrumento confiável para produzir consumo | Sistema | Não pode ser exibido como zero |

## Regras de apresentação

Uma interface só pode exibir um número quando também conhece sua classe e sua
origem. Exemplos válidos:

- `Limite contratado: 40`;
- `Usuários ativos: 7`;
- `Convites reservados: 2`;
- `Ocupação para bloqueio: 9 de 40`;
- `Storage: não medido`.

Exemplos proibidos:

- `40 aplicado`;
- `0 MB utilizados` sem medidor;
- `1 usuário` sem declarar se é limite, cadastro ou consumo;
- `sem nicho` quando o contrato possui várias atividades não resolvidas.

Cliente comercial não pode ser contratado sem atividade. A ausência é permitida
somente para tenant interno de teste, como exceção explícita e justificada pelo
Owner.

## Contagem operacional inicial

As policies definitivas serão implementadas nos sprints seguintes. O baseline
para a reconstrução do read model é:

- usuários configurados: memberships ativas;
- usuários reservados: convites pendentes;
- dispositivos configurados: dispositivos ativos ou pausados;
- dispositivos revogados: não ocupam capacidade;
- unidades configuradas: unidades ativas;
- storage utilizado: somente bytes reconciliados pelo medidor futuro;
- storage reservado: uploads aceitos e ainda não finalizados.
