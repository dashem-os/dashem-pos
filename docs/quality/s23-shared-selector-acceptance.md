# S23 — seleção compartilhada: implementação e aceite

O estado anterior "entregue com entrega aberta" não satisfazia o gate integral.
O seletor de mesa usava produtos herdados de COUNTER/TAKEAWAY, embora o comando
de pedido corretamente verificasse a publicação da jornada no backend.

## Implementação

- ProductSelectionProvider fornece dados, escopo, permissão e comando explícitos.
- ProductSelector reúne a mesma busca, grade com categorias/fotos e vitrine.
- Balcão conserva venda condicionada a caixa aberto; mesa não herda essa condição.
- Mesa consulta todas as páginas TABLE/FOOD_SERVICE, sem recorrer ao catálogo mestre.
- Destino permanece no cabeçalho da janela, com quantidade por toque.
- Repetição após resposta incerta mantém a chave do lançamento; uma confirmação
  bem-sucedida não é refeita quando apenas a atualização do resumo falha.
- Falha de carregamento é distinta de cardápio vazio.

## Limites do aceite

Validação local: 102 testes frontend; build de produção; 7 verificações do
seletor de mesa com resposta perdida e mesma chave de retry; 42 verificações
de regressão responsiva do recorte PDV, incluindo busca e caixa fechado.

Testes de interface usam fixtures isoladas, não vendas reais. Ainda é necessário
aceite em homologação pelo operador. Esta integração não certifica periféricos,
SmartPOS, expiração de sessão ou todos os gates históricos de S23/S24.

Incoerências históricas de outras sprints não foram reclassificadas nesta entrega.
A deduplicação entre faixas foi substituída explicitamente por posições estáveis.
