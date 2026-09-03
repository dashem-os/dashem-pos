import React, { useEffect, useMemo, useState } from 'react'
import { Mail, Pencil, Phone, Plus, Search, ShoppingBag, UserRound, X } from 'lucide-react'
import { usePos } from '../../context/PosContext'
import * as api from '../../services/api'

const blank = { name: '', cpf_cnpj: '', phone: '', email: '' }

export function CustomerManager() {
  const { tenant, store, permissions } = usePos()
  const [customers, setCustomers] = useState<api.Customer[]>([])
  const [sales, setSales] = useState<api.Sale[]>([])
  const [query, setQuery] = useState('')
  const [editing, setEditing] = useState<api.Customer | null>(null)
  const [form, setForm] = useState(blank)
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const headers = useMemo<Record<string, string>>(
    () => tenant && store
      ? { 'X-Tenant-ID': tenant.id, 'X-Store-ID': store.id }
      : {} as Record<string, string>,
    [tenant, store],
  )
  const canManage = permissions.includes('customer.update')

  const load = async () => {
    if (!tenant || !store) return
    setError(null)
    try {
      const [people, history] = await Promise.all([api.fetchCustomers(headers), api.fetchSales(headers)])
      setCustomers(people); setSales(history)
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Falha ao carregar clientes.') }
  }
  useEffect(() => { void load() }, [tenant?.id, store?.id]) // eslint-disable-line react-hooks/exhaustive-deps

  const visible = useMemo(() => {
    const term = query.trim().toLocaleLowerCase('pt-BR')
    if (!term) return customers
    return customers.filter(item => `${item.name} ${item.cpf_cnpj || ''} ${item.phone || ''} ${item.email || ''}`.toLocaleLowerCase('pt-BR').includes(term))
  }, [customers, query])

  const startCreate = () => { setEditing(null); setForm(blank); setOpen(true) }
  const startEdit = (customer: api.Customer) => {
    setEditing(customer)
    setForm({ name: customer.name, cpf_cnpj: customer.cpf_cnpj || '', phone: customer.phone || '', email: customer.email || '' })
    setOpen(true)
  }
  const save = async (event: React.FormEvent) => {
    event.preventDefault(); setBusy(true); setError(null)
    try {
      const input = { name: form.name.trim(), cpf_cnpj: form.cpf_cnpj.trim() || undefined, phone: form.phone.trim() || undefined, email: form.email.trim() || undefined }
      if (editing) await api.updateCustomer(headers, editing.id, input)
      else await api.createCustomer(headers, input)
      setOpen(false); await load()
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Falha ao salvar cliente.') }
    finally { setBusy(false) }
  }

  const totalRevenue = (customerId: string) => sales.filter(sale => sale.customer_id === customerId && ['PAID', 'COMPLETED'].includes(sale.status)).reduce((sum, sale) => sum + Number(sale.net_total), 0)
  const purchaseCount = (customerId: string) => sales.filter(sale => sale.customer_id === customerId && sale.status !== 'CANCELED').length

  return <div className="space-y-5">
    <header className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end"><div><p className="text-xs font-black uppercase tracking-[.16em] text-dashem-red">Relacionamento</p><h1 className="mt-1 text-3xl font-black text-dashem-strong">Clientes</h1><p className="mt-2 text-sm text-dashem-muted">Cadastro, contato e histórico comercial no mesmo contexto do tenant.</p></div>{canManage && <button onClick={startCreate} className="flex h-11 items-center justify-center gap-2 rounded-xl bg-dashem-red px-5 text-sm font-black"><Plus className="h-4 w-4" />Novo cliente</button>}</header>
    <section className="grid gap-3 sm:grid-cols-3"><Metric label="Clientes cadastrados" value={String(customers.length)} /><Metric label="Com histórico" value={String(customers.filter(item => purchaseCount(item.id) > 0).length)} /><Metric label="Vendas identificadas" value={String(sales.filter(item => item.customer_id).length)} /></section>
    <div className="flex h-12 items-center rounded-xl border border-dashem-border bg-dashem-surface px-4"><Search className="h-4 w-4 text-dashem-muted" /><input value={query} onChange={event => setQuery(event.target.value)} placeholder="Buscar por nome, documento, telefone ou e-mail" className="h-full min-w-0 flex-1 bg-transparent px-3 text-sm font-bold outline-none" /></div>
    {error && <p className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm font-bold text-red-700">{error}</p>}
    <section className="overflow-hidden rounded-2xl border border-dashem-border bg-dashem-surface"><div className="overflow-x-auto"><table className="w-full min-w-[820px] text-left"><thead className="bg-dashem-surface-elevated text-[10px] font-black uppercase tracking-wider text-dashem-muted"><tr><th className="p-4">Cliente</th><th className="p-4">Contato</th><th className="p-4">Compras</th><th className="p-4">Relacionamento</th><th className="p-4" /></tr></thead><tbody className="divide-y divide-dashem-border">{visible.map(customer => <tr key={customer.id}><td className="p-4"><div className="flex items-center gap-3"><div className="flex h-10 w-10 items-center justify-center rounded-xl bg-dashem-bg text-dashem-red"><UserRound className="h-5 w-5" /></div><div><p className="font-black text-dashem-strong">{customer.name}</p><p className="mt-1 font-mono text-[11px] text-dashem-muted">{customer.cpf_cnpj || 'Documento não informado'}</p></div></div></td><td className="p-4 text-xs text-dashem-muted"><p className="flex items-center gap-2"><Phone className="h-3.5 w-3.5" />{customer.phone || 'Não informado'}</p><p className="mt-2 flex items-center gap-2"><Mail className="h-3.5 w-3.5" />{customer.email || 'Não informado'}</p></td><td className="p-4"><p className="font-black text-dashem-strong">{purchaseCount(customer.id)} vendas</p><p className="mt-1 text-xs text-emerald-700">{totalRevenue(customer.id).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })}</p></td><td className="p-4 text-xs text-dashem-muted">Desde {new Date(customer.created_at).toLocaleDateString('pt-BR')}</td><td className="p-4">{canManage && <button onClick={() => startEdit(customer)} className="flex h-9 items-center gap-2 rounded-lg border border-dashem-border px-3 text-xs font-black text-dashem-muted"><Pencil className="h-3.5 w-3.5" />Editar</button>}</td></tr>)}</tbody></table></div>{visible.length === 0 && <div className="p-12 text-center"><ShoppingBag className="mx-auto h-9 w-9 text-slate-600" /><p className="mt-3 text-sm font-bold text-dashem-muted">Nenhum cliente encontrado.</p></div>}</section>
    {open && <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-4"><section className="w-full max-w-xl rounded-3xl border border-dashem-border bg-dashem-surface p-6"><div className="flex items-center justify-between"><div><p className="text-xs font-black uppercase tracking-wider text-dashem-red">Ficha do cliente</p><h2 className="mt-1 text-xl font-black">{editing ? 'Editar cadastro' : 'Novo cliente'}</h2></div><button onClick={() => setOpen(false)} className="flex h-10 w-10 items-center justify-center rounded-xl border border-dashem-border"><X className="h-5 w-5" /></button></div><form onSubmit={save} className="mt-6 grid gap-4 sm:grid-cols-2"><Field label="Nome completo / razão social" value={form.name} onChange={name => setForm({ ...form, name })} wide /><Field label="CPF / CNPJ" value={form.cpf_cnpj} onChange={cpf_cnpj => setForm({ ...form, cpf_cnpj })} /><Field label="Telefone" value={form.phone} onChange={phone => setForm({ ...form, phone })} /><Field label="E-mail" type="email" value={form.email} onChange={email => setForm({ ...form, email })} wide /><button disabled={busy || form.name.trim().length < 2} className="h-12 rounded-xl bg-dashem-red font-black disabled:opacity-40 sm:col-span-2">{busy ? 'Salvando...' : 'Salvar ficha do cliente'}</button></form></section></div>}
  </div>
}

function Metric({ label, value }: { label: string; value: string }) { return <div className="rounded-2xl border border-dashem-border bg-dashem-surface p-4"><p className="text-xs font-black uppercase text-dashem-muted">{label}</p><p className="mt-2 text-2xl font-black text-dashem-strong">{value}</p></div> }
function Field({ label, value, onChange, type = 'text', wide = false }: { label: string; value: string; onChange: (value: string) => void; type?: string; wide?: boolean }) { return <label className={`text-xs font-black uppercase text-dashem-muted ${wide ? 'sm:col-span-2' : ''}`}>{label}<input required={label.startsWith('Nome')} type={type} value={value} onChange={event => onChange(event.target.value)} className="mt-2 h-11 w-full rounded-xl border border-dashem-border bg-dashem-bg px-3 text-sm font-bold normal-case text-dashem-strong outline-none focus:border-dashem-red" /></label> }
