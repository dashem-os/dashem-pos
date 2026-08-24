import React, { useEffect, useMemo, useState } from 'react'
import { FolderTree, Layers3, Pencil, Plus, Search, Trash2 } from 'lucide-react'
import { usePos } from '../../context/PosContext'
import { Modal } from '../common/Modal'
import * as api from '../../services/api'

export function CategoryManager() {
  const { tenant, store, products, permissions, showToast } = usePos()
  const [categories, setCategories] = useState<api.Category[]>([])
  const [search, setSearch] = useState('')
  const [editing, setEditing] = useState<api.Category | null>(null)
  const [dialog, setDialog] = useState(false)
  const [busy, setBusy] = useState(false)
  const [form, setForm] = useState({ name: '', slug: '', parent_id: '' })
  const headers = useMemo<Record<string, string>>(() => tenant && store ? { 'X-Tenant-ID': tenant.id, 'X-Store-ID': store.id } : {} as Record<string, string>, [tenant, store])
  const canEdit = permissions.includes('catalog.update')
  const load = () => api.fetchCategories(headers).then(setCategories).catch(() => setCategories([]))
  useEffect(() => { if (tenant && store) void load() }, [tenant?.id, store?.id])

  const open = (category?: api.Category) => {
    setEditing(category || null)
    setForm(category ? { name: category.name, slug: category.slug, parent_id: category.parent_id || '' } : { name: '', slug: '', parent_id: '' })
    setDialog(true)
  }
  const save = async (event: React.FormEvent) => {
    event.preventDefault(); setBusy(true)
    try {
      if (editing) await api.updateCategory(headers, editing.id, { name: form.name, slug: form.slug, parent_id: form.parent_id || undefined })
      else await api.createCategory(headers, form.name, form.slug)
      setDialog(false); showToast('success', editing ? 'Categoria atualizada.' : 'Categoria cadastrada.'); await load()
    } catch (reason) { showToast('error', reason instanceof Error ? reason.message : 'Falha ao salvar categoria.') }
    finally { setBusy(false) }
  }
  const archive = async (category: api.Category) => {
    if (!window.confirm(`Arquivar a categoria ${category.name}?`)) return
    setBusy(true)
    try { await api.archiveCategory(headers, category.id); showToast('success', 'Categoria arquivada.'); await load() }
    catch (reason) { showToast('error', reason instanceof Error ? reason.message : 'Falha ao arquivar categoria.') }
    finally { setBusy(false) }
  }
  const filtered = categories.filter((item) => item.name.toLocaleLowerCase('pt-BR').includes(search.toLocaleLowerCase('pt-BR')))
  return <div className="space-y-6"><section className="flex flex-col justify-between gap-5 rounded-3xl border border-dashem-border bg-dashem-surface p-6 lg:flex-row lg:items-end"><div><p className="text-[11px] font-black uppercase tracking-[.18em] text-violet-400">Organização do catálogo</p><h1 className="mt-2 text-3xl font-black text-white">Categorias e grupos</h1><p className="mt-2 max-w-2xl text-sm leading-6 text-dashem-muted">Estruture a navegação do PDV sem depender da ordem dos produtos ou de nomes implícitos.</p></div>{canEdit && <button onClick={() => open()} className="flex h-11 items-center justify-center gap-2 rounded-xl bg-dashem-red px-5 text-xs font-black text-white"><Plus className="h-4 w-4" />Nova categoria</button>}</section><div className="relative"><Search className="absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-dashem-muted" /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Buscar categoria..." className="h-12 w-full rounded-xl border border-dashem-border bg-dashem-surface pl-11 pr-4 text-sm text-white outline-none focus:border-violet-600" /></div><section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{filtered.map((category) => { const count = products.filter((product) => product.category_id === category.id).length; const parent = categories.find((item) => item.id === category.parent_id); return <article key={category.id} className="rounded-2xl border border-dashem-border bg-dashem-surface p-5"><div className="flex items-start justify-between"><div className="flex h-10 w-10 items-center justify-center rounded-xl bg-violet-950/60 text-violet-300"><FolderTree className="h-5 w-5" /></div><span className="rounded-full bg-dashem-bg px-2 py-1 text-[10px] font-black text-dashem-muted">{count} itens</span></div><h3 className="mt-4 font-black text-white">{category.name}</h3><p className="mt-1 text-xs text-dashem-muted">{parent ? `${parent.name} / ` : ''}{category.slug}</p>{canEdit && <div className="mt-4 flex gap-2"><button onClick={() => open(category)} className="rounded-lg border border-dashem-border px-3 py-2 text-[11px] font-black text-slate-300"><Pencil className="mr-1 inline h-3.5 w-3.5" />Editar</button><button disabled={count > 0 || busy} title={count > 0 ? 'Mova os produtos antes de arquivar' : undefined} onClick={() => void archive(category)} className="rounded-lg px-3 py-2 text-[11px] font-black text-red-300 disabled:opacity-30"><Trash2 className="mr-1 inline h-3.5 w-3.5" />Arquivar</button></div>}</article> })}</section>{filtered.length === 0 && <div className="rounded-3xl border border-dashed border-dashem-border p-12 text-center"><Layers3 className="mx-auto h-10 w-10 text-slate-600" /><h3 className="mt-4 font-black text-white">Nenhuma categoria encontrada</h3><p className="mt-2 text-sm text-dashem-muted">Crie uma organização clara antes de cadastrar um catálogo extenso.</p></div>}<Modal isOpen={dialog} onClose={() => setDialog(false)} title={editing ? 'Editar categoria' : 'Nova categoria'} subtitle="O slug é a referência estável usada por integrações."><form onSubmit={save} className="space-y-4"><Field label="Nome" value={form.name} onChange={(value) => setForm({ ...form, name: value })} /><Field label="Slug" value={form.slug} onChange={(value) => setForm({ ...form, slug: value.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') })} /><label className="block text-xs font-black text-white">Grupo superior<select value={form.parent_id} onChange={(event) => setForm({ ...form, parent_id: event.target.value })} className="mt-2 h-11 w-full rounded-xl border border-dashem-border bg-dashem-surface-elevated px-3 text-sm text-white"><option value="">Categoria principal</option>{categories.filter((item) => item.id !== editing?.id).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><button disabled={busy || !form.name || !form.slug} className="h-12 w-full rounded-xl bg-dashem-red text-sm font-black text-white disabled:opacity-40">{busy ? 'Salvando...' : 'Salvar categoria'}</button></form></Modal></div>
}

function Field({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) { return <label className="block text-xs font-black text-white">{label}<input required value={value} onChange={(event) => onChange(event.target.value)} className="mt-2 h-11 w-full rounded-xl border border-dashem-border bg-dashem-surface-elevated px-3 text-sm text-white outline-none focus:border-dashem-red" /></label> }
