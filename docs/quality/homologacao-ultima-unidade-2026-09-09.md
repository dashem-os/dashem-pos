# Homologação — a segunda estação e a unidade já reservada

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

**O roteiro é sequencial.** Ele espera a estação 1 pôr a unidade no carrinho
antes de mandar a estação 2 tentar. Isso comprova uma coisa, e não a outra:

| Prova | Situação |
|---|---|
| Duas estações, e a segunda encontra a unidade **já reservada** | **demonstrada** aqui, pela tela |
| Duas inclusões **simultâneas** disputando a unidade antes de qualquer reserva concluir | **demonstrada** em 09/09/2026, por prova determinística no backend |

A segunda linha não era "provavelmente também funciona". O mecanismo existe —
`inventory_service` materializa a linha de saldo e a trava com `FOR UPDATE`
antes de reservar — mas **ler o código não é prova**, e nenhum teste do
repositório construía essa corrida.

### A corrida construída — fechada em 09/09/2026

`test_two_simultaneous_inclusions_race_for_the_last_unit_and_only_one_wins`, em
`backend/tests/test_inventory_reservation.py`, não torce pelo escalonador: ele
constrói a corrida. Uma unidade na prateleira, e:

1. a estação 1 abre transação, trava a linha do saldo com `FOR UPDATE` e
   **segura**;
2. a estação 2 dispara a inclusão **com a trava de pé**;
3. meio segundo depois, a prova exige que a estação 2 **ainda não tenha
   terminado** — se ela tivesse, não teria esperado por nada;
4. a estação 1 solta, promete a unidade e faz commit;
5. a estação 2 é recusada, e o relógio dela mostra a espera.

Ao fim: **uma** reserva ativa, disponível zero, e a prateleira em 1 — reservar
não move mercadoria.

**O controle é o que dá valor a isso.** Tirando o `with_for_update()` de
`_lock_balance_row`, a estação 2 terminou em **71ms** com a linha "travada" e
**prometeu a mesma unidade**: a prova reprova com *"a estação 2 concluiu com a
linha travada: a inclusão não serializa no banco"*. Ela passa com a trava e
reprova sem ela — que é a única forma de a medida falar sobre a regra.

**Também não** percorrido: disputa com mais de duas estações, disputa em
unidades diferentes da mesma empresa, e disputa sobre mercadoria com reserva de
canal (pedido de delivery segurando estoque). Ficam nomeadas, não implícitas.

## Lacunas de homologação, depois desta

| Lacuna | Estado |
|---|---|
| Dois destinos nunca percorridos | fechada em 09/09/2026 |
| Duas estações, a segunda achando a unidade já reservada | **fechada em 09/09/2026** |
| **Duas inclusões simultâneas disputando a última unidade** | **fechada em 09/09/2026**, com o controle que reprova sem a trava |
| Conceder e retirar autoridade de um operador | aberta — próxima |
| Catálogo volumoso não exercitado | aberta |
| Estado "em processamento" do TEF | aberta |
| Transação real com provedor | aberta, pendência separada |
| Vínculo de maquininha | aberta, pendência separada |
