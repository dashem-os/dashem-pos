import React from 'react'
import { PosProvider, usePos } from './context/PosContext'
import { PosLayout } from './layouts/PosLayout'
import { ManagementLayout } from './layouts/ManagementLayout'
import { Toast } from './components/common/Toast'
import { Loader2 } from 'lucide-react'

const AppContent: React.FC = () => {
  const { activeView, loading, toast } = usePos()

  if (loading) {
    return (
      <div className="min-h-screen bg-dashem-bg flex flex-col items-center justify-center space-y-4 text-white">
        <div className="w-14 h-14 rounded-2xl bg-dashem-surface-elevated border border-dashem-border flex items-center justify-center text-dashem-red shadow-xl">
          <Loader2 className="w-8 h-8 animate-spin" />
        </div>
        <div className="text-center">
          <h2 className="text-base font-black tracking-tight">DASHEM POS</h2>
          <p className="text-xs text-dashem-muted font-medium mt-1">Carregando ambiente operacional...</p>
        </div>
      </div>
    )
  }

  return (
    <>
      <Toast toast={toast} />
      {activeView === 'pdv' ? <PosLayout /> : <ManagementLayout />}
    </>
  )
}

export default function App() {
  return (
    <PosProvider>
      <AppContent />
    </PosProvider>
  )
}
