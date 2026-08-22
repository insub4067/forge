<script setup>
import { ref, reactive, nextTick, onMounted } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'

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
const activeQuestion = ref(null)
const questionAnswer = ref('')
const debug = ref('대기 중')

const rooms = ref([])
const currentRoomId = ref(localStorage.getItem('forge_room') || '')
const showRooms = ref(false)
const showCreateRoom = ref(false)
const newRoomName = ref('')
const newRoomPath = ref('')
const tasks = ref([])
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
const AVAILABLE_MODELS = ['deepseek-v4-pro', 'deepseek-v4-flash', 'deepseek-v4-flash-vision-exp']
const attachedImage = ref(null)
const fileInput = ref(null)
const kanbanOpen = ref({
  todo: true,
  planning: true,
  in_progress: true,
  review: true,
  debug: true,
  done: true,
})

let touchStartX = 0
let touchStartY = 0

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
    gitError.value = '방을 먼저 선택하세요.'
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
      `/api/fs/list?path=${encodeURIComponent(path || '')}&show_hidden=${showHidden.value}`
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

function toggleHidden() {
  showHidden.value = !showHidden.value
  navigateFiles(filePath.value)
}

async function openFile(path) {
  try {
    const res = await fetch(`/api/fs/read?path=${encodeURIComponent(path)}`)
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

async function loadMessages() {
  const id = currentRoomId.value
  if (!id) return
  messages.value = []
  try {
    const res = await fetch(`/api/sessions/${id}/messages`)
    if (!res.ok) return
    const data = await res.json()
    if (!Array.isArray(data)) return
    for (const m of data) {
      if (m.role === 'user') {
        messages.value.push({ role: 'user', content: m.content })
      } else if (m.role === 'assistant') {
        const am = reactive({
          role: 'assistant',
          thinking: m.reasoning_content || '',
          text: m.content || '',
          tools: [],
          approval: null,
        })
        for (const tc of m.tool_calls || []) {
          let args = {}
          try {
            args = JSON.parse(tc.function.arguments || '{}')
          } catch {}
          am.tools.push({ name: tc.function.name, args, status: 'done', result: '' })
        }
        messages.value.push(am)
      }
    }
    scrollBottom()
  } catch {}
}

async function selectRoom(id) {
  currentRoomId.value = id
  localStorage.setItem('forge_room', id)
  showRooms.value = false
  await loadMessages()
  await loadTasks()
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
      await selectRoom(room.id)
    }
  } catch {}
}

async function deleteRoom(id) {
  if (!confirm('이 채팅방을 삭제할까요?')) return
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
  const name = prompt('새 방 이름', room?.title || '')
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

function newUser(text) {
  messages.value.push({ role: 'user', content: text })
}

function newAssistant() {
  const m = reactive({ role: 'assistant', thinking: '', text: '', tools: [], approval: null, role_label: null })
  messages.value.push(m)
  return m
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
    case 'thinking_delta':
      assistant.thinking += d.content || ''
      break
    case 'text_delta':
      assistant.text += d.content || ''
      break
    case 'tool_call':
      assistant.tools.push({ name: d.name, args: d.args, status: 'running', result: '' })
      break
    case 'tool_result': {
      const t = assistant.tools.find((x) => x.status === 'running')
      if (t) {
        t.status = 'done'
        t.result = d.result || ''
        t.diff = d.diff || ''
      }
      break
    }
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
      tasks.value = d.tasks || []
      break
    case 'role_start':
      assistant.role_label = d.role
      break
    case 'error':
      assistant.text += '\n\n오류: ' + (d.message || '')
      break
    case 'context_usage':
      assistant.context = d
      break
    case 'done':
      if (d.content) {
        assistant.text = d.content
      }
      break
  }
  scrollBottom()
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

async function send() {
  const text = input.value.trim()
  const imageUrl = attachedImage.value?.url
  if (!text && !imageUrl) return
  if (busy.value) {
    if (text) await steerDuringRun(text)
    return
  }
  busy.value = true
  input.value = ''
  debug.value = '전송 중…'
  console.log('[forge] send 시작:', text.slice(0, 60))

  newUser(text || '[이미지]')
  const assistant = newAssistant()
  scrollBottom()
  attachedImage.value = null

  try {
    const roomId = await ensureRoom(text || '이미지 분석')
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: roomId, message: text, image_url: imageUrl }),
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
        console.log('[forge] 스트림 종료. chunk:', chunkCount, '이벤트:', eventCount, 'text길이:', assistant.text.length)
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
  const file = e.target.files[0]
  if (!file) return
  const formData = new FormData()
  formData.append('file', file)
  try {
    const res = await fetch('/api/upload', { method: 'POST', body: formData })
    if (res.ok) {
      attachedImage.value = await res.json()
    }
  } catch {}
  e.target.value = ''
}

function removeImage() {
  attachedImage.value = null
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

async function cancelSession() {
  try {
    await fetch(`/api/sessions/${currentRoomId.value}/cancel`, { method: 'POST' })
  } catch {}
}

function resetSession() {
  showCreateRoom.value = true
}

onMounted(async () => {
  await loadRooms()
  await loadMessages()
})
</script>

<template>
  <div class="app">
    <header>
      <button class="ctx-btn" @click="openAdmin" aria-label="관리자">
        <svg class="ctx" viewBox="0 0 36 36">
          <circle class="ctx-bg" cx="18" cy="18" r="15" pathLength="100" />
          <circle
            class="ctx-fg"
            cx="18"
            cy="18"
            r="15"
            pathLength="100"
            :stroke-dasharray="`${ctxPct(currentRoom())} 100`"
            :class="ctxClass(ctxPct(currentRoom()))"
          />
        </svg>
      </button>
      <button class="room-btn" @click="showRooms = !showRooms">
        <span class="room-title-main">{{ currentRoom()?.title || 'FORGE' }}</span>
        <span class="room-sub">{{ shortPath(currentRoom()?.workspace_path) }}</span>
      </button>
      <button v-if="busy" class="stop-btn" @click="cancelSession">중단</button>
      <button class="todo-btn" @click="showMenu = !showMenu" aria-label="메뉴">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="19" cy="12" r="1.6"/></svg>
      </button>
    </header>

    <div v-if="showMenu" class="menu-overlay" @click="showMenu = false">
      <div class="menu-panel" @click.stop>
        <div class="menu-item" @click="openFiles(); showMenu = false">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>
          <span>파일 브라우저</span>
        </div>
        <div class="menu-item" @click="openGit(); showMenu = false">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><line x1="6" y1="9" x2="6" y2="15"/><path d="M18 6c0 4-6 3-6 9"/></svg>
          <span>Git</span>
        </div>
        <div class="menu-item" @click="showKanban = true; showMenu = false">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M8 10l2 2 4-4"/><line x1="8" y1="16" x2="16" y2="16"/></svg>
          <span>칸반</span>
        </div>
        <div v-if="busy" class="menu-item danger" @click="cancelSession(); showMenu = false">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>
          <span>중단</span>
        </div>
      </div>
    </div>

    <div v-if="showRooms" class="rooms-overlay" @click="showRooms = false">
      <div class="rooms-panel" @click.stop>
        <div v-for="r in rooms" :key="r.id" class="room-swipe">
          <button class="room-swipe-del" @click.stop="deleteRoom(r.id)">삭제</button>
          <div
            class="room-item"
            :class="{ active: r.id === currentRoomId, swiped: swipedRoomId === r.id }"
            @click="selectRoom(r.id)"
            @touchstart="onRoomTouchStart"
            @touchend="onRoomTouchEnd(r, $event)"
          >
            <svg class="ctx" viewBox="0 0 36 36">
              <circle class="ctx-bg" cx="18" cy="18" r="15" pathLength="100" />
              <circle
                class="ctx-fg"
                cx="18"
                cy="18"
                r="15"
                pathLength="100"
                :stroke-dasharray="`${ctxPct(r)} 100`"
                :class="ctxClass(ctxPct(r))"
              />
            </svg>
            <div class="room-info">
              <div class="room-title">{{ r.title }}</div>
              <div class="room-path">{{ r.workspace_path || '워크스페이스 설정' }}</div>
            </div>
            <span class="room-pct">{{ ctxPct(r) }}%</span>
            <button class="room-more" @click.stop="roomMenuId = roomMenuId === r.id ? null : r.id" aria-label="메뉴">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="19" cy="12" r="1.6"/></svg>
            </button>
          </div>
        </div>
        <div class="rooms-add" @click="showCreateRoom = true; showRooms = false">+ 새 방 만들기</div>
      </div>
    </div>

    <div v-if="roomMenuId" class="menu-overlay" @click="roomMenuId = null">
      <div class="menu-panel" @click.stop>
        <div class="menu-item" @click="renameRoom(roomMenuId); roomMenuId = null">이름 변경</div>
        <div class="menu-item danger" @click="deleteRoom(roomMenuId); roomMenuId = null">삭제</div>
      </div>
    </div>

    <main ref="chatEl">
      <div v-if="messages.length === 0" class="welcome">
        <p>무엇을 분석할까요?</p>
        <p class="sub">코드 탐색·분석을 자율로 수행합니다.</p>
      </div>

      <div v-for="(m, i) in messages" :key="i" class="msg" :class="m.role">
        <div class="bubble">
          <div v-if="m.role === 'user'" class="user-text">{{ m.content }}</div>

          <template v-if="m.role === 'assistant'">
            <div v-if="m.role_label" class="role-badge">{{ m.role_label }}</div>

            <details v-if="m.thinking" class="thinking">
              <summary>추론</summary>
              <div class="thinking-body">{{ m.thinking }}</div>
            </details>

            <div v-if="m.text" class="text" v-html="renderMarkdown(m.text)"></div>

            <details v-for="(t, j) in m.tools" :key="j" class="tool" :class="{ running: t.status === 'running' }" open>
              <summary>
                <span class="tname">{{ t.name }}</span>
                <span class="targs">{{ summarizeArgs(t.args) }}</span>
              </summary>
              <div v-if="t.diff" class="diff">
                <div v-for="(line, li) in diffLines(t.diff)" :key="li" :class="diffClass(line)">{{ line || ' ' }}</div>
              </div>
              <pre v-else>{{ t.status === 'running' ? '실행 중…' : (t.result || '(출력 없음)') }}</pre>
            </details>

            <div v-if="m.approval" class="approval">
              <div class="approval-head">도구 실행 승인이 필요합니다</div>
              <div class="approval-tool">{{ m.approval.tool }} — {{ summarizeArgs(m.approval.args) }}</div>
              <div class="approval-btns">
                <button class="ok" @click="decide(m.approval, 'approve')">승인</button>
                <button class="no" @click="decide(m.approval, 'reject')">거부</button>
              </div>
            </div>

            <div v-if="m.context" class="context">
              context {{ m.context.prompt_tokens + m.context.completion_tokens }} tokens
            </div>
          </template>
        </div>
      </div>
    </main>

    <div v-if="attachedImage" class="image-preview">
      <img :src="attachedImage.url" alt="첨부 이미지" />
      <button class="image-remove" @click="removeImage" aria-label="제거">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>
      </button>
    </div>

    <div v-if="busy" class="steer-bar">
      <span class="steer-label">작업 중 · 보낼 메시지는</span>
      <button
        class="steer-chip"
        :class="{ active: steerMode === 'queue' }"
        @click="steerMode = 'queue'"
      >작업큐 대기</button>
      <button
        class="steer-chip"
        :class="{ active: steerMode === 'switch' }"
        @click="steerMode = 'switch'"
      >중단 후 새로</button>
    </div>

    <footer>
      <input ref="fileInput" type="file" accept="image/*" hidden @change="onFileChange" />
      <button class="attach-btn" @click="fileInput.click()" aria-label="이미지 첨부">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg>
      </button>
      <textarea
        v-model="input"
        rows="1"
        :placeholder="busy ? (steerMode === 'switch' ? '중단하고 새로 요청…' : '작업큐에 메시지 추가…') : '메시지를 입력하세요'"
        @keydown="onKeydown"
        @input="onInput"
      ></textarea>
      <button id="send" :disabled="!input.trim() && !attachedImage" @click="send" aria-label="전송">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg>
      </button>
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
        <div class="modal-head">새 채팅방</div>
        <input v-model="newRoomName" class="modal-field" placeholder="방 이름" />
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
          <div class="admin-stat-title">방별 실행 이력</div>
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

    <div v-if="showFiles" class="fs-overlay">
      <div class="fs-head">
        <button @click="showFiles = false">닫기</button>
        <span class="fs-title">{{ viewingFile || filePath }}</span>
        <button
          v-if="!viewingFile"
          class="fs-hidden-toggle"
          :class="{ active: showHidden }"
          @click="toggleHidden"
        >숨김 {{ showHidden ? 'ON' : 'OFF' }}</button>
        <button v-if="viewingFile" @click="viewingFile = ''; fileContent = ''">목록</button>
      </div>
      <div v-if="!viewingFile" class="fs-list">
        <button v-if="fileParent" class="fs-item parent" @click="navigateFiles(fileParent)">.. 상위 폴더</button>
        <button
          v-for="e in fileEntries"
          :key="e.path"
          class="fs-item"
          :class="{ dir: e.is_dir }"
          @click="e.is_dir ? navigateFiles(e.path) : openFile(e.path)"
        >
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
