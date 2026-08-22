<script setup>
import { ref, reactive, nextTick, onMounted, watch } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'

// 단일 줄바꿈도 <br>로 — 답변 줄바꿈을 적극 반영
marked.setOptions({ breaks: true, gfm: true })

function renderMarkdown(text) {
  try {
    return DOMPurify.sanitize(marked.parse(text || ''))
  } catch {
    return ''
  }
}

const messages = ref([])
const input = ref('')
const busy = ref(false)
const isAtBottom = ref(true)
const autoApprove = ref(localStorage.getItem('forge_auto_approve') === '1')
const sessionRunning = ref(false)
const agentStatus = ref(null)
const showSkills = ref(false)
const skillOpen = ref({}) // 스킬 카드 펼침 상태(기본 닫힘)
const skills = ref([])
const searchQuery = ref('')
const searchResults = ref([])
const theme = ref(localStorage.getItem('forge_theme') || 'dark')
const THEMES = [
  { id: 'dark', label: '코랄', c: '#d97757', bg: '#262523' },
  { id: 'gold', label: '골드', c: '#d9a66f', bg: '#11100f' },
  { id: 'paper', label: '페이퍼', c: '#a67c52', bg: '#faf5e6' },
  { id: 'light', label: '라이트', c: '#8a6d3b', bg: '#ffffff' },
]

function applyTheme(id) {
  if (id === 'dark') document.documentElement.removeAttribute('data-theme')
  else document.documentElement.setAttribute('data-theme', id)
}

function setTheme(id) {
  theme.value = id
  localStorage.setItem('forge_theme', id)
  applyTheme(id)
}
let searchTimer = null

function onSearch() {
  clearTimeout(searchTimer)
  const q = searchQuery.value.trim()
  if (!q) {
    searchResults.value = []
    return
  }
  searchTimer = setTimeout(async () => {
    try {
      const res = await fetch(`/api/search?q=${encodeURIComponent(q)}`)
      if (res.ok) searchResults.value = (await res.json()).results || []
    } catch {}
  }, 250)
}

async function openSkills() {
  showSkills.value = true
  skills.value = []
  const id = currentRoomId.value
  if (!id) return
  try {
    const res = await fetch(`/api/rooms/${id}/skills`)
    if (res.ok) skills.value = (await res.json()).skills || []
  } catch {}
}

async function deleteSkill(name) {
  const id = currentRoomId.value
  if (!id || !confirm(`skill '${name}'을 삭제할까요?`)) return
  try {
    await fetch(`/api/rooms/${id}/skills/${encodeURIComponent(name)}`, { method: 'DELETE' })
    await openSkills()
  } catch {}
}
const activeQuestion = ref(null)
const questionAnswer = ref('')
const debug = ref('대기 중')

const rooms = ref([])
const currentRoomId = ref(localStorage.getItem('forge_room') || '')
const loadingMessages = ref(false)
const showRooms = ref(false)
const showCreateRoom = ref(false)
const newRoomName = ref('')
const newRoomPath = ref('')
const tasks = ref([])
// 칸반 카드 상태 변경을 채팅에 알리기 위한 직전 상태 스냅샷(title→status).
let lastTaskStatus = {}
const showKanban = ref(false)
const showWorkspacePicker = ref(false)
const fsPath = ref('')
const fsParent = ref(null)
const fsEntries = ref([])
const swipedRoomId = ref(null)
const pickerRoomId = ref(null)
const roomMenuId = ref(null)
const showGit = ref(false)
const gitCurrent = ref('')
const gitBranches = ref([])
const gitStatus = ref('')
const gitDiff = ref('')
const gitError = ref('')
const gitLoading = ref(false)
const gitTab = ref('changes') // 'changes' | 'history' | 'branches'
const gitFiles = ref([])
const gitLog = ref([])
const gitDetail = ref(null) // { title, sub, diff, loading }
const steerMode = ref('queue') // 'queue' = 작업큐 대기(기본), 'switch' = 중단 후 새로 시작
const pendingSend = ref(null)
const showFiles = ref(false)
const showHidden = ref(false)
const filePath = ref('')
const fileParent = ref(null)
const fileEntries = ref([])
const fileContent = ref('')
const viewingFile = ref('')
const showMenu = ref(false)
const showAdmin = ref(false)
const adminStats = ref(null)
const showModelPicker = ref(false)
const pickerRole = ref('')
const adminBalance = ref(null)
const adminPolicyOpen = ref(false)
const adminErrors = ref([])
const adminErrorsOpen = ref(false)
const showSessionDetail = ref(false)
const sessionRuns = ref([])
const sessionMetrics = ref(null)
const AVAILABLE_MODELS = ['deepseek-v4-pro', 'deepseek-v4-flash', 'deepseek-v4-flash-vision-exp']
const attachedImages = ref([]) // 여러 장 첨부
const viewerImages = ref([]) // 전체화면 뷰어 이미지 목록
const viewerIndex = ref(0)
function openViewer(images, index = 0) {
  viewerImages.value = Array.isArray(images) ? images : [images]
  viewerIndex.value = index
}
function closeViewer() { viewerImages.value = [] }
function viewerNext() { if (viewerIndex.value < viewerImages.value.length - 1) viewerIndex.value++ }
function viewerPrev() { if (viewerIndex.value > 0) viewerIndex.value-- }
let viewerTouchX = 0
function viewerTouchStart(e) { viewerTouchX = e.changedTouches[0].clientX }
function viewerTouchEnd(e) {
  const dx = e.changedTouches[0].clientX - viewerTouchX
  if (Math.abs(dx) > 40) { dx < 0 ? viewerNext() : viewerPrev() }
}
const attachedText = ref(null) // { name, content, truncated }
const fileInput = ref(null)
const kanbanOpen = ref({
  todo: false,
  planning: false,
  in_progress: false,
  review: false,
  debug: false,
  done: false,
})

let touchStartX = 0
let touchStartY = 0
let runningPoll = null

// 앱을 껐다 켰을 때 서버에서 세션이 아직 실행 중인지 확인 → 완료 시 자동 갱신
// 스트림이 끊겨도 에이전트 상태를 언제나 조회한다(running/role/대기/idle).
// 대기 중(승인·질문)이면 프롬프트를 복구해 사용자가 답할 수 있게 한다.
async function fetchStatus(id) {
  const res = await fetch(`/api/sessions/${id}/status`)
  if (!res.ok) return null
  const st = await res.json()
  agentStatus.value = st
  sessionRunning.value = !!st.running
  // 스트림이 끊긴 사이 뜬 질문을 복구(모달 재노출)
  if (st.waiting_for === 'question' && st.pending && !activeQuestion.value) {
    activeQuestion.value = { id: st.pending.id, question: st.pending.question, options: st.pending.options || [] }
    questionAnswer.value = ''
  }
  return st
}

async function checkRunning() {
  const id = currentRoomId.value
  if (!id || busy.value) return
  try {
    const st = await fetchStatus(id)
    if (st && st.running) startRunningPoll()
  } catch {}
}

function startRunningPoll() {
  if (runningPoll) return
  runningPoll = setInterval(async () => {
    const id = currentRoomId.value
    if (!id) return stopRunningPoll()
    try {
      const st = await fetchStatus(id)
      if (!st || !st.running) {
        stopRunningPoll()
        sessionRunning.value = false
        agentStatus.value = null
        await loadMessages(true) // 완료 결과 반영 — 이미 열린 방 새로고침이라 skeleton 생략
      } else {
        // 실행 중엔 태스크를 폴링해 칸반이 살아있게 한다(SSE 스트림이 끊겨도 최신).
        loadTasks()
      }
    } catch {}
  }, 3000)
}

function stopRunningPoll() {
  if (runningPoll) {
    clearInterval(runningPoll)
    runningPoll = null
  }
}

// 실행 배너 문구 — 무엇을 하는지/대기 중인지 항상 보이게(ROLE_LABELS는 아래에 정의됨).
function runningBannerText() {
  const s = agentStatus.value
  if (!s) return 'Mac에서 작업 진행 중'
  if (s.waiting_for === 'approval') return '승인 대기 중 — 확인이 필요합니다'
  if (s.waiting_for === 'question') return '질문 대기 중 — 답변이 필요합니다'
  const role = s.role ? (ROLE_LABELS[s.role] || s.role) : ''
  const idle = s.idle_seconds != null ? ` · ${Math.round(s.idle_seconds)}초 전` : ''
  if (s.activity) return `${role ? role + ' · ' : ''}${s.activity}${idle}`
  if (role) return `${role} 진행 중${idle}`
  return 'Mac에서 작업 진행 중'
}
// 상세 화면 없이도 "지금 무엇을" 한 줄로. 스트림 끊겨도 폴링으로 갱신.
function liveActivityText() {
  const s = agentStatus.value
  return (s && s.activity) || 'Mac에서 작업 중'
}

// 실행 중(로컬 스트림 또는 서버 run)이며 마지막 메시지인가 — 복사/context 등 '끝난' UI를 숨기는 기준.
function isLiveTurn(i) {
  return (busy.value || sessionRunning.value) && i === messages.value.length - 1
}
let mainStartX = 0
let mainStartY = 0

function onMainTouchStart(e) {
  mainStartX = e.touches[0].clientX
  mainStartY = e.touches[0].clientY
}

function onMainTouchEnd(e) {
  const dx = e.changedTouches[0].clientX - mainStartX
  const dy = e.changedTouches[0].clientY - mainStartY
  // 왼쪽 가장자리에서 오른쪽으로 스와이프 → 세션 드로어
  if (mainStartX < 44 && dx > 60 && Math.abs(dx) > Math.abs(dy) * 1.4 && !showRooms.value) {
    showRooms.value = true
  }
}

function onRoomTouchStart(e) {
  touchStartX = e.touches[0].clientX
  touchStartY = e.touches[0].clientY
}

function onRoomTouchEnd(r, e) {
  const dx = e.changedTouches[0].clientX - touchStartX
  const dy = e.changedTouches[0].clientY - touchStartY
  if (Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy)) {
    swipedRoomId.value = dx < 0 ? r.id : null
  }
}

function toggleKanban(key) {
  kanbanOpen.value[key] = !kanbanOpen.value[key]
}

function formatTokens(n) {
  if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M'
  if (n >= 1000) return (n / 1000).toFixed(1) + 'K'
  return String(n || 0)
}

function roomTitle(id) {
  return rooms.value.find((r) => r.id === id)?.title || id.slice(0, 8)
}

function menuRoom() {
  return rooms.value.find((r) => r.id === roomMenuId.value) || null
}

async function loadAdmin() {
  try {
    const res = await fetch('/api/admin/stats')
    if (res.ok) adminStats.value = await res.json()
  } catch {}
}

async function loadBalance() {
  try {
    const res = await fetch('/api/admin/balance')
    if (res.ok) adminBalance.value = await res.json()
  } catch {}
}

async function loadErrors() {
  try {
    const res = await fetch('/api/admin/errors')
    if (res.ok) adminErrors.value = (await res.json()).errors || []
  } catch {}
}

function openAdmin() {
  showAdmin.value = true
  loadAdmin()
  loadBalance()
  loadErrors()
}

async function openSessionDetail() {
  const id = currentRoomId.value
  if (!id) return
  showSessionDetail.value = true
  sessionRuns.value = []
  sessionMetrics.value = null
  // 방 목록을 새로고침해 컨텍스트 윈도우(used_tokens)를 최신값으로 반영(옛값 0% 방지).
  await loadRooms()
  try {
    const res = await fetch(`/api/rooms/${id}/runs`)
    if (res.ok) sessionRuns.value = await res.json()
    const mres = await fetch(`/api/rooms/${id}/metrics`)
    if (mres.ok) sessionMetrics.value = await mres.json()
  } catch {}
}

function sessionTokenTotals() {
  let prompt = 0, completion = 0
  for (const r of sessionRuns.value) {
    prompt += r.prompt_tokens || 0
    completion += r.completion_tokens || 0
  }
  return { prompt, completion, total: prompt + completion }
}

function sessionRoleBreakdown() {
  const agg = {}
  for (const r of sessionRuns.value) {
    const k = r.role || '기타'
    if (!agg[k]) agg[k] = { role: k, count: 0, prompt: 0, completion: 0 }
    agg[k].count++
    agg[k].prompt += r.prompt_tokens || 0
    agg[k].completion += r.completion_tokens || 0
  }
  return Object.values(agg)
    .map((a) => ({ ...a, total: a.prompt + a.completion }))
    .sort((a, b) => b.total - a.total)
}

function refreshAdmin() {
  loadAdmin()
  loadBalance()
  loadErrors()
}

function togglePolicy() {
  adminPolicyOpen.value = !adminPolicyOpen.value
}

async function changeRoleModel(role) {
  pickerRole.value = role
  showModelPicker.value = true
}

async function selectModel(model) {
  if (!pickerRole.value || !model) return
  try {
    await fetch(`/api/admin/model-policy/${pickerRole.value}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model }),
    })
    await loadAdmin()
    showModelPicker.value = false
  } catch {}
}

async function loadGit() {
  const id = currentRoomId.value
  if (!id) {
    gitError.value = '세션을 먼저 선택하세요.'
    return
  }
  gitError.value = ''
  gitDetail.value = null
  gitLoading.value = true
  const get = async (path) => {
    try {
      const r = await fetch(`/api/rooms/${id}/${path}`)
      if (!r.ok) throw new Error('HTTP ' + r.status)
      return await r.json()
    } catch (e) {
      gitError.value = 'Git 정보를 불러오지 못했습니다: ' + (e.message || e)
      return null
    }
  }
  // 각 요청을 독립 처리 — 하나 실패해도 나머지는 표시한다.
  const [b, s, l] = await Promise.all([get('git/branches'), get('git/status'), get('git/log')])
  if (b) {
    gitCurrent.value = b.current || ''
    gitBranches.value = b.branches || []
  }
  if (s) {
    gitStatus.value = s.output || ''
    gitFiles.value = parseStatus(s.output || '')
  }
  if (l) gitLog.value = l.commits || []
  gitLoading.value = false
}

function parseStatus(raw) {
  return raw
    .split('\n')
    .filter((line) => line.trim())
    .map((line) => {
      // git status --short는 "XY path"(2칸 코드+공백). 백엔드 _git의 strip()이
      // 첫 줄 앞 공백을 먹어 정렬이 밀리므로, 구분 공백이 없으면 복원한다.
      if (line[2] !== ' ') line = ' ' + line
      const code = line.slice(0, 2)
      let path = line.slice(3)
      if (path.includes(' -> ')) path = path.split(' -> ')[1] // rename
      path = path.replace(/^"|"$/g, '')
      const c = code.replace(/\s/g, '')
      let badge = 'M', cls = 'st-mod'
      if (code.includes('?')) { badge = 'U'; cls = 'st-new' }
      else if (c.includes('A')) { badge = 'A'; cls = 'st-new' }
      else if (c.includes('D')) { badge = 'D'; cls = 'st-del' }
      else if (c.includes('R')) { badge = 'R'; cls = 'st-ren' }
      else if (c.includes('U')) { badge = '!'; cls = 'st-del' }
      return { badge, cls, path }
    })
}

async function openFileDiff(f) {
  const id = currentRoomId.value
  gitDetail.value = { title: f.path, sub: '변경 사항', diff: '', loading: true }
  try {
    const r = await fetch(`/api/rooms/${id}/git/file-diff?path=${encodeURIComponent(f.path)}`)
    const d = await r.json()
    gitDetail.value = { title: f.path, sub: '변경 사항', diff: d.diff || '', loading: false }
  } catch {
    gitDetail.value = { title: f.path, sub: '변경 사항', diff: '', loading: false }
  }
}

async function openCommit(c) {
  const id = currentRoomId.value
  const sub = `${c.author} · ${c.date} · ${c.hash}`
  gitDetail.value = { title: c.subject, sub, diff: '', loading: true }
  try {
    const r = await fetch(`/api/rooms/${id}/git/commit?hash=${encodeURIComponent(c.hash)}`)
    const d = await r.json()
    gitDetail.value = {
      title: d.subject || c.subject,
      sub: `${d.author || c.author} · ${d.date || c.date} · ${d.hash || c.hash}`,
      diff: d.diff || '',
      loading: false,
    }
  } catch {
    gitDetail.value = { title: c.subject, sub, diff: '', loading: false }
  }
}

async function checkoutBranch(branch) {
  const id = currentRoomId.value
  if (!id) return
  try {
    await fetch(`/api/rooms/${id}/git/checkout`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ branch }),
    })
    await loadGit()
  } catch {}
}

function openGit() {
  showGit.value = true
  loadGit()
}

async function navigateFiles(path) {
  try {
    const res = await fetch(
      `/api/fs/list?path=${encodeURIComponent(path || '')}&show_hidden=${showHidden.value}&session_id=${currentRoomId.value}`
    )
    if (res.ok) {
      const data = await res.json()
      filePath.value = data.path
      fileParent.value = data.parent
      fileEntries.value = data.entries
      viewingFile.value = ''
      fileContent.value = ''
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
  showHidden.value = !showHidden.value
  navigateFiles(filePath.value)
}

async function openFile(path) {
  try {
    const res = await fetch(`/api/fs/read?path=${encodeURIComponent(path)}&session_id=${currentRoomId.value}`)
    if (res.ok) {
      const data = await res.json()
      viewingFile.value = data.path
      fileContent.value = data.content
    }
  } catch {}
}

function openFiles() {
  showFiles.value = true
  const room = currentRoom()
  navigateFiles(room?.workspace_path || '')
}

const kanbanCols = [
  { key: 'todo', label: 'TODO' },
  { key: 'planning', label: 'PLANNING' },
  { key: 'in_progress', label: 'IN PROGRESS' },
  { key: 'review', label: 'REVIEW' },
  { key: 'debug', label: 'DEBUG' },
  { key: 'done', label: 'DONE' },
]

const chatEl = ref(null)

const version = __APP_VERSION__

const isMobile = window.matchMedia('(pointer: coarse)').matches

function currentRoom() {
  return rooms.value.find((r) => r.id === currentRoomId.value) || null
}

function shortPath(p) {
  if (!p) return ''
  const parts = p.split('/').filter(Boolean)
  if (parts.length <= 2) return p
  return parts.slice(-2).join('/')
}

function ctxPct(room) {
  const used = room?.used_tokens || 0
  const budget = room?.logical_budget || 262144
  if (!budget) return 0
  return Math.min(100, Math.round((used / budget) * 100))
}

function ctxClass(pct) {
  if (pct >= 95) return 'crit'
  if (pct >= 85) return 'danger'
  if (pct >= 75) return 'warn'
  if (pct >= 60) return 'notice'
  return 'ok'
}

async function loadRooms() {
  try {
    const res = await fetch('/api/rooms')
    if (res.ok) rooms.value = await res.json()
  } catch {}
}

async function loadMessages(isNew = false) {
  const id = currentRoomId.value
  if (!id) return
  messages.value = []
  // 기존 방은 이력 로딩 동안 skeleton, 새 방은 곧장 welcome placeholder.
  if (!isNew) loadingMessages.value = true
  try {
    const res = await fetch(`/api/sessions/${id}/messages`)
    if (!res.ok) return
    const data = await res.json()
    if (!Array.isArray(data)) return
    // 도구 결과를 tool_call_id로 미리 매핑
    const toolById = {}
    for (const m of data) {
      if (m.role === 'tool') toolById[m.tool_call_id] = m.content || ''
    }
    let bubble = null
    for (const m of data) {
      if (m.role === 'user') {
        let uContent = m.content
        let uImages = null
        if (Array.isArray(uContent)) {
          const imgs = uContent.filter((c) => c && c.type === 'image_url').map((c) => c.image_url?.url).filter(Boolean)
          uImages = imgs.length ? imgs : null
          const txt = uContent.find((c) => c && c.type === 'text')
          uContent = (txt && txt.text) || '[이미지]'
        }
        messages.value.push({ role: 'user', content: uContent, images: uImages })
        bubble = null
      } else if (m.role === 'assistant') {
        if (!bubble) {
          bubble = reactive({ role: 'assistant', phases: [], approval: null, context: null, state: null, doneMessage: '' })
          messages.value.push(bubble)
        }
        const phase = reactive({
          role: '', model: '', thinking: m.reasoning_content || '', text: m.content || '',
          tools: [], collapsed: true, running: false,
        })
        for (const tc of m.tool_calls || []) {
          let args = {}
          try {
            args = JSON.parse(tc.function.arguments || '{}')
          } catch {}
          const result = toolById[tc.id] || ''
          phase.tools.push({
            name: tc.function.name, args, diff: '',
            status: result.startsWith('오류') ? 'error' : 'done',
            result,
          })
        }
        bubble.phases.push(phase)
      }
    }
    scrollBottom()
  } catch {
  } finally {
    loadingMessages.value = false
  }
}

async function selectRoom(id, isNew = false) {
  stopRunningPoll()
  lastTaskStatus = {}
  sessionRunning.value = false
  searchQuery.value = ''
  searchResults.value = []
  currentRoomId.value = id
  localStorage.setItem('forge_room', id)
  showRooms.value = false
  await loadMessages(isNew)
  await loadTasks()
  checkRunning()
}

async function loadTasks() {
  const id = currentRoomId.value
  if (!id) {
    tasks.value = []
    return
  }
  try {
    const res = await fetch(`/api/rooms/${id}/tasks`)
    if (res.ok) tasks.value = await res.json()
  } catch {}
}

async function createRoom() {
  const name = newRoomName.value.trim()
  if (!name) return
  // 워크스페이스는 필수 — 미선택 시 홈으로 잘못 잡혀 git·skills가 깨진다.
  if (!newRoomPath.value.trim()) {
    alert('워크스페이스 폴더를 선택하세요.')
    return
  }
  try {
    const res = await fetch('/api/rooms', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, workspace_path: newRoomPath.value.trim() }),
    })
    if (res.ok) {
      const room = await res.json()
      newRoomName.value = ''
      newRoomPath.value = ''
      showCreateRoom.value = false
      await loadRooms()
      await selectRoom(room.id, true)
    }
  } catch {}
}

async function deleteRoom(id) {
  if (!confirm('이 세션을 삭제할까요?')) return
  try {
    await fetch(`/api/rooms/${id}`, { method: 'DELETE' })
    await loadRooms()
    if (currentRoomId.value === id) {
      const next = rooms.value[0]
      if (next) {
        await selectRoom(next.id)
      } else {
        currentRoomId.value = ''
        localStorage.removeItem('forge_room')
        messages.value = []
        tasks.value = []
      }
    }
  } catch {}
}

async function renameRoom(id) {
  const room = rooms.value.find((r) => r.id === id)
  const name = prompt('새 세션 이름', room?.title || '')
  if (!name || !name.trim()) return
  try {
    await fetch(`/api/rooms/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: name.trim() }),
    })
    await loadRooms()
  } catch {}
}

async function openWorkspacePicker(roomId) {
  pickerRoomId.value = roomId || null
  showWorkspacePicker.value = true
  const initial = roomId
    ? rooms.value.find((r) => r.id === roomId)?.workspace_path || ''
    : newRoomPath.value
  await navigateFs(initial || '')
}

async function navigateFs(path) {
  try {
    const res = await fetch(`/api/fs/list?path=${encodeURIComponent(path || '')}`)
    if (res.ok) {
      const data = await res.json()
      fsPath.value = data.path
      fsParent.value = data.parent
      fsEntries.value = data.entries
    }
  } catch {}
}

async function pickCurrentPath() {
  if (pickerRoomId.value) {
    try {
      await fetch(`/api/rooms/${pickerRoomId.value}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace_path: fsPath.value }),
      })
      await loadRooms()
    } catch {}
  } else {
    newRoomPath.value = fsPath.value
    if (!newRoomName.value) {
      const parts = fsPath.value.split('/').filter(Boolean)
      newRoomName.value = parts[parts.length - 1] || ''
    }
  }
  showWorkspacePicker.value = false
}

async function ensureRoom(text) {
  if (currentRoomId.value) return currentRoomId.value
  try {
    const res = await fetch('/api/rooms', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: text.slice(0, 40), workspace_path: '' }),
    })
    if (res.ok) {
      const room = await res.json()
      currentRoomId.value = room.id
      localStorage.setItem('forge_room', room.id)
      await loadRooms()
      return room.id
    }
  } catch {}
  return crypto.randomUUID()
}

function scrollBottom() {
  nextTick(() => {
    if (chatEl.value) chatEl.value.scrollTop = chatEl.value.scrollHeight
  })
}

// 하단 근처에 있을 때만 따라 내려간다(읽고 있는 위치를 뺏지 않음).
function maybeScrollBottom() {
  if (isAtBottom.value) scrollBottom()
}

// 버튼용 — 부드럽게 스크롤
function jumpToBottom() {
  if (chatEl.value) chatEl.value.scrollTo({ top: chatEl.value.scrollHeight, behavior: 'smooth' })
  isAtBottom.value = true
}

function onChatScroll() {
  const el = chatEl.value
  if (!el) return
  isAtBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight < 80
}

function newUser(text, images) {
  messages.value.push({ role: 'user', content: text, images: images && images.length ? images : null })
}

function newAssistant() {
  const m = reactive({ role: 'assistant', phases: [], approval: null, context: null, state: null, doneMessage: '', compacted: false, copied: false })
  messages.value.push(m)
  return m
}

const ROLE_LABELS = {
  triage: '분류',
  planner: '계획',
  coder: '구현',
  reviewer: '검토',
  debugger: '디버그',
  chat: '응답',
  vision: '이미지 분석',
}

function startPhase(m, role = '', model = '') {
  m.phases.forEach((p) => {
    p.collapsed = true
    p.running = false
  })
  const p = reactive({ role, model, thinking: '', text: '', tools: [], collapsed: false, running: true })
  m.phases.push(p)
  return p
}

function activePhase(m) {
  if (!m.phases.length) return startPhase(m)
  return m.phases[m.phases.length - 1]
}

function phaseLabel(p) {
  if (p.role && ROLE_LABELS[p.role]) return ROLE_LABELS[p.role]
  const names = p.tools.map((t) => t.name)
  if (names.some((n) => n === 'write_file' || n === 'edit_file')) return '편집'
  if (names.includes('bash')) return '실행'
  if (names.some((n) => ['read_file', 'list_dir', 'grep'].includes(n))) return '탐색'
  return '응답'
}

function phaseStatus(p) {
  if (p.running) return 'running'
  if (p.tools.some((t) => t.status === 'error')) return 'error'
  return 'done'
}

function runningTool(p) {
  return p.tools.find((t) => t.status === 'running')
}

function assistantText(m) {
  const parts = (m.phases || []).map((p) => p.text).filter(Boolean)
  if (m.doneMessage) parts.push(m.doneMessage)
  return parts.join('\n\n').trim()
}

function hasAssistantText(m) {
  return assistantText(m).length > 0
}

async function copyMessage(m) {
  const text = assistantText(m)
  if (!text) return
  // 피드백은 즉시(클립보드 응답을 기다리지 않음)
  m.copied = true
  setTimeout(() => { m.copied = false }, 1500)
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    const ta = document.createElement('textarea')
    ta.value = text
    document.body.appendChild(ta)
    ta.select()
    try { document.execCommand('copy') } catch {}
    document.body.removeChild(ta)
  }
}

function summarizeArgs(args) {
  try {
    const s = JSON.stringify(args)
    return s.length > 80 ? s.slice(0, 80) + '…' : s
  } catch {
    return ''
  }
}

function diffLines(diff) {
  return diff.split('\n')
}

function diffClass(line) {
  if (line.startsWith('+') && !line.startsWith('+++')) return 'add'
  if (line.startsWith('-') && !line.startsWith('---')) return 'del'
  if (line.startsWith('@@')) return 'hunk'
  return ''
}
function handleEvent(evt, assistant) {
  const d = evt.data || {}
  switch (evt.type) {
    case 'role_start':
      startPhase(assistant, d.role, d.model)
      break
    case 'thinking_delta':
      activePhase(assistant).thinking += d.content || ''
      break
    case 'text_delta':
      activePhase(assistant).text += d.content || ''
      break
    case 'tool_call':
      activePhase(assistant).tools.push({ name: d.name, args: d.args, status: 'running', result: '', diff: '' })
      break
    case 'tool_result': {
      const p = activePhase(assistant)
      const t = [...p.tools].reverse().find((x) => x.status === 'running')
      if (t) {
        t.status = (d.result || '').startsWith('오류') ? 'error' : 'done'
        t.result = d.result || ''
        t.diff = d.diff || ''
      }
      break
    }
    case 'compaction':
      assistant.compacted = true
      break
    case 'state_update':
      assistant.state = d
      break
    case 'approval_request':
      assistant.approval = { id: d.id, tool: d.tool, args: d.args }
      break
    case 'approval_granted':
      assistant.approval = null
      break
    case 'question_request':
      activeQuestion.value = { id: d.id, question: d.question, options: d.options || [] }
      questionAnswer.value = ''
      break
    case 'task_update': {
      const newTasks = d.tasks || []
      const labels = { todo: '할 일', planning: '계획', 'in-progress': '진행', in_progress: '진행', review: '검토', debug: '디버그', done: '완료' }
      if (!assistant.taskNotes) assistant.taskNotes = []
      for (const t of newTasks) {
        const prev = lastTaskStatus[t.title]
        if (prev !== t.status) {
          assistant.taskNotes.push({
            title: t.title,
            from: prev ? (labels[prev] || prev) : '',
            to: labels[t.status] || t.status,
            done: t.status === 'done',
          })
        }
      }
      lastTaskStatus = {}
      for (const t of newTasks) lastTaskStatus[t.title] = t.status
      tasks.value = newTasks
      break
    }
    case 'user_injected':
      activePhase(assistant).tools.push({
        name: '사용자 메시지', args: {}, status: 'done', result: d.content || '', diff: '',
      })
      break
    case 'error':
      activePhase(assistant).text += '\n\n오류: ' + (d.message || '')
      break
    case 'context_usage':
      assistant.context = d
      break
    case 'done':
      assistant.phases.forEach((p) => {
        p.running = false
        p.collapsed = true
      })
      if (d.content) assistant.doneMessage = d.content
      break
  }
  maybeScrollBottom()
}

async function steerDuringRun(text) {
  const id = currentRoomId.value
  input.value = ''
  if (steerMode.value === 'switch') {
    // 현재 작업 중단 후, 이 메시지로 새로 시작 (스트림 종료 시 자동 전송)
    try {
      await fetch(`/api/sessions/${id}/cancel`, { method: 'POST' })
    } catch {}
    pendingSend.value = text
  } else {
    // 큐 대기(기본) — 실행 중 에이전트에 주입, 다음 스텝에서 반영
    newUser(text)
    scrollBottom()
    try {
      await fetch(`/api/sessions/${id}/inject`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
      })
    } catch {}
  }
}

function quickAction(text) {
  if (busy.value) return
  input.value = text
  send()
}

function tokenBarPct(t) {
  const roles = adminStats.value?.roles || []
  const max = Math.max(1, ...roles.map((r) => r.tokens || 0))
  return Math.round(((t || 0) / max) * 100)
}

function tokenShare(t) {
  const total = adminStats.value?.total_tokens || 0
  return total ? Math.round(((t || 0) / total) * 100) : 0
}

function toggleAutoApprove() {
  autoApprove.value = !autoApprove.value
  localStorage.setItem('forge_auto_approve', autoApprove.value ? '1' : '0')
  // 실행 중이면 서버에 즉시 반영
  if (busy.value && currentRoomId.value) {
    fetch(`/api/sessions/${currentRoomId.value}/auto-approve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: autoApprove.value }),
    }).catch(() => {})
  }
}

async function send() {
  const text = input.value.trim()
  const imageUrls = attachedImages.value.map((a) => a.url).filter(Boolean)
  const att = attachedText.value
  if (!text && !imageUrls.length && !att) return
  if (busy.value) {
    if (text) await steerDuringRun(text)
    return
  }
  busy.value = true
  input.value = ''
  debug.value = '전송 중…'

  // 백엔드로 보낼 메시지에 파일 내용 포함
  let payloadMsg = text
  if (att) {
    payloadMsg = `첨부 파일: ${att.name}\n\`\`\`\n${att.content}\n\`\`\`${att.truncated ? '\n(파일이 길어 일부만 첨부됨)' : ''}\n\n${text}`.trim()
  }
  const displayText = text || (att ? `[파일: ${att.name}]` : '[이미지]')

  newUser(displayText, imageUrls)
  const assistant = newAssistant()
  isAtBottom.value = true
  scrollBottom()
  attachedImages.value = []
  attachedText.value = null

  try {
    const roomId = await ensureRoom(text || (att ? att.name : '이미지 분석'))
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: roomId, message: payloadMsg, image_urls: imageUrls, auto_approve: autoApprove.value }),
    })
    console.log('[forge] 응답:', res.status, res.headers.get('content-type'))
    if (!res.ok || !res.body) throw new Error('HTTP ' + res.status)
    debug.value = '연결됨'

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let chunkCount = 0
    let eventCount = 0

    while (true) {
      const { done, value } = await reader.read()
      if (done) {
        // 스트림이 done 이벤트 없이 끝나도(에러 등) phase가 running에 멈추지 않도록 마무리
        assistant.phases.forEach((p) => { p.running = false })
        break
      }
      chunkCount++
      const decoded = decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
      if (chunkCount <= 3) console.log('[forge] chunk', chunkCount, value.length, '바이트:', decoded.slice(0, 120))
      buffer += decoded
      let idx
      while ((idx = buffer.indexOf('\n\n')) !== -1) {
        const block = buffer.slice(0, idx)
        buffer = buffer.slice(idx + 2)
        const lines = block.split('\n')
        let data = ''
        for (const line of lines) {
          if (line.startsWith('data: ')) data += line.slice(6)
        }
        if (data) {
          eventCount++
          try {
            const evt = JSON.parse(data)
            if (eventCount <= 5) console.log('[forge] 이벤트', eventCount, ':', evt.type)
            handleEvent({ type: evt.type, data: evt.data }, assistant)
            debug.value = `이벤트 ${eventCount} · ${evt.type}`
          } catch (e) {
            console.log('[forge] 파싱 실패:', e, data.slice(0, 80))
          }
        }
      }
    }
  } catch (err) {
    console.error('[forge] 오류:', err)
    assistant.text += '\n\n오류: ' + (err.message || err)
    debug.value = '오류: ' + (err.message || err)
  } finally {
    busy.value = false
    scrollBottom()
    // '중단 후 새로 시작' 모드로 대기된 메시지가 있으면 현재 스트림 종료 후 전송
    if (pendingSend.value) {
      const t = pendingSend.value
      pendingSend.value = null
      input.value = t
      setTimeout(() => send(), 50)
    }
  }
}

function onKeydown(e) {
  if (e.key !== 'Enter' || e.isComposing) return
  if (!isMobile && !e.shiftKey) {
    e.preventDefault()
    send()
  }
}

function onInput(e) {
  const el = e.target
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 120) + 'px'
}

async function onFileChange(e) {
  const files = Array.from(e.target.files || [])
  for (const file of files) {
    if (file.type.startsWith('image/')) {
      // 이미지 → 업로드(여러 장 누적)
      const formData = new FormData()
      formData.append('file', file)
      try {
        const res = await fetch('/api/upload', { method: 'POST', body: formData })
        if (res.ok) attachedImages.value.push(await res.json())
      } catch {}
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
  e.target.value = ''
}

function removeImage(idx) {
  attachedImages.value.splice(idx, 1)
}

function removeText() {
  attachedText.value = null
}

async function decide(approval, decision) {
  try {
    await fetch(`/api/approvals/${approval.id}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ decision }),
    })
  } catch {}
}

async function answerQuestion(q, answer) {
  if (!answer) return
  activeQuestion.value = null
  try {
    await fetch(`/api/questions/${q.id}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ answer }),
    })
  } catch {}
}

function resetSession() {
  showCreateRoom.value = true
}

// 작업 중 여부를 전역에 노출 — SW 업데이트가 작업 중 리로드하지 않도록(main.js)
watch(busy, (v) => {
  window.__forgeBusy = v
})

applyTheme(theme.value)

onMounted(async () => {
  await loadRooms()
  // 유효한 현재 세션이 없으면 가장 최근 세션으로 랜딩
  const valid = rooms.value.some((r) => r.id === currentRoomId.value)
  if (!valid && rooms.value.length) {
    currentRoomId.value = rooms.value[0].id
    localStorage.setItem('forge_room', currentRoomId.value)
  }
  await loadMessages()
  await loadTasks()
  checkRunning()
})

document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') checkRunning()
})
</script>

<template>
  <div class="app">
    <header>
      <button class="icon-btn" @click="showRooms = true" aria-label="세션 목록">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 6h16M4 12h16M4 18h16"/></svg>
      </button>
      <button class="room-btn" @click="showRooms = true">
        <span class="room-title-main">
          <span class="status-dot" :class="busy ? 'working' : 'idle'"></span>
          {{ currentRoom()?.title || 'FORGE' }}
        </span>
        <span class="room-sub">
          <span v-if="busy" class="status-live">실행 중</span><template v-if="busy"> · </template>{{ shortPath(currentRoom()?.workspace_path) || 'Mobile Coding Agent' }}
        </span>
      </button>
      <button class="todo-btn" @click="showMenu = !showMenu" aria-label="메뉴">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="19" cy="12" r="1.6"/></svg>
      </button>
    </header>

    <div v-if="showMenu" class="menu-overlay" @click="showMenu = false">
      <div class="menu-panel" @click.stop>
        <div class="menu-item" @click="openSessionDetail(); showMenu = false">
          <svg class="ctx menu-ctx-ring" viewBox="0 0 36 36">
            <circle class="ctx-bg" cx="18" cy="18" r="15" pathLength="100" />
            <circle class="ctx-fg" cx="18" cy="18" r="15" pathLength="100" :stroke-dasharray="`${ctxPct(currentRoom())} 100`" :class="ctxClass(ctxPct(currentRoom()))" />
          </svg>
          <span>세션 사용량</span>
          <span class="menu-ctx">Context {{ ctxPct(currentRoom()) }}%</span>
        </div>
        <div class="menu-item" @click="openFiles(); showMenu = false">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>
          <span>파일 브라우저</span>
        </div>
        <div class="menu-item" @click="openGit(); showMenu = false">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><line x1="6" y1="9" x2="6" y2="15"/><path d="M18 6c0 4-6 3-6 9"/></svg>
          <span>Git</span>
        </div>
        <div class="menu-item" @click="showKanban = true; loadTasks(); showMenu = false">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M8 10l2 2 4-4"/><line x1="8" y1="16" x2="16" y2="16"/></svg>
          <span>칸반</span>
        </div>
        <div class="menu-item" @click="openSkills(); showMenu = false">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2L3 14h7l-1 8 10-12h-7z"/></svg>
          <span>Skills</span>
        </div>
        <div class="menu-item" @click="openAdmin(); showMenu = false">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
          <span>관리자</span>
        </div>
        <div class="theme-row">
          <span class="theme-label">테마</span>
          <button
            v-for="t in THEMES"
            :key="t.id"
            class="theme-swatch"
            :class="{ active: theme === t.id }"
            :style="{ background: t.bg }"
            :title="t.label"
            @click.stop="setTheme(t.id)"
          >
            <span class="theme-dot" :style="{ background: t.c }"></span>
          </button>
        </div>
      </div>
    </div>

    <div v-if="showRooms" class="rooms-overlay" @click="showRooms = false">
      <div class="rooms-panel" @click.stop>
        <div class="drawer-head">
          <span class="drawer-title">세션</span>
          <button class="drawer-close" @click="showRooms = false" aria-label="닫기">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>
          </button>
        </div>
        <div class="drawer-search">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4-4"/></svg>
          <input v-model="searchQuery" @input="onSearch" placeholder="세션·대화 검색" />
          <button v-if="searchQuery" class="drawer-search-x" @click="searchQuery=''; searchResults=[]">✕</button>
        </div>
        <div v-if="searchQuery && searchResults.length" class="rooms-scroll">
          <div v-for="r in searchResults" :key="r.session_id" class="search-result" @click="selectRoom(r.session_id)">
            <div class="search-title">{{ roomTitle(r.session_id) }}</div>
            <div class="search-snippet">{{ r.snippet }}</div>
          </div>
        </div>
        <div v-else-if="searchQuery" class="rooms-scroll">
          <div class="admin-sub" style="padding:16px">검색 결과가 없습니다.</div>
        </div>
        <div v-else class="rooms-scroll">
        <div v-for="r in rooms" :key="r.id" class="room-swipe">
          <button class="room-swipe-del" @click.stop="deleteRoom(r.id)">삭제</button>
          <div
            class="room-item"
            :class="{ active: r.id === currentRoomId, swiped: swipedRoomId === r.id }"
            @click="selectRoom(r.id)"
            @touchstart="onRoomTouchStart"
            @touchend="onRoomTouchEnd(r, $event)"
          >
            <span class="room-status" :class="r.id === currentRoomId ? 'active' : 'idle'"></span>
            <div class="room-info">
              <div class="room-title">{{ r.title }}</div>
              <div class="room-path">{{ r.workspace_path || '워크스페이스 설정' }}</div>
            </div>
            <span class="room-pct">Context {{ ctxPct(r) }}%</span>
            <button class="room-more" @click.stop="roomMenuId = roomMenuId === r.id ? null : r.id" aria-label="메뉴">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="19" cy="12" r="1.6"/></svg>
            </button>
          </div>
        </div>
        </div>
        <div class="rooms-add" @click="showCreateRoom = true; showRooms = false">+ 새 세션</div>
      </div>
    </div>

    <div v-if="roomMenuId" class="menu-overlay" @click="roomMenuId = null">
      <div class="menu-panel" @click.stop>
        <div class="menu-item" @click="renameRoom(roomMenuId); roomMenuId = null">이름 변경</div>
        <div v-if="menuRoom() && menuRoom().count === 0" class="menu-item" @click="openWorkspacePicker(roomMenuId); roomMenuId = null">워크스페이스 변경</div>
        <div class="menu-item danger" @click="deleteRoom(roomMenuId); roomMenuId = null">삭제</div>
      </div>
    </div>

    <div v-if="sessionRunning && !busy" class="running-banner" :class="{ waiting: agentStatus && agentStatus.waiting_for }">
      <span class="running-dot"></span>{{ runningBannerText() }}
    </div>

    <main ref="chatEl" @scroll.passive="onChatScroll" @touchstart.passive="onMainTouchStart" @touchend.passive="onMainTouchEnd">
      <div v-if="loadingMessages" class="msg-skeleton">
        <div class="skel-row user"><div class="skel-bubble"></div></div>
        <div class="skel-row"><div class="skel-line w60"></div><div class="skel-line w90"></div><div class="skel-line w75"></div></div>
        <div class="skel-row user"><div class="skel-bubble sm"></div></div>
        <div class="skel-row"><div class="skel-line w80"></div><div class="skel-line w50"></div></div>
      </div>

      <div v-else-if="messages.length === 0" class="welcome">
        <img src="/logo.svg" class="welcome-logo" alt="FORGE" />
        <div class="welcome-brand">FORGE</div>
        <p class="welcome-title">무엇을 작업할까요?</p>
        <p class="sub">{{ shortPath(currentRoom()?.workspace_path) || '워크스페이스 미설정' }}에서 자율로 작업합니다.</p>
        <div class="quick-actions">
          <button class="quick-action" @click="quickAction('이 프로젝트의 구조와 핵심 동작을 파악해서 요약해줘')">프로젝트 파악</button>
          <button class="quick-action" @click="quickAction('현재 git 변경사항을 리뷰해줘')">변경사항 리뷰</button>
          <button class="quick-action" @click="quickAction('git 상태와 최근 커밋을 확인해서 알려줘')">Git 상태 확인</button>
          <button class="quick-action" @click="quickAction('테스트를 실행하고 결과를 알려줘')">테스트 실행</button>
        </div>
      </div>

      <div v-for="(m, i) in messages" :key="i" class="msg" :class="m.role">
        <div class="bubble">
          <template v-if="m.role === 'user'">
            <div v-if="m.images && m.images.length" class="user-images">
              <img v-for="(img, ii) in m.images" :key="ii" :src="img" class="user-image" @click="openViewer(m.images, ii)" alt="첨부 이미지" />
            </div>
            <div v-if="m.content && m.content !== '[이미지]'" class="user-text">{{ m.content }}</div>
          </template>

          <template v-if="m.role === 'assistant'">
            <div v-for="(p, pi) in m.phases" :key="pi" class="activity" :class="[phaseStatus(p), { card: p.tools.length || p.thinking }]">
              <div
                v-if="p.tools.length || p.thinking"
                class="activity-head"
                @click="p.collapsed = !p.collapsed"
              >
                <span class="activity-dot" :class="phaseStatus(p)"></span>
                <span class="activity-label">{{ phaseLabel(p) }}</span>
                <span v-if="p.running && runningTool(p)" class="activity-live">{{ runningTool(p).name }} 실행 중…</span>
                <span v-else-if="p.tools.length" class="activity-count">도구 {{ p.tools.length }}</span>
                <svg class="activity-chevron" :class="{ open: !p.collapsed }" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg>
              </div>

              <div v-if="p.text" class="text" v-html="renderMarkdown(p.text)"></div>

              <template v-if="!p.collapsed">
                <details v-if="p.thinking" class="thinking">
                  <summary>추론</summary>
                  <div class="thinking-body">{{ p.thinking }}</div>
                </details>

                <details
                  v-for="(t, j) in p.tools"
                  :key="j"
                  class="tool"
                  :class="t.status"
                  :open="t.status === 'running' || !!(t.diff && t.diff.length)"
                >
                  <summary>
                    <span class="tool-dot" :class="t.status"></span>
                    <span class="tname">{{ t.name }}</span>
                    <span class="targs">{{ summarizeArgs(t.args) }}</span>
                  </summary>
                  <div v-if="t.diff" class="diff">
                    <div v-for="(line, li) in diffLines(t.diff)" :key="li" :class="diffClass(line)">{{ line || ' ' }}</div>
                  </div>
                  <pre v-else>{{ t.status === 'running' ? '실행 중…' : (t.result || '(출력 없음)') }}</pre>
                </details>
              </template>
            </div>

            <div v-if="(busy || sessionRunning) && i === messages.length - 1" class="typing">
              <span class="typing-label">{{ busy ? '작성 중' : liveActivityText() }}</span>
              <span class="typing-dots"><i></i><i></i><i></i></span>
            </div>

            <div v-if="m.taskNotes && m.taskNotes.length" class="task-notes">
              <div v-for="(tn, ti) in m.taskNotes" :key="ti" class="task-note" :class="{ done: tn.done }">
                <span class="task-note-icon">{{ tn.done ? '✓' : '•' }}</span>
                <span class="task-note-title">{{ tn.title }}</span>
                <span class="task-note-status">{{ tn.from ? tn.from + ' → ' : '' }}{{ tn.to }}</span>
              </div>
            </div>

            <div v-if="(m.state && (m.state.files_changed?.length || m.state.errors?.length)) || m.compacted" class="state-summary">
              <span v-if="m.state?.files_changed?.length" class="state-chip">변경 {{ m.state.files_changed.length }}</span>
              <span v-if="m.state?.errors?.length" class="state-chip err">오류 {{ m.state.errors.length }}</span>
              <span v-if="m.compacted" class="state-chip">컨텍스트 압축됨</span>
            </div>

            <div v-if="m.approval" class="approval">
              <div class="approval-head">도구 실행 승인이 필요합니다</div>
              <div class="approval-tool">{{ m.approval.tool }} — {{ summarizeArgs(m.approval.args) }}</div>
              <div class="approval-btns">
                <button class="ok" @click="decide(m.approval, 'approve')">승인</button>
                <button class="no" @click="decide(m.approval, 'reject')">거부</button>
              </div>
            </div>

            <div v-if="m.doneMessage" class="done-msg">{{ m.doneMessage }}</div>

            <div v-if="m.context && !isLiveTurn(i)" class="context">
              context {{ m.context.prompt_tokens + m.context.completion_tokens }} tokens<span
                v-if="m.context.cache_hit_ratio != null"> · cache {{ Math.round(m.context.cache_hit_ratio * 100) }}%</span>
            </div>

            <div v-if="hasAssistantText(m) && !isLiveTurn(i)" class="msg-actions">
              <button class="msg-action" @click="copyMessage(m)">
                <svg v-if="!m.copied" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
                <svg v-else width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>
                {{ m.copied ? '복사됨' : '복사' }}
              </button>
            </div>
          </template>
        </div>
      </div>
    </main>

    <div v-if="attachedText" class="file-chip">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/></svg>
      <span class="file-chip-name">{{ attachedText.name }}</span>
      <span v-if="attachedText.truncated" class="file-chip-note">일부</span>
      <button class="file-chip-x" @click="removeText" aria-label="제거">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>
      </button>
    </div>

    <div v-if="attachedImages.length" class="image-preview-row">
      <div v-for="(img, ii) in attachedImages" :key="ii" class="image-preview">
        <img :src="img.url" alt="첨부 이미지" @click="openViewer(attachedImages.map((a) => a.url), ii)" />
        <button class="image-remove" @click="removeImage(ii)" aria-label="제거">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>
        </button>
      </div>
    </div>

    <button v-if="!isAtBottom" class="jump-bottom" @click="jumpToBottom" aria-label="맨 아래로">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M5 12l7 7 7-7"/></svg>
    </button>

    <div v-if="viewerImages.length" class="image-viewer" @click="closeViewer"
         @touchstart.passive="viewerTouchStart" @touchend.passive="viewerTouchEnd">
      <img :src="viewerImages[viewerIndex]" alt="이미지" @click.stop />
      <button class="image-viewer-close" @click="closeViewer" aria-label="닫기">✕</button>
      <button v-if="viewerIndex > 0" class="image-viewer-nav prev" @click.stop="viewerPrev" aria-label="이전">‹</button>
      <button v-if="viewerIndex < viewerImages.length - 1" class="image-viewer-nav next" @click.stop="viewerNext" aria-label="다음">›</button>
      <div v-if="viewerImages.length > 1" class="image-viewer-count">{{ viewerIndex + 1 }} / {{ viewerImages.length }}</div>
    </div>

    <footer>
      <input ref="fileInput" type="file" multiple accept="image/*,.md,.txt,.log,.json,.csv,.yml,.yaml,.toml,.py,.js,.ts,.jsx,.tsx,.vue,.html,.css,.sh,.xml,.java,.go,.rs,.c,.cpp,.h,.sql,text/*" hidden @change="onFileChange" />
      <div class="composer">
        <textarea
          v-model="input"
          rows="1"
          class="composer-input"
          :placeholder="busy ? (steerMode === 'switch' ? '중단하고 새로 요청…' : '작업 큐에 메시지 추가…') : '메시지를 입력하세요'"
          @keydown="onKeydown"
          @input="onInput"
        ></textarea>
        <div class="composer-row">
          <button class="attach-btn" @click="fileInput.click()" aria-label="첨부">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M5 12h14"/></svg>
          </button>
          <button class="mode-chip" :class="{ on: autoApprove }" @click="toggleAutoApprove">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M13 2L3 14h7l-1 8 10-12h-7z"/></svg>
            {{ autoApprove ? '자동 승인' : '수동 승인' }}
          </button>
          <template v-if="busy">
            <button class="mode-chip small" :class="{ on: steerMode === 'queue' }" @click="steerMode = 'queue'">작업 대기</button>
            <button class="mode-chip small" :class="{ on: steerMode === 'switch' }" @click="steerMode = 'switch'">계획 수정</button>
          </template>
          <div class="composer-spacer"></div>
          <button id="send" class="composer-send" :disabled="!input.trim() && !attachedImages.length && !attachedText" @click="send" aria-label="전송">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5M6 11l6-6 6 6"/></svg>
          </button>
        </div>
      </div>
    </footer>

    <div v-if="activeQuestion" class="modal-overlay" @click="activeQuestion = null">
      <div class="modal" @click.stop>
        <div class="modal-head">확인이 필요합니다</div>
        <div class="modal-question">{{ activeQuestion.question }}</div>
        <div v-if="activeQuestion.options.length" class="modal-options">
          <button
            v-for="(o, i) in activeQuestion.options"
            :key="i"
            @click="answerQuestion(activeQuestion, o)"
          >{{ o }}</button>
        </div>
        <div v-else class="modal-input">
          <input
            v-model="questionAnswer"
            placeholder="답변을 입력하세요"
            @keydown.enter="answerQuestion(activeQuestion, questionAnswer)"
          />
          <button @click="answerQuestion(activeQuestion, questionAnswer)">보내기</button>
        </div>
      </div>
    </div>

    <div v-if="showCreateRoom" class="modal-overlay" @click="showCreateRoom = false">
      <div class="modal" @click.stop>
        <div class="modal-head">새 세션</div>
        <input v-model="newRoomName" class="modal-field" placeholder="세션 이름" />
        <button type="button" class="modal-field ws-btn" @click="openWorkspacePicker(null)">
          {{ newRoomPath || '워크스페이스 폴더 선택 (선택 사항)' }}
        </button>
        <div class="modal-actions">
          <button class="no" @click="showCreateRoom = false">취소</button>
          <button class="ok" @click="createRoom">만들기</button>
        </div>
      </div>
    </div>

    <div v-if="showKanban" class="kanban-overlay">
      <div class="kanban-head">
        <span class="kanban-title">{{ currentRoom()?.title || 'FORGE' }}</span>
        <button @click="showKanban = false">닫기</button>
      </div>
      <div class="kanban-board">
        <div v-for="col in kanbanCols" :key="col.key" class="kanban-section">
          <div class="kanban-col-head" @click="toggleKanban(col.key)">
            <span>{{ col.label }}</span>
            <span class="kanban-count">{{ tasks.filter((x) => x.status === col.key).length }}</span>
          </div>
          <div v-show="kanbanOpen[col.key]" class="kanban-cards">
            <div
              v-for="t in tasks.filter((x) => x.status === col.key)"
              :key="t.id"
              class="kanban-card"
            >
              <div class="kanban-card-title">{{ t.title }}</div>
              <div class="kanban-bar">
                <div class="kanban-bar-fill" :style="{ width: (t.progress || 0) + '%' }"></div>
              </div>
            </div>
            <div v-if="tasks.filter((x) => x.status === col.key).length === 0" class="kanban-empty">없음</div>
          </div>
        </div>
      </div>
    </div>

    <div v-if="showGit" class="gh-overlay">
      <div class="gh-head">
        <div class="gh-repo">
          <div class="gh-repo-name">{{ currentRoom()?.title || 'FORGE' }}</div>
          <div class="gh-branch">
            <svg width="13" height="13" viewBox="0 0 16 16" fill="currentColor"><path d="M9.5 3.25a2.25 2.25 0 1 1 3 2.122V6A2.5 2.5 0 0 1 10 8.5H6a1 1 0 0 0-1 1v1.128a2.251 2.251 0 1 1-1.5 0V5.372a2.25 2.25 0 1 1 1.5 0v1.836A2.492 2.492 0 0 1 6 7h4a1 1 0 0 0 1-1v-.628A2.25 2.25 0 0 1 9.5 3.25Zm-6 0a.75.75 0 1 0 1.5 0 .75.75 0 0 0-1.5 0Zm8.25-.75a.75.75 0 1 0 0 1.5.75.75 0 0 0 0-1.5ZM4.25 12a.75.75 0 1 0 0 1.5.75.75 0 0 0 0-1.5Z"/></svg>
            <span>{{ gitCurrent || '—' }}</span>
          </div>
        </div>
        <div class="gh-head-actions">
          <button class="gh-icon-btn" :disabled="gitLoading" @click="loadGit" aria-label="새로고침">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 2v6h-6M3 12a9 9 0 0 1 15-6.7L21 8M3 22v-6h6M21 12a9 9 0 0 1-15 6.7L3 16"/></svg>
          </button>
          <button class="gh-close" @click="showGit = false">닫기</button>
        </div>
      </div>

      <div v-if="gitDetail" class="gh-detail">
        <div class="gh-detail-head">
          <button class="gh-back" @click="gitDetail = null">‹ 뒤로</button>
        </div>
        <div class="gh-detail-title">{{ gitDetail.title }}</div>
        <div v-if="gitDetail.sub" class="gh-detail-sub">{{ gitDetail.sub }}</div>
        <div v-if="gitDetail.loading" class="gh-empty">불러오는 중…</div>
        <div v-else-if="gitDetail.diff" class="diff gh-diff">
          <div v-for="(line, li) in diffLines(gitDetail.diff)" :key="li" :class="diffClass(line)">{{ line || ' ' }}</div>
        </div>
        <div v-else class="gh-empty">표시할 변경 내용이 없습니다.</div>
      </div>

      <template v-else>
        <div class="gh-tabs">
          <button :class="{ active: gitTab === 'changes' }" @click="gitTab = 'changes'">
            변경<span v-if="gitFiles.length" class="gh-badge">{{ gitFiles.length }}</span>
          </button>
          <button :class="{ active: gitTab === 'history' }" @click="gitTab = 'history'">히스토리</button>
          <button :class="{ active: gitTab === 'branches' }" @click="gitTab = 'branches'">브랜치</button>
        </div>

        <div v-if="gitError" class="git-error">{{ gitError }}</div>

        <div class="gh-content">
          <template v-if="gitTab === 'changes'">
            <div v-if="gitLoading" class="gh-empty">불러오는 중…</div>
            <div v-else-if="!gitFiles.length" class="gh-empty">변경 사항이 없습니다.</div>
            <div v-for="f in gitFiles" :key="f.path" class="gh-file" @click="openFileDiff(f)">
              <span class="gh-status" :class="f.cls">{{ f.badge }}</span>
              <span class="gh-file-path">{{ f.path }}</span>
              <svg class="gh-chevron" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18l6-6-6-6"/></svg>
            </div>
          </template>

          <template v-else-if="gitTab === 'history'">
            <div v-if="gitLoading" class="gh-empty">불러오는 중…</div>
            <div v-else-if="!gitLog.length" class="gh-empty">커밋이 없습니다.</div>
            <div v-for="c in gitLog" :key="c.hash" class="gh-commit" @click="openCommit(c)">
              <div class="gh-avatar">{{ (c.author || '?').slice(0, 1).toUpperCase() }}</div>
              <div class="gh-commit-body">
                <div class="gh-commit-subject">{{ c.subject }}</div>
                <div class="gh-commit-meta">{{ c.author }} · {{ c.date }} · {{ c.hash }}</div>
              </div>
            </div>
          </template>

          <template v-else>
            <div v-if="!gitBranches.length" class="gh-empty">브랜치가 없습니다.</div>
            <div
              v-for="b in gitBranches"
              :key="b"
              class="gh-branch-row"
              :class="{ current: b === gitCurrent }"
              @click="checkoutBranch(b)"
            >
              <svg width="13" height="13" viewBox="0 0 16 16" fill="currentColor"><path d="M9.5 3.25a2.25 2.25 0 1 1 3 2.122V6A2.5 2.5 0 0 1 10 8.5H6a1 1 0 0 0-1 1v1.128a2.251 2.251 0 1 1-1.5 0V5.372a2.25 2.25 0 1 1 1.5 0v1.836A2.492 2.492 0 0 1 6 7h4a1 1 0 0 0 1-1v-.628A2.25 2.25 0 0 1 9.5 3.25Zm-6 0a.75.75 0 1 0 1.5 0 .75.75 0 0 0-1.5 0Zm8.25-.75a.75.75 0 1 0 0 1.5.75.75 0 0 0 0-1.5ZM4.25 12a.75.75 0 1 0 0 1.5.75.75 0 0 0 0-1.5Z"/></svg>
              <span class="gh-branch-name">{{ b }}</span>
              <span v-if="b === gitCurrent" class="gh-current-tag">현재</span>
            </div>
          </template>
        </div>
      </template>
    </div>

    <div v-if="showSkills" class="kanban-overlay">
      <div class="kanban-head">
        <span class="kanban-title">Skills · 축적된 절차</span>
        <button @click="showSkills = false">닫기</button>
      </div>
      <div class="admin-body">
        <div v-if="!skills.length" class="admin-sub">
          아직 저장된 skill이 없습니다. 에이전트가 반복될 만한 해결 절차를 발견하면 save_skill로 저장합니다.
        </div>
        <div v-for="s in skills" :key="s.name" class="admin-section">
          <div class="skill-head" @click="skillOpen[s.name] = !skillOpen[s.name]">
            <svg class="skill-chevron" :class="{ open: skillOpen[s.name] }" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18l6-6-6-6"/></svg>
            <span class="skill-name">{{ s.name }}</span>
            <button class="skill-del" @click.stop="deleteSkill(s.name)">삭제</button>
          </div>
          <pre v-show="skillOpen[s.name]" class="skill-content">{{ s.content }}</pre>
        </div>
      </div>
    </div>

    <div v-if="showAdmin" class="kanban-overlay">
      <div class="kanban-head">
        <span class="kanban-title">관리자</span>
        <button @click="refreshAdmin">새로고침</button>
        <button @click="showAdmin = false">닫기</button>
      </div>
      <div class="admin-body">
        <div v-if="adminBalance && adminBalance.balance_infos" class="admin-section">
          <div class="admin-stat-title">DeepSeek 잔액</div>
          <div v-for="b in adminBalance.balance_infos" :key="b.currency" class="admin-row">
            <span>{{ b.currency }}</span>
            <span class="admin-big">${{ b.total_balance }}</span>
          </div>
          <a class="admin-charge" href="https://platform.deepseek.com" target="_blank" rel="noopener">충전하러 가기</a>
        </div>
        <div v-if="adminBalance && adminBalance.error" class="admin-section">
          <div class="admin-stat-title">DeepSeek 잔액</div>
          <div class="admin-sub">{{ adminBalance.error }}</div>
        </div>
        <div v-if="adminStats" class="admin-section">
          <div class="admin-stat-title collapsible" @click="togglePolicy">
            <span>Provider / 모델 정책</span>
            <span class="collapsible-right">
              <span v-if="!adminPolicyOpen" class="provider-summary">{{ adminStats.provider }}</span>
              <span class="chevron">{{ adminPolicyOpen ? '▾' : '▸' }}</span>
            </span>
          </div>
          <div v-show="adminPolicyOpen">
            <div class="admin-row"><span>Provider</span><span>{{ adminStats.provider }}</span></div>
            <div v-for="(p, role) in adminStats.policy?.roles" :key="role" class="admin-policy">
              <div class="admin-row">
                <span class="role-name">{{ role }}</span>
                <button class="admin-edit" @click="changeRoleModel(role)">변경</button>
              </div>
              <div class="admin-policy-detail">
                <span class="mono">{{ p.model }}</span>
                <span class="tag">{{ p.thinking ? 'thinking' : 'no-thinking' }} · {{ p.reasoning_effort }}</span>
              </div>
            </div>
          </div>
        </div>
        <div v-if="adminStats" class="admin-section">
          <div class="admin-stat-title">지난 {{ adminStats.days }}일 토큰</div>
          <div class="admin-big">{{ formatTokens(adminStats.total_tokens) }} tokens</div>
          <div class="admin-sub">
            prompt {{ formatTokens(adminStats.total_prompt) }} · completion
            {{ formatTokens(adminStats.total_completion) }}
          </div>
        </div>
        <div v-if="adminStats" class="admin-section">
          <div class="admin-stat-title">에이전트 호출 ({{ adminStats.days }}일)</div>
          <div v-for="r in adminStats.roles" :key="r.role" class="admin-row">
            <span>{{ r.role }}</span>
            <span>{{ r.count }}회 · {{ r.percent }}%</span>
          </div>
          <div v-if="!adminStats.roles.length" class="admin-sub">기록 없음</div>
        </div>
        <div v-if="adminStats" class="admin-section">
          <div class="admin-stat-title">에이전트 토큰 소비 ({{ adminStats.days }}일)</div>
          <div v-for="r in adminStats.roles" :key="r.role" class="token-row">
            <div class="token-row-head">
              <span>{{ r.role }}</span>
              <span class="mono">{{ formatTokens(r.tokens) }} · {{ tokenShare(r.tokens) }}%</span>
            </div>
            <div class="token-bar">
              <div class="token-bar-fill" :style="{ width: tokenBarPct(r.tokens) + '%' }"></div>
            </div>
          </div>
          <div v-if="!adminStats.roles.length" class="admin-sub">기록 없음</div>
        </div>
        <div v-if="adminStats" class="admin-section">
          <div class="admin-stat-title">세션별 실행 이력</div>
          <div v-for="room in adminStats.rooms" :key="room.session_id" class="admin-row">
            <span>{{ roomTitle(room.session_id) }}</span>
            <span>{{ room.count }}회</span>
          </div>
          <div v-if="!adminStats.rooms.length" class="admin-sub">기록 없음</div>
        </div>

        <div class="admin-section">
          <div class="admin-stat-title collapsible" @click="adminErrorsOpen = !adminErrorsOpen">
            <span>에러 로그</span>
            <div class="collapsible-right">
              <span class="provider-summary">{{ adminErrors.length }}건</span>
              <span class="chevron">{{ adminErrorsOpen ? '▾' : '▸' }}</span>
            </div>
          </div>
          <template v-if="adminErrorsOpen">
            <div v-if="!adminErrors.length" class="admin-sub">기록된 에러가 없습니다.</div>
            <div v-for="(e, i) in adminErrors" :key="i" class="err-item">
              <div class="err-meta">{{ e.at }} · {{ e.source }}</div>
              <div class="err-msg">{{ e.message }}</div>
            </div>
          </template>
        </div>

        <div class="admin-version">v{{ version }}</div>
      </div>
    </div>

    <div v-if="showSessionDetail" class="kanban-overlay">
      <div class="kanban-head">
        <span class="kanban-title">{{ currentRoom()?.title || '세션' }} · 사용량</span>
        <button @click="showSessionDetail = false">닫기</button>
      </div>
      <div class="admin-body">
        <div class="admin-section">
          <div class="admin-stat-title">컨텍스트 윈도우 (최근 호출)</div>
          <div class="admin-big">{{ ctxPct(currentRoom()) }}%</div>
          <div class="ctx-bar">
            <div class="ctx-bar-fill" :class="ctxClass(ctxPct(currentRoom()))" :style="{ width: ctxPct(currentRoom()) + '%' }"></div>
          </div>
          <div class="admin-sub">
            {{ formatTokens(currentRoom()?.used_tokens) }} / {{ formatTokens(currentRoom()?.logical_budget) }} tokens
          </div>
        </div>

        <div class="admin-section">
          <div class="admin-stat-title">누적 토큰 (세션 전체)</div>
          <div class="admin-big">{{ formatTokens(sessionTokenTotals().total) }}</div>
          <div class="admin-sub">
            prompt {{ formatTokens(sessionTokenTotals().prompt) }} · completion {{ formatTokens(sessionTokenTotals().completion) }}
          </div>
        </div>

        <div v-if="sessionMetrics" class="admin-section">
          <div class="admin-stat-title">효율 계측</div>
          <div class="metric-grid">
            <div class="metric-cell"><span class="metric-num">{{ Math.round((sessionMetrics.cache_hit_ratio || 0) * 100) }}%</span><span class="metric-lbl">cache 적중</span></div>
            <div class="metric-cell"><span class="metric-num">{{ sessionMetrics.total_model_calls || 0 }}</span><span class="metric-lbl">model 호출</span></div>
            <div class="metric-cell"><span class="metric-num">{{ sessionMetrics.total_tool_calls || 0 }}</span><span class="metric-lbl">tool 호출</span></div>
            <div class="metric-cell"><span class="metric-num">{{ sessionMetrics.pro_calls || 0 }}</span><span class="metric-lbl">Pro 호출</span></div>
            <div class="metric-cell"><span class="metric-num">{{ sessionMetrics.total_compactions || 0 }}</span><span class="metric-lbl">압축</span></div>
            <div class="metric-cell"><span class="metric-num">{{ sessionMetrics.total_retries || 0 }}</span><span class="metric-lbl">재시도</span></div>
          </div>
          <div v-if="sessionMetrics.estimated_cost != null" class="admin-sub">추정 비용 ${{ sessionMetrics.estimated_cost.toFixed(4) }} · 상태 {{ sessionMetrics.final_status || '—' }}</div>
          <div v-if="sessionMetrics.selected_skills" class="admin-sub">skill: {{ sessionMetrics.selected_skills }}</div>
          <div v-for="(b, bi) in (sessionMetrics.bottlenecks || [])" :key="bi" class="metric-warn">⚠ {{ b }}</div>
        </div>

        <div class="admin-section">
          <div class="admin-stat-title">에이전트별 사용량</div>
          <div v-for="a in sessionRoleBreakdown()" :key="a.role" class="admin-row">
            <span>{{ a.role }} <span class="run-count">×{{ a.count }}</span></span>
            <span class="mono">{{ formatTokens(a.total) }}</span>
          </div>
          <div v-if="!sessionRuns.length" class="admin-sub">기록 없음</div>
        </div>

        <div v-if="sessionRuns.length" class="admin-section">
          <div class="admin-stat-title">실행 이력</div>
          <div v-for="(r, i) in sessionRuns" :key="i" class="run-item">
            <div class="run-head">
              <span class="run-role">{{ r.role }}</span>
              <span class="run-model">{{ r.model }}</span>
            </div>
            <div class="run-meta">
              prompt {{ formatTokens(r.prompt_tokens) }} · completion {{ formatTokens(r.completion_tokens) }}<span v-if="r.thinking_enabled"> · thinking {{ r.reasoning_effort }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div v-if="showFiles" class="fs-overlay">
      <div class="fs-head">
        <button @click="showFiles = false">닫기</button>
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
        <button v-if="viewingFile" @click="viewingFile = ''; fileContent = ''">목록</button>
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
          @click="e.is_dir ? navigateFiles(e.path) : openFile(e.path)"
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
      <pre v-else class="file-view">{{ fileContent }}</pre>
    </div>

    <div v-if="showModelPicker" class="modal-overlay" style="z-index: 400" @click="showModelPicker = false">
      <div class="modal" @click.stop>
        <div class="modal-head">{{ pickerRole }} 모델 선택</div>
        <div
          v-for="m in AVAILABLE_MODELS"
          :key="m"
          class="model-option"
          @click="selectModel(m)"
        >{{ m }}</div>
      </div>
    </div>

    <div v-if="showWorkspacePicker" class="fs-overlay">
      <div class="fs-head">
        <button @click="showWorkspacePicker = false">취소</button>
        <span class="fs-title">{{ fsPath }}</span>
        <button class="fs-done" @click="pickCurrentPath">선택</button>
      </div>
        <div class="fs-list">
          <button v-if="fsParent" class="fs-item parent" @click="navigateFs(fsParent)">.. 상위 폴더</button>
          <button
            v-for="e in fsEntries.filter((x) => x.is_dir)"
            :key="e.path"
            class="fs-item dir"
            @click="navigateFs(e.path)"
          >
            {{ e.name }}
          </button>
        </div>
    </div>
  </div>
</template>
