# ADR-012 — Identidade administrativa por e-mail e operação por PIN

Status: histórico; parcialmente substituído pelo ADR-024 em 25/08/2026
Data: 24 de agosto de 2026

## Contexto

O mesmo login não pode representar ao mesmo tempo o administrador contratual e
quem assumiu fisicamente um caixa, atendimento de salão ou turno operacional.
Administradores e gerentes precisam de identidade recuperável e forte no
Supabase Auth. Atendentes, caixas e supervisores precisam de troca rápida de
operador em um terminal já autorizado, sem e-mails fictícios ou contas
compartilhadas.

O acesso ao PDV continua sendo uma escolha explícita do usuário. A decisão
original permitia que um administrador ou gerente autenticado operasse com a
identidade de e-mail. O ADR-024 substitui essa parte: a sessão administrativa
pode autorizar e abrir a superfície do terminal, mas toda mutação operacional
humana exige que um colaborador assuma o ponto com código + PIN pessoal.

## Decisão

- `ADMIN` e `MANAGER` entram por e-mail no Supabase Auth e acessam a Gestão;
- `SUPERVISOR`, `CASHIER` e `OPERATOR` são identidades operacionais vinculadas a
  uma unidade, identificadas por código do colaborador e PIN;
- o antigo papel de tenant `AUDITOR` passa a ser `SUPERVISOR`; auditoria é uma
  trilha do sistema, não uma função oferecida ao cliente;
- um administrador ou gerente autoriza o terminal com sua sessão de gestão e
  abre sua superfície, sem que isso conceda autoria operacional;
- supervisor, caixa ou atendente assume a operação com código e PIN individual,
  sem encerrar a sessão administrativa que autorizou o terminal;
- a ativação emite token curto, assinado e limitado a tenant, unidade, terminal,
  membership e papel;
- o backend valida novamente tenant, unidade, membership, usuário, terminal e
  estado antes de aceitar a sessão operacional;
- PINs usam salt individual, PBKDF2-HMAC-SHA256 e pepper do servidor; o valor em
  texto aberto não é persistido nem retornado;
- cinco falhas consecutivas bloqueiam temporariamente a credencial;
- sair do turno remove somente a identidade operacional e retorna ao portão de
  PIN; não encerra silenciosamente a sessão administrativa que autorizou o
  dispositivo.

## Consequências

- cada ação no PDV, Mesas e futuros terminais de produção pode ser atribuída à
  pessoa que realmente a executou;
- operadores não precisam possuir e-mail nem acesso à Gestão;
- administrador e gerente não caem automaticamente no PDV após o login; se
  também atuarem na operação, usam credencial operacional própria;
- suspensão do membership ou do terminal invalida novas ativações;
- o terminal ainda depende de uma sessão administrativa confiável. Uma futura
  credencial própria de dispositivo poderá substituir essa autorização sem
  mudar o contrato de identidade operacional.
