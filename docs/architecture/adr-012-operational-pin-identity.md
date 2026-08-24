# ADR-012 — Identidade administrativa por e-mail e operação por PIN

Status: aceito no S17.1  
Data: 23 de agosto de 2026

## Contexto

O mesmo login não pode representar ao mesmo tempo o administrador contratual e
quem assumiu fisicamente um caixa, atendimento de salão ou turno operacional.
Administradores e gerentes precisam de identidade recuperável e forte no
Supabase Auth. Atendentes, caixas e supervisores precisam de troca rápida de
operador em um terminal já autorizado, sem e-mails fictícios ou contas
compartilhadas.

Também não é aceitável inferir que o usuário administrativo deseja entrar no
PDV apenas porque possui acesso ao tenant. A Gestão e a operação possuem
fronteiras de autenticação diferentes.

## Decisão

- `ADMIN` e `MANAGER` entram por e-mail no Supabase Auth e acessam a Gestão;
- `SUPERVISOR`, `CASHIER` e `OPERATOR` são identidades operacionais vinculadas a
  uma unidade, identificadas por código do colaborador e PIN;
- o antigo papel de tenant `AUDITOR` passa a ser `SUPERVISOR`; auditoria é uma
  trilha do sistema, não uma função oferecida ao cliente;
- um administrador ou gerente autoriza o terminal com sua sessão de gestão;
- ao abrir PDV ou Mesas, a pessoa que trabalhará no turno assume a operação com
  código e PIN individual;
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
- administrador e gerente não caem automaticamente no PDV após o login;
- suspensão do membership ou do terminal invalida novas ativações;
- o terminal ainda depende de uma sessão administrativa confiável. Uma futura
  credencial própria de dispositivo poderá substituir essa autorização sem
  mudar o contrato de identidade operacional.

