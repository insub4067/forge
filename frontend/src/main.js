import { createApp } from 'vue'
import { registerSW } from 'virtual:pwa-register'
import './style.css'
import App from './App.vue'

createApp(App).mount('#app')

function showToast(msg) {
  let el = document.getElementById('toast')
  if (!el) {
    el = document.createElement('div')
    el.id = 'toast'
    document.body.appendChild(el)
  }
  el.textContent = msg
  el.classList.add('show')
  setTimeout(() => el.classList.remove('show'), 3000)
}

// vite-plugin-pwa(workbox) — 배포마다 precache manifest가 바뀌어 확실히 감지된다.
// autoUpdate: 새 SW가 활성화되면 자동 리로드. 작업 중이면 미루고 포그라운드에서 적용.
const updateSW = registerSW({
  immediate: true,
  onNeedRefresh() {
    if (window.__forgeBusy) {
      window.__forgeUpdateReady = true
      showToast('새 버전 준비됨 — 작업 후 적용됩니다')
      return
    }
    showToast('새 버전으로 업데이트합니다…')
    setTimeout(() => updateSW(true), 800)
  },
  onOfflineReady() {},
})

// 포그라운드 복귀 시 업데이트 확인 → 있으면 onNeedRefresh가 발화
function onForeground() {
  navigator.serviceWorker?.getRegistration().then((reg) => reg && reg.update())
  if (window.__forgeUpdateReady && !window.__forgeBusy) {
    window.__forgeUpdateReady = false
    showToast('새 버전으로 업데이트합니다…')
    setTimeout(() => updateSW(true), 800)
  }
}
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') onForeground()
})
window.addEventListener('focus', onForeground)
window.addEventListener('pageshow', onForeground)
