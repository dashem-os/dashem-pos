import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { Images, Loader2, Search, ShieldCheck, Upload } from 'lucide-react'

import * as api from '../../services/api'

const ACTIVITIES: Array<[api.BusinessNiche, string]> = [
  ['FOOD_SERVICE', 'Alimentação'],
  ['RETAIL', 'Varejo'],
  ['BEAUTY_RESELLER', 'Beleza'],
]

export function MediaLibraryView() {
  const [items, setItems] = useState<api.LibraryImage[]>([])
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [file, setFile] = useState<File | null>(null)
  const [code, setCode] = useState('')
  const [name, setName] = useState('')
  const [collection, setCollection] = useState('GERAL')
  const [tags, setTags] = useState('')
  const [activities, setActivities] = useState<api.BusinessNiche[]>([])

  const preview = useMemo(() => file ? URL.createObjectURL(file) : null, [file])
  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview) }, [preview])

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setItems(await api.fetchPlatformMediaLibrary(search.trim() || undefined))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Falha ao carregar a biblioteca.')
    } finally {
      setLoading(false)
    }
  }, [search])

  useEffect(() => {
    const timer = window.setTimeout(() => { void load() }, 250)
    return () => window.clearTimeout(timer)
  }, [load])

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!file || !code.trim() || !name.trim()) return
    setBusy(true)
    setError(null)
    try {
      await api.uploadPlatformMediaLibrary({
        code: code.trim().toUpperCase(),
        name: name.trim(),
        collection: collection.trim().toUpperCase() || 'GERAL',
        tags: tags.split(',').map((item) => item.trim()).filter(Boolean),
        activities,
      }, file)
      setFile(null)
      setCode('')
      setName('')
      setTags('')
      setActivities([])
      await load()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Não foi possível enviar a imagem.')
    } finally {
      setBusy(false)
    }
  }

  const toggleActivity = (activity: api.BusinessNiche) => {
    setActivities((current) => current.includes(activity)
      ? current.filter((item) => item !== activity)
      : [...current, activity])
  }

  return <div className="mx-auto max-w-[1500px] p-5 sm:p-8">
    <div>
      <p className="text-xs font-black uppercase tracking-wider text-[#E12120]">Acervo da plataforma</p>
      <h2 className="mt-2 text-3xl font-black">Biblioteca de imagens DASHEM</h2>
      <p className="mt-2 max-w-3xl text-slate-500">Imagens daqui podem ser escolhidas por qualquer cliente em modo somente leitura. Arquivos enviados por clientes nunca aparecem nesta tela.</p>
    </div>

    {error && <p className="mt-5 rounded-xl border border-red-200 bg-red-50 p-4 text-sm font-bold text-red-700">{error}</p>}

    <section className="mt-6 grid gap-6 xl:grid-cols-[24rem_minmax(0,1fr)]">
      <form onSubmit={submit} className="h-fit rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex items-start gap-3"><div className="rounded-xl bg-red-50 p-2.5"><Upload className="h-5 w-5 text-[#E12120]" /></div><div><h3 className="font-black">Adicionar à biblioteca</h3><p className="mt-1 text-xs leading-5 text-slate-500">Upload exclusivo do Owner, sem copiar dados de tenant.</p></div></div>
        <label className="mt-5 flex min-h-40 cursor-pointer items-center justify-center overflow-hidden rounded-2xl border-2 border-dashed border-slate-300 bg-slate-50 text-center">
          {preview ? <img src={preview} alt="Prévia do arquivo" className="h-48 w-full object-cover" /> : <span className="px-5 text-sm font-bold text-slate-500">Escolher JPEG, PNG ou WebP<br /><small className="font-medium">até 5 MiB</small></span>}
          <input className="hidden" type="file" accept="image/jpeg,image/png,image/webp" onChange={(event) => setFile(event.target.files?.[0] || null)} />
        </label>
        <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
          <Field required label="Código único" value={code} onChange={setCode} placeholder="EX: BURGER-CLASSICO" />
          <Field required label="Nome" value={name} onChange={setName} placeholder="Ex.: Hambúrguer clássico" />
          <Field label="Coleção" value={collection} onChange={setCollection} placeholder="GERAL" />
          <Field label="Tags (separadas por vírgula)" value={tags} onChange={setTags} placeholder="hambúrguer, lanche, artesanal" />
        </div>
        <fieldset className="mt-4"><legend className="text-xs font-black text-slate-700">Atividades sugeridas</legend><div className="mt-2 flex flex-wrap gap-2">{ACTIVITIES.map(([key, label]) => <button key={key} type="button" onClick={() => toggleActivity(key)} className={`rounded-full border px-3 py-2 text-xs font-black ${activities.includes(key) ? 'border-[#E12120] bg-red-50 text-[#E12120]' : 'border-slate-300 text-slate-500'}`}>{label}</button>)}</div></fieldset>
        <button disabled={busy || !file || !code.trim() || !name.trim()} className="mt-5 flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-[#E12120] text-sm font-black text-white disabled:opacity-40">{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}{busy ? 'Enviando...' : 'Adicionar à biblioteca'}</button>
        <p className="mt-3 flex items-start gap-2 text-xs leading-5 text-slate-500"><ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />Este fluxo grava apenas no acervo da plataforma. A biblioteca não recebe, importa ou lista imagens privadas de clientes.</p>
      </form>

      <div className="min-w-0">
        <label className="relative block"><Search className="absolute left-4 top-3.5 h-4 w-4 text-slate-400" /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Buscar por nome, código ou tag" className="h-11 w-full rounded-xl border border-slate-300 bg-white pl-11 pr-4 text-sm font-semibold" /></label>
        {loading ? <Loader2 className="mx-auto my-24 h-8 w-8 animate-spin text-[#E12120]" /> : items.length === 0 ? <div className="mt-4 rounded-2xl border border-slate-200 bg-white p-12 text-center"><Images className="mx-auto h-9 w-9 text-slate-300" /><p className="mt-3 font-black">Nenhuma imagem encontrada</p><p className="mt-1 text-sm text-slate-500">O Owner pode iniciar o acervo pelo formulário ao lado.</p></div> : <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">{items.map((item) => <article key={item.id} className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">{item.url ? <img src={item.url} alt={item.name} loading="lazy" className="h-36 w-full object-cover" /> : <div className="flex h-36 items-center justify-center bg-slate-100 text-xs font-bold text-slate-400">Prévia indisponível</div>}<div className="p-4"><p className="truncate font-black">{item.name}</p><p className="mt-1 font-mono text-xs text-slate-400">{item.code}</p><div className="mt-3 flex flex-wrap gap-1">{item.tags.slice(0, 4).map((tag) => <span key={tag} className="rounded-full bg-slate-100 px-2 py-1 text-[10px] font-bold text-slate-500">{tag}</span>)}</div></div></article>)}</div>}
      </div>
    </section>
  </div>
}

function Field({ label, value, onChange, placeholder, required = false }: { label: string; value: string; onChange: (value: string) => void; placeholder: string; required?: boolean }) {
  return <label className="block"><span className="text-xs font-black text-slate-700">{label}</span><input required={required} value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} className="mt-1.5 h-10 w-full rounded-xl border border-slate-300 px-3 text-sm font-semibold" /></label>
}
