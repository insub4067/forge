<script setup>
// PDF 뷰어 — pdfjs를 dynamic import로 로드해 메인 번들에서 분리한다.
import { ref, watch, onMounted, onBeforeUnmount } from 'vue'

const props = defineProps({ url: { type: String, required: true } })

const container = ref(null)
const scale = ref(1)
let _pinchDist = 0
let _pinchScale = 1
let _renderSeq = 0 // 렌더 경합 방지: 마지막 요청만 화면에 남긴다
let _pdfWorker = null // pdfjs 워커 1회 생성 후 재사용

function _touchDist(t) {
  return Math.hypot(t[0].clientX - t[1].clientX, t[0].clientY - t[1].clientY)
}
function onTouchStart(e) {
  if (e.touches.length === 2) {
    _pinchDist = _touchDist(e.touches)
    _pinchScale = scale.value
  }
}
function onTouchMove(e) {
  if (e.touches.length === 2 && _pinchDist) {
    e.preventDefault() // 핀치 중 페이지 스크롤 방지
    const s = _pinchScale * (_touchDist(e.touches) / _pinchDist)
    scale.value = Math.max(1, Math.min(4, s))
  }
}
function resetZoom() {
  scale.value = 1
}

async function render(url) {
  const seq = ++_renderSeq
  scale.value = 1
  const el = container.value
  if (!el || !url) return
  el.innerHTML = ''
  try {
    const pdfjsLib = await import('pdfjs-dist')
    // Vite `?worker` import로 워커를 직접 생성해 workerPort로 넘긴다(1회 생성 후 재사용).
    if (!_pdfWorker) {
      const PdfWorker = (await import('pdfjs-dist/build/pdf.worker.min.mjs?worker')).default
      _pdfWorker = new PdfWorker()
    }
    pdfjsLib.GlobalWorkerOptions.workerPort = _pdfWorker
    const pdf = await pdfjsLib.getDocument({ url }).promise
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    const cssWidth = Math.min(el.clientWidth || 360, 900)
    for (let n = 1; n <= pdf.numPages; n++) {
      if (seq !== _renderSeq) return // 새 문서가 열렸으면 중단
      const page = await pdf.getPage(n)
      const base = page.getViewport({ scale: 1 })
      const vpScale = (cssWidth / base.width) * dpr
      const vp = page.getViewport({ scale: vpScale })
      const canvas = document.createElement('canvas')
      canvas.width = vp.width
      canvas.height = vp.height
      canvas.style.width = cssWidth + 'px'
      canvas.style.height = (vp.height / dpr) + 'px'
      canvas.className = 'pdf-page'
      el.appendChild(canvas)
      await page.render({ canvasContext: canvas.getContext('2d'), viewport: vp }).promise
    }
  } catch (e) {
    if (seq === _renderSeq) el.textContent = 'PDF를 불러오지 못했습니다: ' + (e.message || e)
  }
}

// immediate 없이 — immediate watch는 마운트 전에 실행돼 container ref가 null이라 렌더가
// 조기 반환됐다(빈 화면 버그). 초기 렌더는 container가 준비된 onMounted에서 호출한다.
watch(() => props.url, render)
onMounted(() => render(props.url))

onBeforeUnmount(() => { _renderSeq++ }) // 진행 중 렌더 무효화
</script>

<template>
  <div class="pdf-view"
       @touchstart.passive="onTouchStart" @touchmove="onTouchMove" @dblclick="resetZoom">
    <div ref="container" class="pdf-pages" :style="{ transform: `scale(${scale})` }"></div>
  </div>
</template>
