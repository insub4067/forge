// 워크스페이스 선택용 파일시스템 탐색 상태. 방(room) 연동(어느 방에 적용할지·방 생성)은
// App.vue가 그대로 갖고, 여기엔 '지금 어느 경로를 보고 있나'만 둔다.
import { ref, computed } from 'vue'

export const showHidden = ref(false)   // 숨김 파일 표시
export const fsPath = ref('')
export const fsParent = ref(null)
export const fsEntries = ref([])
export const fsFilter = ref('')
export const homePath = ref('')        // 홈 디렉터리 — 최초 세션이 workspace_path로 저장하는 값. 미설정 판별 기준.

// 폴더 먼저(선택 가능한 것이 위로), 그다음 이름순.
export const fsVisible = computed(() => {
  const q = fsFilter.value.trim().toLowerCase()
  const list = q ? fsEntries.value.filter((e) => e.name.toLowerCase().includes(q)) : fsEntries.value
  return [...list].sort((a, b) => (Number(b.is_dir) - Number(a.is_dir)) || a.name.localeCompare(b.name))
})

export async function navigateFs(path) {
  fsFilter.value = ''
  try {
    const res = await fetch(
      `/api/fs/list?path=${encodeURIComponent(path || '')}&show_hidden=${showHidden.value}`
    )
    if (res.ok) {
      const data = await res.json()
      fsPath.value = data.path
      fsParent.value = data.parent
      fsEntries.value = data.entries
    }
  } catch {}
}

export async function loadHomePath() {
  try {
    const res = await fetch('/api/fs/list?path=')
    if (res.ok) {
      const data = await res.json()
      homePath.value = data.path || ''
    }
  } catch {}
}
