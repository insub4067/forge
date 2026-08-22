import { createApp } from 'vue'
import { registerSW } from 'virtual:pwa-register'
import './style.css'
import App from './App.vue'

createApp(App).mount('#app')

// autoUpdate: 새 버전이 배포되면 서비스워커가 자동 교체되고 페이지가 리로드된다(항상 최신).
// (sw.js/index.html은 backend no-store + Cloudflare Access Bypass 필요)
registerSW({ immediate: true })

// standalone PWA는 페이지 로드 때만 SW 갱신을 확인한다. 앱을 다시 열 때(포그라운드)
// 명시적으로 확인해, 열려있는 채로도 최신 버전을 당겨오게 한다.
function checkForUpdate() {
  navigator.serviceWorker?.getRegistration().then((reg) => reg && reg.update()).catch(() => {})
}
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') checkForUpdate()
})
window.addEventListener('focus', checkForUpdate)
