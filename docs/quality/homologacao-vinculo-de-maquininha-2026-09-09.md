# Homologação — vincular a maquininha ao caixa, pela tela

Data: 09/09/2026 · trilha: [sprints da experiência](../product/ui-ux-implementation-sprints.md) ·
evidência: [`evidence/hom-08-vinculo-de-maquininha/`](evidence/hom-08-vinculo-de-maquininha/) ·
roteiro: `frontend/e2e/presentation/hom08_vinculo_de_maquininha.cjs` ·
cenário: `backend/tests/support/seed_tef_awaiting_bridge.py --sem-vinculo`.

A [hom02](homologacao-destinos-nunca-percorridos-2026-09-09.md) percorreu
configuração de provedor e pareamento de bridge, e o cabeçalho dela chegou a
dizer que percorria o vínculo de maquininha também. **Não percorria** — foi
imprecisão minha, corrigida, e o vínculo ficou como pendência separada. É esta
travessia.

O cenário é semeado **sem vínculo** de propósito: quem tem de criá-lo é a
gestora, clicando.

## A pergunta que dá sentido à jornada

Vincular é configuração, e configuração é fácil de fingir. A pergunta que
interessa não é "o vínculo aparece na lista?", e sim:

> pausar um vínculo tira a maquininha do caixa **de verdade**, ou só muda um
> rótulo na Gestão?

Por isso a travessia abre **duas telas ao mesmo tempo** — a Gestão e o salão — e
mede na segunda o que se faz na primeira.

## A jornada, como foi percorrida

| Etapa | O que aconteceu | Evidência |
|---|---|---|
| Antes de tudo | *"Nenhuma maquininha vinculada nesta unidade."* | `01-sem-vinculo-a-tela-diz-o-que-falta.png` |
| Vincular | caixa, POS, provedor, modo **TEF Bridge** e terminal | `02-dialogo-de-vinculo-preenchido.png` |
| O seletor de terminal | oferece **só** o bridge pareado com aquele caixa e provedor: `BRIDGE-… · Online` | idem |
| Criado | a listagem mostra o POS, o caixa, o provedor e **TEF Bridge** | `03-vinculo-criado-e-listado.png` |
| **No salão** | a conta passa a oferecer **Crédito via TEF** | `04-balcao-com-tef-disponivel.png` |
| Pausar com motivo de 2 letras | não passa: o diálogo continua aberto e o vínculo segue **ACTIVE** | — |
| Pausar com motivo | *"Maquininha recolhida para manutenção pela adquirente"* fica à vista na listagem | `05-vinculo-pausado-com-motivo.png` |
| **No salão** | o TEF **some** do seletor, e a tela diz que não está disponível | `06-balcao-sem-tef-com-o-vinculo-pausado.png` |
| Reativar com motivo | volta a **ACTIVE** | — |
| **No salão** | o TEF volta | `07-balcao-recupera-o-tef.png` |

No servidor, os três momentos: `ACTIVE` → `PAUSED` com o motivo gravado →
`ACTIVE`, sempre o mesmo vínculo, sempre em modo `TEF_BRIDGE` e apontando para o
terminal escolhido.

## O motivo, e por que a asserção mudou

A primeira versão desta travessia cobrava a **frase** do aplicativo ao pausar com
motivo curto — *"Informe um motivo com pelo menos três caracteres"* — e reprovou:
quem barra ali é a validação do próprio campo (`minLength`), antes de o
aplicativo dizer qualquer coisa.

A asserção passou a cobrar o **efeito**: o diálogo continua aberto e o vínculo
segue ativo no servidor. Isso é verdade seja qual for a camada que barra, e é o
que importa — a versão anterior media a implementação, não o resultado.

## O controle

Fazendo o balcão ignorar a situação do vínculo — `bindings.find` sem o
`status === 'ACTIVE'` — a travessia reprova **exatamente nas duas asserções que
sustentam a jornada**:

> com o vínculo pausado, o balcão continuou oferecendo cobrança por TEF
> o balcão deveria dizer que o TEF não está disponível

Sem esse controle, "pausar funciona" seria uma frase sobre a Gestão. Com ele, é
uma frase sobre o caixa.

## Alcance desta evidência

Percorrido: criação do vínculo pela tela, com o seletor de terminal restrito ao
bridge pareado; pausa recusada por motivo insuficiente; pausa e reativação com
motivo, refletidas no servidor e **no balcão**.

**Não** percorrido, e nomeado:

- **maquininha física** — não existe nenhuma; o terminal é declarado online pelo
  heartbeat que o roteiro de cenário envia, no papel do bridge;
- **transação real com provedor** — continua pendência separada, e nada aqui
  deve ser lido como se fosse;
- **revogar** o vínculo, que é definitivo e impede reativação: o botão existe e
  não foi percorrido;
- **modo SmartPOS**, que a própria tela declara como somente cadastro;
- pausar **durante** uma cobrança em voo — está no roteiro da homologação real
  como buraco de cobertura;
- mais de um vínculo na mesma unidade, e vínculo em unidades diferentes.

## Onde isso deixa a integração

O vínculo sai da lista de pendências separadas. O que resta para a homologação
real está levantado em
[preparação da homologação com provedor](preparacao-homologacao-provedor-2026-09-09.md),
que nomeia inclusive um bloqueador achado ao escrever este documento: **o bridge
não tem rota para saber que existe uma cobrança esperando por ele**.

| Lacuna | Estado |
|---|---|
| **Vínculo de maquininha percorrido pela tela** | **fechada em 09/09/2026** |
| Transação real com provedor | aberta, pendência separada |
| Entrega de comando ao bridge | **aberta, achada aqui** — bloqueia a homologação real |
