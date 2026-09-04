# Responsividade — DASHEM POS — 04/09/2026

Escopo: Owner/Control, Gestão, entrada operacional, PDV, Mesas, KDS, login,
primeiro acesso e MFA. Alterações restritas à disposição e ao dimensionamento;
cores, famílias, tamanhos, pesos de fonte e anéis de foco existentes preservados.

## Ajustes

- Tabelas legadas do Owner, Financeiro SaaS, sortimentos, canais e BI usam os
  mesmos registros e ações em cartões abaixo de 768 px. Cabeçalhos continuam
  associados às células; rótulos móveis não são repetidos por leitores de tela.
- Grades de formulários e indicadores passam a uma coluna quando necessário.
  Campos, nomes extensos, identificadores e valores podem ocupar a largura
  disponível sem aumentar a largura da página.
- Gestão usa menu recolhível até 1023 px. O menu do Owner permite rolagem em
  telas baixas. Cabeçalhos e barras de ações acomodam quebras de linha.
- O PDV conserva a identificação do colaborador, a conferência gerencial e
  os controles de abertura de caixa autorizados em todos os tamanhos.
  Carrinho e barra inferior respeitam o espaço disponível e a área segura.
- Modais compartilhados são renderizados fora do contêiner da página, têm
  cabeçalho fixo e corpo rolável. Redimensionar a janela não anima sua altura.
  Janelas específicas de cadastro/cobrança também respeitam a altura dinâmica.

## Verificação

Comandos executados em `frontend`:

```powershell
npm test
npm run build
npm run test:e2e:responsive
```

- 95 testes de unidade/fronteira passaram. Nenhum teste foi removido ou
  flexibilizado. Contraste, foco, identidade operacional, caixa e carimbos UTC
  continuam cobertos pelas suítes existentes.
- Compilação TypeScript e bundle de produção concluídos.
- Auditoria de layout em Chromium: 62 cenários em 7 tamanhos, com 434
  verificações sem falhas. Abrange os 14 módulos da Gestão, áreas do Owner,
  abas de cliente e financeiro, cadastros, as quatro áreas do editor de contrato,
  cobrança, PIN, PDV, carrinho, pagamento, Mesas e KDS.
- Tamanhos: 320×568, 390×844, 768×1024, 1024×768, 1366×768, 1920×1080 e 844×390.
- A auditoria verifica largura da página, texto cortado em botões, limites de
  modais durante redimensionamento e erros de renderização. Capturas de tela
  foram inspecionadas para tabelas móveis, PDV, contrato e formulários.
- A comparação das classes de cores/tipografia antes e depois não encontrou
  alterações nesses tokens.

O comando usa componentes reais com fixtures sintéticas, incluindo nomes e
códigos longos e valores monetários. Ele não acessa a API publicada, não usa
credenciais reais e não altera cadastros ou vendas. Algumas listas secundárias
são exercitadas vazias. Esta é uma validação de layout, não substitui o aceite
operacional com dados persistidos, aparelhos físicos ou navegadores adicionais.

O runner inicia e encerra seu próprio servidor isolado. As instruções estão em
`frontend/e2e/responsive/README.md`; resultados JSON e PNGs ficam em
`.tmp/responsive-audit/`. A entrada de teste não integra o bundle de produção.

A validação descrita neste registro foi realizada localmente antes do envio
  das alterações ao GitHub.
