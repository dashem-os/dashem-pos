# ADR-021 — Gate B: autoridade operacional persistida e revogável

Status: aceito no Gate B, em 24/08/2026.

## Contexto

Assinar um JWT prova que o Dashem o emitiu, mas não basta para provar que o
turno e o terminal continuam autorizados agora. Sem uma autoridade persistida,
pausar e reativar um dispositivo, redefinir um PIN ou reativar um vínculo poderia
fazer uma credencial antiga voltar a ser aceita.

## Decisão

Uma entrada por PIN exige simultaneamente três autoridades independentes:

1. `OperationalDevice` POS ativo, ligado a uma unidade e a um caixa, com uma
   autorização gerencial vigente e versionada;
2. `OperationalCredential` ativa, ligada a um funcionário e membership ativos,
   também com versão de sessão;
3. `OperationalSession` persistida, ativa, não expirada e ligada exatamente à
   pessoa, credencial, terminal, unidade e caixa contidos no token.

O backend revalida as três autoridades sob o contexto RLS em toda requisição
operacional. O token não escolhe nem amplia escopo: apenas referencia registros
que continuam válidos no servidor.

Reautorizar, pausar, revogar ou reativar o terminal gira sua versão e encerra os
turnos ativos. Alterar o vínculo funcional, suspender o membership ou redefinir
o PIN gira a versão da credencial e revoga suas sessões. Sair do turno persiste
o encerramento antes de remover o token do navegador.

Gestores autenticados por e-mail continuam podendo abrir o PDV sem um segundo
login. Essa sessão preserva a autoria gerencial e não se apresenta como um turno
PIN. TEF Bridge, Print Bridge e KDS mantêm identidades de dispositivo próprias,
conforme o ADR-019.

## Critérios de aceite fixos

1. administrador ou gerente autenticado por e-mail acessa o PDV sem novo login;
2. código e PIN somente são trocados em POS ativo e previamente autorizado;
3. PIN nunca recebe seletor público de tenant, unidade ou caixa;
4. pessoa, turno, terminal POS, TEF Bridge e Print Bridge são revogáveis de forma
   independente;
5. pausa, revogação, reativação ou reautorização de terminal invalida tokens
   anteriores no servidor;
6. PIN redefinido, funcionário inativo ou membership suspenso/revogado invalida
   o turno existente no servidor;
7. turno encerrado ou expirado não volta a operar por reutilização do JWT;
8. eventos de entrada e saída registram pessoa, sessão, dispositivo, unidade e
   caixa sem aceitar autoria declarada pelo cliente;
9. testes negativos cobrem ausência de terminal, versões antigas, revogação,
   troca de escopo e reutilização após encerramento;
10. migration, rollback, testes backend, typecheck/build frontend e verificação
    de drift Alembic permanecem verdes.

## Consequências

- `sessionStorage` e `localStorage` são apenas transporte; a autoridade reside no
  banco e pode ser cortada imediatamente;
- reativar um terminal não restaura sua autorização anterior: o gestor deve
  pareá-lo novamente;
- as sessões persistidas passam a ser a base para duração de turno e métricas de
  horas trabalhadas, sem inferir jornada apenas por vendas;
- o Gate B não declara TEF ou impressão comercialmente homologados.
