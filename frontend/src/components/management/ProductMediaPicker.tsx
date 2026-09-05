import React, { useCallback, useEffect, useState } from 'react'
import { Image as ImageIcon, Library, Trash2, Upload } from 'lucide-react'

import * as api from '../../services/api'

/**
 * How a product gets a picture: the shopkeeper's own file, or one from the
 * DASHEM shelf. The shelf is inspiration and never a fallback — a product left
 * without a picture shows its initial on the POS card.
 *
 * Uploading needs storage provisioned for the tenant; choosing from the shelf
 * does not, because nothing is copied. So the state of that provisioning is
 * read once, up front, and the upload button is disabled with the real reason
 * instead of letting someone pick a file and walk into a wall.
 *
 * The layout stays on one row and the words stay short: this lives inside a
 * narrow modal beside SKU and price, and a paragraph here breaks into a column
 * of single syllables.
 */

export type PendingMedia =
  | { kind: 'UPLOAD'; bucket_id: string; object_path: string; content_type: string; size_bytes: number; original_filename: string }
  | { kind: 'LIBRARY'; library_asset_id: string; preview: string | null }
  | { kind: 'CLEAR' }

interface Props {
  headers: Record<string, string>
  activity?: string | null
  current?: api.ProductImage | null
  onChange: (pending: PendingMedia | null) => void
}

const BUCKET = 'tenant-assets'
const ACCEPTED = 'image/jpeg,image/png,image/webp'

/**
 * Short, and true. The server's own sentences are precise but written for
 * whoever operates the platform; beside a SKU field they read as a wall. Each
 * of these says what is blocked and who unblocks it.
 */
const STORAGE_BLOCK_REASON: Record<string, string> = {
  NO_CONTRACT_QUOTA: 'Envio de arquivo indisponível: o contrato ainda não declara limite de storage.',
  NO_SOURCES: 'Envio de arquivo indisponível: storage não provisionado para este tenant.',
  NO_MEASUREMENT: 'Envio de arquivo indisponível: inventário de storage ainda não gerado.',
}
const DEFAULT_BLOCK_REASON = 'Envio de arquivo indisponível: storage não está pronto para este tenant.'

export const ProductMediaPicker: React.FC<Props> = ({ headers, activity, current, onChange }) => {
  const [preview, setPreview] = useState<string | null>(current?.url ?? null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [uploadBlocked, setUploadBlocked] = useState<string | null>(null)
  const [browsing, setBrowsing] = useState(false)
  const [library, setLibrary] = useState<api.LibraryImage[]>([])
  const [search, setSearch] = useState('')

  useEffect(() => { setPreview(current?.url ?? null) }, [current?.url])

  // Asked once, so the button knows whether it can work before it is pressed,
  // and says the real reason instead of a shrug after the file was chosen.
  useEffect(() => {
    let alive = true
    void api.fetchTenantStorageQuota(headers)
      .then((quota) => {
        if (!alive) return
        const healthy = quota.quota_status !== 'UNKNOWN' && quota.measurement_status !== 'UNAVAILABLE'
        setUploadBlocked(healthy ? null : STORAGE_BLOCK_REASON[quota.status_code] ?? DEFAULT_BLOCK_REASON)
      })
      .catch(() => { if (alive) setUploadBlocked(DEFAULT_BLOCK_REASON) })
    return () => { alive = false }
  }, [headers])

  const loadLibrary = useCallback(async (term: string) => {
    setLibrary(await api.fetchMediaLibrary(headers, term || undefined, activity || undefined))
  }, [headers, activity])

  useEffect(() => { if (browsing) void loadLibrary(search) }, [browsing, search, loadLibrary])

  const upload = async (file: File) => {
    setBusy(true)
    setError(null)
    try {
      const safeName = file.name.replace(/[^\w.\-]+/g, '-').slice(-80)
      const objectPath = `catalog/${crypto.randomUUID()}-${safeName}`
      const stored = await api.uploadTenantStorageObject(headers, BUCKET, objectPath, file, crypto.randomUUID())
      setPreview(URL.createObjectURL(file))
      onChange({
        kind: 'UPLOAD', bucket_id: stored.bucket_id, object_path: stored.object_path,
        content_type: file.type, size_bytes: stored.size_bytes, original_filename: file.name,
      })
    } catch (reason) {
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

  return (
    <div className="space-y-2">
      <label className="block text-xs font-bold text-dashem-strong">Foto do produto</label>

      <div className="flex items-center gap-2">
        <div className="flex h-14 w-14 shrink-0 items-center justify-center overflow-hidden rounded-xl border border-dashem-border bg-dashem-surface-elevated">
          {preview
            ? <img src={preview} alt="" className="h-full w-full object-cover" />
            : <ImageIcon className="h-5 w-5 text-dashem-muted" />}
        </div>

        <label
          title={uploadBlocked || 'Enviar uma foto do seu computador'}
          className={`flex h-10 shrink-0 items-center gap-1.5 rounded-xl border border-dashem-border px-3 text-xs font-black ${
            uploadBlocked || busy
              ? 'cursor-not-allowed bg-dashem-bg text-dashem-muted'
              : 'cursor-pointer bg-dashem-surface-elevated text-dashem-strong'
          }`}
        >
          <Upload className="h-4 w-4" />
          <span className="whitespace-nowrap">{busy ? 'Enviando' : 'Enviar'}</span>
          <input
            type="file" accept={ACCEPTED} className="hidden" disabled={busy || !!uploadBlocked}
            onChange={(event) => {
              const file = event.target.files?.[0]
              if (file) void upload(file)
              event.target.value = ''
            }}
          />
        </label>

        <button type="button" onClick={() => setBrowsing(!browsing)}
          className="flex h-10 shrink-0 items-center gap-1.5 rounded-xl border border-dashem-border bg-dashem-surface-elevated px-3 text-xs font-black text-dashem-strong">
          <Library className="h-4 w-4" />
          <span className="whitespace-nowrap">Biblioteca</span>
        </button>

        {preview && (
          <button type="button" onClick={() => { setPreview(null); onChange({ kind: 'CLEAR' }) }}
            title="Remover a foto" aria-label="Remover a foto"
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-dashem-border text-dashem-muted">
            <Trash2 className="h-4 w-4" />
          </button>
        )}
      </div>

      <p className="text-xs text-dashem-muted">Sem foto, o PDV usa a inicial do nome.</p>
      {uploadBlocked && <p className="text-xs font-semibold text-amber-700">{uploadBlocked}</p>}
      {error && <p className="text-xs font-semibold text-red-700">{error}</p>}

      {browsing && (
        <div className="rounded-xl border border-dashem-border bg-dashem-surface p-2">
          <input
            value={search} onChange={(event) => setSearch(event.target.value)}
            placeholder="Buscar imagem..."
            className="mb-2 h-10 w-full rounded-xl border border-dashem-border bg-dashem-surface-elevated px-3 text-xs text-dashem-strong"
          />
          {library.length === 0 ? (
            <p className="p-3 text-center text-xs text-dashem-muted">Biblioteca ainda sem imagens.</p>
          ) : (
            <div className="grid max-h-48 grid-cols-4 gap-2 overflow-y-auto">
              {library.map((asset) => (
                <button key={asset.id} type="button" onClick={() => chooseFromLibrary(asset)} title={asset.name}
                  className="overflow-hidden rounded-lg border border-dashem-border transition hover:border-brand">
                  {asset.url
                    ? <img src={asset.url} alt={asset.name} loading="lazy" className="h-14 w-full object-cover" />
                    : <div className="flex h-14 items-center justify-center bg-dashem-surface-elevated px-1 text-[10px] leading-tight text-dashem-muted">{asset.name}</div>}
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
