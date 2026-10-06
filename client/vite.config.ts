import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(import.meta.dirname, './src'),
    },
  },
  server: {
    port: 5173,
    host: true,
    // The browser only ever calls the Centerline api (ANA-02); in development that is
    // the FastAPI service in services/api on 127.0.0.1:8000 (CENTERLINE_API overrides it).
    proxy: {
      '/api': { target: process.env.CENTERLINE_API ?? 'http://127.0.0.1:8000', changeOrigin: false },
    },
  },
  build: {
    // ECharts' core is ~590 kB minified even tree-shaken; it loads lazily with the Analytics page.
    chunkSizeWarningLimit: 650,
    rolldownOptions: {
      output: {
        // Recharts and React change far less often than application code;
        // splitting them out keeps the app chunk small and cacheable.
        codeSplitting: {
          groups: [
            { name: 'recharts', test: /node_modules[\\/](recharts|d3-|victory-|decimal\.js)/ },
            { name: 'echarts', test: /node_modules[\\/](echarts|zrender)[\\/]/ },
            // three.js loads with the line view's 3D model only, never with the rest of the app (ADR-0033)
            { name: 'three', test: /node_modules[\\/]three[\\/]/ },
            { name: 'react', test: /node_modules[\\/](react|react-dom|react-router|scheduler)[\\/]/ },
            { name: 'vendor', test: /node_modules/, minShareCount: 1 },
          ],
        },
      },
    },
  },
})
