<script setup>
import { ref, computed, watch, nextTick } from 'vue'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'
import { makeMoveThrottle } from '../lib/moveThrottle.js'
import { pullDistance, pullReady } from '../lib/pullToRefresh.js'
import { toScreenXY, containContentRect } from '../lib/screenCoord.js'

const props = defineProps({
  rooms: { type: Array, default: () => [] },
  currentRoomId: { type: String, default: '' },
  isWide: { type: Boolean, default: false },
  pinnedSidebar: { type: Boolean, default: true },
  showRooms: { type: Boolean, default: false },
  // 세션 목록 새로고침(rooms는 부모 소유) — await 가능한 함수 prop.
  refreshRooms: { type: Function, default: null },
})
const emit = defineEmits([
  'select-room',
  'jump-to-message',
  'delete-room',
  'rename-room',
  'open-workspace-picker',
  'open-create-room',
  'close',
  'toggle-pin',
])

const sidebarTab = ref('sessions') // sessions | jobs | mac
const searchQuery = ref('')
const searchResults = ref([])
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

// ─── 예약 작업(Scheduled Jobs) ───
const jobs = ref([])
const showJobForm = ref(false)
const jobForm = ref({ name: '', prompt: '', workspace_path: '', schedule: 'once', at: '', time: '09:00', interval: 60 })
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

// ─── 맥: 카페인 / 화면 / 터미널 / 카메라 ───
const macView = ref('')
const macControls = ref(true) // 유튜브형: 화면 탭하면 컨트롤 토글
const screenOn = ref(false)
const screenSrc = ref('')
const screenErr = ref('')
let screenSeq = 0
const remoteCtrl = ref(false) // 원격제어(마우스/키보드) 활성화
const remoteErr = ref('')
function toggleRemote(ev) {
  remoteCtrl.value = !!ev.target.checked
  if (remoteCtrl.value) macControls.value = false // 켜면 바를 숨겨 터치영역 확보
}
let screenImg = null // 현재 표시된 이미지 요소(좌표 스케일링용)
let screenNatural = { w: 0, h: 0 } // 원본 캡처 해상도
// 마우스 이동은 ~25Hz로 줄여 보낸다 — 이벤트마다 POST하면 host가 입력 폭주로 밀린다.
const sendMove = makeMoveThrottle((p) => macSend({ type: 'move', x: p.x, y: p.y }), 40)
const caffeineOn = ref(false)
const camOn = ref(false)
const camSrc = ref('')
const camErr = ref('')
let camSeq = 0

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
  remoteCtrl.value = false
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
  screenSrc.value = `/api/mac/screen?d=1&max_px=1280&t=${Date.now()}_${screenSeq++}`
}
function onScreenImgLoad(e) {
  screenImg = e.target
  screenNatural = { w: e.target.naturalWidth || 0, h: e.target.naturalHeight || 0 }
  screenErr.value = ''
  if (screenOn.value) setTimeout(screenTick, 150)
}
function onScreenError() {
  screenErr.value = '화면을 가져오지 못했습니다. 시스템 설정 › 개인정보 보호 › 화면 기록에서 백엔드(터미널/파이썬)에 권한을 허용하세요.'
  screenOn.value = false
}
// CSS와 동일 조건(portrait에서 rotate(90deg) 표시) — 회전 보정이 필요한지 판단
const isRotatedScreen = () => window.matchMedia('(orientation: portrait)').matches
// 표시된 이미지 좌표 → 실제 화면 좌표 변환 (회전 보정 포함)
function toDisplayScreenXY(ev) {
  if (!screenImg || !screenNatural.w) return null
  const rect = screenImg.getBoundingClientRect()
  const rotated = isRotatedScreen()
  const content = containContentRect(rect, screenNatural, rotated)
  return toScreenXY(ev, content, screenNatural, rotated)
}
async function macSend(payload) {
  try {
    const r = await fetch('/api/mac/input', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    if (!r.ok) {
      const t = await r.text()
      remoteErr.value = t.includes('unsupported') ? '원격제어는 macOS 백엔드에서만 지원합니다.' : `입력 실패: ${t}`
    }
  } catch (err) {
    remoteErr.value = '입력 전송 실패: ' + err.message
  }
}
// pointerdown 기반: 터치·마우스 모두 즉시 처리. click은 500ms 화면 갱신 시 취소될 수 있어
// 사용하지 않는다(탭 중 src가 교체되면 click이 발생하지 않는 모바일 브라우저 동작 우회).
function onScreenPointerDown(ev) {
  if (!remoteCtrl.value) {
    macControls.value = !macControls.value // 원격제어 꺼져 있으면 탭으로 컨트롤 표시/숨김
    return
  }
  const p = toDisplayScreenXY(ev)
  if (!p) return
  macSend({ type: 'click', x: p.x, y: p.y, button: ev.button === 2 ? 'right' : 'left', clicks: ev.detail || 1 })
}
function onScreenMove(ev) {
  if (!remoteCtrl.value) return
  const p = toDisplayScreenXY(ev)
  if (p) sendMove(p)
}
function onScreenWheel(ev) {
  if (!remoteCtrl.value) return
  ev.preventDefault()
  macSend({ type: 'scroll', dy: Math.round(ev.deltaY) })
}
function onScreenKey(ev) {
  if (!remoteCtrl.value) return
  // 키 코드 매핑 (macOS key code)
  const map = {
    Enter: 36, Tab: 48, Escape: 53, Backspace: 51, Delete: 117,
    ArrowUp: 126, ArrowDown: 125, ArrowLeft: 123, ArrowRight: 124,
    Home: 115, End: 119, PageUp: 116, PageDown: 121,
    ' ': 49, '.': 47, ',': 43, '/': 44, ';': 41, "'": 39,
    '[': 33, ']': 30, '\\': 42, '-': 27, '=': 24, '`': 50,
  }
  const code = map[ev.key]
  if (code !== undefined) {
    ev.preventDefault()
    macSend({ type: 'key', key: code })
  } else if (ev.key.length === 1) {
    // 일반 문자는 텍스트 입력으로 전달
    ev.preventDefault()
    macSend({ type: 'text', text: ev.key })
  }
}

function closeMacView() {
  stopScreen()
  stopTerminal()
  stopCamera()
  macView.value = ''
  macControls.value = true // 다음에 열 때 컨트롤 보이게
  remoteCtrl.value = false
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
  const sid = props.currentRoomId || ''
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

// ─── 스와이프 삭제 ───
const swipedRoomId = ref(null)
const swipedJobId = ref(null)
// ─── 풀투리프레시(세션·예약 목록) ───
// 스크롤 최상단에서 아래로 당기면 새로고침. 가로 스와이프(아이템 삭제)와 축이 달라 충돌 안 함.
const pullY = ref(0)
const pullRefreshing = ref(false)
let pullStartY = 0
let pullAtTop = false
function activeRefresh() {
  if (sidebarTab.value === 'jobs') return loadJobs()
  if (sidebarTab.value === 'sessions' && props.refreshRooms) return props.refreshRooms()
  return Promise.resolve()
}
function onPullStart(e) {
  if (pullRefreshing.value) return
  pullAtTop = e.currentTarget.scrollTop <= 0
  pullStartY = e.touches[0].clientY
}
function onPullMove(e) {
  if (!pullAtTop || pullRefreshing.value) return
  const dy = e.touches[0].clientY - pullStartY
  const d = pullDistance(dy)
  pullY.value = d
  if (d > 0) e.preventDefault()  // 당기는 동안만 브라우저 고무줄 스크롤을 막는다
}
const pullReadyNow = computed(() => pullReady(pullY.value))
async function onPullEnd() {
  if (pullRefreshing.value) return
  if (pullReady(pullY.value)) {
    pullRefreshing.value = true
    try { await activeRefresh() } finally {
      pullRefreshing.value = false
      pullY.value = 0
    }
  } else {
    pullY.value = 0
  }
}

// 손가락을 따라 실시간 이동하는 드래그 추적 스와이프.
// touchmove 중 transform을 직접 갱신하고, touchend에서 이동 거리·방향으로 열림/닫힘을 결정한다.
const SWIPE_DEL_W = 84
let swipeEl = null          // 드래그 중인 아이템 DOM
let swipeKey = null         // 'r:<id>' | 'j:<id>'
let swipeStartX = 0
let swipeStartY = 0
let swipeActive = false     // 가로 스와이프로 확정됨
let swipeFromOpen = false   // 시작 시 이미 열려 있었나
let swipeX = 0              // 현재 translateX
function swipeIsOpen(key) {
  const isRoom = key.startsWith('r:')
  return isRoom ? swipedRoomId.value === key.slice(2) : swipedJobId.value === key.slice(2)
}
function onSwipeStart(key, e) {
  if (swipeEl) return
  const t = e.touches[0]
  swipeStartX = t.clientX
  swipeStartY = t.clientY
  swipeEl = e.currentTarget
  swipeKey = key
  swipeActive = false
  swipeFromOpen = swipeIsOpen(key)
  swipeEl.style.transition = 'none'
  swipeEl.style.transform = swipeFromOpen ? `translateX(${-SWIPE_DEL_W}px)` : ''
  swipeX = swipeFromOpen ? -SWIPE_DEL_W : 0
}
function onSwipeMove(e) {
  if (!swipeEl) return
  const t = e.touches[0]
  const dx = t.clientX - swipeStartX
  const dy = t.clientY - swipeStartY
  if (!swipeActive) {
    if (Math.abs(dx) < 8 && Math.abs(dy) < 8) return
    if (Math.abs(dy) > Math.abs(dx)) { resetSwipe(); return }  // 세로 스크롤로 판정 → 취소
    swipeActive = true
  }
  e.preventDefault()  // 스와이프 중 세로 스크롤·고무줄을 막는다
  swipeX = Math.max(-SWIPE_DEL_W, Math.min(0, (swipeFromOpen ? -SWIPE_DEL_W : 0) + dx))
  swipeEl.style.transform = `translateX(${swipeX}px)`
}
function onSwipeEnd() {
  if (!swipeEl || !swipeActive) { resetSwipe(); return }
  const open = swipeX <= -SWIPE_DEL_W / 2
  const id = swipeKey.slice(2)
  if (swipeKey.startsWith('r:')) swipedRoomId.value = open ? id : null
  else swipedJobId.value = open ? id : null
  swipeEl.style.transition = 'transform .22s cubic-bezier(.22,1,.36,1)'
  swipeEl.style.transform = open ? `translateX(${-SWIPE_DEL_W}px)` : ''
  resetSwipe()
}
function onSwipeCancel() { resetSwipe() }
function resetSwipe() {
  if (swipeEl) { swipeEl.style.transition = ''; swipeEl.style.transform = '' }
  swipeEl = null
  swipeKey = null
  swipeActive = false
  swipeFromOpen = false
  swipeX = 0
}

// ─── 방 메뉴(이름 변경·워크스페이스·삭제) ───
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
function menuRoom() {
  return props.rooms.find((r) => r.id === roomMenuId.value) || null
}

function roomTitle(id) {
  return props.rooms.find((r) => r.id === id)?.title || id.slice(0, 8)
}

function selectRoom(id, isNew = false) {
  searchQuery.value = ''
  searchResults.value = []
  emit('select-room', id, isNew)
}

function ctxPct(room) {
  const used = room?.used_tokens || 0
  const budget = room?.logical_budget || 262144
  if (!budget) return 0
  return Math.min(100, Math.round((used / budget) * 100))
}

function statusClass(status) {
  if (status === 'completed') return 'ok'
  if (status === 'verification_failed' || status === 'failed') return 'err'
  if (status === 'completed_unverified') return 'warn'
  return 'idle'
}

watch(
  () => props.showRooms,
  (v) => {
    if (!v) stopScreen() // 닫으면 화면 폴링 정지
  }
)
</script>

<template>
  <div
    v-if="showRooms || isWide"
    class="rooms-overlay"
    :class="{ pinned: isWide && pinnedSidebar, peek: isWide && !pinnedSidebar }"
    @click="!isWide && emit('close')"
  >
    <div class="rooms-panel" @click.stop>
      <div class="drawer-head">
        <span class="drawer-title">{{ sidebarTab === 'sessions' ? '세션' : sidebarTab === 'jobs' ? '예약 작업' : '맥' }}</span>
        <div class="drawer-head-actions">
          <button v-if="sidebarTab === 'sessions'" class="drawer-add" @click="emit('open-create-room')" aria-label="새 세션">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>
          </button>
          <button v-if="sidebarTab === 'jobs'" class="drawer-add" @click="showJobForm = true" aria-label="새 예약">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>
          </button>
          <button v-if="isWide" class="drawer-close pin" :class="{ on: pinnedSidebar }" @click="emit('toggle-pin')" :aria-label="pinnedSidebar ? '사이드바 고정 해제' : '사이드바 고정'">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="16" rx="2"/><line x1="9" y1="4" x2="9" y2="20"/></svg>
          </button>
          <button v-else class="drawer-close" @click="emit('close')" aria-label="닫기">
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
          <div v-for="r in searchResults" :key="r.session_id + (r.message_id || '')" class="search-result" @click="emit('jump-to-message', r, searchQuery)">
            <div class="search-title">{{ roomTitle(r.session_id) }}</div>
            <div class="search-snippet">{{ r.snippet }}</div>
          </div>
        </div>
        <div v-else-if="searchQuery" class="rooms-scroll">
          <div class="admin-sub" style="padding:16px">검색 결과가 없습니다.</div>
        </div>
        <div v-else class="ptr-wrap" :style="{ transform: (pullY || pullRefreshing) ? `translateY(${pullRefreshing ? 40 : pullY}px)` : '', transition: (pullY && !pullRefreshing) ? 'none' : 'transform .22s' }">
          <div class="ptr-hint" :class="{ ready: pullReadyNow, spin: pullRefreshing }">
            <span v-if="pullRefreshing" class="ptr-spinner"></span>
            <span v-else class="ptr-text">{{ pullReadyNow ? '놓으면 새로고침' : '당겨서 새로고침' }}</span>
          </div>
          <div class="rooms-scroll ptr-scroll" @touchstart.passive="onPullStart" @touchmove="onPullMove" @touchend="onPullEnd">
            <div v-for="r in rooms" :key="r.id" class="room-swipe">
              <button class="room-swipe-del" @click.stop="emit('delete-room', r.id)">삭제</button>
              <div
                class="room-item"
                :class="{ active: r.id === currentRoomId, swiped: swipedRoomId === r.id }"
                @click="selectRoom(r.id)"
                @touchstart="onSwipeStart('r:' + r.id, $event)"
                @touchmove="onSwipeMove"
                @touchend="onSwipeEnd"
                @touchcancel="onSwipeCancel"
              >
                <span v-if="r.running" class="room-spinner" title="작업 중"></span>
                <span v-else-if="r.final_status" class="room-status" :class="statusClass(r.final_status)" :title="r.final_status"></span>
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
        </div>
      </template>

      <!-- 예약 탭 -->
      <template v-else-if="sidebarTab === 'jobs'">
        <div class="ptr-wrap" :style="{ transform: (pullY || pullRefreshing) ? `translateY(${pullRefreshing ? 40 : pullY}px)` : '', transition: (pullY && !pullRefreshing) ? 'none' : 'transform .22s' }">
          <div class="ptr-hint" :class="{ ready: pullReadyNow, spin: pullRefreshing }">
            <span v-if="pullRefreshing" class="ptr-spinner"></span>
            <span v-else class="ptr-text">{{ pullReadyNow ? '놓으면 새로고침' : '당겨서 새로고침' }}</span>
          </div>
          <div class="rooms-scroll ptr-scroll" @touchstart.passive="onPullStart" @touchmove="onPullMove" @touchend="onPullEnd">
            <div v-if="!jobs.length" class="admin-sub" style="padding:16px">예약된 작업이 없습니다. 우측 상단 +로 추가하세요.</div>
            <div v-for="j in jobs" :key="j.id" class="room-swipe">
              <button class="room-swipe-del" @click.stop="deleteJob(j.id)">삭제</button>
              <div
                class="job-item"
                :class="{ off: !j.enabled, swiped: swipedJobId === j.id }"
                @touchstart="onSwipeStart('j:' + j.id, $event)"
                @touchmove="onSwipeMove"
                @touchend="onSwipeEnd"
                @touchcancel="onSwipeCancel"
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
        </div>
      </template>

      <!-- 맥 탭 -->
      <template v-else>
        <div class="rooms-scroll">
          <div class="mac-launcher">
            <button class="mac-tile" @click="openMacScreen">
              <span class="mac-ico"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/></svg></span><span>화면 보기</span>
            </button>
            <button class="mac-tile" @click="openMacTerminal">
              <span class="mac-ico"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="18" rx="2"/><path d="M7 8l3 3-3 3M13 15h4"/></svg></span><span>터미널 연결</span>
            </button>
            <button class="mac-tile" @click="openMacCamera">
              <span class="mac-ico"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg></span><span>카메라 보기</span>
            </button>
            <div class="mac-tile mac-toggle" @click="toggleCaffeine">
              <span class="mac-ico"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8h1a4 4 0 0 1 0 8h-1"/><path d="M2 8h16v9a4 4 0 0 1-4 4H6a4 4 0 0 1-4-4V8z"/><path d="M6 1v3M10 1v3M14 1v3"/></svg></span>
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
      <div v-show="macControls" class="mac-remote-bar">
        <label class="mac-remote-toggle">
          <input type="checkbox" :checked="remoteCtrl" @change="toggleRemote" />
          <span>원격제어</span>
        </label>
        <span v-if="remoteCtrl" class="mac-remote-hint">클릭·이동·스크롤·키보드 입력 활성</span>
        <span v-if="remoteErr" class="mac-remote-err">{{ remoteErr }}</span>
      </div>
      <img
        v-show="!screenErr && screenSrc"
        :src="screenSrc"
        class="mac-screen-video"
        :class="{ 'remote-on': remoteCtrl }"
        alt="맥 화면"
        @load="onScreenImgLoad"
        @error="onScreenError"
        @pointerdown="onScreenPointerDown"
        @pointermove="onScreenMove"
        @wheel="onScreenWheel"
        @keydown="onScreenKey"
        tabindex="0"
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
      <div class="menu-item" @click="emit('rename-room', roomMenuId); roomMenuId = null">이름 변경</div>
      <div v-if="menuRoom() && menuRoom().count === 0" class="menu-item" @click="emit('open-workspace-picker', roomMenuId); roomMenuId = null">워크스페이스 변경</div>
      <div class="menu-item danger" @click="emit('delete-room', roomMenuId); roomMenuId = null">삭제</div>
    </div>
  </div>
</template>
