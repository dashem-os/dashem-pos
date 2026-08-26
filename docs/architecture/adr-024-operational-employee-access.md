# ADR-024 — Acesso operacional do colaborador e autoria de jornada

Status: aceito como correção canônica; Gate B reaberto em 25/08/2026.

Substitui as partes dos ADRs 012, 013, 014 e 021 que tratavam o PIN isolado
como identidade operacional, permitiam à Gestão definir o PIN definitivo ou
permitiam que a identidade gerencial substituísse a assunção de uma operação.

## Contexto

O Dashem já separa a identidade administrativa por e-mail da credencial de um
terminal. A implementação, porém, manteve decisões incompatíveis entre si:

- o login público passou a anunciar `/operate`, embora o ADR-014 o proíba;
- depois de código e PIN válidos, o POS voltou a procurar tenant, unidade e
  caixa pela identidade da pessoa;
- a Gestão passou a criar e redefinir o PIN definitivo do colaborador;
- testes estáticos validaram textos e componentes isolados, mas não a jornada
  real no navegador;
- a identidade gerencial ainda podia chegar à operação sem uma sessão que
  identificasse quem assumiu aquele ponto de trabalho.

Essas divergências preservam partes técnicas corretas, mas rompem a cadeia de
autoridade que deve ligar pessoa, infraestrutura, turno e operação.

## Decisão

### 1. Nome e composição

O conceito canônico é **Acesso Operacional do Colaborador**. Ele não é sinônimo
de PIN e possui elementos distintos:

1. `Employee`: pessoa e ficha funcional;
2. código individual: identificação operacional estável e única no tenant;
3. PIN pessoal: segredo de autenticação definido pelo próprio colaborador;
4. função e permissions: autorização concedida pela Gestão;
5. unidades autorizadas: escopo funcional concedido pela Gestão;
6. terminal autorizado: tenant, unidade, caixa e dispositivo assinados pelo
   servidor;
7. `OperationalSession`: autoridade persistida que registra quem assumiu o
   terminal, em qual função, contexto e intervalo.

Função, unidade e terminal não fazem parte do segredo digitado. Eles são
autoridades server-side que devem concordar antes de uma sessão ser criada.

### 2. Cadeia de autoridade

```text
Tenant
  → unidade
    → terminal POS autorizado
      → colaborador autorizado na unidade
        → código + PIN pessoal
          → sessão operacional
            → turno e operações auditáveis
```

O colaborador nunca escolhe nem envia tenant, unidade, caixa ou dispositivo. O
backend deriva esse contexto da autorização do terminal, valida o vínculo do
colaborador e emite uma sessão restrita à interseção dessas autoridades.

### 3. Fronteiras das superfícies

- `/login` é exclusivamente administrativo, por e-mail/OAuth, e não anuncia nem
  navega para `/operate`;
- `/manage` administra organização, equipe, autorizações e infraestrutura;
- `/operate` é uma superfície dedicada de terminal e só apresenta código + PIN
  quando existe autorização válida para aquele navegador;
- `/pos` aceita mutações humanas somente com `OperationalSession` válida;
- uma identidade administrativa pode autorizar o navegador e abrir a superfície
  do PDV, mas não substitui a assunção operacional;
- se um administrador ou gerente também trabalhar na operação, deve possuir
  `Employee`, função operacional e código + PIN próprios.

A interface de `/operate` deve ser visual e funcionalmente distinta do login
administrativo. Ela mostra o terminal e a unidade já resolvidos, recebe código e
PIN, oferece controles adequados ao toque e nunca enumera colaboradores.

### 4. Ciclo do PIN pessoal

- a Gestão cadastra ou seleciona o funcionário, concede função, permissions,
  unidades e código operacional;
- a Gestão emite uma ativação temporária, de uso único e com expiração curta;
- no primeiro acesso em terminal autorizado, o colaborador informa a ativação e
  cria e confirma o próprio PIN;
- somente salt, hash, parâmetros de derivação e versão são persistidos;
- o PIN nunca é retornado, exibido, enviado por e-mail ou conhecido pela Gestão;
- esquecimento ou comprometimento revoga sessões e gera nova ativação; o gestor
  não escolhe o PIN substituto;
- bloqueio, rate limit e mensagens não revelam se código ou PIN estava correto.

### 5. Função, permissions e mudança de autoridade

A função exibida na Gestão é parte da autorização, não uma opção escolhida no
login operacional. A sessão registra a função e as permissions efetivas no
momento da assunção. Suspensão, troca de função, remoção de unidade ou mudança de
grants gira a versão da credencial e invalida sessões incompatíveis.

### 6. Autoria da jornada

Toda mutação operacional humana registra, direta ou indiretamente pela sessão:

- colaborador e credencial;
- função e permissions efetivas;
- sessão operacional e turno;
- tenant, unidade, caixa, POS e dispositivos relacionados;
- instante, ação, resultado e correlation/idempotency IDs aplicáveis;
- solicitante, aprovador e executor quando forem pessoas diferentes.

Venda, desconto, cancelamento, sangria, suprimento, mesa, comanda, produção,
pagamento, estorno e fechamento não podem aceitar autor informado pelo cliente.

## Máquina de estados canônica

```text
NAVEGADOR_SEM_AUTORIZAÇÃO
  → autenticação administrativa
  → autorização do terminal
  → TERMINAL_AUTORIZADO_SEM_OPERADOR
  → código + PIN pessoal
  → SESSÃO_OPERACIONAL_ATIVA
  → operação
  → encerramento/expiração/revogação
  → TERMINAL_AUTORIZADO_SEM_OPERADOR
```

Revogar ou expirar o terminal retorna a
`NAVEGADOR_SEM_AUTORIZAÇÃO`. Nenhum estado posterior volta a consultar ou
oferecer seletor de tenant, unidade, caixa, dispositivo ou função.

## Critérios de aceite inegociáveis

1. login administrativo válido encaminha o gestor para `/manage`;
2. `/login` não contém atalho operacional;
3. `/operate` sem terminal válido não oferece código ou PIN;
4. autorização do terminal fixa tenant, unidade, caixa e POS no servidor;
5. o gestor nunca define, visualiza ou redefine o PIN definitivo;
6. o colaborador ativa o acesso e define o próprio PIN;
7. código + PIN válidos criam uma sessão operacional no mesmo contexto do
   terminal, sem seleção organizacional posterior;
8. `/pos` abre diretamente no contexto assinado e recusa contexto divergente;
9. sair do turno preserva a autorização física e remove apenas a pessoa;
10. expiração, revogação, mudança funcional e troca de escopo interrompem a
    sessão no servidor, mesmo com JWT ainda válido;
11. operador não acessa a Gestão; gestor sem sessão operacional não executa
    mutações humanas do POS;
12. a jornada completa possui teste E2E em navegador e evidência no deploy;
13. contraste, foco, teclado, toque, loading, erro e bloqueio passam por aceite
    visual e de acessibilidade;
14. CI verde sem a jornada E2E não fecha o Gate B.

## Consequências

- o Gate B volta a `REOPENED` até backend, frontend, E2E e deploy obedecerem a
  este contrato;
- Gates C e D preservam sua implementação, mas ficam bloqueados para aceitação
  operacional enquanto o Gate B estiver aberto;
- os formulários atuais de criação/redefinição de PIN pela Gestão são dívida de
  segurança e produto;
- o `OperationalContextGate` genérico não pode participar de uma sessão PIN;
- testes que exigem “Entrar como operador” no login público protegem uma
  regressão e devem ser substituídos;
- o piloto comercial permanece `NO-GO`.
