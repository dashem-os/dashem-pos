# Etapa 2 — correção visual e operacional das três superfícies

Capturas de uma travessia real, no mesmo tamanho (1660 × 860), com o conteúdo do
`Tenant de Homologação`. Elas existem porque build e medida de geometria não
enxergam a tela: o que reprovou a versão anterior foi olhar.

## O que reprovou, e onde está corrigido

| Reprovação | Onde estava | O que mudou |
|---|---|---|
| Palavra partida no meio: `PRODUT O`, `ATIV O` | `body { overflow-wrap: anywhere }` deixava qualquer coluna encolher até um caractere | `break-word`: a coluna nunca fica menor que a palavra. Tabela larga rola no próprio container |
| `10 / 0 un` | Coluna "Atual / mínimo" | "Em estoque" com valor e unidade, e o mínimo dito por extenso — inclusive **"Sem mínimo definido"**, que não é zero |
| Cinco botões iguais por linha | Produtos, Estoque e Sortimentos | Ações diárias visíveis; raras num menu **⋯**: excluir, arquivar, acesso rápido, ajuste técnico |
| Explicação técnica no caminho de todo dia | Faixa 1‑2‑3, "acervo deste tenant", "produto é o cadastro", "não consome a sua cota" | Aparece sozinha quando ainda não há nada cadastrado; depois disso fica a um clique |
| `PURCHASE`, `ADJUSTMENT` no histórico | "Movimentações recentes" | **Entrada**, **Perda**, **Conferência**, **Devolução**, **Venda**, com sinal e unidade |
| Recusa do servidor sumia com o aviso flutuante | Formulário de movimentação | A recusa fica no formulário, com o que a pessoa digitou |
| `5,0000` num campo de gente | Estoque mínimo | `5` |
| Saldo ainda não lido exibido como `0 UN` | Modal de contagem | "Lendo o saldo registrado…", e o botão só habilita quando o saldo chega |

## As capturas

| # | Arquivo | O que mostra |
|---|---|---|
| 1 | `01-produtos-lista.png` | Lista com nomes longos reais, estoque rotulado e serviço que não controla estoque |
| 2 | `02-produtos-mais-acoes.png` | Menu de ações raras aberto, sem recorte |
| 3 | `03-produtos-editar-preenchido.png` | Formulário preenchido; inclui o aviso real de armazenamento de imagem indisponível neste ambiente |
| 4 | `04-estoque-lista.png` | Colunas "Em estoque", "Mínimo desejado" e "Situação" com os quatro estados |
| 5 | `05-estoque-entrada-preenchida.png` | Entrada preenchida antes de confirmar |
| 6 | `06-estoque-entrada-concluida.png` | Depois da entrada aceita |
| 7 | `07-estoque-erro-recusa-do-servidor.png` | **Erro real**: perda de 999 com 27 na prateleira. A recusa é do servidor e fica na tela |
| 8 | `08-estoque-contagem-com-diferenca.png` | Contagem com saldo lido e diferença calculada à vista |
| 9 | `09-estoque-depois-das-acoes.png` | Saldo e situação depois da conferência |
| 10 | `10-estoque-historico-legivel.png` | Histórico em português: "Conferência +4 UN", "Entrada +24 UN" |
| 11 | `11-sortimentos-lista.png` | "Onde é vendido", "Ainda não publicado" e a pilha de ações reorganizada |

## Como as capturas foram feitas, sem maquiagem

* banco **local**, criado do zero e migrado até `084`. **Nada foi escrito em
  produção**;
* conteúdo semeado por `backend/tests/support/seed_presentation_walkthrough.py`
  com o acervo real do tenant de homologação — Coca‑Cola Lata, Coca‑Cola Sem
  Açucar 600ml, Hambúrguer Artesanal Bacon — lido em modo somente leitura, mais
  os dois nomes mais longos que existem no acervo do sistema, uma mercadoria
  zerada e um serviço;
* API e frontend reais, com permissões reais de `TENANT_OWNER`. A sessão de
  gestão é escrita no armazenamento do navegador com um token assinado pelo
  segredo de teste: **nenhum código de produto foi alterado para autenticar**;
* roteiro em `frontend/e2e/presentation/walkthrough.cjs`, repetível.

**Isto não declara o portão de apresentação aprovado.** Aprovar é sua decisão,
olhando estas telas. O portão de operação continua pendente: ele exige o ciclo
completo pela navegação real, com pessoa representativa do cliente.
