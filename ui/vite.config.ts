import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { devServerHost } from './devServer'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Local only unless VITE_DEV_LAN=1 (the Docker dev stack passes --host itself).
    host: devServerHost(process.env),
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          charts: ['recharts'],
          motion: ['gsap'],
          vendor: ['react', 'react-dom', 'react-router-dom', 'axios', '@tanstack/react-query'],
        },
      },
    },
  },
})
