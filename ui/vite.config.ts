import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { devServerHost } from './devServer.ts'

// Node's process, typed here so the config type-checks without @types/node.
declare const process: { env: Record<string, string | undefined> }

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Local only unless VITE_DEV_LAN=1 (the Docker dev stack passes --host itself).
    host: devServerHost(process.env),
  },
  build: {
    // Vite 8 bundles with Rolldown: chunk groups replace Rollup's manualChunks.
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: [
            { name: 'charts', test: /node_modules[\\/](recharts|d3-[^\\/]+|victory-vendor)[\\/]/ },
            { name: 'motion', test: /node_modules[\\/]gsap[\\/]/ },
            {
              name: 'vendor',
              test: /node_modules[\\/](react|react-dom|react-router|react-router-dom|scheduler|axios|@tanstack)[\\/]/,
            },
          ],
        },
      },
    },
  },
})
