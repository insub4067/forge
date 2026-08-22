import { createApp } from 'vue'
import { registerSW } from 'virtual:pwa-register'
import './style.css'
import App from './App.vue'

// 앱 토큰(백엔드 FORGE_AUTH_TOKEN 활성화 시). localStorage에 넣어두면 same-origin
// 쿠키로 실려 fetch·<img>·WebSocket에 자동 첨부된다. 미설정이면 아무 일도 없다.
// 설정: 브라우저 콘솔에서 localStorage.setItem('forge_token', '토큰') 후 새로고침.
const _forgeToken = localStorage.getItem('forge_token')
if (_forgeToken) document.cookie = `forge_token=${_forgeToken}; path=/; SameSite=Strict; max-age=31536000`

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
