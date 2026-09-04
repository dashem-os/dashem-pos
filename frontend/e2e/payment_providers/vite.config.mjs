import path from 'node:path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  cacheDir: 'node_modules/.vite-provider-acceptance',
  optimizeDeps: { entries: ['e2e/payment_providers/index.html'] },
  define: { 'import.meta.env.VITE_API_URL': JSON.stringify('http://127.0.0.1:5192') },
  plugins: [react(), {
    name: 'provider-acceptance-context', enforce: 'pre',
    resolveId(source) {
      if (source.endsWith('/context/PosContext')) return path.resolve('e2e/payment_providers/context.ts')
    },
  }],
  // This entry point is only served by this test config, never the app build.
  server: { host: '127.0.0.1', port: 5192, strictPort: true, proxy: { '/api': 'http://localhost:8002' } },
})
