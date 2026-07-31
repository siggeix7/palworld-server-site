import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: '/static/dashboard/live-map/',
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    rollupOptions: {
      output: {
        entryFileNames: 'live-map.js',
        chunkFileNames: 'live-map-[name].js',
        assetFileNames: (assetInfo) => (assetInfo.name?.endsWith('.css') ? 'live-map.css' : 'live-map-[name][extname]')
      }
    }
  },
  server: {
    proxy: {
      '/api': 'http://localhost:8080',
      '/-/health': 'http://localhost:8080',
      '/assets/map': 'http://localhost:8080'
    }
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    css: true
  }
})
