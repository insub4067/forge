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
    // autoUpdate — 새 버전이 배포되면 SW가 자동 교체되고 페이지가 리로드된다(항상 최신).
    // sw.js/index.html은 백엔드에서 no-store로 서빙되므로 stale SW에 막히지 않는다.
    VitePWA({
      registerType: 'autoUpdate',
      // 랜딩 로고는 오프라인에도 떠야 한다 — 기본 glob이 svg를 안 잡아 배너 뜰 때만 깨졌다.
      includeAssets: ['logo.svg'],
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
        // Web Push 핸들러를 생성된 SW에 주입
        importScripts: ['/push-handler.js'],
      },
    }),
  ],
  define: {
    __APP_VERSION__: JSON.stringify(buildVersion()),
  },
  server: {
    // 5173(기본값)은 다른 로컬 프로젝트가 이미 쓴다 — 백엔드 8790에 맞춰 5790으로 고정.
    // strictPort: 조용히 다른 포트로 옮겨가지 않고 실패시켜 어디에 붙었는지 헷갈리지 않게.
    port: 5790,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://localhost:8790',
        changeOrigin: true,
      },
    },
  },
})
