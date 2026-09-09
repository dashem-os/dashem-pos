# Homologação — duas estações sobre a última unidade

Data: 09/09/2026 · trilha: [sprints da experiência](../product/ui-ux-implementation-sprints.md) ·
evidência: [`evidence/hom-03-ultima-unidade/`](evidence/hom-03-ultima-unidade/) ·
roteiro: `frontend/e2e/presentation/hom03_ultima_unidade.cjs`.

Uma Coca-Cola na prateleira, dois caixas abertos lado a lado, duas pessoas
querendo a mesma peça. É onde overselling nasce: se as duas venderem, o lojista
prometeu mercadoria que não tem e vai descobrir no balcão, na frente do cliente.

A semeadura é a das duas estações que já existia, com um parâmetro novo:
`seed_two_station_authorization.py --saldo 1`. O cenário de autoridade continua
inteiro; muda só quantas unidades estão em disputa.

## O que aconteceu nas duas telas

| Momento | Estação 1 | Estação 2 |
|---|---|---|
| Põe no carrinho | 1 item, a unidade fica prometida | — |
| Tenta a mesma unidade | — | **recusada**: *"Não há mais 'Coca-Cola Lata' para vender agora: 1 unidade está em vendas abertas."* |
| Depois da recusa | — | a grade relê: o cartão passa a dizer **"Sem estoque"** |
| Fecha a venda | venda concluída | — |
| Tenta de novo | — | recusada de novo, e sem concluir venda nenhuma |

A recusa faz as três coisas que o balcão precisa: nomeia a mercadoria, diz que
não dá **agora**, e diz o porquê — está em venda aberta, não sumiu.

## O que o servidor diz

| Momento | Físico | Reservado | Disponível |
|---|---|---|---|
| Durante a disputa | 1 | **1** | **0** |
| Ao fim | 0 | 0 | 0 |

E as vendas: **uma** venda com o produto, **uma** fechada, situação `COMPLETED`.
Nenhuma reserva sobrou.

O que o cenário existe para não deixar passar — **saldo físico negativo** — não
aconteceu: a prateleira foi de 1 para 0, e não para −1.

> Sobre reservas: não há rota de listagem, e inventar uma para a travessia
> provaria uma leitura que o produto não oferece. O `reserved` do saldo é a
> soma das reservas ativas, e é por ele que se confere.

## O defeito que a disputa encontrou

Na primeira execução, a estação 2 mostrava três coisas ao mesmo tempo:

- o aviso: *"Não há mais 'Coca-Cola Lata' para vender agora"*;
- a linha da busca: *"Nada disponível agora · 1 un em vendas abertas"*;
- **o cartão do produto: "Última unidade"**.

O cartão já lia `available`, então não era erro de conta: era **dado velho**. A
inclusão bem-sucedida relia a prateleira — há um comentário no código
explicando por quê, desde a UX-06 — e **a recusa não relia**. Justamente o
caminho em que a tela está comprovadamente atrasada era o único que não
atualizava, e o cartão continuava convidando a operadora a clicar de novo.

Os dois caminhos de recusa passaram a reler: o bloqueio calculado nesta tela e a
recusa vinda do servidor. Depois da correção, cartão, linha e aviso dizem a
mesma coisa — `03-estacao-2-grade-relida.png`.

## Alcance desta evidência

Percorrido: duas estações reais, cada uma com o seu terminal autorizado e a sua
pessoa entrando por código e PIN, disputando a mesma unidade, com conferência no
servidor.

**Não** percorrido aqui: disputa com mais de duas estações, disputa em unidades
diferentes da mesma empresa, e disputa sobre mercadoria com reserva de canal
(pedido de delivery segurando estoque). Ficam nomeadas, não implícitas.

## Lacunas de homologação, depois desta

| Lacuna | Estado |
|---|---|
| Dois destinos nunca percorridos | fechada em 09/09/2026 |
| **Concorrência de duas estações pela última unidade** | **fechada em 09/09/2026** |
| Conceder e retirar autoridade de um operador | aberta — próxima |
| Catálogo volumoso não exercitado | aberta |
| Estado "em processamento" do TEF | aberta |
| Transação real com provedor | aberta, pendência separada |
| Vínculo de maquininha | aberta, pendência separada |
