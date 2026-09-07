/**
 * Bancada para exercitar a recusa de movimentação na tela de verdade.
 *
 * Monta o `CatalogManager` real dentro do `PosProvider` real, contra o backend
 * real. O que ela dispensa é só a tela de login — o ambiente local não tem
 * projeto Supabase configurado, e entrar pela porta da frente exigiria
 * credencial que ainda não temos. Nada do comportamento sob teste é simulado:
 * a requisição sai, o servidor recusa, e quem decide o que a tela faz com a
 * recusa é o mesmo código que roda em produção.
 *
 * Não é o gate de operação. Aquele exige uma pessoa representativa do cliente
 * percorrendo o ciclo pela navegação completa, sem dica do desenvolvedor.
 */
import React from 'react'
import ReactDOM from 'react-dom/client'
import { PosProvider, usePos } from '../src/context/PosContext'
import { CatalogManager } from '../src/components/management/CatalogManager'
import { Toast } from '../src/components/common/Toast'
import '../src/index.css'

/** O aviso vive na casca, como em `ManageShell`; sem ele a recusa não teria onde aparecer. */
function Surface() {
  const { toast } = usePos()
  return <><Toast toast={toast} /><div className="p-6"><CatalogManager /></div></>
}

const params = new URLSearchParams(window.location.search)
const tenantId = params.get('tenant') || ''
const storeId = params.get('store') || ''
const operatorId = params.get('operator') || ''

ReactDOM.createRoot(document.getElementById('root')!).render(
  <PosProvider
    source="OPERATIONAL_SESSION"
    tenantId={tenantId}
    storeId={storeId}
    operatorId={operatorId}
    operatorName="Gerente de loja"
    tenantName="Bancada"
    storeName="Matriz"
  >
    <Surface />
  </PosProvider>,
)
