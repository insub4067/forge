<script setup>
// 파일 브라우저 — 워크스페이스 파일 탐색·열람·다운로드.
// App.vue의 showFiles 관련 상태·함수·마크업을 이 컴포넌트로 이관.
import { ref, onMounted } from 'vue'
import FileViewer from './FileViewer.vue'

const props = defineProps({
  sessionId: { type: String, default: '' },
  workspacePath: { type: String, default: '' },
  showHidden: { type: Boolean, default: false },
})
const emit = defineEmits(['close', 'image-click', 'toggle-hidden'])

const filePath = ref('')
const fileParent = ref(null)
const fileEntries = ref([])
const viewingFile = ref('')

async function navigateFiles(path) {
  try {
    const res = await fetch(
      `/api/fs/list?path=${encodeURIComponent(path || '')}&show_hidden=${props.showHidden}&session_id=${props.sessionId}`
    )
    if (res.ok) {
      const data = await res.json()
      filePath.value = data.path
      fileParent.value = data.parent
      fileEntries.value = data.entries
      viewingFile.value = ''
    }
  } catch {}
}

function fileKind(e) {
  if (e.is_dir) return 'dir'
  const n = (e.name || '').toLowerCase()
  const ext = n.includes('.') ? n.slice(n.lastIndexOf('.') + 1) : ''
  if (['py', 'js', 'ts', 'jsx', 'tsx', 'vue', 'go', 'rs', 'java', 'c', 'cpp', 'h', 'rb', 'php', 'swift', 'sh', 'html', 'css', 'sql'].includes(ext)) return 'code'
  if (['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp', 'ico', 'bmp'].includes(ext)) return 'image'
  if (['md', 'txt', 'log', 'rst', 'pdf'].includes(ext)) return 'doc'
  if (['json', 'yml', 'yaml', 'toml', 'env', 'ini', 'conf', 'lock', 'cfg'].includes(ext)) return 'config'
  return 'file'
}

function toggleHidden() {
  emit('toggle-hidden')
  navigateFiles(filePath.value)
}

// 파일 길게 누르면 다운로드(iOS는 공유시트로 '파일에 저장'). 폴더는 제외.
let _lpTimer = null
let _lpFired = false
function fileTouchStart(e) {
  if (e.is_dir) return
  _lpFired = false
  _lpTimer = setTimeout(() => { _lpFired = true; downloadFile(e) }, 500)
}
function fileTouchCancel() {
  if (_lpTimer) { clearTimeout(_lpTimer); _lpTimer = null }
}
function onFileClick(e) {
  if (_lpFired) { _lpFired = false; return } // 길게눌러 다운로드했으면 열지 않음
  e.is_dir ? navigateFiles(e.path) : openFile(e.path)
}
async function downloadFile(e) {
  fileTouchCancel()
  const url = `/api/fs/raw?path=${encodeURIComponent(e.path)}&session_id=${props.sessionId}`
  try {
    const res = await fetch(url)
    if (!res.ok) throw new Error('HTTP ' + res.status)
    const blob = await res.blob()
    const file = new File([blob], e.name, { type: blob.type || 'application/octet-stream' })
    if (navigator.canShare && navigator.canShare({ files: [file] })) {
      await navigator.share({ files: [file], title: e.name })
      return
    }
    const objUrl = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = objUrl
    a.download = e.name
    document.body.appendChild(a)
    a.click()
    a.remove()
    setTimeout(() => URL.revokeObjectURL(objUrl), 1500)
  } catch (err) {
    if (err && err.name === 'AbortError') return // 사용자가 공유 취소
    alert('다운로드 실패: ' + (err.message || err))
  }
}

// 파일 열기 — 종류 판별·읽기·렌더는 FileViewer 컴포넌트가 담당
function openFile(path) {
  viewingFile.value = path
}

onMounted(() => navigateFiles(props.workspacePath))
</script>

<template>
  <div class="fs-overlay">
    <div class="fs-head">
      <button @click="emit('close')">닫기</button>
      <span class="fs-title">{{ viewingFile || filePath }}</span>
      <button
        v-if="!viewingFile"
        class="fs-hidden-toggle"
        :class="{ active: showHidden }"
        @click="toggleHidden"
      >
        <svg v-if="showHidden" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/></svg>
        <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-10-8-10-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 10 8 10 8a18.5 18.5 0 0 1-2.16 3.19M1 1l22 22"/></svg>
        숨김
      </button>
      <button v-if="viewingFile" @click="viewingFile = ''">목록</button>
    </div>
    <div v-if="!viewingFile" class="fs-list">
      <button v-if="fileParent" class="fs-item parent" @click="navigateFiles(fileParent)">
        <svg class="fs-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18l-6-6 6-6"/><path d="M3 12h12a6 6 0 0 1 6 6v2"/></svg>
        상위 폴더
      </button>
      <button
        v-for="e in fileEntries"
        :key="e.path"
        class="fs-item"
        :class="{ dir: e.is_dir }"
        @click="onFileClick(e)"
        @touchstart.passive="fileTouchStart(e)"
        @touchmove.passive="fileTouchCancel"
        @touchend.passive="fileTouchCancel"
        @contextmenu.prevent="!e.is_dir && downloadFile(e)"
      >
        <span class="fs-icon" :class="'kind-' + fileKind(e)">
          <svg v-if="fileKind(e) === 'dir'" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>
          <svg v-else-if="fileKind(e) === 'code'" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 18l6-6-6-6M8 6l-6 6 6 6"/></svg>
          <svg v-else-if="fileKind(e) === 'image'" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg>
          <svg v-else-if="fileKind(e) === 'config'" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h2M16 3h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-2"/></svg>
          <svg v-else width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/></svg>
        </span>
        {{ e.name }}
      </button>
    </div>
    <FileViewer
      v-else-if="viewingFile"
      :path="viewingFile"
      :session-id="sessionId"
      @image-click="emit('image-click', $event)"
    />
  </div>
</template>
