import React from 'react'
import { createRoot } from 'react-dom/client'
import '../../src/index.css'
import { PaymentProviderManager } from '../../src/components/management/PaymentProviderManager'

createRoot(document.getElementById('root')!).render(<>
  <style>{'@media (min-width: 1024px) { #root > main { margin-left: 288px; } }'}</style>
  <main className="p-4 sm:p-7"><PaymentProviderManager /></main>
</>)
