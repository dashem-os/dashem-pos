/**
 * Bancada da caixa de entrada de canais (S10.1, passo 3).
 *
 * Monta o `ChannelHubWorkspace` real dentro do `PosProvider` real, contra o
 * backend real, como a bancada da contagem de estoque. Ficam de fora a tela de
 * login e as permissões, que o bypass de desenvolvimento não devolve: o roteiro
 * as fornece interceptando `capabilities/effective` no navegador da bancada.
 *
 * O backend continua exigindo o que exige. Isto não substitui a travessia
 * autenticada do aplicativo, e não homologa nada.
 */
import React from 'react'
import ReactDOM from 'react-dom/client'
import { PosProvider, usePos } from '../src/context/PosContext'
import { ChannelHubWorkspace } from '../src/components/management/ChannelHubWorkspace'
import { Toast } from '../src/components/common/Toast'
import '../src/index.css'

function Surface() {
  const { toast } = usePos()
  return <><Toast toast={toast} /><div className="p-3 sm:p-6"><ChannelHubWorkspace /></div></>
}

const params = new URLSearchParams(window.location.search)

ReactDOM.createRoot(document.getElementById('root')!).render(
  <PosProvider
    source="OPERATIONAL_SESSION"
    tenantId={params.get('tenant') || ''}
    storeId={params.get('store') || ''}
    operatorId={params.get('operator') || ''}
    operatorName="Gestora"
    tenantName="Bancada"
    storeName="Matriz"
  >
    <Surface />
  </PosProvider>,
)
