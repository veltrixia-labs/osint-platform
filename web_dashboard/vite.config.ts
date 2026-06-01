import { defineConfig, loadEnv } from 'vite'
import { resolve } from 'path'

const dashboardDir = resolve(__dirname)
const repoRoot = resolve(__dirname, '..')

export default defineConfig(({ mode }) => {
  const parentVite = loadEnv(mode, repoRoot, 'VITE_')
  const localVite = loadEnv(mode, dashboardDir, 'VITE_')
  const define: Record<string, string> = {
    __APP_BUILD_INFO__: JSON.stringify(new Date().toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo' })),
  }
  // Inject repo-root VITE_* (e.g. VITE_DEV_TIER) when not set under web_dashboard/.
  for (const [key, value] of Object.entries(parentVite)) {
    if (localVite[key] === undefined) {
      define[`import.meta.env.${key}`] = JSON.stringify(value)
    }
  }

  return {
    optimizeDeps: {
      include: [
        'earcut',
        'maplibre-gl',
        '@deck.gl/core',
        '@deck.gl/layers',
        '@deck.gl/mapbox',
        '@luma.gl/core',
        '@luma.gl/webgl',
      ],
      exclude: [],
    },
    build: {
      rollupOptions: {
        input: {
          main: resolve(dashboardDir, 'index.html'),
          app: resolve(dashboardDir, 'app.html'),
          login: resolve(dashboardDir, 'login.html'),
        },
      },
    },
    define,
    envDir: dashboardDir,
    server: {
      proxy: {
        '/api': {
          target: 'http://127.0.0.1:8000',
          changeOrigin: true,
        },
      },
    },
  }
})
