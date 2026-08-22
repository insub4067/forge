<script setup>
import { ref, reactive, nextTick, onMounted } from 'vue'

const messages = ref([])
const input = ref('')
const busy = ref(false)
const activeQuestion = ref(null)
const questionAnswer = ref('')

const sessionId = localStorage.getItem('forge_session') || crypto.randomUUID()
localStorage.setItem('forge_session', sessionId)

const chatEl = ref(null)

function scrollBottom() {
  nextTick(() => {
    if (chatEl.value) chatEl.value.scrollTop = chatEl.value.scrollHeight
  })
}

function newUser(text) {
  messages.value.push({ role: 'user', content: text })
}

function newAssistant() {
  const m = reactive({ role: 'assistant', thinking: '', text: '', tools: [], approval: null })
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

let flushRaf = null
let thinkingBuf = ''
let textBuf = ''

function flush(assistant) {
  if (flushRaf) return
  flushRaf = requestAnimationFrame(() => {
    flushRaf = null
    if (thinkingBuf) {
      assistant.thinking += thinkingBuf
      thinkingBuf = ''
    }
    if (textBuf) {
      assistant.text += textBuf
      textBuf = ''
    }
    scrollBottom()
  })
}

function flushNow(assistant) {
  if (flushRaf) {
    cancelAnimationFrame(flushRaf)
    flushRaf = null
  }
  if (thinkingBuf) {
    assistant.thinking += thinkingBuf
    thinkingBuf = ''
  }
  if (textBuf) {
    assistant.text += textBuf
    textBuf = ''
  }
  scrollBottom()
}

function handleEvent(evt, assistant) {
  const d = evt.data || {}
  switch (evt.type) {
    case 'thinking_delta':
      thinkingBuf += d.content || ''
      flush(assistant)
      break
    case 'text_delta':
      textBuf += d.content || ''
      flush(assistant)
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
    case 'error':
      assistant.text += '\n\n오류: ' + (d.message || '')
      break
    case 'context_usage':
      assistant.context = d
      break
    case 'done':
      if (d.content) {
        thinkingBuf = ''
        textBuf = ''
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

  newUser(text)
  const assistant = newAssistant()
  scrollBottom()

  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId, message: text }),
    })
    if (!res.ok || !res.body) throw new Error('HTTP ' + res.status)

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let eventType = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let idx
      while ((idx = buffer.indexOf('\n\n')) !== -1) {
        const block = buffer.slice(0, idx)
        buffer = buffer.slice(idx + 2)
        const lines = block.split('\n')
        let data = ''
        for (const line of lines) {
          if (line.startsWith('event: ')) eventType = line.slice(7).trim()
          else if (line.startsWith('data: ')) data += line.slice(6)
        }
        if (data) {
          try {
            const evt = JSON.parse(data)
            handleEvent({ type: evt.type, data: evt.data }, assistant)
          } catch {}
        }
      }
    }
  } catch (err) {
    assistant.text += '\n\n오류: ' + (err.message || err)
  } finally {
    flushNow(assistant)
    busy.value = false
    scrollBottom()
  }
}

function onKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    send()
  }
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
    await fetch(`/api/sessions/${sessionId}/cancel`, { method: 'POST' })
  } catch {}
}

function resetSession() {
  const id = crypto.randomUUID()
  localStorage.setItem('forge_session', id)
  location.reload()
}

onMounted(async () => {
  try {
    const res = await fetch(`/api/sessions/${sessionId}/messages`)
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
})
</script>

<template>
  <div class="app">
    <header>
      <span class="dot"></span>
      <h1>FORGE</h1>
      <button v-if="busy" @click="cancelSession">중단</button>
      <button @click="resetSession">새로</button>
    </header>

    <main ref="chatEl">
      <div v-if="messages.length === 0" class="welcome">
        <p>무엇을 분석할까요?</p>
        <p class="sub">코드 탐색·분석을 자율로 수행합니다.</p>
      </div>

      <div v-for="(m, i) in messages" :key="i" class="msg" :class="m.role">
        <div class="bubble">
          <div v-if="m.role === 'user'" class="user-text">{{ m.content }}</div>

          <template v-if="m.role === 'assistant'">
            <details v-if="m.thinking" class="thinking">
              <summary>추론</summary>
              <div class="thinking-body">{{ m.thinking }}</div>
            </details>

            <div v-if="m.text" class="text">{{ m.text }}</div>

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
  </div>
</template>
