import { createApp } from 'vue'
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

let swRegistration = null
let refreshing = false

if ('serviceWorker' in navigator) {
  // 이미 SW가 페이지를 제어 중이면(재방문), 새 버전 활성화 시 자동 리로드해 즉시 반영.
  // 최초 설치(controller 없음)에는 리로드하지 않는다.
  const applyUpdate = () => {
    if (refreshing) return
    // 작업 중이면 리로드를 미룬다(SSE 스트림 끊김 방지). 다음 포그라운드·유휴 때 적용.
    if (window.__forgeBusy) {
      window.__forgeUpdateReady = true
      return
    }
    // 무한 리로드 차단: refreshing은 리로드마다 초기화돼 루프를 못 막는다.
    // 리로드를 건너 살아남는 sessionStorage로 한 탭 세션당 업데이트 리로드를 1회로 제한한다.
    if (sessionStorage.getItem('forge_sw_reloaded')) return
    sessionStorage.setItem('forge_sw_reloaded', '1')
    refreshing = true
    window.location.reload()
  }
  if (navigator.serviceWorker.controller) {
    navigator.serviceWorker.addEventListener('controllerchange', applyUpdate)
  }
  window.__forgeApplyUpdate = applyUpdate

  navigator.serviceWorker.register('/sw.js').then((reg) => {
    swRegistration = reg
    reg.addEventListener('updatefound', () => {
      const newWorker = reg.installing
      if (!newWorker) return
      showToast('업데이트 적용 중…')
      newWorker.addEventListener('statechange', () => {
        // 설치 완료 + 기존 controller 존재 → 대기 SW를 즉시 활성화(그러면 controllerchange→reload)
        if (newWorker.state === 'installed' && navigator.serviceWorker.controller) {
          newWorker.postMessage({ type: 'SKIP_WAITING' })
        }
      })
    })
  })
}

// 포그라운드 복귀 시 즉시 업데이트 확인
function checkUpdate() {
  if (swRegistration) swRegistration.update()
}
function onForeground() {
  checkUpdate()
  // 작업 중이라 미뤄둔 업데이트가 있고 지금 유휴면 적용
  if (window.__forgeUpdateReady && !window.__forgeBusy && window.__forgeApplyUpdate) {
    window.__forgeApplyUpdate()
  }
}
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') onForeground()
})
window.addEventListener('focus', onForeground)
window.addEventListener('pageshow', onForeground)
