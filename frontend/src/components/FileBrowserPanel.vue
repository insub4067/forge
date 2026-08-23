<script setup>
// 파일 브라우저 — 워크스페이스 파일 탐색·열람·다운로드.
// App.vue의 showFiles 관련 상태·함수·마크업을 이 컴포넌트로 이관.
import { ref, computed, onMounted } from 'vue'
import FileViewer from './FileViewer.vue'
import FsIcon from './FsIcon.vue'

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

async function navigateFiles(path, hidden = props.showHidden) {
  try {
    const res = await fetch(
      `/api/fs/list?path=${encodeURIComponent(path || '')}&show_hidden=${hidden}&session_id=${props.sessionId}`
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

// 정렬 통일 — 워크스페이스 피커 기준: 폴더 먼저, 그다음 이름순(localeCompare).
const fileVisible = computed(() =>
  [...fileEntries.value].sort(
    (a, b) => (Number(b.is_dir) - Number(a.is_dir)) || a.name.localeCompare(b.name)
  )
)

function toggleHidden() {
  // prop 업데이트는 비동기라 emit 직후 props.showHidden은 아직 옛 값 — 새 값을 직접 넘겨 fetch한다.
  const next = !props.showHidden
  emit('toggle-hidden')
  navigateFiles(filePath.value, next)
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
        v-for="e in fileVisible"
        :key="e.path"
        class="fs-item"
        :class="{ dir: e.is_dir }"
        @click="onFileClick(e)"
        @touchstart.passive="fileTouchStart(e)"
        @touchmove.passive="fileTouchCancel"
        @touchend.passive="fileTouchCancel"
        @contextmenu.prevent="!e.is_dir && downloadFile(e)"
      >
        <FsIcon :entry="e" />
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
