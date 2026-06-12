import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
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
