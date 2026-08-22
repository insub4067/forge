import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { VitePWA } from 'vite-plugin-pwa'

function buildVersion() {
  const d = new Date()
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}.${pad(d.getMonth() + 1)}.${pad(d.getDate())}.${pad(d.getHours())}${pad(d.getMinutes())}`
}

export default defineConfig({
  plugins: [
    vue(),
    // 수제 sw.js 대신 workbox 기반 PWA — 배포마다 precache manifest가 갱신되어
    // autoUpdate가 새 버전을 확실히 감지·교체한다(trade-bot에서 검증된 구성).
    VitePWA({
      registerType: 'autoUpdate',
      manifest: {
        name: 'FORGE',
        short_name: 'FORGE',
        start_url: '/',
        display: 'standalone',
        background_color: '#262523',
        theme_color: '#262523',
        icons: [
          { src: '/logo.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
          { src: '/logo.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
      workbox: {
        // API·업로드는 절대 캐시하지 않는다(SSE·실시간 데이터)
        navigateFallbackDenylist: [/^\/api\//, /^\/uploads\//],
        runtimeCaching: [],
      },
    }),
  ],
  define: {
    __APP_VERSION__: JSON.stringify(buildVersion()),
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8790',
        changeOrigin: true,
      },
    },
  },
})
