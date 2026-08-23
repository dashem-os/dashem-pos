import React, { useState } from 'react'
import { Activity, Database, CheckCircle2, AlertCircle, RefreshCw, Layers, Cpu } from 'lucide-react'
import { usePos } from '../../context/PosContext'
import * as api from '../../services/api'

export const Diagnostics: React.FC = () => {
  const { tenant, store, register, health, showToast } = usePos()
  const [checking, setChecking] = useState(false)
  const [liveHealth, setLiveHealth] = useState<api.ApiHealth | null>(health)

  const handleCheckHealth = async () => {
    try {
      setChecking(true)
      const res = await api.fetchHealth()
      setLiveHealth(res)
      showToast('success', 'Comunicação com Backend FastAPI validada!')
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'API Indisponível'
      showToast('error', msg)
    } finally {
      setChecking(false)
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h2 className="text-xl font-black text-white tracking-tight flex items-center space-x-2">
          <Activity className="w-5 h-5 text-dashem-red" />
          <span>Diagnóstico & Conectividade do Sistema</span>
        </h2>
        <p className="text-xs text-dashem-muted font-medium mt-0.5">
          Verificações reais disponíveis para o contexto operacional atual.
        </p>
      </div>

      {/* Services Health Grid */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Backend API Service */}
        <div className="p-5 rounded-2xl bg-dashem-surface border border-dashem-border flex flex-col justify-between shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-dashem-muted uppercase">Backend API (FastAPI)</span>
            <div className="w-9 h-9 rounded-xl bg-emerald-950/60 border border-emerald-800/40 text-emerald-400 flex items-center justify-center">
              <Cpu className="w-5 h-5" />
            </div>
          </div>
          <div className="mt-3">
            <div className="flex items-center space-x-2 text-sm font-extrabold text-white">
              {liveHealth ? <CheckCircle2 className="w-4 h-4 text-emerald-400" /> : <AlertCircle className="w-4 h-4 text-amber-400" />}
              <span>{liveHealth?.service || 'API ainda não verificada'}</span>
            </div>
            <span className={`text-[11px] font-mono mt-1 block ${liveHealth ? 'text-emerald-400' : 'text-amber-400'}`}>
              Status: {liveHealth?.status || 'DESCONHECIDO'}
            </span>
          </div>
        </div>

        {/* Database PostgreSQL */}
        <div className="p-5 rounded-2xl bg-dashem-surface border border-dashem-border flex flex-col justify-between shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-dashem-muted uppercase">Banco PostgreSQL (Docker)</span>
            <div className="w-9 h-9 rounded-xl bg-slate-900 border border-slate-700 text-slate-400 flex items-center justify-center">
              <Database className="w-5 h-5" />
            </div>
          </div>
          <div className="mt-3">
            <div className="flex items-center space-x-2 text-sm font-extrabold text-white">
              <AlertCircle className="w-4 h-4 text-amber-400" />
              <span>Não instrumentado</span>
            </div>
            <span className="text-[11px] font-mono text-dashem-muted mt-1 block">
              A API ainda não fornece uma sondagem dedicada do banco.
            </span>
          </div>
        </div>

        {/* Outbox & Workers */}
        <div className="p-5 rounded-2xl bg-dashem-surface border border-dashem-border flex flex-col justify-between shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-dashem-muted uppercase">Outbox Worker & Auditoria</span>
            <div className="w-9 h-9 rounded-xl bg-slate-900 border border-slate-700 text-slate-400 flex items-center justify-center">
              <Layers className="w-5 h-5" />
            </div>
          </div>
          <div className="mt-3">
            <div className="flex items-center space-x-2 text-sm font-extrabold text-white">
              <AlertCircle className="w-4 h-4 text-amber-400" />
              <span>Não instrumentado</span>
            </div>
            <span className="text-[11px] font-mono text-dashem-muted mt-1 block">
              Sem heartbeat real do worker neste endpoint.
            </span>
          </div>
        </div>
      </div>

      {/* Multi-Tenant Active Context Card */}
      <div className="p-6 rounded-3xl bg-dashem-surface border border-dashem-border space-y-4 shadow-sm">
        <h3 className="text-sm font-black text-white flex items-center space-x-2">
          <Layers className="w-4 h-4 text-dashem-red" />
          <span>Contexto da Instância & Headers de Requisição</span>
        </h3>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <div className="p-3.5 rounded-xl bg-dashem-surface-elevated border border-dashem-border">
            <span className="text-[10px] font-bold uppercase text-dashem-muted block">Tenant Ativo</span>
            <span className="text-xs font-mono font-bold text-white block mt-0.5">{tenant?.name}</span>
            <span className="text-[10px] font-mono text-dashem-muted">{tenant?.id}</span>
          </div>

          <div className="p-3.5 rounded-xl bg-dashem-surface-elevated border border-dashem-border">
            <span className="text-[10px] font-bold uppercase text-dashem-muted block">Loja Ativa</span>
            <span className="text-xs font-mono font-bold text-white block mt-0.5">{store?.name}</span>
            <span className="text-[10px] font-mono text-dashem-muted">{store?.id}</span>
          </div>

          <div className="p-3.5 rounded-xl bg-dashem-surface-elevated border border-dashem-border">
            <span className="text-[10px] font-bold uppercase text-dashem-muted block">Terminal / Caixa</span>
            <span className="text-xs font-mono font-bold text-white block mt-0.5">{register?.name}</span>
            <span className="text-[10px] font-mono text-dashem-muted">{register?.id}</span>
          </div>
        </div>

        <div className="pt-2 flex items-center space-x-3">
          <button
            onClick={handleCheckHealth}
            disabled={checking}
            className="h-11 px-4 rounded-xl bg-dashem-surface-elevated hover:bg-dashem-border text-white text-xs font-bold transition-all border border-dashem-border flex items-center space-x-2"
          >
            <RefreshCw className={`w-4 h-4 ${checking ? 'animate-spin' : ''}`} />
            <span>Testar Healthcheck API</span>
          </button>

        </div>
      </div>
    </div>
  )
}
