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

if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js').then((reg) => {
    reg.addEventListener('updatefound', () => {
      const newWorker = reg.installing
      if (!newWorker) return
      showToast('리소스 다운로드 중..')
      newWorker.addEventListener('statechange', () => {
        if (newWorker.state === 'activated') {
          showToast('업데이트 완료')
        }
      })
    })
  })
}
