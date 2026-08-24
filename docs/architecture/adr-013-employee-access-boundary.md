# ADR-013 — Funcionário não é credencial

Status: aceito no S17.2
Data: 24 de agosto de 2026

## Contexto

Nome, matrícula, lotação, cargo e contatos pertencem ao cadastro funcional do
tenant. E-mail de gestão, código de operação e PIN são meios de acesso. Criar os
dois registros no mesmo formulário impedia cadastrar um funcionário antes de
liberar acesso, reaproveitar a ficha e revogar uma credencial sem perder seus
dados administrativos.

## Decisão

- `Employee` é o registro canônico do funcionário dentro do tenant;
- a ficha possui matrícula, nome, CPF opcional, contatos, cargo, setor, admissão,
  lotação, endereço, contato de emergência, situação e observações;
- `OperationalCredential` referencia um `Employee`, uma membership e um usuário
  técnico interno, mantendo separados cadastro, autorização e autenticação;
- conceder PIN exige selecionar um funcionário ativo já cadastrado ou concluir
  sua ficha antes da concessão;
- atualização e inativação da ficha são auditadas; um funcionário inativo não
  pode iniciar nova sessão operacional;
- código de colaborador e PIN não substituem a matrícula funcional;
- o CPF completo não é exibido na listagem, apenas o final, reduzindo exposição
  desnecessária de dado pessoal.

## Consequências

- um funcionário pode existir sem acesso e receber uma credencial depois;
- revogar acesso não apaga ficha, histórico ou autoria de operações passadas;
- a Gestão passa a ter visões distintas de **Cadastro de funcionários** e
  **Acessos**;
- futuras integrações de folha, ponto ou RH podem referenciar `Employee` sem
  depender do provedor de autenticação.
