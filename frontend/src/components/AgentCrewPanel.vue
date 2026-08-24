<script setup>
// Agent Crew / Roster — 실제 Runtime에서 파생한 Agent를 게임 캐릭터 선택 화면처럼 보여준다.
// 단, 표시되는 모든 정보(역할·모델·도구·fresh/read-only·상태·프롬프트)는 /api/agents에서
// 내려온 값을 그대로 쓴다. frontend에서 metadata를 하드코딩하거나 복제하지 않는다.
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import AgentAvatar from './AgentAvatar.vue'

const props = defineProps({
  sessionId: { type: String, default: '' },
})
const emit = defineEmits(['close'])

const agents = ref([])
const internal = ref([])
const activeRole = ref('')
const loading = ref(true)
const error = ref('')

const selectedId = ref('')
const showPrompt = ref(false)
const promptData = ref(null)
const promptLoading = ref(false)
const promptError = ref('')
const copied = ref(false)
const promptMode = ref('read') // 'read' | 'raw'

const selected = computed(() => agents.value.find((a) => a.id === selectedId.value) || null)

// 긴 hash가 title 영역을 깨지 않게 모바일에선 짧게. 전체는 복사/detail에서 확인 가능.
function shortHash(h) {
  return h ? String(h).slice(0, 7) : ''
}

const promptHtml = computed(() => {
  if (!promptData.value) return ''
  return DOMPurify.sanitize(marked.parse(promptData.value.prompt || ''))
})

const STATUS = {
  working: { label: '작업 중', dot: 'working', cls: 'working' },
  recent: { label: '최근 실행', dot: 'recent', cls: 'recent' },
  idle: { label: '대기', dot: 'idle', cls: 'idle' },
}

function shortModel(m) {
  if (!m) return ''
  if (m.includes('pro')) return 'Pro'
  if (m.includes('vision')) return 'Vision'
  if (m.includes('flash')) return 'Flash'
  return m.split('/').pop()
}

function tierLabel(a) {
  if (!a.model) return ''
  const base = shortModel(a.model)
  if (a.escalation_model && shortModel(a.escalation_model) !== base) {
    return `${base} → ${shortModel(a.escalation_model)}`
  }
  return base
}

function statusOf(a) {
  return STATUS[a.status] || STATUS.idle
}

let pollTimer = null

async function load() {
  try {
    const q = props.sessionId ? '?session_id=' + encodeURIComponent(props.sessionId) : ''
    const res = await fetch('/api/agents' + q)
    if (!res.ok) throw new Error('HTTP ' + res.status)
    const data = await res.json()
    agents.value = data.agents || []
    internal.value = data.internal || []
    activeRole.value = data.active_role || ''
    error.value = ''
  } catch (e) {
    error.value = '에이전트 목록을 불러오지 못했습니다: ' + (e.message || e)
  } finally {
    loading.value = false
  }
}

function openDetail(a) {
  selectedId.value = a.id
  showPrompt.value = false
}

function back() {
  selectedId.value = ''
  showPrompt.value = false
}

async function openPrompt() {
  if (!selected.value) return
  promptLoading.value = true
  promptError.value = ''
  copied.value = false
  try {
    const res = await fetch('/api/agents/' + encodeURIComponent(selected.value.id) + '/prompt')
    if (!res.ok) throw new Error('HTTP ' + res.status)
    promptData.value = await res.json()
    showPrompt.value = true
  } catch (e) {
    promptError.value = '프롬프트를 불러오지 못했습니다: ' + (e.message || e)
  } finally {
    promptLoading.value = false
  }
}

function closePrompt() {
  showPrompt.value = false
}

async function copyPrompt() {
  if (!promptData.value) return
  try {
    await navigator.clipboard.writeText(promptData.value.prompt)
    copied.value = true
    setTimeout(() => { copied.value = false }, 1600)
  } catch (e) {
    // 클립보드 권한이 없으면 fallback: textarea 선택 복사.
    const ta = document.createElement('textarea')
    ta.value = promptData.value.prompt
    document.body.appendChild(ta)
    ta.select()
    try { document.execCommand('copy') } catch (_) {}
    document.body.removeChild(ta)
    copied.value = true
    setTimeout(() => { copied.value = false }, 1600)
  }
}

onMounted(() => {
  load()
  // 라이브 상태 갱신 — 실제 runtime.get_status() 기반. 별도 상태 시스템을 만들지 않는다.
  pollTimer = setInterval(load, 4000)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<template>
  <div class="crew-overlay">
    <div class="crew-head">
      <button v-if="selected || showPrompt" class="crew-back" @click="showPrompt ? closePrompt() : back()" aria-label="뒤로">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 18l-6-6 6-6"/></svg>
      </button>
      <div class="crew-head-text">
        <div class="crew-title">{{ selected ? selected.name : '에이전트' }}</div>
        <div class="crew-sub">{{ selected ? selected.display_name : 'FORGE와 함께 일하는 AI 팀' }}</div>
      </div>
      <button class="crew-close" @click="emit('close')" aria-label="닫기">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M18 6L6 18M6 6l12 12"/></svg>
      </button>
    </div>

    <div class="crew-body">
      <!-- ───────────── 메인 roster ───────────── -->
      <template v-if="!selected">
        <div v-if="loading" class="crew-skeleton">
          <div class="skel-card" v-for="i in 4" :key="i"></div>
        </div>
        <div v-else-if="error" class="crew-error">{{ error }}</div>
        <template v-else>
          <p class="crew-lead">각 Agent의 실제 모델·도구·Prompt를 확인할 수 있습니다.</p>
          <div class="crew-grid">
            <button
              v-for="a in agents"
              :key="a.id"
              class="agent-card"
              :class="[a.status, a.icon]"
              @click="openDetail(a)"
            >
              <AgentAvatar :role="a.icon" :status="a.status" size="md" />
              <div class="agent-card-name">{{ a.name }}</div>
              <div class="agent-card-nick">{{ a.display_name }}</div>
              <div class="agent-card-status" :class="statusOf(a).cls">
                <span class="agent-status-dot" :class="statusOf(a).dot"></span>{{ statusOf(a).label }}
              </div>
              <div class="agent-card-caps">
                <span v-for="c in a.capabilities.slice(0, 3)" :key="c" class="agent-cap">{{ c }}</span>
              </div>
              <div class="agent-card-tier">{{ tierLabel(a) }}</div>
            </button>
          </div>

          <div v-if="internal.length" class="crew-internal">
            <div class="crew-internal-title">내부 시스템</div>
            <div v-for="i in internal" :key="i.id" class="crew-internal-row">
              <span class="crew-internal-mark" aria-hidden="true">◇</span>
              <div class="crew-internal-text">
                <span class="crew-internal-name">{{ i.name }}</span>
                <span class="crew-internal-flavor">{{ i.flavor }}</span>
              </div>
            </div>
          </div>
        </template>
      </template>

      <!-- ───────────── 상세 ───────────── -->
      <template v-else>
        <div class="agent-detail">
          <div class="detail-hero">
            <AgentAvatar :role="selected.icon" :status="selected.status" size="lg" />
            <div class="detail-hero-text">
              <div class="detail-name">{{ selected.name }}</div>
              <div class="detail-nick">{{ selected.display_name }}</div>
              <div class="agent-card-status" :class="statusOf(selected).cls">
                <span class="agent-status-dot" :class="statusOf(selected).dot"></span>{{ statusOf(selected).label }}
                <span v-if="selected.activity" class="detail-activity">· {{ selected.activity }}</span>
              </div>
            </div>
          </div>
          <div class="detail-flavor">“{{ selected.flavor }}”</div>
          <p class="detail-desc lead">{{ selected.description }}</p>

          <div class="detail-block">
            <div class="detail-label">MODEL</div>
            <div class="detail-kv">
              <div class="detail-row"><span class="detail-key">Current</span><span class="detail-val mono">{{ selected.model || '—' }}</span></div>
              <div class="detail-row"><span class="detail-key">Thinking</span><span class="detail-val">{{ selected.thinking ? '켜짐 · ' + (selected.reasoning_effort || '') : '꺼짐' }}</span></div>
              <div v-if="selected.escalation_model" class="detail-row"><span class="detail-key">Escalation</span><span class="detail-val mono">{{ selected.escalation_model }}</span></div>
            </div>
          </div>

          <div class="detail-block">
            <div class="detail-label">CONTEXT</div>
            <div class="detail-kv">
              <div class="detail-row">
                <span class="detail-key">Context</span>
                <span class="detail-val">{{ selected.fresh_context ? 'Fresh Context' : 'Persistent Developer Context' }}</span>
              </div>
              <div class="detail-row">
                <span class="detail-key">Mutation</span>
                <span class="detail-val">{{ selected.read_only ? '읽기 전용' : '전체' }}</span>
              </div>
            </div>
            <p class="detail-hint">{{ selected.fresh_context
              ? 'Fresh — 긴 Developer 대화를 그대로 상속하지 않고 독립된 새 컨텍스트에서 판단합니다.'
              : 'Persistent — 현재 작업의 실행 맥락을 이어받아 구현을 계속합니다.' }}</p>
          </div>

          <div class="detail-block">
            <div class="detail-label">Capabilities · 도구 {{ selected.tool_count }}</div>
            <div class="detail-caps">
              <span v-for="c in selected.capabilities" :key="c" class="agent-cap big">{{ c }}</span>
            </div>
            <div v-if="selected.policy_note" class="detail-policy">⚠ {{ selected.policy_note }}</div>
            <div class="detail-tools">
              <div v-for="t in selected.tool_details || []" :key="t.name" class="detail-tool-row">
                <span class="tool-mark">{{ t.approval_required ? '✎' : '✓' }}</span>
                <span class="tool-name mono">{{ t.name }}</span>
                <span class="tool-desc">{{ t.description }}</span>
              </div>
            </div>
          </div>

          <div class="detail-block">
            <div class="detail-label">System Prompt</div>
            <button class="prompt-open-btn" @click="openPrompt()" :disabled="promptLoading">
              {{ promptLoading ? '불러오는 중…' : '실제 Base Role Prompt 보기' }}
            </button>
            <div v-if="promptError" class="detail-policy">{{ promptError }}</div>
            <div class="prompt-source">
              <span class="mono">{{ selected.prompt_source }}</span>
              <span class="prompt-rev mono">revision {{ shortHash(selected.prompt_hash) }}</span>
            </div>
          </div>
        </div>
      </template>
    </div>

    <!-- ───────────── Prompt Viewer (read-only) ───────────── -->
    <div v-if="showPrompt && promptData" class="prompt-overlay">
      <div class="prompt-head">
        <div class="prompt-head-text">
          <div class="prompt-title">{{ promptData.id }} · System Prompt</div>
          <div class="prompt-source">
            <span class="mono">{{ promptData.source }}</span>
            <span class="prompt-rev mono">revision {{ shortHash(promptData.hash) }}</span>
          </div>
        </div>
        <div class="prompt-head-actions">
          <div class="prompt-mode" role="group" aria-label="보기 모드">
            <button class="prompt-mode-btn" :class="{ on: promptMode === 'read' }" @click="promptMode = 'read'">읽기</button>
            <button class="prompt-mode-btn" :class="{ on: promptMode === 'raw' }" @click="promptMode = 'raw'">Raw</button>
          </div>
          <button class="prompt-btn" @click="copyPrompt()">{{ copied ? '복사됨' : '복사' }}</button>
          <button class="prompt-btn" @click="closePrompt()">닫기</button>
        </div>
      </div>
      <div class="prompt-note">읽기 전용 — 런타임이 사용하는 Base Role Prompt입니다. 동적 메모리·스킬·대화·비밀값은 포함하지 않습니다.</div>
      <div v-if="promptMode === 'read'" class="prompt-body prompt-read" v-html="promptHtml"></div>
      <pre v-else class="prompt-body mono">{{ promptData.prompt }}</pre>
    </div>
  </div>
</template>
