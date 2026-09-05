import React, { useCallback, useEffect, useState } from 'react'
import { Image as ImageIcon, Library, Trash2, Upload } from 'lucide-react'

import * as api from '../../services/api'

/**
 * How a product gets a picture: the shopkeeper's own file, or one from the
 * DASHEM shelf.
 *
 * The shelf is inspiration and never a fallback — nothing here picks an image
 * on the shopkeeper's behalf, and a product left without one shows its initial
 * on the POS card. Choosing from the shelf copies no bytes, so it works for a
 * tenant with no storage contract at all; only uploading a file needs one, and
 * when it is missing the server says exactly that.
 *
 * The file is stored before the product exists, because a new registration has
 * no id yet. The caller receives a pending selection and applies it once the
 * product is saved.
 */

export type PendingMedia =
  | { kind: 'UPLOAD'; bucket_id: string; object_path: string; content_type: string; size_bytes: number; original_filename: string }
  | { kind: 'LIBRARY'; library_asset_id: string; preview: string | null }
  | { kind: 'CLEAR' }

interface Props {
  headers: Record<string, string>
  activity?: string | null
  /** The picture the product already resolves to, if any. */
  current?: api.ProductImage | null
  onChange: (pending: PendingMedia | null) => void
}

const BUCKET = 'tenant-assets'
const ACCEPTED = 'image/jpeg,image/png,image/webp'

export const ProductMediaPicker: React.FC<Props> = ({ headers, activity, current, onChange }) => {
  const [preview, setPreview] = useState<string | null>(current?.url ?? null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [browsing, setBrowsing] = useState(false)
  const [library, setLibrary] = useState<api.LibraryImage[]>([])
  const [search, setSearch] = useState('')

  useEffect(() => { setPreview(current?.url ?? null) }, [current?.url])

  const loadLibrary = useCallback(async (term: string) => {
    setLibrary(await api.fetchMediaLibrary(headers, term || undefined, activity || undefined))
  }, [headers, activity])

  useEffect(() => { if (browsing) void loadLibrary(search) }, [browsing, search, loadLibrary])

  const upload = async (file: File) => {
    setBusy(true)
    setError(null)
    try {
      // The path is generated here, before the product has an id, and stays
      // inside the tenant's namespace — the server prefixes it and never trusts
      // this value to place the file.
      const safeName = file.name.replace(/[^\w.\-]+/g, '-').slice(-80)
      const objectPath = `catalog/${crypto.randomUUID()}-${safeName}`
      const stored = await api.uploadTenantStorageObject(
        headers, BUCKET, objectPath, file, crypto.randomUUID(),
      )
      setPreview(URL.createObjectURL(file))
      onChange({
        kind: 'UPLOAD', bucket_id: stored.bucket_id, object_path: stored.object_path,
        content_type: file.type, size_bytes: stored.size_bytes, original_filename: file.name,
      })
    } catch (reason) {
      // The commercial entitlement is the usual cause, and its message is the
      // real one: saying "falha ao enviar" would hide a contract decision behind
      // a technical shrug.
      setError(reason instanceof Error ? reason.message : 'Não foi possível enviar a imagem.')
    } finally {
      setBusy(false)
    }
  }

  const chooseFromLibrary = (asset: api.LibraryImage) => {
    setPreview(asset.url)
    onChange({ kind: 'LIBRARY', library_asset_id: asset.id, preview: asset.url })
    setBrowsing(false)
  }

  const clear = () => {
    setPreview(null)
    onChange({ kind: 'CLEAR' })
  }

  return (
    <div className="space-y-2">
      <label className="block text-xs font-bold text-dashem-strong">Foto do produto</label>

      <div className="flex items-start gap-3">
        <div className="flex h-24 w-24 shrink-0 items-center justify-center overflow-hidden rounded-xl border border-dashem-border bg-dashem-surface-elevated">
          {preview
            ? <img src={preview} alt="" className="h-full w-full object-cover" />
            : <ImageIcon className="h-7 w-7 text-dashem-muted" />}
        </div>

        <div className="flex-1 space-y-2">
          <div className="flex flex-wrap gap-2">
            <label className="flex h-10 cursor-pointer items-center gap-1.5 rounded-xl border border-dashem-border bg-dashem-surface-elevated px-3 text-xs font-black text-dashem-strong">
              <Upload className="h-4 w-4" />
              {busy ? 'Enviando...' : 'Enviar foto'}
              <input
                type="file" accept={ACCEPTED} className="hidden" disabled={busy}
                onChange={(event) => {
                  const file = event.target.files?.[0]
                  if (file) void upload(file)
                  event.target.value = ''
                }}
              />
            </label>

            <button type="button" onClick={() => setBrowsing(!browsing)}
              className="flex h-10 items-center gap-1.5 rounded-xl border border-dashem-border bg-dashem-surface-elevated px-3 text-xs font-black text-dashem-strong">
              <Library className="h-4 w-4" />Biblioteca DASHEM
            </button>

            {preview && (
              <button type="button" onClick={clear}
                className="flex h-10 items-center gap-1.5 rounded-xl border border-dashem-border px-3 text-xs font-black text-dashem-muted">
                <Trash2 className="h-4 w-4" />Remover
              </button>
            )}
          </div>

          <p className="text-xs text-dashem-muted">
            JPEG, PNG ou WebP. Sem foto, o cartão do PDV usa a inicial do nome — a
            biblioteca é sugestão, nada é escolhido por você.
          </p>
          {error && <p className="rounded-lg bg-red-50 p-2 text-xs font-bold text-red-700">{error}</p>}
        </div>
      </div>

      {browsing && (
        <div className="rounded-xl border border-dashem-border bg-dashem-surface p-3">
          <input
            value={search} onChange={(event) => setSearch(event.target.value)}
            placeholder="Buscar na biblioteca: hambúrguer, frasco, lâmpada..."
            className="mb-3 h-10 w-full rounded-xl border border-dashem-border bg-dashem-surface-elevated px-3 text-xs text-dashem-strong"
          />
          {library.length === 0 ? (
            <p className="p-4 text-center text-xs text-dashem-muted">
              Nenhuma imagem na biblioteca para esta busca.
            </p>
          ) : (
            <div className="grid max-h-64 grid-cols-3 gap-2 overflow-y-auto sm:grid-cols-5">
              {library.map((asset) => (
                <button key={asset.id} type="button" onClick={() => chooseFromLibrary(asset)}
                  className="overflow-hidden rounded-lg border border-dashem-border transition hover:border-brand">
                  {asset.url
                    ? <img src={asset.url} alt={asset.name} loading="lazy" className="h-16 w-full object-cover" />
                    : <div className="flex h-16 items-center justify-center bg-dashem-surface-elevated text-[10px] text-dashem-muted">{asset.name}</div>}
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
