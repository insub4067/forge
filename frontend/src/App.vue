<script setup>
import { ref, reactive, nextTick, onMounted, watch, computed } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import 'highlight.js/styles/github-dark.css'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import FileViewer from './components/FileViewer.vue'
import GitPanel from './components/GitPanel.vue'
import AdminPanel from './components/AdminPanel.vue'
import PushPanel from './components/PushPanel.vue'
import KanbanPanel from './components/KanbanPanel.vue'
import MenuPanel from './components/MenuPanel.vue'
import SessionDetailPanel from './components/SessionDetailPanel.vue'
import { balance as adminBalance, loadBalance } from './store'
import '@xterm/xterm/css/xterm.css'

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
// 모델 티어(클로드식 선택) — auto: flash+think, 막히면 pro 승격 / pro: 항상 pro / flash: flash만
const _savedTier = localStorage.getItem('forge_model_tier') || 'auto'
const modelTier = ref(_savedTier === 'ox' ? 'auto' : _savedTier)  // Ox 제거 — 기존 ox 세션은 auto로
const showModelPick = ref(false)
const MODEL_TIERS = [
  { key: 'auto', label: '자동', desc: 'Flash로 처리하고 막히면 Pro로 승격 (권장·균형)' },
  { key: 'pro', label: '프로', desc: '항상 Pro — 가장 정확, 비용 높음' },
  { key: 'flash', label: '플래시', desc: 'Flash만 — 가장 빠르고 저렴, 승격 없음' },
]
function pickModel(key) {
  modelTier.value = key
  localStorage.setItem('forge_model_tier', key)
  showModelPick.value = false
}
function tierLabel() {
  return (MODEL_TIERS.find((t) => t.key === modelTier.value) || MODEL_TIERS[0]).label
}
// 에이전트 모드 — auto: FORGE가 복잡도로 판단 / multi: 계획→구현→리뷰 3역할 / single: 올인원 Developer
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

async function deleteSkill(name, scope = 'workspace') {
  const id = currentRoomId.value
  if (!id || !confirm(`skill '${name}'을 삭제할까요?`)) return
  try {
    await fetch(`/api/rooms/${id}/skills/${encodeURIComponent(name)}?scope=${scope}`, { method: 'DELETE' })
    await openSkills()
  } catch {}
}
const activeQuestion = ref(null)
const activeApproval = ref(null) // 스트림 끊긴 사이 뜬 승인 요청 복구용
const questionAnswer = ref('')
const debug = ref('대기 중')

const rooms = ref([])
const currentRoomId = ref(localStorage.getItem('forge_room') || '')
const loadingMessages = ref(false)
const showRooms = ref(false)
const isWide = ref(false) // 넓은 화면(맥) 여부
const pinnedSidebar = ref(localStorage.getItem('forge_sidebar_pinned') !== '0') // 고정 여부(기본 고정)
const sidebarTab = ref('sessions') // sessions | jobs | mac
function togglePin() {
  pinnedSidebar.value = !pinnedSidebar.value
  localStorage.setItem('forge_sidebar_pinned', pinnedSidebar.value ? '1' : '0')
}
const showCreateRoom = ref(false)
const newRoomName = ref('')
const newRoomPath = ref('')
// 예약 작업(Scheduled Jobs)
const jobs = ref([])
const showJobForm = ref(false)
const jobForm = ref({ name: '', prompt: '', workspace_path: '', schedule: 'once', at: '', time: '09:00', interval: 60 })
// 맥 탭 서브뷰: '' | 'screen' | 'terminal' | 'camera'
const macView = ref('')
const macControls = ref(true) // 유튜브형: 화면 탭하면 컨트롤 토글
const screenOn = ref(false)
const screenSrc = ref('')
const screenErr = ref('')
let screenSeq = 0
const caffeineOn = ref(false)
const camOn = ref(false)
const camSrc = ref('')
const camErr = ref('')
let camSeq = 0
let camWarmup = 0
const tasks = ref([])
// 칸반 카드 상태 변경을 채팅에 알리기 위한 직전 상태 스냅샷(title→status).
const showKanban = ref(false)
const showWorkspacePicker = ref(false)
const fsPath = ref('')
const fsParent = ref(null)
const fsEntries = ref([])
const swipedRoomId = ref(null)
const swipedJobId = ref(null)
const pickerRoomId = ref(null)
const roomMenuId = ref(null)
const roomMenuPos = ref({ top: 0, left: 0 })
function openRoomMenu(id, e) {
  if (roomMenuId.value === id) { roomMenuId.value = null; return }
  const r = e.currentTarget.getBoundingClientRect()
  const w = 170
  const left = Math.max(8, Math.min(r.right - w, window.innerWidth - w - 8))
  const top = Math.min(r.bottom + 4, window.innerHeight - 160)
  roomMenuPos.value = { top, left }
  roomMenuId.value = id
}
const showGit = ref(false)
const steerMode = ref('queue') // 'queue' = 작업큐 대기(기본), 'switch' = 중단 후 새로 시작
const pendingSend = ref(null)
const showFiles = ref(false)
const showHidden = ref(false)
const filePath = ref('')
const fileParent = ref(null)
const fileEntries = ref([])
const viewingFile = ref('')
const showMenu = ref(false)
const showAdmin = ref(false)
const showPush = ref(false)
const showSessionDetail = ref(false)
// 잔액 영역 탭 → "충전 화면으로 이동하시겠습니까?" 팝업
const showTopUpConfirm = ref(false)
function openTopUpConfirm() {
  if (adminBalance.value && adminBalance.value.ok) showTopUpConfirm.value = true
}
function goTopUp() {
  const url = (adminBalance.value && adminBalance.value.top_up_url) || 'https://platform.deepseek.com/top_up'
  window.open(url, '_blank', 'noopener')
  showTopUpConfirm.value = false
}
const attachedImages = ref([]) // 여러 장 첨부
const viewerImages = ref([]) // 전체화면 뷰어 이미지 목록
const viewerIndex = ref(0)
const imgScale = ref(1)
const imgTx = ref(0)
const imgTy = ref(0)
function resetImgZoom() { imgScale.value = 1; imgTx.value = 0; imgTy.value = 0 }
function openViewer(images, index = 0) {
  viewerImages.value = Array.isArray(images) ? images : [images]
  viewerIndex.value = index
  resetImgZoom()
}
function closeViewer() { viewerImages.value = [] }
function viewerNext() { if (viewerIndex.value < viewerImages.value.length - 1) { viewerIndex.value++; resetImgZoom() } }
function viewerPrev() { if (viewerIndex.value > 0) { viewerIndex.value--; resetImgZoom() } }
let viewerTouchX = 0
let _imgPinchDist = 0, _imgPinchScale = 1
let _imgPanX = 0, _imgPanY = 0, _imgStartTx = 0, _imgStartTy = 0
function viewerTouchStart(e) {
  if (e.touches.length === 2) {
    _imgPinchDist = _touchDist(e.touches)
    _imgPinchScale = imgScale.value
  } else if (e.touches.length === 1) {
    viewerTouchX = e.touches[0].clientX
    _imgPanX = e.touches[0].clientX; _imgPanY = e.touches[0].clientY
    _imgStartTx = imgTx.value; _imgStartTy = imgTy.value
  }
}
function viewerTouchMove(e) {
  if (e.touches.length === 2 && _imgPinchDist) {
    e.preventDefault()
    imgScale.value = Math.max(1, Math.min(5, _imgPinchScale * (_touchDist(e.touches) / _imgPinchDist)))
  } else if (e.touches.length === 1 && imgScale.value > 1) {
    e.preventDefault()
    imgTx.value = _imgStartTx + (e.touches[0].clientX - _imgPanX)
    imgTy.value = _imgStartTy + (e.touches[0].clientY - _imgPanY)
  }
}
function viewerTouchEnd(e) {
  if (imgScale.value > 1) return // 줌 중엔 스와이프 내비게이션 안 함(팬 우선)
  const dx = e.changedTouches[0].clientX - viewerTouchX
  if (Math.abs(dx) > 40) { dx < 0 ? viewerNext() : viewerPrev() }
}
const attachedText = ref(null) // { name, content, truncated }
const fileInput = ref(null)
// 레거시 status를 신뢰성 4단계로 정규화는 KanbanPanel 내부에서 처리.
let touchStartX = 0
let touchStartY = 0
let runningPoll = null
let eventPollTimer = null

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
  // 승인도 동일하게 복구 — 리로드로 스트림이 끊기면 인라인 승인 버튼이 사라져 막힌다
  if (st.waiting_for === 'approval' && st.pending) {
    if (!activeApproval.value) activeApproval.value = st.pending // {id, tool, args}
  } else {
    activeApproval.value = null
  }
  return st
}

let wasRunning = false

// 단일 진실 = 서버 /status. 방이 열려있는 동안 항상 폴링해 클라 상태를 서버로 수렴시킨다.
async function checkRunning() {
  const id = currentRoomId.value
  if (!id) return
  if (!busy.value) await fetchStatus(id).catch(() => {})
  startRunningPoll()
}

// 포그라운드 복귀 시 stale 상태 수렴. 모바일 백그라운드에서 SSE reader.read()가 끊기지 않고
// 무한 대기하면 busy가 true로 고착돼 '실행 중'이 남고 폴링도 건너뛴다. 복귀하면 서버 진실을
// 강제로 확인해, busy 중이어도 서버가 idle이면 busy를 풀고 최종 결과를 DB에서 반영한다.
async function reconcileOnResume() {
  const id = currentRoomId.value
  if (id && busy.value) {
    const st = await fetchStatus(id).catch(() => null)
    if (st && !st.running) {
      busy.value = false // 죽은 스트림의 stale '실행 중' 해제
      await loadMessages(true) // 스트림으로 못 받은 최종 결과 반영
    }
  }
  checkRunning()
}

function startRunningPoll() {
  if (runningPoll) return
  runningPoll = setInterval(async () => {
    const id = currentRoomId.value
    if (!id) return stopRunningPoll()
    if (busy.value) return // SSE 스트림이 주도 중이면 폴링 생략(중복 방지)
    try {
      const st = await fetchStatus(id) // sessionRunning/agentStatus 갱신(단일 진실)
      const running = !!(st && st.running)
      if (running) {
        loadTasks() // 실행 중엔 칸반 라이브 갱신(스트림 끊겨도 최신)
      } else if (wasRunning) {
        await loadMessages(true) // 방금 끝남 → 결과 1회 반영
      }
      wasRunning = running
    } catch {}
  }, 3000)
}

function stopRunningPoll() {
  wasRunning = false
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
  // 경과 시간은 5초 넘게 멈췄을 때만 노출 — 숫자가 커지면 곧 '멈춤 조짐' 신호.
  const idle = s.idle_seconds != null && s.idle_seconds > 5 ? ` · ${Math.round(s.idle_seconds)}초째 대기` : ''
  if (s.activity) return `${role ? role + ' · ' : ''}${s.activity}${idle}`
  if (role) return `${role} 진행 중${idle}`
  return 'Mac에서 작업 진행 중'
}
// 도구 이름 → 지금 무슨 일인지. 프론트가 상태를 만들어내지 않고, 백엔드가 보낸
// 도구 이름·검증 이벤트만 사람 말로 옮긴다. 모르면 '작업 중'.
const TOOL_WORK = {
  read_file: '분석 중', list_dir: '분석 중', grep: '분석 중',
  write_file: '구현 중', edit_file: '구현 중',
  bash: '실행 중', build_frontend: '검증 중',
  update_tasks: '작업 중', save_skill: '정리 중', ask_user: '답변 대기',
}

// 하네스가 all_messages에 넣는 프로세스 메시지(role:user)를 사용자 발화와 구분한다.
// 모델 컨텍스트에는 원문이 남지만, 화면엔 회원님 말풍선 대신 흐린 한 줄로 보인다.
function processNote(content) {
  const t = typeof content === 'string' ? content : ''
  if (t.startsWith('[프로세스 확인]')) return '프로세스 — 변경 없이 끝나려 해 이어서 진행'
  if (t.startsWith('[검증 실패')) return '프로세스 — 검증 실패, 수리 재시도'
  return ''
}

function typingLabel(m) {
  if (!busy.value) return liveActivityText()
  // 검증/복구는 프로세스가 보낸 이벤트로만 표시한다(추측 없음).
  if (m.verifyPhase) return m.verifyPhase
  const p = m.phases[m.phases.length - 1]
  const t = p && p.tools.find((x) => x.status === 'running')
  if (t) return TOOL_WORK[t.name] || '작업 중'
  if (p && p.text) return '작성 중'
  return '작업 중'
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
let scrollLocked = false
let scrollUnlockTimer = null
let scrollRaf = null

function onMainTouchStart(e) {
  mainStartX = e.touches[0].clientX
  mainStartY = e.touches[0].clientY
  // 사용자가 스크롤 조작하는 동안 auto-scroll 잠금(스트리밍이 위로 읽기를 방해하지 않게)
  scrollLocked = true
  if (scrollUnlockTimer) clearTimeout(scrollUnlockTimer)
  if (scrollRaf) { cancelAnimationFrame(scrollRaf); scrollRaf = null }
}

function onMainTouchEnd(e) {
  // 손 뗀 뒤 관성 스크롤 여유를 두고 잠금 해제
  if (scrollUnlockTimer) clearTimeout(scrollUnlockTimer)
  scrollUnlockTimer = setTimeout(() => { scrollLocked = false }, 400)
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

function onJobTouchEnd(j, e) {
  const dx = e.changedTouches[0].clientX - touchStartX
  const dy = e.changedTouches[0].clientY - touchStartY
  if (Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy)) {
    swipedJobId.value = dx < 0 ? j.id : null
  }
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

function openAdmin() {
  showAdmin.value = true
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
  if (showWorkspacePicker.value) navigateFs(fsPath.value)
  else navigateFiles(filePath.value)
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
  const url = `/api/fs/raw?path=${encodeURIComponent(e.path)}&session_id=${currentRoomId.value}`
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

function openFiles() {
  showFiles.value = true
  const room = currentRoom()
  navigateFiles(room?.workspace_path || '')
}

const chatEl = ref(null)


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
  stopEventPolling()   // 이전 방의 이벤트 폴러가 새 방을 옛 seq로 폴링하던 버그 방지
  sessionRunning.value = false
  searchQuery.value = ''
  searchResults.value = []
  currentRoomId.value = id
  localStorage.setItem('forge_room', id)
  showRooms.value = false
  await loadMessages(isNew)
  await loadTasks()
  await loadRefinements()
  checkRunning()
}

// 검색 결과 클릭 → 방을 열고 매칭 메시지로 스크롤+하이라이트
async function jumpToMessage(r) {
  const q = (searchQuery.value || '').toLowerCase()
  await selectRoom(r.session_id)
  await nextTick()
  setTimeout(() => {
    const idx = messages.value.findIndex((m) => {
      const c = m.content
      const t =
        typeof c === 'string'
          ? c
          : Array.isArray(c)
          ? c.map((x) => (x && x.text) || '').join(' ')
          : JSON.stringify(c || '')
      return q && t.toLowerCase().includes(q)
    })
    if (idx < 0) return
    const el = document.querySelector(`[data-msg-idx="${idx}"]`)
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' })
      el.classList.add('msg-highlight')
      setTimeout(() => el.classList.remove('msg-highlight'), 2000)
    }
  }, 160)
}

// 지금 무슨 태스크를 하는지 한 줄 — 스크롤 위치와 무관하게 composer 위에 고정.
// 상태는 백엔드 task_update가 준 그대로 쓴다.
const taskBar = computed(() => {
  const list = tasks.value || []
  if (!list.length || !(busy.value || sessionRunning.value)) return null
  const cur =
    list.find((t) => t.status === 'working') ||
    list.find((t) => t.status === 'testing') ||
    list.find((t) => t.status === 'todo')
  return {
    title: cur ? cur.title : '마무리 중',
    done: list.filter((t) => t.status === 'done').length,
    total: list.length,
  }
})

// 학습 후보(RefinementCandidate) — 실행 근거로 만들어진 개선안. 승인해도 자동 적용은 없다.
const refinements = ref([])

async function loadRefinements() {
  const id = currentRoomId.value
  if (!id) {
    refinements.value = []
    return
  }
  try {
    const res = await fetch(`/api/rooms/${id}/refinements`)
    if (res.ok) refinements.value = (await res.json()).refinements || []
  } catch {}
}

async function decideRefinement(r, decision) {
  try {
    await fetch(`/api/refinements/${r.id}/decide`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ decision }),
    })
    await loadRefinements()
  } catch {}
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
  const name = newRoomName.value.trim() || 'Forge'
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

// ─── 예약 작업(Scheduled Jobs) ───
async function loadJobs() {
  try {
    const r = await fetch('/api/jobs')
    jobs.value = (await r.json()).jobs || []
  } catch {}
}

// 폼 입력(로컬 시각/반복)을 next_run_at(ISO)+recurrence로 변환.
function jobPayload(f) {
  const p = {
    name: f.name.trim(),
    prompt: f.prompt.trim(),
    // 워크스페이스 미지정 → 백엔드가 예약 작업 전용 폴더를 자동 생성(현재 방 워크스페이스 상속 안 함)
    workspace_path: f.workspace_path || '',
    recurrence: '',
    recurrence_value: '',
  }
  const now = new Date()
  if (f.schedule === 'once') {
    p.next_run_at = f.at ? new Date(f.at).toISOString() : new Date(now.getTime() + 60000).toISOString()
  } else if (f.schedule === 'interval') {
    p.recurrence = 'interval'
    p.recurrence_value = String(f.interval || 60)
    p.next_run_at = new Date(now.getTime() + (f.interval || 60) * 60000).toISOString()
  } else if (f.schedule === 'daily') {
    p.recurrence = 'daily'
    p.recurrence_value = f.time || '09:00'
    const [hh, mm] = (f.time || '09:00').split(':').map(Number)
    const nxt = new Date(now)
    nxt.setHours(hh, mm, 0, 0)
    if (nxt <= now) nxt.setDate(nxt.getDate() + 1)
    p.next_run_at = nxt.toISOString()
  }
  return p
}

async function createJob() {
  const f = jobForm.value
  if (!f.name.trim() || !f.prompt.trim()) {
    alert('이름과 작업 내용을 입력하세요.')
    return
  }
  try {
    await fetch('/api/jobs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(jobPayload(f)),
    })
    jobForm.value = { name: '', prompt: '', workspace_path: '', schedule: 'once', at: '', time: '09:00', interval: 60 }
    showJobForm.value = false
    await loadJobs()
  } catch {}
}

async function toggleJob(job) {
  try {
    await fetch(`/api/jobs/${job.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: !job.enabled }),
    })
    await loadJobs()
  } catch {}
}

async function deleteJob(id) {
  if (!confirm('이 예약 작업을 삭제할까요?')) return
  try {
    await fetch(`/api/jobs/${id}`, { method: 'DELETE' })
    await loadJobs()
  } catch {}
}

async function runJobNow(id) {
  try {
    await fetch(`/api/jobs/${id}/run`, { method: 'POST' })
    setTimeout(loadJobs, 800)
  } catch {}
}

function jobScheduleLabel(job) {
  if (job.recurrence === 'interval') return `${job.recurrence_value}분마다`
  if (job.recurrence === 'daily') return `매일 ${job.recurrence_value}`
  return '1회'
}

function fmtTime(iso) {
  if (!iso) return '—'
  const d = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z')
  return d.toLocaleString('ko-KR', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function switchSidebarTab(tab) {
  sidebarTab.value = tab
  closeMacView()
  if (tab === 'jobs') loadJobs()
  if (tab === 'mac') loadCaffeine()
}

async function loadCaffeine() {
  try {
    caffeineOn.value = !!(await (await fetch('/api/mac/caffeinate')).json()).on
  } catch {}
}
async function toggleCaffeine() {
  const next = !caffeineOn.value
  caffeineOn.value = next // 낙관적 업데이트
  try {
    const r = await fetch('/api/mac/caffeinate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ on: next }),
    })
    caffeineOn.value = !!(await r.json()).on
  } catch {
    caffeineOn.value = !next
  }
}

// ─── 맥: 화면 보기 (screencapture 폴링) ───
function openMacScreen() {
  macView.value = 'screen'
  macControls.value = true
  startScreen()
  // 지원 브라우저(안드로이드 등)는 실제 가로 잠금. iOS는 미지원 → CSS 회전으로 대체.
  try {
    screen.orientation?.lock?.('landscape').catch(() => {})
  } catch {}
}
function startScreen() {
  screenOn.value = true
  screenErr.value = ''
  screenTick()
}
function stopScreen() {
  screenOn.value = false
}
function screenTick() {
  if (!screenOn.value) return
  screenSrc.value = `/api/mac/screen?d=1&t=${Date.now()}_${screenSeq++}`
}
function onScreenLoad() {
  screenErr.value = ''
  if (screenOn.value) setTimeout(screenTick, 500)
}
function onScreenError() {
  screenErr.value = '화면을 가져오지 못했습니다. 시스템 설정 › 개인정보 보호 › 화면 기록에서 백엔드(터미널/파이썬)에 권한을 허용하세요.'
  screenOn.value = false
}
function closeMacView() {
  stopScreen()
  stopTerminal()
  stopCamera()
  macView.value = ''
  macControls.value = true // 다음에 열 때 컨트롤 보이게
  try {
    screen.orientation?.unlock?.()
  } catch {}
}

// ─── 맥: 터미널 연결 (PTY + WebSocket + xterm) ───
const termEl = ref(null)
let term = null
let termFit = null
let termWs = null

async function openMacTerminal() {
  macView.value = 'terminal'
  macControls.value = true
  await nextTick()
  if (!termEl.value) return
  term = new Terminal({
    fontSize: 13,
    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
    theme: { background: '#000000', foreground: '#e6e6e6' },
    cursorBlink: true,
  })
  termFit = new FitAddon()
  term.loadAddon(termFit)
  term.open(termEl.value)
  termFit.fit()
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  const sid = currentRoomId.value || ''
  termWs = new WebSocket(`${proto}://${location.host}/api/terminals/ws?session_id=${sid}&cols=${term.cols}&rows=${term.rows}`)
  termWs.onmessage = (e) => term && term.write(e.data)
  termWs.onclose = () => term && term.write('\r\n\x1b[90m[연결 종료]\x1b[0m\r\n')
  term.onData((d) => termWs && termWs.readyState === 1 && termWs.send(JSON.stringify({ type: 'input', data: d })))
  term.onResize(({ cols, rows }) => termWs && termWs.readyState === 1 && termWs.send(JSON.stringify({ type: 'resize', cols, rows })))
  window.addEventListener('resize', fitTerminal)
}

function fitTerminal() {
  try { termFit && termFit.fit() } catch {}
}

function termKey(seq) {
  if (termWs && termWs.readyState === 1) termWs.send(JSON.stringify({ type: 'input', data: seq }))
  term && term.focus()
}

function stopTerminal() {
  window.removeEventListener('resize', fitTerminal)
  if (termWs) { try { termWs.close() } catch {} termWs = null }
  if (term) { try { term.dispose() } catch {} term = null }
  termFit = null
}

// ─── 맥: 카메라 보기 (ffmpeg avfoundation 폴링) ───
function openMacCamera() {
  macView.value = 'camera'
  macControls.value = true
  camOn.value = true
  camErr.value = ''
  camTick()
}
function camTick() {
  if (!camOn.value) return
  camSrc.value = `/api/mac/camera?t=${Date.now()}_${camSeq++}`
}
function onCamLoad() {
  camErr.value = ''
  if (camOn.value) setTimeout(camTick, 400)
}
function onCamError() {
  camErr.value = '카메라를 가져오지 못했습니다. imagesnap 설치(brew install imagesnap) 및 시스템 설정 › 개인정보 보호 › 카메라 권한을 확인하세요.'
  camOn.value = false
}
function stopCamera() {
  camOn.value = false
  camSrc.value = ''
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

// 피커 검색 — 지금 보는 폴더 안에서 이름으로 거른다(디스크 전체 탐색 아님).
const fsFilter = ref('')
const fsVisible = computed(() => {
  const q = fsFilter.value.trim().toLowerCase()
  return q ? fsEntries.value.filter((e) => e.name.toLowerCase().includes(q)) : fsEntries.value
})

async function navigateFs(path) {
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
    const parts = fsPath.value.split('/').filter(Boolean)
    newRoomName.value = parts[parts.length - 1] || 'Forge'
  }
  showWorkspacePicker.value = false
}

async function ensureRoom(text) {
  if (currentRoomId.value) return currentRoomId.value
  try {
    const res = await fetch('/api/rooms', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: 'Forge', workspace_path: '' }),
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

// 스트리밍 중 텍스트가 조금씩 늘어날 때 부드럽게 따라 내려간다.
// 큰 이동(새 메시지 등장 등)은 즉시 점프해 답답함을 없앤다.
function smoothScrollToBottom() {
  const el = chatEl.value
  if (!el) return
  const target = el.scrollHeight - el.clientHeight
  const current = el.scrollTop
  const diff = target - current
  if (Math.abs(diff) > 160) {
    // 새 메시지·이미지 등 큰 높이 변화는 즉시(애니메이션이 오히려 답답)
    el.scrollTop = target
    if (scrollRaf) { cancelAnimationFrame(scrollRaf); scrollRaf = null }
    return
  }
  if (scrollRaf) return // 이미 부드럽게 따라가는 중
  const step = () => {
    const el2 = chatEl.value
    if (!el2) { scrollRaf = null; return }
    const t = el2.scrollHeight - el2.clientHeight
    const c = el2.scrollTop
    const d = t - c
    if (Math.abs(d) < 1.5) {
      el2.scrollTop = t
      scrollRaf = null
      return
    }
    el2.scrollTop = c + d * 0.32
    scrollRaf = requestAnimationFrame(step)
  }
  scrollRaf = requestAnimationFrame(step)
}

// 하단 근처에 있고, 사용자가 스크롤 조작 중이 아닐 때만 따라 내려간다(읽는 위치를 뺏지 않음).
function maybeScrollBottom() {
  if (isAtBottom.value && !scrollLocked) smoothScrollToBottom()
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
  developer: '개발',
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

// 도구 항목의 안정 key — 최근 N개만 보여줄 때 인덱스 key로는 DOM이 잘못 재사용된다.
let toolSeq = 0
// 기본 노출 개수. 실행 중인 도구는 항상 마지막이라 이 창에 들어온다.
const ACTIVITY_LIMIT = 4

function visibleTools(p) {
  return p.showAll || p.tools.length <= ACTIVITY_LIMIT ? p.tools : p.tools.slice(-ACTIVITY_LIMIT)
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

// 작성 중 어떤 모델이 답하는지 한눈에 — 모델명을 짧은 배지로.
function shortModel(m) {
  if (!m) return ''
  if (m.includes('pro')) return 'Pro'
  if (m.includes('vision')) return 'Vision'
  if (m.includes('flash')) return 'Flash'
  return m.split('/').pop()
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

// 한 줄 요약 — 도구별로 의미 있는 필드만(경로·명령·패턴). 날 JSON 대신 읽기 좋게.
function summarizeArgs(args) {
  if (!args || typeof args !== 'object') return ''
  if (typeof args.command === 'string') return args.command.split('\n')[0].slice(0, 80)
  if (args.path) return String(args.path)
  if (args.pattern) return String(args.pattern)
  try {
    const s = JSON.stringify(args)
    return s.length > 80 ? s.slice(0, 80) + '…' : s
  } catch {
    return ''
  }
}

// 승인 다이얼로그용 — 실제 내용을 진짜 줄바꿈으로(코드블록). 무엇을 쓰/실행하는지 검토 가능하게.
function approvalBody(args) {
  if (!args || typeof args !== 'object') return ''
  if (typeof args.command === 'string') return args.command
  if (typeof args.content === 'string') return args.content.slice(0, 2000)
  if (typeof args.new_string === 'string') {
    return '- ' + String(args.old_string || '').slice(0, 600) + '\n+ ' + args.new_string.slice(0, 600)
  }
  return ''
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
  // seq dedup: SSE와 폴링이 같은 seq를 쓰므로, 이미 적용한 seq 이하는 무시한다.
  // text_delta는 content를 누적하므로 중복 적용 시 텍스트가 두 배가 된다.
  if (evt.seq != null) {
    if (evt.seq <= (assistant.lastSeq || 0)) return
    assistant.lastSeq = evt.seq
  }
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
      activePhase(assistant).tools.push({ id: ++toolSeq, name: d.name, args: d.args, status: 'running', result: '', diff: '' })
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
      const labels = { todo: '할 일', working: '진행', testing: '테스트', done: '완료', planning: '할 일', in_progress: '진행', 'in-progress': '진행', review: '테스트', verifying: '테스트', debug: '진행' }
      // 태스크당 한 줄 — 상태가 바뀌어도 줄이 늘지 않는다(id가 신원, 제목은 백엔드가 고정).
      // 재연결로 예전 이벤트가 재생돼도 같은 줄이 갱신될 뿐 중복되지 않는다.
      if (!assistant.taskNotes) assistant.taskNotes = []
      for (const t of newTasks) {
        const key = t.id != null ? `id:${t.id}` : `t:${t.title}`
        let note = assistant.taskNotes.find((n) => n.key === key)
        if (!note) {
          note = { key, title: t.title, to: '', done: false }
          assistant.taskNotes.push(note)
        }
        note.title = t.title
        note.to = labels[t.status] || t.status
        note.done = t.status === 'done'
      }
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
    case 'verify_start':
      assistant.verifyPhase = '검증 중'
      break
    case 'verify_failed':
      assistant.verifyPhase = '복구 중'
      break
    case 'verify_unavailable':
      assistant.verifyPhase = ''
      break
    case 'refinement_candidate':
      loadRefinements()
      break
    case 'done':
      assistant.verifyPhase = ''
      assistant.phases.forEach((p) => {
        p.running = false
        p.collapsed = true
      })
      if (d.content) assistant.doneMessage = d.content
      break
  }
  maybeScrollBottom()
}

// 실행 중 진행을 eventlog 폴링으로 렌더 — Cloudflare가 SSE를 버퍼링해 폰에서
// '실행 중'만 보이던 문제 해결. SSE와 폴링은 같은 seq를 쓰므로 handleEvent의
// seq dedup이 중복을 막는다(데스크톱은 매번 '새 이벤트 없음' → 무동작).
function startEventPolling(assistant) {
  if (eventPollTimer) return
  eventPollTimer = setInterval(async () => {
    const id = currentRoomId.value
    if (!id) return stopEventPolling()
    // run이 끝났으면(SSE done 또는 서버 idle) 멈춘다.
    if (!busy.value && !sessionRunning.value) return stopEventPolling()
    try {
      const res = await fetch(`/api/sessions/${id}/events?since=${assistant.lastSeq || 0}`)
      if (!res.ok) return
      const { events } = await res.json()
      for (const evt of events) {
        handleEvent({ seq: evt.seq, type: evt.type, data: evt.data }, assistant)
        if (evt.type === 'done') { stopEventPolling(); break }
      }
    } catch {}
  }, 1000)
}

function stopEventPolling() {
  if (eventPollTimer) {
    clearInterval(eventPollTimer)
    eventPollTimer = null
  }
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

function toggleAutoApprove() {
  autoApprove.value = !autoApprove.value
  localStorage.setItem('forge_auto_approve', autoApprove.value ? '1' : '0')
  // 실행 중이면 서버에 즉시 반영(스트림이 끊겨 busy가 false여도 sessionRunning이면 반영)
  if ((busy.value || sessionRunning.value) && currentRoomId.value) {
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
  // 스트림이 done 없이 끊기면(폰 잠금·터널 재연결) 받은 만큼만 남아 본문이 잘린다.
  let sawDone = false
  let gotEvents = false

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
      body: JSON.stringify({ session_id: roomId, message: payloadMsg, image_urls: imageUrls, auto_approve: autoApprove.value, model_tier: modelTier.value }),
    })
    console.log('[forge] 응답:', res.status, res.headers.get('content-type'))
    if (!res.ok || !res.body) throw new Error('HTTP ' + res.status)
    // 폴링·SSE 시작점: 이번 run 직전까지의 마지막 seq. 이 값부터 새 이벤트를 이어받는다.
    assistant.lastSeq = Number(res.headers.get('X-Last-Seq')) || 0
    debug.value = '연결됨'
    // SSE와 함께 폴러 시작 — 폰(SSE 버퍼링)은 폴러가 진행을 채우고, 데스크톱은 무동작.
    startEventPolling(assistant)

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
            gotEvents = true
            if (evt.type === 'done') { sawDone = true; stopEventPolling() }
            if (eventCount <= 5) console.log('[forge] 이벤트', eventCount, ':', evt.type)
            handleEvent({ seq: evt.seq, type: evt.type, data: evt.data }, assistant)
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
    stopEventPolling()
    scrollBottom()
    // 스트림이 done 없이 끊겼을 수도 있으므로 서버 상태를 확인 → 아직 돌면 폴링 시작.
    // (모바일에서 스트림이 조용히 끊기면 sessionRunning이 false로 남아 '끝난 것처럼' 보이던 문제)
    checkRunning()
    // '중단 후 새로 시작' 모드로 대기된 메시지가 있으면 현재 스트림 종료 후 전송
    if (pendingSend.value) {
      const t = pendingSend.value
      pendingSend.value = null
      input.value = t
      setTimeout(() => send(), 50)
    } else if (gotEvents && !sawDone) {
      // 끝까지 못 받았으면 서버 기록으로 되맞춘다(단일 진실 = 서버).
      loadMessages(true)
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

// 입력이 비워지면(send/pendingSend 등 모든 경로) textarea 높이를 한 줄로 리셋 —
// 전송 후 커진 채로 남는 버그 방지. nextTick 후에 해야 v-model 반영이 끝난 높이로 계산한다.
const composerInput = ref(null)
watch(input, (v) => {
  if (v) return
  nextTick(() => {
    if (composerInput.value) composerInput.value.style.height = 'auto'
  })
})

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
  activeApproval.value = null // 복구 모달 닫기
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

watch(showRooms, (v) => {
  if (v) loadRooms() // 열 때마다 running 등 최신화(스피너 stale 방지)
  else stopScreen()  // 닫으면 화면 폴링 정지
})

applyTheme(theme.value)

onMounted(async () => {
  // 넓은 화면(맥)에선 사이드바를 상시 렌더(고정 또는 hover 노출). 좁으면 오버레이 드로어.
  const mq = window.matchMedia('(min-width: 900px)')
  const applyWide = () => { isWide.value = mq.matches }
  applyWide()
  mq.addEventListener('change', applyWide)
  loadBalance() // 앱 실행 시 잔액 최초 1회 fetch(전역 상태로 공유)
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
  if (document.visibilityState === 'visible') reconcileOnResume()
})
</script>

<template>
  <div class="app" :class="{ 'sidebar-pinned': isWide && pinnedSidebar }">
    <header>
      <button v-if="!(isWide && pinnedSidebar)" class="icon-btn" @click="isWide ? togglePin() : (showRooms = true)" aria-label="세션 목록">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 6h16M4 12h16M4 18h16"/></svg>
      </button>
      <button class="room-btn" @click="showRooms = true">
        <span class="room-title-main">
          <span class="status-dot" :class="busy ? 'working' : 'idle'"></span>
          {{ currentRoom()?.title || 'FORGE' }}
        </span>
        <span class="room-sub">
          <span v-if="busy || sessionRunning" class="status-live">실행 중</span><template v-if="busy || sessionRunning"> · </template>{{ shortPath(currentRoom()?.workspace_path) || 'Mobile Coding Agent' }}
        </span>
      </button>
      <div class="header-right">
        <button class="todo-btn" @click="showMenu = !showMenu" aria-label="메뉴">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="19" cy="12" r="1.6"/></svg>
        </button>
      </div>
    </header>

    <MenuPanel
      v-if="showMenu"
      :ctx-pct="ctxPct(currentRoom())"
      :ctx-class="ctxClass(ctxPct(currentRoom()))"
      :theme="theme"
      :themes="THEMES"
      @close="showMenu = false"
      @session-detail="showSessionDetail = true; showMenu = false"
      @top-up="openTopUpConfirm(); showMenu = false"
      @files="openFiles(); showMenu = false"
      @git="showGit = true; showMenu = false"
      @kanban="showKanban = true; loadTasks(); showMenu = false"
      @skills="openSkills(); showMenu = false"
      @push="showPush = true; showMenu = false"
      @admin="openAdmin(); showMenu = false"
      @set-theme="setTheme($event)"
    />

    <div v-if="showRooms || isWide" class="rooms-overlay" :class="{ pinned: isWide && pinnedSidebar, peek: isWide && !pinnedSidebar }" @click="!isWide && (showRooms = false)">
      <div class="rooms-panel" @click.stop>
        <div class="drawer-head">
          <span class="drawer-title">{{ sidebarTab === 'sessions' ? '세션' : sidebarTab === 'jobs' ? '예약 작업' : '맥' }}</span>
          <div class="drawer-head-actions">
            <button v-if="sidebarTab === 'sessions'" class="drawer-add" @click="showCreateRoom = true; showRooms = false" aria-label="새 세션">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>
            </button>
            <button v-if="sidebarTab === 'jobs'" class="drawer-add" @click="showJobForm = true" aria-label="새 예약">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>
            </button>
            <button v-if="isWide" class="drawer-close pin" :class="{ on: pinnedSidebar }" @click="togglePin" :aria-label="pinnedSidebar ? '사이드바 고정 해제' : '사이드바 고정'">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="16" rx="2"/><line x1="9" y1="4" x2="9" y2="20"/></svg>
            </button>
            <button v-else class="drawer-close" @click="showRooms = false" aria-label="닫기">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>
            </button>
          </div>
        </div>

        <!-- 세션 탭 -->
        <template v-if="sidebarTab === 'sessions'">
          <div class="drawer-search">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4-4"/></svg>
            <input v-model="searchQuery" @input="onSearch" placeholder="세션·대화 검색" />
            <button v-if="searchQuery" class="drawer-search-x" @click="searchQuery=''; searchResults=[]">✕</button>
          </div>
          <div v-if="searchQuery && searchResults.length" class="rooms-scroll">
            <div v-for="r in searchResults" :key="r.session_id + (r.message_id || '')" class="search-result" @click="jumpToMessage(r)">
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
                <span v-if="r.running" class="room-spinner" title="작업 중"></span>
                <span v-else class="room-status" :class="r.id === currentRoomId ? 'active' : 'idle'"></span>
                <div class="room-info">
                  <div class="room-title">{{ r.title }}<span v-if="r.scheduled" class="room-badge">예약</span></div>
                  <div class="room-path">{{ r.workspace_path || '워크스페이스 설정' }}</div>
                </div>
                <span class="room-pct">Context {{ ctxPct(r) }}%</span>
                <button class="room-more" @click.stop="openRoomMenu(r.id, $event)" aria-label="메뉴">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="19" cy="12" r="1.6"/></svg>
                </button>
              </div>
            </div>
          </div>
        </template>

        <!-- 예약 탭 -->
        <template v-else-if="sidebarTab === 'jobs'">
          <div class="rooms-scroll">
            <div v-if="!jobs.length" class="admin-sub" style="padding:16px">예약된 작업이 없습니다. 우측 상단 +로 추가하세요.</div>
            <div v-for="j in jobs" :key="j.id" class="room-swipe">
              <button class="room-swipe-del" @click.stop="deleteJob(j.id)">삭제</button>
              <div
                class="job-item"
                :class="{ off: !j.enabled, swiped: swipedJobId === j.id }"
                @touchstart="onRoomTouchStart"
                @touchend="onJobTouchEnd(j, $event)"
              >
                <div class="job-main">
                  <div class="job-name">{{ j.name }}</div>
                  <div class="job-meta">{{ jobScheduleLabel(j) }} · 다음 {{ fmtTime(j.next_run_at) }}</div>
                  <div v-if="j.last_result" class="job-result">{{ j.status === 'running' ? '실행 중…' : j.last_result }}</div>
                </div>
                <div class="job-actions">
                  <button @click="runJobNow(j.id)" title="지금 실행">▶</button>
                  <button :class="{ on: j.enabled }" @click="toggleJob(j)">{{ j.enabled ? '켜짐' : '꺼짐' }}</button>
                </div>
              </div>
            </div>
          </div>
        </template>

        <!-- 맥 탭 -->
        <template v-else>
          <div class="rooms-scroll">
            <div class="mac-launcher">
              <button class="mac-tile" @click="openMacScreen">
                <span class="mac-ico">🖥️</span><span>화면 보기</span>
              </button>
              <button class="mac-tile" @click="openMacTerminal">
                <span class="mac-ico">⌨️</span><span>터미널 연결</span>
              </button>
              <button class="mac-tile" @click="openMacCamera">
                <span class="mac-ico">📷</span><span>카메라 보기</span>
              </button>
              <div class="mac-tile mac-toggle" @click="toggleCaffeine">
                <span class="mac-ico">☕</span>
                <span class="mac-toggle-label">맥 잠들지 않게 하기</span>
                <span class="mac-switch" :class="{ on: caffeineOn }"><span class="mac-switch-knob"></span></span>
              </div>
            </div>
          </div>
        </template>

        <!-- 하단 탭바 -->
        <div class="sidebar-tabbar">
          <button :class="{ active: sidebarTab === 'sessions' }" @click="switchSidebarTab('sessions')">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
            <span>세션</span>
          </button>
          <button :class="{ active: sidebarTab === 'jobs' }" @click="switchSidebarTab('jobs')">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>
            <span>예약</span>
          </button>
          <button :class="{ active: sidebarTab === 'mac' }" @click="switchSidebarTab('mac')">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="4" width="20" height="13" rx="2"/><path d="M8 21h8M12 17v4"/></svg>
            <span>맥</span>
          </button>
        </div>
      </div>
    </div>

    <!-- 예약 작업 생성 모달 -->
    <div v-if="showJobForm" class="modal-overlay job-modal" @click="showJobForm = false">
      <div class="modal" @click.stop>
        <div class="modal-head">새 예약 작업</div>
        <input v-model="jobForm.name" class="modal-field" placeholder="작업 이름" />
        <textarea v-model="jobForm.prompt" class="modal-field" rows="3" placeholder="작업 내용 (예: 매일 아침 README 요약)"></textarea>
        <div class="job-sched-tabs">
          <button :class="{ active: jobForm.schedule === 'once' }" @click="jobForm.schedule = 'once'">1회</button>
          <button :class="{ active: jobForm.schedule === 'daily' }" @click="jobForm.schedule = 'daily'">매일</button>
          <button :class="{ active: jobForm.schedule === 'interval' }" @click="jobForm.schedule = 'interval'">반복</button>
        </div>
        <input v-if="jobForm.schedule === 'once'" v-model="jobForm.at" type="datetime-local" class="modal-field" />
        <input v-if="jobForm.schedule === 'daily'" v-model="jobForm.time" type="time" class="modal-field" />
        <div v-if="jobForm.schedule === 'interval'" class="job-interval-row">
          <input v-model.number="jobForm.interval" type="number" min="1" class="modal-field" /><span>분마다</span>
        </div>
        <div class="modal-actions">
          <button class="no" @click="showJobForm = false">취소</button>
          <button class="ok" @click="createJob">만들기</button>
        </div>
      </div>
    </div>

    <!-- 맥 상세: 전체화면 + 우측 하단 닫기 X 하나만 -->
    <div v-if="macView" class="mac-overlay" :class="{ 'is-screen': macView === 'screen' }">
      <template v-if="macView === 'screen'">
        <div v-if="screenErr" class="mac-screen-err">{{ screenErr }}</div>
        <img
          v-show="!screenErr && screenSrc"
          :src="screenSrc"
          class="mac-screen-video"
          alt="맥 화면"
          @load="onScreenLoad"
          @error="onScreenError"
        />
      </template>
      <div v-else-if="macView === 'terminal'" class="term-wrap">
        <div ref="termEl" class="term-host"></div>
        <div class="term-keys">
          <button @click="termKey('\t')">Tab</button>
          <button @click="termKey('\x1b')">Esc</button>
          <button @click="termKey('\x03')">Ctrl-C</button>
          <button @click="termKey('\x04')">Ctrl-D</button>
          <button @click="termKey('\x1b[A')">↑</button>
          <button @click="termKey('\x1b[B')">↓</button>
          <button @click="termKey('\x1b[D')">←</button>
          <button @click="termKey('\x1b[C')">→</button>
        </div>
      </div>
      <template v-else-if="macView === 'camera'">
        <div v-if="camErr" class="mac-screen-err">{{ camErr }}</div>
        <div v-else-if="!camSrc" class="mac-placeholder">카메라 준비 중…</div>
        <img
          v-show="!camErr && camSrc"
          :src="camSrc"
          class="mac-screen-video"
          alt="맥 카메라"
          @load="onCamLoad"
          @error="onCamError"
        />
      </template>
      <button class="mac-ov-close" :class="{ top: macView === 'terminal' }" @click="closeMacView" aria-label="닫기">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>
      </button>
    </div>

    <div v-if="roomMenuId" class="menu-overlay" @click="roomMenuId = null">
      <div class="menu-panel" @click.stop :style="{ top: roomMenuPos.top + 'px', left: roomMenuPos.left + 'px', right: 'auto' }">
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

      <div v-for="(m, i) in messages" :key="i" :data-msg-idx="i" class="msg" :class="m.role">
        <div class="bubble">
          <template v-if="m.role === 'user'">
            <div v-if="processNote(m.content)" class="process-note">⚙ {{ processNote(m.content) }}</div>
            <template v-else>
              <div v-if="m.images && m.images.length" class="user-images">
                <img v-for="(img, ii) in m.images" :key="ii" :src="img" class="user-image" @click="openViewer(m.images, ii)" alt="첨부 이미지" />
              </div>
              <div v-if="m.content && m.content !== '[이미지]'" class="user-text">{{ m.content }}</div>
            </template>
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
                <span v-if="p.model" class="activity-model">{{ shortModel(p.model) }}</span>
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

                <button
                  v-if="!p.showAll && p.tools.length > ACTIVITY_LIMIT"
                  class="activity-more"
                  @click.stop="p.showAll = true"
                >이전 활동 {{ p.tools.length - ACTIVITY_LIMIT }}개 보기</button>

                <details
                  v-for="t in visibleTools(p)"
                  :key="t.id"
                  class="tool"
                  :class="t.status"
                  :open="t.status === 'running'"
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
              <span class="typing-label">{{ typingLabel(m) }}</span>
              <span class="typing-dots"><i></i><i></i><i></i></span>
            </div>

            <div v-if="m.taskNotes && m.taskNotes.length" class="task-notes">
              <div v-for="tn in m.taskNotes" :key="tn.key" class="task-note" :class="{ done: tn.done }">
                <span class="task-note-icon">{{ tn.done ? '✓' : '•' }}</span>
                <span class="task-note-title">{{ tn.title }}</span>
                <span class="task-note-status">{{ tn.to }}</span>
              </div>
            </div>

            <div v-if="(m.state && (m.state.files_changed?.length || m.state.errors?.length)) || m.compacted" class="state-summary">
              <span v-if="m.state?.files_changed?.length" class="state-chip">변경 {{ m.state.files_changed.length }}</span>
              <span v-if="m.state?.errors?.length" class="state-chip err">오류 {{ m.state.errors.length }}</span>
              <span v-if="m.compacted" class="state-chip">컨텍스트 압축됨</span>
            </div>

            <div v-if="m.approval" class="approval">
              <div class="approval-head">도구 실행 승인이 필요합니다</div>
              <div class="approval-tool">{{ m.approval.tool }}<span v-if="summarizeArgs(m.approval.args)"> — {{ summarizeArgs(m.approval.args) }}</span></div>
              <pre v-if="approvalBody(m.approval.args)" class="approval-body">{{ approvalBody(m.approval.args) }}</pre>
              <div class="approval-btns">
                <button class="ok" @click="decide(m.approval, 'approve')">승인</button>
                <button class="no" @click="decide(m.approval, 'reject')">거부</button>
              </div>
            </div>

            <div v-if="m.doneMessage" class="done-msg">{{ m.doneMessage }}</div>

            <div
              v-for="r in (i === messages.length - 1 ? refinements : [])"
              :key="r.id"
              class="refine"
              :class="{ decided: r.status !== 'pending' }"
            >
              <div class="refine-head">이번 작업에서 학습 — {{ r.type }} 후보 ({{ r.scope }})</div>
              <div class="refine-target">{{ r.target }}</div>
              <div class="refine-ev">근거 · 서로 다른 run {{ r.evidence_runs.length }}회 반복 실패<span
                v-if="r.evidence?.session_cost_usd != null"> · 이번 세션 비용 ${{ r.evidence.session_cost_usd }}</span></div>
              <pre class="refine-body">{{ r.failure_pattern }}</pre>
              <div class="refine-ev">기대 효과 · {{ r.expected_effect }}</div>
              <div class="refine-btns" v-if="r.status === 'pending'">
                <button class="ok" @click="decideRefinement(r, 'approve')">승인</button>
                <button class="no" @click="decideRefinement(r, 'ignore')">무시</button>
              </div>
              <div class="refine-btns" v-else>
                <span class="refine-status">{{ r.status === 'approved' ? '승인됨(적용은 수동)' : '무시함' }}</span>
                <button class="no" @click="decideRefinement(r, 'rollback')">되돌리기</button>
              </div>
            </div>

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

    <div v-if="viewerImages.length" class="image-viewer" @click="closeViewer"
         @touchstart.passive="viewerTouchStart" @touchmove="viewerTouchMove" @touchend.passive="viewerTouchEnd">
      <img :src="viewerImages[viewerIndex]" alt="이미지" @click.stop @dblclick="resetImgZoom"
           :style="{ transform: `translate(${imgTx}px, ${imgTy}px) scale(${imgScale})` }" />
      <button class="image-viewer-close" @click="closeViewer" aria-label="닫기">✕</button>
      <button v-if="viewerIndex > 0" class="image-viewer-nav prev" @click.stop="viewerPrev" aria-label="이전">‹</button>
      <button v-if="viewerIndex < viewerImages.length - 1" class="image-viewer-nav next" @click.stop="viewerNext" aria-label="다음">›</button>
      <div v-if="viewerImages.length > 1" class="image-viewer-count">{{ viewerIndex + 1 }} / {{ viewerImages.length }}</div>
    </div>

    <footer>
      <button v-if="!isAtBottom" class="jump-bottom" @click="jumpToBottom" aria-label="맨 아래로">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M5 12l7 7 7-7"/></svg>
      </button>
      <div v-if="taskBar" class="task-bar" @click="showKanban = true; loadTasks()">
        <span class="task-bar-dot"></span>
        <span class="task-bar-title">{{ taskBar.title }}</span>
        <span class="task-bar-count">{{ taskBar.done }}/{{ taskBar.total }}</span>
      </div>
      <input ref="fileInput" type="file" multiple accept="image/*,.md,.txt,.log,.json,.csv,.yml,.yaml,.toml,.py,.js,.ts,.jsx,.tsx,.vue,.html,.css,.sh,.xml,.java,.go,.rs,.c,.cpp,.h,.sql,text/*" hidden @change="onFileChange" />
      <div class="composer">
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

        <textarea
          ref="composerInput"
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
          <div class="composer-chips">
            <button class="mode-chip ghost" @click="showModelPick = true" aria-label="모델 선택">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a7 7 0 0 0-4 12.7V17a2 2 0 0 0 2 2h4a2 2 0 0 0 2-2v-2.3A7 7 0 0 0 12 2z"/><path d="M9 22h6"/></svg>
              {{ tierLabel() }}
            </button>
            <button class="mode-chip" :class="{ on: autoApprove }" @click="toggleAutoApprove">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M13 2L3 14h7l-1 8 10-12h-7z"/></svg>
              {{ autoApprove ? '자동 승인' : '수동 승인' }}
            </button>
            <button v-if="busy || sessionRunning" class="mode-chip small ghost" @click="steerMode = steerMode === 'queue' ? 'switch' : 'queue'">
              {{ steerMode === 'queue' ? '작업 대기' : '계획 수정' }}
            </button>
          </div>
          <button id="send" class="composer-send" :disabled="!input.trim() && !attachedImages.length && !attachedText" @click="send" aria-label="전송">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5M6 11l6-6 6 6"/></svg>
          </button>
        </div>
      </div>
    </footer>

    <!-- 모델 선택 시트(클로드식) -->
    <div v-if="showModelPick" class="sheet-overlay" @click="showModelPick = false">
      <div class="sheet" @click.stop>
        <div class="sheet-head">
          <span class="sheet-title">모델 선택</span>
          <button class="sheet-x" @click="showModelPick = false" aria-label="닫기">✕</button>
        </div>
        <button v-for="t in MODEL_TIERS" :key="t.key" class="sheet-item" :class="{ on: modelTier === t.key }" @click="pickModel(t.key)">
          <div class="sheet-item-main">
            <span class="sheet-item-label">{{ t.label }}</span>
            <span v-if="modelTier === t.key" class="sheet-item-check">✓</span>
          </div>
          <span class="sheet-item-desc">{{ t.desc }}</span>
        </button>
      </div>
    </div>

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

    <!-- 잔액 탭 → 충전 화면 이동 확인 팝업 -->
    <div v-if="showTopUpConfirm" class="modal-overlay topup-modal" @click="showTopUpConfirm = false">
      <div class="modal" @click.stop>
        <div class="modal-head">충전 안내</div>
        <div class="modal-question">충전 화면으로 이동하시겠습니까?</div>
        <div class="modal-options">
          <button @click="showTopUpConfirm = false">취소</button>
          <button @click="goTopUp">충전 화면으로 이동</button>
        </div>
      </div>
    </div>

    <!-- 승인 요청 복구 모달(스트림 끊긴 뒤에도 승인/거부 가능) -->
    <div v-if="activeApproval" class="modal-overlay">
      <div class="modal" @click.stop>
        <div class="modal-head">도구 실행 승인이 필요합니다</div>
        <div class="modal-question">{{ activeApproval.tool }}<span v-if="summarizeArgs(activeApproval.args)"> — {{ summarizeArgs(activeApproval.args) }}</span></div>
        <pre v-if="approvalBody(activeApproval.args)" class="approval-body">{{ approvalBody(activeApproval.args) }}</pre>
        <div class="modal-actions">
          <button class="no" @click="decide(activeApproval, 'reject')">거부</button>
          <button class="ok" @click="decide(activeApproval, 'approve')">승인</button>
        </div>
      </div>
    </div>

    <div v-if="showCreateRoom" class="modal-overlay" @click="showCreateRoom = false">
      <div class="modal" @click.stop>
        <div class="modal-head">새 세션</div>
        <input v-model="newRoomName" class="modal-field" placeholder="세션 이름 (기본: Forge)" />
        <button type="button" class="modal-field ws-btn" @click="openWorkspacePicker(null)">
          {{ newRoomPath || '워크스페이스 폴더 선택 (선택 사항)' }}
        </button>
        <div class="modal-actions">
          <button class="no" @click="showCreateRoom = false">취소</button>
          <button class="ok" @click="createRoom">만들기</button>
        </div>
      </div>
    </div>

    <KanbanPanel
      v-if="showKanban"
      :tasks="tasks"
      :room-title="currentRoom()?.title || 'FORGE'"
      @close="showKanban = false"
    />

    <GitPanel
      v-if="showGit"
      :room-id="currentRoomId"
      :workspace-path="currentRoom()?.workspace_path"
      @close="showGit = false"
    />

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
            <span class="skill-scope" :class="s.origin || s.scope">{{ { curated: '큐레이트', learned: '학습', project: '프로젝트' }[s.origin] || (s.scope === 'global' ? '전역' : '프로젝트') }}</span>
            <button v-if="s.origin !== 'curated'" class="skill-del" @click.stop="deleteSkill(s.name, s.scope)">삭제</button>
          </div>
          <pre v-show="skillOpen[s.name]" class="skill-content">{{ s.content }}</pre>
        </div>
      </div>
    </div>

    <PushPanel v-if="showPush" @close="showPush = false" />

    <AdminPanel
      v-if="showAdmin"
      :rooms="rooms"
      @close="showAdmin = false"
    />

    <SessionDetailPanel
      v-if="showSessionDetail"
      :room-id="currentRoomId"
      :room-title="currentRoom()?.title || '세션'"
      :room="currentRoom()"
      @close="showSessionDetail = false"
      @top-up="openTopUpConfirm()"
    />

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
        :session-id="currentRoomId || ''"
        @image-click="openViewer($event)"
      />
    </div>

    <div v-if="showWorkspacePicker" class="fs-overlay">
      <div class="fs-head">
        <button @click="showWorkspacePicker = false">취소</button>
        <span class="fs-title">{{ fsPath }}</span>
        <button class="fs-hidden-toggle" :class="{ active: showHidden }" @click="toggleHidden">
          <svg v-if="showHidden" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/></svg>
          <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-10-8-10-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 10 8 10 8a18.5 18.5 0 0 1-2.16 3.19M1 1l22 22"/></svg>
          숨김
        </button>
        <button class="fs-done" @click="pickCurrentPath">선택</button>
      </div>
        <input v-model="fsFilter" class="fs-search" type="search" placeholder="이 폴더에서 이름 검색" />
        <div class="fs-list">
          <button v-if="fsParent && !fsFilter" class="fs-item parent" @click="navigateFs(fsParent)">.. 상위 폴더</button>
          <div v-if="fsFilter && !fsVisible.length" class="fs-empty">일치하는 항목 없음</div>
          <button
            v-for="e in fsVisible"
            :key="e.path"
            class="fs-item"
            :class="e.is_dir ? 'dir' : 'file'"
            :disabled="!e.is_dir"
            @click="navigateFs(e.path)"
          >
            {{ e.name }}
          </button>
        </div>
    </div>
  </div>
</template>
