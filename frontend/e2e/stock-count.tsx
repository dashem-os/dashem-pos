/**
 * Bancada da contagem de estoque.
 *
 * Monta o `InventoryManager` real dentro do `PosProvider` real, contra o backend
 * real. Duas coisas ficam de fora, e só elas: a tela de login — o ambiente local
 * não tem projeto Supabase — e as permissões, que o bypass de desenvolvimento
 * não devolve. As permissões são fornecidas pelo roteiro de teste, interceptando
 * a resposta de `capabilities/effective` **no navegador da bancada**.
 *
 * Isso não altera permissão de produto nenhuma: o backend continua exigindo o
 * que exige, e um pedido sem autorização real continuaria sendo recusado por
 * ele. O que a interceptação faz é permitir que o componente renderize as ações
 * que aquele perfil veria, para exercitar preenchimento, recusa e preservação
 * dos dados. Não substitui o teste autenticado, e não homologa nada.
 */
import React from 'react'
import ReactDOM from 'react-dom/client'
import { PosProvider, usePos } from '../src/context/PosContext'
import { InventoryManager } from '../src/components/management/InventoryManager'
import { Toast } from '../src/components/common/Toast'
import '../src/index.css'

function Surface() {
  const { toast } = usePos()
  return <><Toast toast={toast} /><div className="p-6"><InventoryManager /></div></>
}

const params = new URLSearchParams(window.location.search)

ReactDOM.createRoot(document.getElementById('root')!).render(
  <PosProvider
    source="OPERATIONAL_SESSION"
    tenantId={params.get('tenant') || ''}
    storeId={params.get('store') || ''}
    operatorId={params.get('operator') || ''}
    operatorName="Conferente"
    tenantName="Bancada"
    storeName="Matriz"
  >
    <Surface />
  </PosProvider>,
)
