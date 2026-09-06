import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Loopback por padrão, mesma variável do docker-compose. Em `0.0.0.0` o dev
    // server ficava acessível a qualquer máquina da rede local — é o que torna
    // alcançável o aviso conhecido do dev server (responde a requisições de
    // qualquer origem) e expõe a interface ao lado de uma API que, em
    // desenvolvimento, aceita X-User-ID sem token.
    //
    // Abrir para testar num tablet é necessidade real de um PDV, então continua
    // possível — só deixa de ser o padrão: BIND_HOST=0.0.0.0 npm run dev
    host: process.env.BIND_HOST || '127.0.0.1'
  }
})
