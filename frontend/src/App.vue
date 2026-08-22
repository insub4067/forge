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
const showGit = ref(false)
const gitCurrent = ref('')
const gitBranches = ref([])
const gitStatus = ref('')
const gitDiff = ref('')
const showFiles = ref(false)
const filePath = ref('')
const fileParent = ref(null)
const fileEntries = ref([])
const fileContent = ref('')
const viewingFile = ref('')
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

async function loadGit() {
  const id = currentRoomId.value
  if (!id) return
  try {
    const [b, s, d] = await Promise.all([
      fetch(`/api/rooms/${id}/git/branches`).then((r) => r.json()),
      fetch(`/api/rooms/${id}/git/status`).then((r) => r.json()),
      fetch(`/api/rooms/${id}/git/diff`).then((r) => r.json()),
    ])
    gitCurrent.value = b.current
    gitBranches.value = b.branches || []
    gitStatus.value = s.output
    gitDiff.value = d.output
  } catch {}
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
    const res = await fetch(`/api/fs/list?path=${encodeURIComponent(path || '')}`)
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

async function send() {
  const text = input.value.trim()
  if (!text || busy.value) return
  busy.value = true
  input.value = ''
  debug.value = '전송 중…'
  console.log('[forge] send 시작:', text.slice(0, 60))

  newUser(text)
  const assistant = newAssistant()
  scrollBottom()

  try {
    const roomId = await ensureRoom(text)
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: roomId, message: text }),
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
      <button class="room-btn" @click="showRooms = !showRooms">
        <span class="room-title-main">{{ currentRoom()?.title || 'FORGE' }}</span>
        <span class="room-sub">{{ shortPath(currentRoom()?.workspace_path) }}</span>
      </button>
      <button v-if="busy" class="stop-btn" @click="cancelSession">중단</button>
      <button class="todo-btn" @click="openFiles" aria-label="파일">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>
      </button>
      <button class="todo-btn" @click="openGit" aria-label="Git">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><line x1="6" y1="9" x2="6" y2="15"/><path d="M18 6c0 4-6 3-6 9"/></svg>
      </button>
      <button class="todo-btn" @click="showKanban = true" aria-label="칸반">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M8 10l2 2 4-4"/><line x1="8" y1="16" x2="16" y2="16"/></svg>
      </button>
    </header>

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
              <div class="room-path" @click.stop="openWorkspacePicker(r.id)">
                {{ r.workspace_path || '워크스페이스 설정' }}
              </div>
            </div>
            <span class="room-pct">{{ ctxPct(r) }}%</span>
          </div>
        </div>
        <div class="rooms-add" @click="showCreateRoom = true; showRooms = false">+ 새 방 만들기</div>
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

    <footer>
      <textarea
        v-model="input"
        rows="1"
        placeholder="메시지를 입력하세요"
        @keydown="onKeydown"
        @input="onInput"
      ></textarea>
      <button id="send" :disabled="busy" @click="send" aria-label="전송">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg>
      </button>
    </footer>

    <div v-if="activeQuestion" class="modal-overlay">
      <div class="modal">
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

    <div v-if="showCreateRoom" class="modal-overlay">
      <div class="modal">
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

    <div v-if="showGit" class="kanban-overlay">
      <div class="kanban-head">
        <span class="kanban-title">Git — {{ gitCurrent || '브랜치 없음' }}</span>
        <button @click="showGit = false">닫기</button>
      </div>
      <div class="git-body">
        <div class="git-section">
          <div class="git-section-title">브랜치 (탭하여 전환)</div>
          <div
            v-for="b in gitBranches"
            :key="b"
            class="git-branch"
            :class="{ current: b === gitCurrent }"
            @click="checkoutBranch(b)"
          >{{ b }}</div>
        </div>
        <div class="git-section">
          <div class="git-section-title">변경 사항</div>
          <pre class="git-pre">{{ gitStatus || '(변경 없음)' }}</pre>
        </div>
        <div class="git-section">
          <div class="git-section-title">Diff (--stat)</div>
          <pre class="git-pre">{{ gitDiff || '(diff 없음)' }}</pre>
        </div>
      </div>
    </div>

    <div v-if="showFiles" class="fs-overlay">
      <div class="fs-head">
        <button @click="showFiles = false">닫기</button>
        <span class="fs-title">{{ viewingFile || filePath }}</span>
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
