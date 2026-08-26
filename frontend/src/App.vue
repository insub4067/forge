<script setup>
import { ref, reactive, nextTick, onMounted, watch, computed } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import 'highlight.js/styles/github-dark.css'
import FileViewer from './components/FileViewer.vue'
import RoomsPanel from './components/RoomsPanel.vue'
import GitPanel from './components/GitPanel.vue'
import AdminPanel from './components/AdminPanel.vue'
import PushPanel from './components/PushPanel.vue'
import KanbanPanel from './components/KanbanPanel.vue'
import MenuPanel from './components/MenuPanel.vue'
import SessionDetailPanel from './components/SessionDetailPanel.vue'
import FileBrowserPanel from './components/FileBrowserPanel.vue'
import AgentCrewPanel from './components/AgentCrewPanel.vue'
import ActivityDetailPanel from './components/ActivityDetailPanel.vue'
import FsIcon from './components/FsIcon.vue'
import { balance as adminBalance, loadBalance } from './store'
import { isOpenSwipe } from './lib/drawerDrag.js'

// 단일 줄바꿈도 <br>로 — 답변 줄바꿈을 적극 반영
marked.setOptions({ breaks: true, gfm: true })

function renderMarkdown(text) {
  try {
    return DOMPurify.sanitize(marked.parse(text || ''))
  } catch {
    return ''
  }
}

// 카드 헤더가 이미 skill 이름을 보여주므로, 본문 첫 줄의 '# 이름' H1은 중복이라 제거.
function skillBody(content) {
  return (content || '').replace(/^\s*#[^\n]*\n+/, '')
}

const messages = ref([])
const input = ref('')
const busy = ref(false)
const isAtBottom = ref(true)
const unseenCount = ref(0)   // 스크롤을 벗어난 동안 도착한 새 메시지 수 — jump-bottom 배지
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
  // localStorage는 '새 세션의 기본값'으로만 쓴다 — 세션별 값은 서버가 소유한다.
  localStorage.setItem('forge_model_tier', key)
  showModelPick.value = false
  // 고른 즉시 이 세션에 붙인다. 전송 때만 저장하면 고르고 방을 옮겼을 때 선택이 사라진다.
  if (currentRoomId.value) {
    fetch(`/api/sessions/${currentRoomId.value}/model-tier`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tier: key }),
    }).then(() => loadRooms()).catch(() => {})
  }
}
function tierLabel() {
  return (MODEL_TIERS.find((t) => t.key === modelTier.value) || MODEL_TIERS[0]).label
}
// 에이전트 모드 — auto: FORGE가 복잡도로 판단 / multi: 계획→구현→리뷰 3역할 / single: 올인원 Developer
const sessionRunning = ref(false)
const agentStatus = ref(null)
// 서버 도달 가능 여부 — 헬스 하트비트가 판정한다. 서버가 먹통이면 모든 fetch가 조용히
// 실패해 화면이 빈 채로 멈추던 문제(실측)를 배너로 드러낸다.
const serverDown = ref(false)
let healthTimer = null
const showSkills = ref(false)
const skillOpen = ref({}) // 스킬 카드 펼침 상태(기본 닫힘)
const skills = ref([])
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
const approvalError = ref('')    // 승인 API 실패(409 이미 처리/만료·404 없음) 시 안내
const questionAnswer = ref('')
const debug = ref('대기 중')

const rooms = ref([])
// 서버(/api/rooms)에서 세션방 목록을 실제로 받아왔는지. 이게 true여야 "방 없음"을 진짜
// 미설정으로 단정할 수 있다 — 로드 실패로 목록이 비어 있는 것과 서버가 0개라고 확인해준
// 것을 구분해, 로드 실패 시 '워크스페이스 미설정'을 오표시하지 않는다.
const roomsLoaded = ref(false)
const currentRoomId = ref(localStorage.getItem('forge_room') || '')
const loadingMessages = ref(false)
const showRooms = ref(false)
const isWide = ref(false) // 넓은 화면(맥) 여부
const pinnedSidebar = ref(localStorage.getItem('forge_sidebar_pinned') !== '0') // 고정 여부(기본 고정)
function togglePin() {
  pinnedSidebar.value = !pinnedSidebar.value
  localStorage.setItem('forge_sidebar_pinned', pinnedSidebar.value ? '1' : '0')
}
const showCreateRoom = ref(false)
const newRoomName = ref('')
const newRoomPath = ref('')
const tasks = ref([])
const gates = ref([])  // Acceptance Gate — 요구사항별 검증 상태(passed는 프로세스 소유)
// 칸반 카드 상태 변경을 채팅에 알리기 위한 직전 상태 스냅샷(title→status).
const showKanban = ref(false)
const showWorkspacePicker = ref(false)
const showHidden = ref(false)  // 리팩토링 중 선언이 유실돼 워크스페이스 피커가 빈 목록이었다(복구)
const fsPath = ref('')
const fsParent = ref(null)
const fsEntries = ref([])
const pickerRoomId = ref(null)
const homePath = ref('')  // 홈 디렉터리 — 최초 세션이 workspace_path로 저장하는 값. 미설정 판별 기준.
const needsWorkspace = computed(() => {
  // 서버에서 세션방 목록을 확인하기 전엔 단정하지 않는다(로드 실패 시 오표시 방지).
  if (!roomsLoaded.value) return false
  const room = currentRoom()
  // 서버 확인 결과 방이 아예 없으면(첫 진입·전부 삭제) 워크스페이스 선택부터 유도한다.
  // 선택하면 chooseWorkspace가 방을 만들어 이 상태를 벗어난다(선택해도 계속 뜨던 무한 반복
  // 은, 없는 방에 PATCH하던 게 원인이었고 chooseWorkspace/ensureRoom 수정으로 해소된다).
  if (!room) return true
  // 워크스페이스가 홈/루트/빈 값이면 '미설정'으로 보고 선택을 유도한다(홈에서 작업 시 git·skills가 깨진다).
  const ws = (room.workspace_path || '').trim()
  if (!ws || ws === '/' || ws === '~') return true
  if (homePath.value && ws === homePath.value) return true
  return false
})
async function loadHomePath() {
  try {
    const res = await fetch('/api/fs/list?path=')
    if (res.ok) {
      const data = await res.json()
      homePath.value = data.path || ''
    }
  } catch {}
}
const showGit = ref(false)
const steerMode = ref('queue') // 'queue' = 작업큐 대기(기본), 'switch' = 중단 후 새로 시작
const pendingSend = ref(null)
const showFiles = ref(false)
const showMenu = ref(false)
const showAdmin = ref(false)
const showPush = ref(false)
const showCrew = ref(false)
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
  } else if (st.waiting_for !== 'approval') {
    activeApproval.value = null
  }
  return st
}

// SSE·브라우저 재연결(서버 프로세스는 생존) 시 아직 살아있는 미결 승인 카드를 복원한다.
// 서버 프로세스 재시작은 다르다 — 실행 주체(메모리 Future·continuation)를 잃은 승인은 서버
// 기동 시 cancelled로 정리되므로 여기서 조회해도 나오지 않는다(실행 불가 카드를 띄우지 않음).
async function restorePendingApproval(id) {
  if (!id || activeApproval.value) return
  try {
    const res = await fetch(`/api/sessions/${id}/pending-approvals`)
    if (!res.ok) return
    const { pending } = await res.json()
    if (pending && pending.length) {
      const p = pending[0]
      // PG엔 원문 args를 두지 않으므로 안전 preview로 표시한다(민감정보 비노출).
      activeApproval.value = { id: p.id, tool: p.tool_name, args: {}, preview: p.preview }
    }
  } catch {}
}

let wasRunning = false

// 단일 진실 = 서버 /status. 방이 열려있는 동안 항상 폴링해 클라 상태를 서버로 수렴시킨다.
async function checkRunning() {
  const id = currentRoomId.value
  if (!id) return
  if (!busy.value) await fetchStatus(id).catch(() => {})
  startRunningPoll()
  // 실행 중인 세션을 열었는데 이 클라이언트가 스트림을 안 열고 있으면(=API/다른 기기에서
  // 시작·재개된 run) 라이브 이벤트 폴링을 시작한다. 없으면 대화·"작성 중"이 정지된 것처럼 보였다.
  if (sessionRunning.value && !busy.value && !eventPollTimer) {
    const assistant = newAssistant()
    try {
      const r = await fetch(`/api/sessions/${id}/events?since=0`)
      const evs = r.ok ? ((await r.json()).events || []) : []
      assistant.lastSeq = evs.length ? evs[evs.length - 1].seq : 0
    } catch { assistant.lastSeq = 0 }
    startEventPolling(assistant)
  }
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

// 서버 헬스 하트비트 — 방/세션과 무관하게 항상 돈다. /api/health를 짧은 타임아웃으로
// 찔러 도달 불가(먹통·재시작·네트워크)면 배너를 띄운다. 연속 실패해야 down으로 판정해
// 일시적 지연에 깜빡이지 않는다.
let healthFails = 0
async function pingHealth() {
  try {
    const ctrl = new AbortController()
    const t = setTimeout(() => ctrl.abort(), 4000)
    const res = await fetch('/api/health', { signal: ctrl.signal, cache: 'no-store' })
    clearTimeout(t)
    if (!res.ok) throw new Error('bad')
    const wasDown = serverDown.value
    healthFails = 0
    serverDown.value = false
    if (wasDown) {
      // 서버가 방금 복구됨 — 방 목록을 다시 받아 랜딩을 보정한다. 최초 로드 실패로 지워졌거나
      // 무효해진 현재 세션을 기존 방으로 되돌리고, 방이 새로 정해지면 이력을 불러온다.
      await loadRooms()
      if (reconcileCurrentRoom() && currentRoom()) loadMessages()
    }
  } catch {
    healthFails += 1
    if (healthFails >= 2) serverDown.value = true   // 2회 연속(=최대 ~8s) 실패 시 down
  }
}
function startHealthPoll() {
  if (healthTimer) return
  pingHealth()
  healthTimer = setInterval(pingHealth, 5000)
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
// 하네스가 all_messages에 넣는 프로세스 메시지(role:user)를 사용자 발화와 구분한다.
// 모델 컨텍스트에는 원문이 남지만, 화면엔 회원님 말풍선 대신 흐린 한 줄로 보인다.
// 하네스가 all_messages에 넣는 프로세스 메시지(role:user)의 접두사 → 뱃지 라벨.
// [작업 중 사용자 메시지]는 실제 사용자 발화라 제외한다(주입 아님).
// Agent Activity 라벨 — 무엇이 일어났나(action)와 상태(state)를 담고, tone으로 의미를 색에
// 싣는다(전부 accent 금지). tone은 기존 FORGE 상태색을 재사용한다(warn/error/accent/muted).
const PROCESS_NOTES = [
  ['[검증 실패', { label: '검증 실패', state: '수리 중', tone: 'warn' }],
  ['[요구사항 게이트 검증 실패', { label: '요구사항 게이트 실패', state: '수리 중', tone: 'warn' }],
  ['[Reviewer 지적', { label: 'Reviewer 지적', state: '반영 중', tone: 'accent' }],
  ['[이전 작업 요약', { label: '컨텍스트 압축', state: '', tone: 'muted' }],
  ['[구현은 끝났다', { label: '요구사항 게이트 등록', state: '', tone: 'muted' }],
]
function processNote(content) {
  const t = typeof content === 'string' ? content : ''
  for (const [prefix, meta] of PROCESS_NOTES) {
    if (t.startsWith(prefix)) return meta
  }
  return null
}

// 펼친 disclosure(<details>) 본문을 탭하면 닫는다 — process-note·도구 결과 등 공통.
// 링크·버튼 탭은 제외(오작동 방지). 드래그 선택은 click을 안 내므로 텍스트 선택은 유지.
function closeParentDetails(e) {
  if (e.target.closest('a, button')) return
  const d = e.target.closest('details')
  if (d) d.open = false
}

// 상세 화면 없이도 "지금 무엇을" 한 줄로. 스트림 끊겨도 폴링으로 갱신.
function liveActivityText() {
  const s = agentStatus.value
  return (s && s.activity) || 'Mac에서 작업 중'
}

// 실행 중이며 '진행 중인 사용자 요청'의 응답인가 — 복사/context 등 '끝난' UI를 숨기는 기준.
// 한 요청이 여러 어시스턴트 턴(분류→개발→…)으로 이어지는 동안, 중간 턴이 끝나 다음 턴이
// 시작되면 그 중간 턴에 copy가 조기 노출됐다. → 마지막 사용자 메시지 이후의 어시스턴트는
// 전부 '진행 중인 응답'으로 보고 숨긴다(실행이 끝나면 전부 노출). 이전 요청의 응답은 유지.
function isLiveTurn(i) {
  if (!(busy.value || sessionRunning.value)) return false
  for (let j = i + 1; j < messages.value.length; j++) {
    if (messages.value[j].role === 'user') return false  // 뒤에 또 다른 사용자 요청 → 이건 과거 응답
  }
  return true
}
let mainStartX = 0
let mainStartY = 0
let scrollLocked = false
let scrollUnlockTimer = null
let scrollRaf = null
let startedInHScroll = false

// 터치 시작 지점이 '가로로 실제 스크롤되는' 요소(코드블록·diff·표) 안인가. 그렇다면 우측
// 스와이프는 그 안을 가로 스크롤하려는 의도이므로 드로어 열기로 오인하지 않는다(간섭 해소).
function _inHorizontalScroller(el) {
  for (let n = el; n && n !== chatEl.value; n = n.parentElement) {
    if (n.scrollWidth > n.clientWidth + 2) {
      const ox = getComputedStyle(n).overflowX
      if (ox === 'auto' || ox === 'scroll') return true
    }
  }
  return false
}

function onMainTouchStart(e) {
  mainStartX = e.touches[0].clientX
  mainStartY = e.touches[0].clientY
  startedInHScroll = _inHorizontalScroller(e.target)
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
  // 세션방 어디서든 오른쪽 스와이프 → 드로어를 단순 슬라이드로 연다(따라오는 드래그 없음).
  // 단, 횡스크롤 요소 안에서 시작한 스와이프는 가로 스크롤 의도이므로 드로어를 열지 않는다.
  if (!startedInHScroll && isOpenSwipe(dx, dy) && !showRooms.value) showRooms.value = true
}

function formatTokens(n) {
  if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M'
  if (n >= 1000) return (n / 1000).toFixed(1) + 'K'
  return String(n || 0)
}

function openAdmin() {
  showAdmin.value = true
}

function toggleHidden() {
  showHidden.value = !showHidden.value
  if (showWorkspacePicker.value) navigateFs(fsPath.value)
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
  // 런타임 compaction과 같은 기준(모델 실제 한도 ~128k)으로 표시한다. DB 세션값은 옛 256k라
  // 쓰면 실제 60% 소진이 30%로 보이는 표시/실제 불일치가 생긴다.
  const budget = 131072
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
    if (res.ok) {
      rooms.value = await res.json()
      roomsLoaded.value = true // 서버가 방 목록을 확인해줬다 — 이후 "방 없음"은 진짜 미설정
    }
  } catch {}
}

// 서버에서 방 목록을 받은 뒤에만(roomsLoaded) 현재 세션 유효성을 보정한다. 로드 실패로
// 목록을 못 받았을 땐 currentRoomId를 건드리지 않아(localStorage 값 보존), 서버 복구 후
// 기존 방으로 되돌아갈 수 있게 한다 — 로드 실패 시 성급히 지워 방이 있는데도 '미설정'으로
// 빠지던 회귀를 막는다. 유효한 방이 없으면 가장 최근 방으로, 0개면 빈 값. 변경 시 true.
function reconcileCurrentRoom() {
  if (!roomsLoaded.value) return false
  if (rooms.value.some((r) => r.id === currentRoomId.value)) return false
  currentRoomId.value = rooms.value.length ? rooms.value[0].id : ''
  localStorage.setItem('forge_room', currentRoomId.value)
  return true
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
  // 세션 진입 시 PG에서 미결 승인 복원(재시작·SSE 재연결로 인라인 카드가 사라진 경우).
  restorePendingApproval(id)
}

// 타이틀 탭 → 방 설정 시트(이름·모드 변경). 방이 없으면 방 목록을 연다.
const showRoomSettings = ref(false)
const roomSettingsTitle = ref('')
const roomSettingsMode = ref('work')
// 작업 1회 비용 상한($) — 비우면 서버 기본값. runaway 비용 가드레일. 전역 client 설정.
const budgetUsd = ref(localStorage.getItem('forge_budget') || '')
function saveBudget() {
  localStorage.setItem('forge_budget', budgetUsd.value || '')
}
function openRoomSettings() {
  const r = currentRoom()
  if (!r) { showRooms.value = true; return }
  // 워크스페이스 미설정 세션은 방 설정보다 선택 유도가 먼저다(헤더 탭 → 피커).
  if (needsWorkspace.value) {
    openWorkspacePicker(r.id)
    return
  }
  roomSettingsTitle.value = r.title || ''
  // 실제 mode를 그대로 노출: ''(빈값)=자동 분류. 예전엔 ''를 'work'로 뭉개 "작업 모드인 줄"
  // 착각하게 만들었다(실제론 auto라 코딩 턴이 chat으로 분류돼 편집이 막혔다).
  roomSettingsMode.value = r.mode === 'chat' ? 'chat' : r.mode === 'work' ? 'work' : 'auto'
  showRoomSettings.value = true
}
async function saveRoomSettings() {
  const id = currentRoomId.value
  if (!id) return
  // work는 워크스페이스가 있어야 해서, 없으면 백엔드가 거부하고 안내한다.
  // 'auto'는 백엔드 표현상 빈 문자열('')로 보낸다(triage 자동 분류).
  const body = { mode: roomSettingsMode.value === 'auto' ? '' : roomSettingsMode.value }
  const t = roomSettingsTitle.value.trim()
  if (t) body.title = t
  try {
    const res = await fetch(`/api/rooms/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    const data = await res.json().catch(() => ({}))
    if (data && data.ok === false) {
      alert(data.error || '저장에 실패했습니다.')
      return
    }
    await loadRooms()
    showRoomSettings.value = false
  } catch {}
}

async function selectRoom(id, isNew = false) {
  stopRunningPoll()
  stopEventPolling()   // 이전 방의 이벤트 폴러가 새 방을 옛 seq로 폴링하던 버그 방지
  sessionRunning.value = false
  currentRoomId.value = id
  localStorage.setItem('forge_room', id)
  showRooms.value = false
  await loadMessages(isNew)
  await loadTasks()
  await loadGates()
  await loadRefinements()
  // 승인 정책은 '읽기'로 수렴한다 — 세션 전환은 정책을 쓰는 동작이 아니다(권한 확대 금지).
  // 서버에 저장된 이 세션의 auto_approve를 UI에 반영. 사용자가 토글을 직접 바꿀 때만 POST한다.
  const r = currentRoom()
  if (r && typeof r.auto_approve === 'boolean') {
    autoApprove.value = r.auto_approve
    localStorage.setItem('forge_auto_approve', r.auto_approve ? '1' : '0')
  }
  // 모델 티어도 세션별 설정이다 — 서버에 저장된 이 방의 값으로 복원한다.
  // (전역값 하나만 쓰면 다른 방에서 고른 티어가 그대로 보여 실제 동작과 어긋난다.)
  if (r && r.model_tier) modelTier.value = r.model_tier
  checkRunning()
}

// 같은 워크스페이스로 새 세션 시작(컨텍스트만 리셋) — 작업 경계에서 히스토리 누적·드리프트·
// 비용을 끊는다. 워크스페이스·모드는 현재 세션에서 승계한다.
async function forkSession() {
  const r = currentRoom()
  const ws = r?.workspace_path || ''
  try {
    const res = await fetch('/api/rooms', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: 'New Session', workspace_path: ws }),
    })
    const data = await res.json()
    if (!data || !data.id) return
    // 모드 승계 — work는 워크스페이스가 있어야 하므로 ws 있을 때만.
    const mode = r?.mode === 'work' && ws ? 'work' : r?.mode === 'chat' ? 'chat' : ''
    if (mode) {
      await fetch(`/api/rooms/${data.id}`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode }),
      }).catch(() => {})
    }
    await loadRooms()
    await selectRoom(data.id, true)
  } catch {}
}

// 검색 결과 클릭 → 방을 열고 매칭 메시지로 스크롤+하이라이트
async function jumpToMessage(r, q = '') {
  const qq = (q || '').toLowerCase()
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
      return qq && t.toLowerCase().includes(qq)
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
  if (!list.length) return null  // 아이템 0이면 닫힘 · 1개 이상이면 실행 여부와 무관하게 열림
  const cur =
    list.find((t) => t.status === 'working') ||
    list.find((t) => t.status === 'testing') ||
    list.find((t) => t.status === 'todo')
  const done = list.filter((t) => t.status === 'done').length
  // 진행률은 '완료 수'가 아니라 '현재 위치'로 보여준다 — 0/3이 "아무것도 안 됨"으로
  // 오해되지 않게, 현재 task가 있으면 (완료+1)/전체로 몇 번째인지 표현한다.
  const pos = cur ? done + 1 : done
  return {
    title: cur ? cur.title : (done === list.length ? '완료' : '마무리 중'),
    done,
    total: list.length,
    pos,
    cur,
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

async function loadGates() {
  const id = currentRoomId.value
  if (!id) {
    gates.value = []
    return
  }
  try {
    const res = await fetch(`/api/sessions/${id}/gates`)
    if (res.ok) gates.value = await res.json()
  } catch {}
}

async function createRoom() {
  const name = newRoomName.value.trim() || 'New Session'
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
        gates.value = []
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

// 미설정 상태에서 워크스페이스를 고른다 — 방이 없으면(첫 진입·전부 삭제됨) 먼저 만든다.
// 방 없이 피커만 열면 선택해도 PATCH 대상이 없어 저장이 안 되고 계속 미설정으로 남는다.
async function chooseWorkspace() {
  let id = currentRoomId.value
  if (!id || !currentRoom()) {
    id = await ensureRoom('')
    if (!id) return
    await loadRooms()
  }
  openWorkspacePicker(id)
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
  const list = q ? fsEntries.value.filter((e) => e.name.toLowerCase().includes(q)) : fsEntries.value
  // 폴더 먼저(선택 가능한 것이 위로), 그다음 이름순.
  return [...list].sort((a, b) => (Number(b.is_dir) - Number(a.is_dir)) || a.name.localeCompare(b.name))
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
    newRoomName.value = parts[parts.length - 1] || 'New Session'
  }
  showWorkspacePicker.value = false
}

async function ensureRoom(text) {
  // 유효한(실제 존재하는) 방일 때만 재사용한다 — 유령 id면 새로 만든다.
  if (currentRoomId.value && currentRoom()) return currentRoomId.value
  try {
    const res = await fetch('/api/rooms', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: 'New Session', workspace_path: '' }),
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
// 하단 고정 상태에선 부드러운 추격(rAF)이 스트림마다 출렁여 멀미를 유발한다 → 즉시 스냅.
function maybeScrollBottom() {
  if (isAtBottom.value && !scrollLocked) {
    const el = chatEl.value
    if (el) el.scrollTop = el.scrollHeight
  }
}

// 버튼용 — 부드럽게 스크롤
function jumpToBottom() {
  if (chatEl.value) chatEl.value.scrollTo({ top: chatEl.value.scrollHeight, behavior: 'smooth' })
  isAtBottom.value = true
  unseenCount.value = 0
}

function onChatScroll() {
  const el = chatEl.value
  if (!el) return
  isAtBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight < 80
  if (isAtBottom.value) unseenCount.value = 0   // 최신 위치로 오면 배지 리셋
}
// 스크롤을 벗어난 동안 새 메시지(턴)가 오면 배지 카운트 — 최신에 있으면 늘지 않는다.
watch(() => messages.value.length, (n, old) => {
  if (n > old && !isAtBottom.value) unseenCount.value += n - old
})

function newUser(text, images, queued = false) {
  messages.value.push({ role: 'user', content: text, images: images && images.length ? images : null, queued })
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
  const p = reactive({ role, model, thinking: '', text: '', tools: [], collapsed: false, running: true, thinkOpen: false })
  m.phases.push(p)
  return p
}

// 도구 항목의 안정 key — 최근 N개만 보여줄 때 인덱스 key로는 DOM이 잘못 재사용된다.
let toolSeq = 0

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
  // Tool Failure ≠ Activity Failure. 코딩 에이전트에게 read_file ENOENT·grep no-match 등은
  // 탐색의 정상 과정이다. 도구 하나가 실패했다고 Activity 전체를 '!'로 만들지 않는다.
  // Activity 실패(!)는 검증 실패/완료 터미널(completionNode)에서만 온다. 도구 실패는 통계로.
  if (p.running) return 'running'
  return 'done'
}

// Timeline 노드에 "실패 N" — 실패한 도구 수(Activity 실패가 아니라 도구 통계). 상세는 Sheet.
function phaseErrorCount(p) {
  return (p.tools || []).filter((t) => t.status === 'error').length
}

// 상태를 색이 아니라 '형태'로 — 다크모드 가독성. ● 진행 / ✓ 성공 / ! 실패.
function phaseGlyph(p) {
  const s = phaseStatus(p)
  return s === 'running' ? '●' : s === 'error' ? '!' : '✓'
}

// 첫 문장(두괄식 lead)만 — 마침표(.。!?)가 문장 끝일 때만 자른다(agent.py 같은 파일명 오분할 방지:
// 마침표 뒤가 공백·끝·한글일 때만 문장 종료로 본다). 종료 못 찾으면(스트리밍 중 등) 원문.
function _firstSentence(t) {
  const m = t.match(/[.!?。](?=\s|$|[가-힣])/u)
  return m ? t.slice(0, m.index + 1).trim() : t.trim()
}
// Timeline은 '흐름·요약만' — 상세(추론·도구)가 있는 phase는 두괄식 첫 문장만 보여주고 전문은
// Detail Surface에서(탭). 장황한 진행 narration이 Timeline을 잠식하지 않게. running도 짧게 유지.
// 순수 텍스트 phase(탭 상세 없음=최종 답변 등)는 자르지 않는다(전문 회수 경로가 없으므로).
// 완료 phase는 미래·의도 종결("…하겠습니다")을 결과형으로 벗긴다(새 LLM 호출 없이).
function phaseSummary(p) {
  const t = (p.text || '').trim()
  if (!t) return t
  const lead = phaseHasDetail(p) ? _firstSentence(t) : t
  if (p.running) return lead
  const stripped = lead
    .replace(/(하겠습니다|하겠어요|하려고\s*합니다|해\s*보겠습니다|아?\s*보겠습니다|겠습니다)\s*[.。]?\s*$/u, '')
    .replace(/[.。\s]+$/u, '')
    .trim()
  return stripped || lead   // 통째로 비면(예: 문장 전체가 종결어미) lead 유지
}

// 이 assistant 메시지가 Agent 활동(도구·추론)을 포함하는가. ✓ 등 상태 기호는 Agent Activity
// 전용이다 — 순수 대화 답변(도구 없는 텍스트)은 상태 기호 없이 본문만 보여준다.
function hasActivity(m) {
  // 도구·추론이 있거나, agent 작업 role(chat 아님)이면 Activity. 후자를 포함해야 developer/
  // planner 등 phase가 시작되자마자(첫 도구 전에도) 라이브 타임라인에 '● 실행 중'으로 뜬다.
  // 순수 대화(role 'chat' 또는 '')는 도구가 없으면 상태 기호 없이 본문만.
  return (m.phases || []).some(
    (p) => (p.tools && p.tools.length) || p.thinking || (p.role && p.role !== 'chat'))
}

// ── 최종 결과 카드 — 상태·진행률·검증을 '별도 값'으로. 색만이 아니라 상태 텍스트를 함께. ──
// 검증 개수는 요구사항 gate(현재 세션)에서 센다. passed/failed 외는 전부 미검증(unavailable 등).
function verifyCounts() {
  const g = gates.value || []
  let passed = 0, failed = 0, unverified = 0
  for (const x of g) {
    if (x.status === 'passed') passed++
    else if (x.status === 'failed') failed++
    else unverified++
  }
  return { passed, failed, unverified, total: g.length }
}
// 상태 판정: 미검증 항목이 하나라도 있으면 completed여도 '부분 완료'. 색이 아니라 형태·텍스트.
const _RESULT_STATUS = {
  completed: { key: 'done', label: '완료', cls: 'done', glyph: '✓' },
  completed_unverified: { key: 'partial', label: '부분 완료', cls: 'warn', glyph: '◐' },
  verification_failed: { key: 'failed', label: '실패', cls: 'error', glyph: '✕' },
  failed: { key: 'failed', label: '실패', cls: 'error', glyph: '✕' },
  cancelled: { key: 'cancelled', label: '중단됨', cls: 'muted', glyph: '·' },
  context_blocked: { key: 'partial', label: '부분 완료', cls: 'warn', glyph: '◐' },
  budget_exceeded: { key: 'partial', label: '부분 완료', cls: 'warn', glyph: '◐' },
}
// live 'done' 이벤트는 m.finalStatus를 채운다. history 재구성엔 없으므로, 마지막 메시지는
// 세션 final_status(room 객체)로 보완 — 리로드해도 카드가 유지된다. 실행 중엔 stale 방지로 미보완.
function resolveFinalStatus(m, i) {
  if (m.finalStatus) return m.finalStatus
  if (i === messages.value.length - 1 && !busy.value && !sessionRunning.value) {
    return currentRoom()?.final_status || ''
  }
  return ''
}
function finalStatusInfo(m, i) {
  const st = resolveFinalStatus(m, i)
  if (!st) return null
  const base = _RESULT_STATUS[st]
  if (!base) return null
  // completed여도 검증 실패·미검증 gate가 있으면 '부분 완료'로 강등한다 — 상태와 본문(경고)이
  // 모순되지 않게(핵심 문제 1: '완료 4/4'인데 미검증 존재). 완료는 모든 검증 통과일 때만.
  if (base.key === 'done') {
    const vc = verifyCounts()
    if (vc.failed > 0 || vc.unverified > 0) return _RESULT_STATUS.completed_unverified
  }
  return base
}
// 실패·미검증 gate + 실행 오류를 '별도 경고 카드'로. 사유와 다음 행동을 함께.
function resultWarnings(m) {
  const out = []
  for (const g of (gates.value || [])) {
    if (g.status === 'failed') out.push({ kind: '실패', title: g.title, reason: g.failure_reason || '검증에 실패했습니다.' })
    else if (g.status !== 'passed') out.push({ kind: '미검증', title: g.title, reason: g.failure_reason || '독립 검증을 수행하지 못했습니다.' })
  }
  for (const e of (m.state?.errors || [])) out.push({ kind: '오류', title: '실행 오류', reason: String(e) })
  return out
}
// 접힌 로그 헤더용 개수 — 실행·추론·도구 호출.
function logCounts(m) {
  const ph = m.phases || []
  let think = 0, tools = 0
  for (const p of ph) { if (p.thinking) think++; tools += (p.tools?.length || 0) }
  return { steps: ph.length, think, tools }
}
// Activity(타임라인) 펼침 여부 — 사용자가 명시 토글했으면(m.logsOpen 정의됨) 그 값이 우선,
// 아니면 live 턴 기본(실행 중엔 열림). 이렇게 해야 실행 중 마지막 메시지에서도 토글이 먹는다.
// (예전엔 isLiveTurn이 강제로 열어둬 토글이 무시됐다 — '될 때도 안 될 때도'의 원인.)
function logsShown(m, i) {
  return m.logsOpen !== undefined ? m.logsOpen : isLiveTurn(i)
}
function toggleLogs(m, i) {
  m.logsOpen = !logsShown(m, i)
}
// 사용자-facing 최종 답변 — 개발자의 마지막 텍스트 phase(실제 결과). 없으면 doneMessage(프로세스
// 요약) fallback. 이것을 채팅 본문 primary로 승격한다(Activity 로그에 묻지 않는다). 문자열 파싱이
// 아니라 구조화된 phase 데이터를 쓴다(spec §6).
function finalAnswer(m) {
  const withText = (m.phases || []).filter((p) => p.text && p.text.trim())
  if (withText.length) return withText[withText.length - 1].text
  return m.doneMessage || ''
}
// 검증이 NOT_APPLICABLE인가(read-only 성공) — completed인데 gate 0개면 read-only로 추론한다.
// (mutation completed는 반드시 gate passed>0이므로 gate 0 + completed = read-only.)
function isVerificationNA(m, i) {
  const s = resolveFinalStatus(m, i)
  return s === 'completed' && verifyCounts().total === 0
}
// compact 상태줄에 붙는 검증 요약(NOT_APPLICABLE·검증 없음이면 빈 문자열).
function verifySummary(m, i) {
  if (isVerificationNA(m, i)) return ''
  const v = verifyCounts()
  if (!v.total) return ''
  let s = `검증 ${v.passed} 통과`
  if (v.failed) s += ` · ${v.failed} 실패`
  if (v.unverified) s += ` · ${v.unverified} 미검증`
  return s
}

// 완료 semantic을 타임라인 터미널 노드로 — backend 실제 상태를 왜곡하지 않는다.
// completed_unverified를 ✓로 위장하지 않는다(검증 불완전은 !).
const _COMPLETION_NODES = {
  completed: { glyph: '✓', label: '완료', cls: 'done' },
  completed_unverified: { glyph: '!', label: '검증 불완전', cls: 'warn' },
  verification_failed: { glyph: '!', label: '검증 실패', cls: 'error' },
  context_blocked: { glyph: '!', label: '컨텍스트 한도 도달', cls: 'warn' },
  budget_exceeded: { glyph: '!', label: '예산 초과', cls: 'warn' },
  failed: { glyph: '!', label: '실패', cls: 'error' },
  cancelled: { glyph: '·', label: '중단됨', cls: 'muted' },
}
function completionNode(status) {
  return _COMPLETION_NODES[status] || null
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

// Timeline 항목을 탭하면 여는 Detail Surface. 상세(추론·도구 결과·검증)는 여기서만 렌더한다.
// detail = { phase, message, gates } 스냅샷. gates는 최신 메시지일 때만 실어 과거 메시지에 현재
// 세션 게이트가 잘못 붙는 것을 막는다.
const detail = ref(null)
let detailReturnEl = null
function phaseHasDetail(p) {
  return !!((p.tools && p.tools.length) || p.thinking)
}
function openDetail(m, p) {
  if (!phaseHasDetail(p)) return
  detailReturnEl = document.activeElement
  const isLast = messages.value[messages.value.length - 1] === m
  detail.value = { phase: p, message: m, gates: isLast ? gates.value : [] }
  nextTick(() => detailPanelEl.value?.focus())
}
function closeDetail() {
  detail.value = null
  const el = detailReturnEl
  detailReturnEl = null
  if (el && typeof el.focus === 'function') el.focus()
}
const detailPanelEl = ref(null)

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
    case 'task_update':
      // 진행 상황은 하단 task-bar가 "현재 태스크 n/전체"로 보여준다.
      // 메시지 카드에 목록을 또 나열하면 같은 정보를 두 번 말하게 된다.
      tasks.value = d.tasks || []
      break
    case 'gates_update':
      gates.value = d.gates || []
      break
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
      // 내부 단계명(generic/integration)을 사람 말로 옮긴다 — 내부 이벤트는 그대로 유지.
      assistant.verifyPhase = d.stage === 'integration' ? '최종 회귀 확인 중' : '테스트 중'
      break
    case 'gate_recovery':
      assistant.verifyPhase = d.phase === 'start' ? '요구사항 정리 중' : ''
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
    case 'mode_changed':
      loadRooms()  // 채팅→작업 자동 전환 시 헤더 모드 배지 갱신
      break
    case 'done':
      assistant.verifyPhase = ''
      assistant.finalStatus = d.status || ''   // 타임라인 터미널 노드용 — 실제 완료 semantic
      assistant.phases.forEach((p) => {
        p.running = false
        p.collapsed = true
      })
      if (d.content) assistant.doneMessage = d.content
      loadGates()  // 최종 게이트 상태 재조회(누락 이벤트 보정)
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

// 모드 전용 토글 — 작업 실행에는 전혀 영향을 주지 않는다(네트워크 호출 없음).
// 작업 중단(일시 정지)은 계획수정 메시지가 실제로 채팅에 전송될 때만 일어난다(steerDuringRun).
function toggleSteerMode() {
  steerMode.value = steerMode.value === 'queue' ? 'switch' : 'queue'
}

async function steerDuringRun(text) {
  const id = currentRoomId.value
  input.value = ''
  if (steerMode.value === 'switch') {
    // 계획수정: 메시지가 전송된 이 순간에만 작업을 일시 정지한다.
    // 이후 이 메시지로 새 작업을 시작(스트림 종료 시 자동 전송).
    try {
      await fetch(`/api/sessions/${id}/cancel`, { method: 'POST' })
    } catch {}
    pendingSend.value = text
  } else {
    // 큐 대기(기본) — 실행 중 에이전트에 주입, 다음 스텝에서 반영. 대기큐 배지로 표시.
    newUser(text, null, true)
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
  // 워크스페이스 미설정 세션에서 작업성 요청은 먼저 선택을 유도한다. chat(읽기전용)은 허용.
  if (needsWorkspace.value && currentRoom()?.mode !== 'chat') {
    alert('워크스페이스를 먼저 선택하세요. 홈 폴더에서 작업하면 git·스킬 동작이 깨질 수 있습니다.')
    openWorkspacePicker(currentRoomId.value)
    return
  }
  busy.value = true
  input.value = ''
  gates.value = []  // 새 run 시작 — 이전 run의 게이트 상태 제거(이번 run이 다시 등록)
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
  attachedImages.value.forEach(_revokePreview)
  attachedImages.value = []
  attachedText.value = null

  try {
    const roomId = await ensureRoom(text || (att ? att.name : '이미지 분석'))
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: roomId, message: payloadMsg, image_urls: imageUrls, auto_approve: autoApprove.value, model_tier: modelTier.value, budget_usd: budgetUsd.value === '' ? null : Number(budgetUsd.value) }),
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

// 파일(이미지/텍스트) 처리 공통 경로 — 파일 선택(onFileChange)과 드래그앤드롭(onDrop)이 함께 사용
async function handleFiles(files) {
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
        else { _revokePreview(entry); attachedImages.value = attachedImages.value.filter((a) => a !== entry) }
      } catch { _revokePreview(entry); attachedImages.value = attachedImages.value.filter((a) => a !== entry) }
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

async function onFileChange(e) {
  await handleFiles(Array.from(e.target.files || []))
  e.target.value = ''
}

// 드래그앤드롭 첨부
const dragActive = ref(false)
let dragCounter = 0

function onDragOver(e) {
  if (e.dataTransfer && Array.from(e.dataTransfer.types || []).includes('Files')) {
    e.preventDefault()
    dragCounter++
    dragActive.value = true
  }
}

function onDragLeave() {
  dragCounter = Math.max(0, dragCounter - 1)
  if (dragCounter === 0) dragActive.value = false
}

async function onDrop(e) {
  e.preventDefault()
  dragCounter = 0
  dragActive.value = false
  const files = Array.from(e.dataTransfer?.files || [])
  if (files.length) await handleFiles(files)
}

function _revokePreview(entry) {
  if (entry && entry.previewUrl) { try { URL.revokeObjectURL(entry.previewUrl) } catch {} }
}
function removeImage(idx) {
  _revokePreview(attachedImages.value[idx])
  attachedImages.value.splice(idx, 1)
}

function removeText() {
  attachedText.value = null
}

async function decide(approval, decision) {
  approvalError.value = ''
  try {
    const res = await fetch(`/api/approvals/${approval.id}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ decision }),
    })
    // 성공(2xx)일 때만 카드를 닫는다 — DB 상태와 화면이 어긋나지 않게. 실패면 카드를 유지하고
    // 짧은 안내를 띄운다(409=이미 처리·만료, 404=없음). 재시작으로 실행 주체를 잃은 승인은
    // 서버가 cancelled로 정리하므로 여기서 409로 걸러진다.
    if (res.ok) {
      activeApproval.value = null // 복구 모달 닫기
    } else {
      approvalError.value = res.status === 409 ? '이미 처리됐거나 만료된 승인입니다.'
        : res.status === 404 ? '승인을 찾을 수 없습니다.'
        : '승인 처리에 실패했습니다.'
    }
  } catch {
    approvalError.value = '네트워크 오류로 처리하지 못했습니다.'
  }
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
})

applyTheme(theme.value)

onMounted(async () => {
  // 넓은 화면(맥)에선 사이드바를 상시 렌더(고정 또는 hover 노출). 좁으면 오버레이 드로어.
  const mq = window.matchMedia('(min-width: 900px)')
  const applyWide = () => { isWide.value = mq.matches }
  applyWide()
  mq.addEventListener('change', applyWide)
  // Detail Surface: Escape로 닫기(dialog 접근성).
  window.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && detail.value) { e.preventDefault(); closeDetail() }
  })
  loadBalance() // 앱 실행 시 잔액 최초 1회 fetch(전역 상태로 공유)
  startHealthPoll() // 서버 도달성 상시 감시 — 먹통이면 배너로 알린다
  loadHomePath() // 워크스페이스 미설정(홈) 판별 기준
  await loadRooms()
  // 서버가 목록을 확인해준 경우에만 랜딩을 보정한다. 로드 실패면 currentRoomId를 보존해
  // 서버 복구 후 기존 방으로 되돌아갈 수 있게 한다(pingHealth 복구 분기가 재동기화).
  reconcileCurrentRoom()
  // 첫 랜딩도 방 전환과 같은 규칙으로 세션 설정을 복원한다(selectRoom을 거치지 않는 경로).
  const landed = currentRoom()
  if (landed && landed.model_tier) modelTier.value = landed.model_tier
  await loadMessages()
  await loadTasks()
  await loadGates()
  checkRunning()
})

document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') reconcileOnResume()
})
</script>

<template>
  <div class="app" :class="{ 'sidebar-pinned': isWide && pinnedSidebar }">
    <div v-if="serverDown" class="server-down" @click="pingHealth()">
      <span class="server-down-dot"></span>
      서버에 연결할 수 없습니다 — 백엔드가 재시작 중이거나 응답하지 않습니다. 자동으로 다시 시도합니다.
    </div>
    <header>
      <button v-if="!(isWide && pinnedSidebar)" class="icon-btn" @click="isWide ? togglePin() : (showRooms = true)" aria-label="세션 목록">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 6h16M4 12h16M4 18h16"/></svg>
      </button>
      <button class="room-btn" @click="openRoomSettings()">
        <span class="room-title-main">
          <span class="status-dot" :class="(busy || sessionRunning) ? 'working' : 'idle'"></span>
          <span class="room-title-text">{{ currentRoom()?.title || 'FORGE' }}</span>
          <span v-if="currentRoom()?.mode === 'chat'" class="room-mode-badge chat">채팅</span>
        </span>
        <span class="room-sub">
          <span v-if="busy" class="status-live">실행 중</span><template v-if="busy"> · </template>
          <template v-if="needsWorkspace"><span class="ws-badge">워크스페이스 미설정 · 선택</span></template>
          <template v-else>{{ shortPath(currentRoom()?.workspace_path) || 'Mobile Coding Agent' }}</template>
        </span>
      </button>
      <div class="header-right">
        <button class="todo-btn" @click="showMenu = !showMenu" aria-label="메뉴">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="19" cy="12" r="1.6"/></svg>
        </button>
      </div>
    </header>

    <div v-if="busy || sessionRunning" class="running-banner" :class="{ waiting: agentStatus && agentStatus.waiting_for }">
      <span class="running-dot"></span>{{ runningBannerText() }}
    </div>

    <MenuPanel
      v-if="showMenu"
      :ctx-pct="ctxPct(currentRoom())"
      :ctx-class="ctxClass(ctxPct(currentRoom()))"
      :theme="theme"
      :themes="THEMES"
      @close="showMenu = false"
      @session-detail="showSessionDetail = true; showMenu = false"
      @fork-session="forkSession(); showMenu = false"
      @top-up="openTopUpConfirm(); showMenu = false"
      @files="showFiles = true; showMenu = false"
      @git="showGit = true; showMenu = false"
      @kanban="showKanban = true; loadTasks(); showMenu = false"
      @skills="openSkills(); showMenu = false"
      @push="showPush = true; showMenu = false"
      @agents="showCrew = true; showMenu = false"
      @admin="openAdmin(); showMenu = false"
      @set-theme="setTheme($event)"
    />

    <RoomsPanel
      :rooms="rooms"
      :current-room-id="currentRoomId"
      :is-wide="isWide"
      :pinned-sidebar="pinnedSidebar"
      :show-rooms="showRooms"
      :refresh-rooms="loadRooms"
      @select-room="selectRoom"
      @jump-to-message="jumpToMessage"
      @delete-room="deleteRoom"
      @rename-room="renameRoom"
      @open-workspace-picker="openWorkspacePicker"
      @open-create-room="showCreateRoom = true; showRooms = false"
      @close="showRooms = false"
      @toggle-pin="togglePin"
    />


    <div class="chat-area">
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
        <template v-if="needsWorkspace">
          <div class="ws-guide">
            <p class="ws-guide-title">워크스페이스가 설정되지 않았습니다</p>
            <p class="ws-guide-sub">작업할 폴더를 먼저 선택하세요. 홈 폴더에서 작업하면 git·스킬 동작이 깨질 수 있습니다.</p>
            <button class="ws-guide-btn" @click="chooseWorkspace()">워크스페이스 선택</button>
          </div>
        </template>
        <!-- 방이 실제로 있을 때만 작업 안내·퀵액션. 서버 확인 전/실패(room 없음+미설정 아님)엔
             빈 경로로 안내 문구가 뜨지 않도록 currentRoom() 존재를 조건으로 둔다. -->
        <p v-else-if="currentRoom()" class="sub">{{ shortPath(currentRoom()?.workspace_path) }}에서 자율로 작업합니다.</p>
        <div v-if="!needsWorkspace && currentRoom()" class="quick-actions">
          <button class="quick-action" @click="quickAction('이 프로젝트의 구조와 핵심 동작을 파악해서 요약해줘')">프로젝트 파악</button>
          <button class="quick-action" @click="quickAction('현재 git 변경사항을 리뷰해줘')">변경사항 리뷰</button>
          <button class="quick-action" @click="quickAction('git 상태와 최근 커밋을 확인해서 알려줘')">Git 상태 확인</button>
          <button class="quick-action" @click="quickAction('테스트를 실행하고 결과를 알려줘')">테스트 실행</button>
        </div>
      </div>

      <div v-for="(m, i) in messages" :key="i" :data-msg-idx="i" class="msg" :class="m.role">
        <div class="bubble">
          <template v-if="m.role === 'user'">
            <details v-if="processNote(m.content)" class="process-note" :class="'tone-' + processNote(m.content).tone">
              <summary>
                <span class="proc-icon" aria-hidden="true">⚙</span>
                <span class="proc-label">{{ processNote(m.content).label }}</span>
                <span v-if="processNote(m.content).state" class="proc-state">{{ processNote(m.content).state }}</span>
                <svg class="proc-chevron" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18l6-6-6-6"/></svg>
              </summary>
              <div class="process-note-body" @click="closeParentDetails">{{ m.content }}</div>
            </details>
            <div v-else-if="m.queued" class="queue-badge">
              <span class="queue-dot"></span>대기큐<span class="queue-text">{{ m.content }}</span>
            </div>
            <template v-else>
              <div v-if="m.images && m.images.length" class="user-images">
                <img v-for="(img, ii) in m.images" :key="ii" :src="img" class="user-image" @click="openViewer(m.images, ii)" alt="첨부 이미지" />
              </div>
              <div v-if="m.content && m.content !== '[이미지]'" class="user-text">{{ m.content }}</div>
            </template>
          </template>

          <template v-if="m.role === 'assistant'">
            <!-- 순수 대화 답변(도구·추론 없음) — 상태 기호 없이 본문만. ✓는 Agent Activity 전용. -->
            <template v-if="!hasActivity(m)">
              <template v-for="(p, pi) in m.phases" :key="'txt' + pi">
                <div v-if="p.text" class="text" v-html="renderMarkdown(p.text)"></div>
              </template>
            </template>
            <!-- Activity 메시지: 응답을 먼저, 실행 로그(타임라인)는 아래로 · 완료 후 기본 접힘(정보밀도↓).
                 헤더에 종류·개수(실행 N · 추론 N · 도구 N). 실행 중엔 접기 없이 라이브로 펼쳐 둔다. -->
            <template v-else>
            <!-- 1. 최종 답변(primary) — 개발자의 실제 결과를 채팅 본문으로 승격(Activity에 묻지 않는다). -->
            <div v-if="finalAnswer(m)" class="text answer" v-html="renderMarkdown(finalAnswer(m))"></div>
            <!-- 2. compact 상태 + Activity 토글 — 상태·검증요약·개수는 secondary. 탭하면 로그 펼침. -->
            <div v-if="m.phases.length" class="activity">
              <button class="activity-line" :aria-expanded="logsShown(m, i) ? 'true' : 'false'" @click="toggleLogs(m, i)">
                <span v-if="finalStatusInfo(m, i)" class="al-status" :class="finalStatusInfo(m, i).cls">
                  <span class="al-glyph" aria-hidden="true">{{ finalStatusInfo(m, i).glyph }}</span>{{ finalStatusInfo(m, i).label }}<span v-if="verifySummary(m, i)"> · {{ verifySummary(m, i) }}</span>
                </span>
                <span class="al-counts"><span v-if="finalStatusInfo(m, i)"> · </span>실행 {{ logCounts(m).steps }}<span v-if="logCounts(m).think"> · 추론 {{ logCounts(m).think }}</span><span v-if="logCounts(m).tools"> · 도구 {{ logCounts(m).tools }}</span></span>
                <svg class="al-chevron" :class="{ open: logsShown(m, i) }" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 18l6-6-6-6"/></svg>
              </button>
              <div v-if="logsShown(m, i)" class="activity-body">
              <!-- 검증 경고(미검증·실패)는 기본 숨김 — Activity 펼침(상세)에서만 노출. -->
              <div v-for="(w, wi) in resultWarnings(m)" :key="'w' + wi" class="result-warn" :class="w.kind === '실패' ? 'error' : 'warn'">
                <div class="rw-head"><span class="rw-kind">{{ w.kind }}</span><span v-if="w.title" class="rw-title">· {{ w.title }}</span></div>
                <div class="rw-reason">{{ w.reason }}</div>
              </div>
              <div class="timeline">
            <div v-for="(p, pi) in m.phases" :key="pi" class="tl-node" :class="phaseStatus(p)">
              <span class="tl-marker" :class="phaseStatus(p)" aria-hidden="true">{{ phaseGlyph(p) }}</span>
              <div class="tl-content">
              <!-- phase 헤더 — 상세(추론·도구 호출·결과)가 있으면 탭해서 Detail Surface를 연다.
                   Timeline엔 흐름·요약만: 긴 추론·도구 결과는 여기서 펼치지 않는다. -->
              <div
                v-if="phaseHasDetail(p)"
                class="tl-head tappable"
                role="button"
                tabindex="0"
                aria-haspopup="dialog"
                @click="openDetail(m, p)"
                @keydown.enter.prevent="openDetail(m, p)"
                @keydown.space.prevent="openDetail(m, p)"
              >
                <span class="tl-agent">{{ phaseLabel(p) }}</span>
                <span v-if="p.model" class="tl-model">{{ shortModel(p.model) }}</span>
                <span v-if="p.running && runningTool(p)" class="tl-state">{{ runningTool(p).name }} 실행 중…</span>
                <!-- 검증 단계(테스트/요구사항/회귀/복구)는 프로세스가 보낸 이벤트로만 표시한다. -->
                <span v-else-if="m.verifyPhase && pi === m.phases.length - 1" class="tl-state">{{ m.verifyPhase }}<span class="typing-dots"><i></i><i></i><i></i></span></span>
                <span v-else-if="p.running" class="tl-state">생각 중<span class="typing-dots"><i></i><i></i><i></i></span></span>
                <template v-else>
                  <span v-if="p.thinking" class="tl-count">추론</span>
                  <span v-if="p.tools.length" class="tl-count">도구 {{ p.tools.length }}</span>
                  <!-- 도구 실패 통계(Activity 실패 아님) — "문제 N"은 모호해 "실패 N"으로. -->
                  <span v-if="phaseErrorCount(p)" class="tl-problem">실패 {{ phaseErrorCount(p) }}</span>
                </template>
                <svg class="tl-open" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 18l6-6-6-6"/></svg>
              </div>

              <!-- 핵심 결과 요약 — 완료 phase는 결과형 시제로(미래형 "…하겠습니다" 제거). -->
              <div v-if="p.text" class="text" v-html="renderMarkdown(phaseSummary(p))"></div>
              </div>
            </div>
            <!-- 완료 터미널 노드 — backend 실제 completion semantic. completed_unverified를
                 ✓로 위장하지 않는다(검증 불완전은 !). live done 이벤트에서만(재구성 시엔 요약 본문). -->
            <div v-if="completionNode(m.finalStatus)" class="tl-node tl-terminal" :class="completionNode(m.finalStatus).cls">
              <span class="tl-marker" :class="completionNode(m.finalStatus).cls" aria-hidden="true">{{ completionNode(m.finalStatus).glyph }}</span>
              <div class="tl-content">
                <div class="tl-head"><span class="tl-agent">{{ completionNode(m.finalStatus).label }}</span></div>
              </div>
            </div>
            </div>
            </div>
            </div>
            </template>

            <div v-if="(m.state && (m.state.files_changed?.length || m.state.errors?.length)) || m.compacted" class="state-summary">
              <span v-if="m.state?.files_changed?.length" class="state-chip tappable" role="button" tabindex="0" @click="m.filesOpen = !m.filesOpen" @keydown.enter="m.filesOpen = !m.filesOpen">변경 파일 {{ m.state.files_changed.length }}</span>
              <span v-if="m.state?.errors?.length" class="state-chip err">오류 {{ m.state.errors.length }}</span>
              <span v-if="m.compacted" class="state-chip">컨텍스트 압축됨</span>
            </div>
            <!-- 변경 파일 경로 칩 — 접힘 기본. 경로는 nowrap+말줄임(중간 줄바꿈 방지), 탭하면 diff(Git). -->
            <div v-if="m.filesOpen && m.state?.files_changed?.length" class="file-chips">
              <button v-for="(f, fi) in m.state.files_changed" :key="fi" class="path-chip" :title="f" @click="showGit = true">{{ f }}</button>
            </div>

            <div v-if="m.approval" class="approval">
              <div class="approval-head">도구 실행 승인이 필요합니다</div>
              <div class="approval-tool">{{ m.approval.tool }}<span v-if="summarizeArgs(m.approval.args)"> — {{ summarizeArgs(m.approval.args) }}</span></div>
              <pre v-if="approvalBody(m.approval.args)" class="approval-body">{{ approvalBody(m.approval.args) }}</pre>
              <div class="approval-btns">
                <button class="ok" @click="decide(m.approval, 'approve')">승인</button>
                <button class="no" @click="decide(m.approval, 'reject')">거부</button>
              </div>
              <div v-if="approvalError" class="approval-err">{{ approvalError }}</div>
            </div>

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
                <span class="refine-status">{{ r.status === 'approved' ? '승인됨 · skill 적용' : '무시함' }}</span>
                <button class="no" @click="decideRefinement(r, 'rollback')">되돌리기</button>
              </div>
            </div>

            <div v-if="m.context && !isLiveTurn(i)" class="context">
              context {{ m.context.prompt_tokens + m.context.completion_tokens }} tokens<span
                v-if="m.context.cache_hit_ratio != null"> · cache {{ Math.round(m.context.cache_hit_ratio * 100) }}%</span>
            </div>

            <div v-if="hasAssistantText(m) && !isLiveTurn(i)" class="msg-actions">
              <button class="msg-action icon-only" @click="copyMessage(m)" :aria-label="m.copied ? '복사됨' : '복사'" :title="m.copied ? '복사됨' : '복사'">
                <svg v-if="!m.copied" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
                <svg v-else width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>
              </button>
            </div>
          </template>
        </div>
      </div>

      <!-- 대기큐 채팅처럼 마지막 메시지가 사용자면, 작성 중 표시가 사용자 말풍선 안에
           들어가 보였다. 어시스턴트 쪽(왼쪽) 별도 말풍선으로 띄운다. -->
      <div
        v-if="(busy || sessionRunning) && messages.length && messages[messages.length - 1].role === 'user'"
        class="msg assistant"
      >
        <div class="bubble">
          <div class="typing">
            <span class="typing-label">{{ busy ? '작성 중' : liveActivityText() }}</span>
            <span class="typing-dots"><i></i><i></i><i></i></span>
          </div>
        </div>
      </div>
    </main>
      <button v-if="!isAtBottom" class="jump-bottom" @click="jumpToBottom" :aria-label="unseenCount ? `새 메시지 ${unseenCount}개, 맨 아래로` : '맨 아래로'">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M5 12l7 7 7-7"/></svg>
        <span v-if="unseenCount" class="jump-badge">{{ unseenCount > 9 ? '9+' : unseenCount }}</span>
      </button>
    </div>

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
      <div v-if="taskBar" class="task-bar" :class="{ idle: !(busy || sessionRunning) }" @click="showKanban = true; loadTasks()">
        <span class="task-bar-dot" :class="{ running: busy || sessionRunning }"></span>
        <span class="task-bar-title">{{ taskBar.title }}</span>
        <span class="task-bar-count">{{ taskBar.pos }}/{{ taskBar.total }}</span>
      </div>
      <input ref="fileInput" type="file" multiple accept="image/*,.md,.txt,.log,.json,.csv,.yml,.yaml,.toml,.py,.js,.ts,.jsx,.tsx,.vue,.html,.css,.sh,.xml,.java,.go,.rs,.c,.cpp,.h,.sql,text/*" hidden @change="onFileChange" />
      <div class="composer-wrap">
      <div class="composer" :class="{ 'drag-over': dragActive }" @dragover="onDragOver" @dragleave="onDragLeave" @drop="onDrop">
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
        <img :src="img.previewUrl || img.url" alt="첨부 이미지" @click="openViewer(attachedImages.map((a) => a.previewUrl || a.url), ii)" />
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
              모델 {{ tierLabel() }}
            </button>
            <button
              class="mode-chip"
              :class="{ on: autoApprove }"
              @click="toggleAutoApprove"
              :title="autoApprove ? '자동: 위험 명령도 확인 없이 실행됩니다' : '요청: 실행 전 승인을 요청합니다'"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M13 2L3 14h7l-1 8 10-12h-7z"/></svg>
              승인 {{ autoApprove ? '자동' : '요청' }}
            </button>
            <button v-if="busy || sessionRunning" class="mode-chip small ghost" @click="toggleSteerMode">
              {{ steerMode === 'queue' ? '작업 대기' : '계획 수정' }}
            </button>
          </div>
          <button id="send" class="composer-send" :disabled="!input.trim() && !attachedImages.length && !attachedText" @click="send" aria-label="전송">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5M6 11l6-6 6 6"/></svg>
          </button>
        </div>
      </div>
      </div>
    </footer>

    <!-- Agent 활동 Detail Surface — 모바일=bottom sheet / 데스크톱=우측 side panel.
         내용은 ActivityDetailPanel 하나를 공유(두 번 구현 금지). Escape·overlay 클릭으로 닫힘. -->
    <div v-if="detail" class="detail-surface" :class="{ wide: isWide }" @click="closeDetail">
      <div
        ref="detailPanelEl"
        class="detail-dock"
        role="dialog"
        aria-modal="true"
        aria-label="활동 상세"
        tabindex="-1"
        @click.stop
      >
        <ActivityDetailPanel
          :phase="detail.phase"
          :message="detail.message"
          :gates="detail.gates"
          :render-markdown="renderMarkdown"
          @close="closeDetail"
        />
      </div>
    </div>

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
        <div v-if="approvalError" class="approval-err">{{ approvalError }}</div>
        <div class="modal-actions">
          <button class="no" @click="decide(activeApproval, 'reject')">거부</button>
          <button class="ok" @click="decide(activeApproval, 'approve')">승인</button>
        </div>
      </div>
    </div>

    <div v-if="showCreateRoom" class="modal-overlay" @click="showCreateRoom = false">
      <div class="modal" @click.stop>
        <div class="modal-head">새 세션</div>
        <input v-model="newRoomName" class="modal-field" placeholder="세션 이름 (기본: New Session)" />
        <button type="button" class="modal-field ws-btn" @click="openWorkspacePicker(null)">
          {{ newRoomPath || '워크스페이스 선택(필수)' }}
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
      :gates="gates"
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
        <div v-for="s in skills" :key="s.name" class="admin-section skill-card">
          <div class="skill-head" @click="skillOpen[s.name] = !skillOpen[s.name]">
            <svg class="skill-chevron" :class="{ open: skillOpen[s.name] }" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18l6-6-6-6"/></svg>
            <span class="skill-name">{{ s.name }}</span>
            <span class="skill-scope" :class="s.origin || s.scope">{{ { curated: '큐레이트', learned: '학습', project: '프로젝트' }[s.origin] || (s.scope === 'global' ? '전역' : '프로젝트') }}</span>
            <button v-if="s.origin !== 'curated'" class="skill-del" @click.stop="deleteSkill(s.name, s.scope)">삭제</button>
          </div>
          <pre v-show="skillOpen[s.name]" class="skill-content">{{ skillBody(s.content) }}</pre>
        </div>
      </div>
    </div>

    <PushPanel v-if="showPush" @close="showPush = false" />

    <AgentCrewPanel
      v-if="showCrew"
      :session-id="currentRoomId || ''"
      @close="showCrew = false"
    />

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

    <FileBrowserPanel
      v-if="showFiles"
      :session-id="currentRoomId || ''"
      :workspace-path="currentRoom()?.workspace_path || ''"
      :show-hidden="showHidden"
      @close="showFiles = false"
      @toggle-hidden="showHidden = !showHidden"
      @image-click="openViewer($event)"
    />

    <div v-if="showRoomSettings" class="sheet-overlay" @click="showRoomSettings = false">
      <div class="sheet" @click.stop>
        <div class="sheet-head">방 설정</div>
        <input v-model="roomSettingsTitle" class="modal-field" placeholder="방 이름" />
        <div class="mode-seg big" role="group" aria-label="방 모드">
          <button :class="{ on: roomSettingsMode === 'auto' }" @click="roomSettingsMode = 'auto'">자동</button>
          <button :class="{ on: roomSettingsMode === 'work' }" @click="roomSettingsMode = 'work'">작업</button>
          <button :class="{ on: roomSettingsMode === 'chat' }" @click="roomSettingsMode = 'chat'">채팅</button>
        </div>
        <p class="sheet-note">자동: 요청마다 작업/채팅 자동 판단 · 작업: 항상 코드 수정·검증·커밋 · 채팅: 읽기전용 대화</p>
        <input v-model="budgetUsd" @change="saveBudget" class="modal-field" type="number" min="0" step="0.5"
               inputmode="decimal" placeholder="작업 비용 상한 $ (비우면 기본 $2, 0=무제한)" />
        <p class="sheet-note">작업 1회 비용이 이 상한을 넘으면 안전하게 중단합니다(runaway 비용 방지). 모든 세션 공통 기본값입니다.</p>
        <button class="sheet-save" @click="saveRoomSettings">저장</button>
      </div>
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
          <button v-if="fsParent && !fsFilter" class="fs-item parent" @click="navigateFs(fsParent)">
            <svg class="fs-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18l-6-6 6-6"/><path d="M3 12h12a6 6 0 0 1 6 6v2"/></svg>
            상위 폴더
          </button>
          <div v-if="fsFilter && !fsVisible.length" class="fs-empty">일치하는 항목 없음</div>
          <button
            v-for="e in fsVisible"
            :key="e.path"
            class="fs-item"
            :class="e.is_dir ? 'dir' : 'file'"
            :disabled="!e.is_dir"
            @click="navigateFs(e.path)"
          >
            <FsIcon :entry="e" />
            {{ e.name }}
          </button>
        </div>
    </div>
  </div>
</template>
