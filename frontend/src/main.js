import { createApp } from 'vue'
import { registerSW } from 'virtual:pwa-register'
import './style.css'
import App from './App.vue'

createApp(App).mount('#app')

// autoUpdate: 새 버전이 배포되면 서비스워커가 자동 교체되고 페이지가 리로드된다(항상 최신).
// (sw.js/index.html은 백엔드 no-store 헤더로 서빙되어 Cloudflare/브라우저 캐시에 막히지 않는다)
registerSW({ immediate: true })
