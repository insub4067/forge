// 첨부(이미지·텍스트 파일)와 전체화면 이미지 뷰어 상태.
// App.vue에서 분리 — 세션·채팅 상태에 의존하지 않는 독립 묶음이다(store.js와 같은
// 모듈 스코프 ref 방식: 임포트하는 쪽이 같은 인스턴스를 공유한다).
import { ref, reactive } from 'vue'

// ── 첨부 ──
export const attachedImages = ref([])      // 여러 장 첨부 [{ previewUrl, url, name }]
export const attachedText = ref(null)      // { name, content, truncated } — 마지막 1개
export const dragActive = ref(false)

// ── 전체화면 뷰어 ──
export const viewerImages = ref([])
export const viewerIndex = ref(0)
export const imgScale = ref(1)
export const imgTx = ref(0)
export const imgTy = ref(0)

export function resetImgZoom() { imgScale.value = 1; imgTx.value = 0; imgTy.value = 0 }

export function openViewer(images, index = 0) {
  viewerImages.value = Array.isArray(images) ? images : [images]
  viewerIndex.value = index
  resetImgZoom()
}

export function closeViewer() { viewerImages.value = [] }
export function viewerNext() { if (viewerIndex.value < viewerImages.value.length - 1) { viewerIndex.value++; resetImgZoom() } }
export function viewerPrev() { if (viewerIndex.value > 0) { viewerIndex.value--; resetImgZoom() } }

// 두 손가락 사이 거리(핀치 배율 계산용).
function touchDist(t) {
  return Math.hypot(t[0].clientX - t[1].clientX, t[0].clientY - t[1].clientY)
}

let viewerTouchX = 0
let pinchDist = 0, pinchScale = 1
let panX = 0, panY = 0, startTx = 0, startTy = 0

export function viewerTouchStart(e) {
  if (e.touches.length === 2) {
    pinchDist = touchDist(e.touches)
    pinchScale = imgScale.value
  } else if (e.touches.length === 1) {
    viewerTouchX = e.touches[0].clientX
    panX = e.touches[0].clientX; panY = e.touches[0].clientY
    startTx = imgTx.value; startTy = imgTy.value
  }
}

export function viewerTouchMove(e) {
  if (e.touches.length === 2 && pinchDist) {
    e.preventDefault()
    imgScale.value = Math.max(1, Math.min(5, pinchScale * (touchDist(e.touches) / pinchDist)))
  } else if (e.touches.length === 1 && imgScale.value > 1) {
    e.preventDefault()
    imgTx.value = startTx + (e.touches[0].clientX - panX)
    imgTy.value = startTy + (e.touches[0].clientY - panY)
  }
}

export function viewerTouchEnd(e) {
  if (imgScale.value > 1) return // 줌 중엔 스와이프 내비게이션 안 함(팬 우선)
  const dx = e.changedTouches[0].clientX - viewerTouchX
  if (Math.abs(dx) > 40) { dx < 0 ? viewerNext() : viewerPrev() }
}

export function revokePreview(entry) {
  if (entry && entry.previewUrl) { try { URL.revokeObjectURL(entry.previewUrl) } catch {} }
}

export function removeImage(idx) {
  revokePreview(attachedImages.value[idx])
  attachedImages.value.splice(idx, 1)
}

export function removeText() {
  attachedText.value = null
}

export function clearAttachments() {
  attachedImages.value.forEach(revokePreview)
  attachedImages.value = []
  attachedText.value = null
}

export async function handleFiles(files) {
  for (const file of files) {
    if (file.type.startsWith('image/')) {
      // 이미지 → 로컬 프리뷰를 즉시 붙이고(선택 즉시 표시), 서버 업로드는 뒤에서 진행한다.
      // 예전엔 업로드→서버 URL을 <img>가 다시 fetch할 때까지 프리뷰가 안 떠 늦게 보였다.
      const entry = reactive({ previewUrl: URL.createObjectURL(file), url: null, name: file.name })
      attachedImages.value.push(entry)
      const formData = new FormData()
      formData.append('file', file)
      try {
        const res = await fetch('/api/upload', { method: 'POST', body: formData })
        if (res.ok) { const j = await res.json(); entry.url = j.url; entry.name = j.name }
        else { revokePreview(entry); attachedImages.value = attachedImages.value.filter((a) => a !== entry) }
      } catch { revokePreview(entry); attachedImages.value = attachedImages.value.filter((a) => a !== entry) }
    } else {
      // 텍스트/코드 파일 → 내용을 읽어 메시지에 포함(마지막 1개)
      try {
        let content = await file.text()
        const MAX = 200000
        const truncated = content.length > MAX
        if (truncated) content = content.slice(0, MAX)
        attachedText.value = { name: file.name, content, truncated }
      } catch {}
    }
  }
}

export async function onFileChange(e) {
  await handleFiles(Array.from(e.target.files || []))
  e.target.value = ''
}

let dragCounter = 0

export function onDragOver(e) {
  if (e.dataTransfer && Array.from(e.dataTransfer.types || []).includes('Files')) {
    e.preventDefault()
    dragCounter++
    dragActive.value = true
  }
}

export function onDragLeave() {
  dragCounter = Math.max(0, dragCounter - 1)
  if (dragCounter === 0) dragActive.value = false
}

export async function onDrop(e) {
  e.preventDefault()
  dragCounter = 0
  dragActive.value = false
  const files = Array.from(e.dataTransfer?.files || [])
  if (files.length) await handleFiles(files)
}
