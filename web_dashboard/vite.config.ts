import { defineConfig } from 'vite'
import { resolve } from 'path'

export default defineConfig({
  build: {
    rollupOptions: {
      input: {
        main: resolve(__dirname, 'index.html'),
        app: resolve(__dirname, 'app.html'),
        privacy: resolve(__dirname, 'privacy.html'),
        terms: resolve(__dirname, 'terms.html'),
        disclosure: resolve(__dirname, 'disclosure.html'),
      },
    },
  },
  define: {
    __APP_BUILD_INFO__: JSON.stringify(new Date().toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo' }))
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      }
    }
  }
})
