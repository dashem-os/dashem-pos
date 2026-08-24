# ADR-019 — Pessoas, terminais e periféricos não compartilham identidade

Status: aceito no gate corretivo S21.1, em 24/08/2026.

## Contexto

O login de gestão, a troca de operador em um caixa e o pareamento de um
equipamento são cerimônias diferentes. Colocá-las na mesma tela transforma um
PIN local em aparente login global, mistura permissões humanas com credenciais
de máquina e torna difícil explicar ou revogar o acesso.

## Decisão

Existem três superfícies independentes:

1. **Gestão:** administrador e gerente entram por e-mail, OAuth e MFA através do
   Supabase Auth. O login público não oferece código e PIN.
2. **Operação:** supervisor, caixa e atendente informam código e PIN somente na
   rota local `/operate`, depois que um gestor autorizou aquele navegador contra
   um `OperationalDevice` POS. O token do turno identifica a pessoa; a
   credencial do terminal fixa tenant, unidade e caixa.
3. **Dispositivo:** TEF Bridge, KDS e agente de impressão não recebem papel
   humano nem PIN de funcionário. Cada instalação é pareada por um gestor,
   recebe uma credencial própria, envia heartbeat e pode ser pausada ou revogada
   sem afetar a identidade das pessoas.

Um gestor autenticado que abre o PDV continua com sua sessão gerencial e não
precisa assumir um operador por PIN. Ao sair da sessão gerencial em um navegador
que já é terminal autorizado, a aplicação retorna à superfície `/operate`.

### TEF

O `PaymentIntent` identifica a parcela e o ator humano continua vindo da sessão
Dashem. O caixa chama a API, que cria uma `ProviderTransaction` para um
`TefBridgeTerminal` pareado ao mesmo `Register` e à configuração do provider.
Somente o bridge local conversa com SDK/DLL/pinpad. NSU, autorização, adquirente,
correlation ID e resultado sanitizado retornam ao orquestrador; a maquininha não
faz login na Gestão.

### Impressão sem tela

A impressora USB, de rede ou serial não autentica uma pessoa. Um **Dashem Print
Bridge** local é o cliente autenticado, mantém o vínculo com tenant, unidade,
ponto de produção e impressora física, busca trabalhos destinados àquele ponto
e confirma impressão. O segredo é exibido uma única vez e armazenado somente
como hash no servidor. Ações humanas que originaram a comanda permanecem nos
eventos do pedido; não são atribuídas à impressora.

O modelo atual já possui `OperationalDevice` e destino de produção, mas o
protocolo seguro do Print Bridge ainda é um gate pendente. Até ele existir, uma
referência de configuração e um heartbeat com sessão gerencial **não equivalem
a uma impressora pronta para operação comercial**.

## Consequências

- o PIN nunca revela nem seleciona tenant, unidade ou caixa;
- revogar uma pessoa, um terminal POS, um TEF Bridge ou um Print Bridge são
  operações distintas;
- KDS com tela pode exigir PIN para ações humanas; uma impressora sem tela nunca
  exige PIN;
- provider/hardware não homologado permanece indisponível, ainda que o contrato
  interno de integração exista;
- a Gestão apresenta Clientes e Funcionários como cadastros separados de suas
  credenciais de acesso.
