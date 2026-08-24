<script setup>
// Agent Crew / Roster — 실제 Runtime에서 파생한 Agent를 게임 캐릭터 선택 화면처럼 보여준다.
// 단, 표시되는 모든 정보(역할·모델·도구·fresh/read-only·상태·프롬프트)는 /api/agents에서
// 내려온 값을 그대로 쓴다. frontend에서 metadata를 하드코딩하거나 복제하지 않는다.
import { ref, computed, onMounted, onUnmounted } from 'vue'

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

const selected = computed(() => agents.value.find((a) => a.id === selectedId.value) || null)

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
          <p class="crew-lead">내 컴퓨터에서 함께 일하는 팀. 누구를 눌러도 실제 모델·도구·프롬프트가 보입니다.</p>
          <div class="crew-grid">
            <button
              v-for="a in agents"
              :key="a.id"
              class="agent-card"
              :class="[a.status, a.icon]"
              @click="openDetail(a)"
            >
              <div class="agent-avatar">
                <svg class="robot" viewBox="0 0 64 64" aria-hidden="true">
                  <line class="antenna" x1="32" y1="3" x2="32" y2="9" />
                  <circle class="antenna-dot" cx="32" cy="3" r="2.6" />
                  <rect class="head" x="13" y="9" width="38" height="27" rx="8" />
                  <circle class="eye" cx="24.5" cy="22" r="3.4" />
                  <circle class="eye" cx="39.5" cy="22" r="3.4" />
                  <path class="mouth" d="M25 29h14" />
                  <rect class="body" x="17" y="40" width="30" height="20" rx="6" />
                  <line class="arm" x1="10" y1="45" x2="17" y2="49" />
                  <line class="arm" x1="54" y1="45" x2="47" y2="49" />
                </svg>
                <span class="agent-accessory" :class="a.icon" aria-hidden="true">
                  <svg v-if="a.icon === 'hammer'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 4l5 5-4 4-5-5 4-4z"/><path d="M11 8L4 15v5h5l7-7"/></svg>
                  <svg v-else-if="a.icon === 'map'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 4L3 6v14l6-2 6 2 6-2V4l-6 2-6-2z"/><path d="M9 4v14M15 6v14"/></svg>
                  <svg v-else-if="a.icon === 'magnifier'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.65" y2="16.65"/><path d="M8 11h6M11 8v6"/></svg>
                  <svg v-else-if="a.icon === 'chat'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
                  <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M19.1 4.9L17 7M7 17l-2.1 2.1"/></svg>
                </span>
              </div>
              <div class="agent-card-name">{{ a.name }}</div>
              <div class="agent-card-nick">{{ a.display_name }}</div>
              <div class="agent-card-tier">{{ tierLabel(a) }}</div>
              <div class="agent-card-status" :class="statusOf(a).cls">
                <span class="agent-status-dot" :class="statusOf(a).dot"></span>{{ statusOf(a).label }}
              </div>
              <div class="agent-card-caps">
                <span v-for="c in a.capabilities.slice(0, 3)" :key="c" class="agent-cap">{{ c }}</span>
              </div>
            </button>
          </div>

          <div v-if="internal.length" class="crew-internal">
            <div class="crew-internal-title">내부 시스템 · 라우팅</div>
            <div v-for="i in internal" :key="i.id" class="crew-internal-row">
              <span class="crew-internal-name">{{ i.name }}</span>
              <span class="crew-internal-flavor">{{ i.flavor }}</span>
            </div>
          </div>
        </template>
      </template>

      <!-- ───────────── 상세 ───────────── -->
      <template v-else>
        <div class="agent-detail">
          <div class="detail-hero">
            <div class="agent-avatar detail-avatar" :class="selected.icon">
              <svg class="robot" viewBox="0 0 64 64" aria-hidden="true">
                <line class="antenna" x1="32" y1="3" x2="32" y2="9" />
                <circle class="antenna-dot" cx="32" cy="3" r="2.6" />
                <rect class="head" x="13" y="9" width="38" height="27" rx="8" />
                <circle class="eye" cx="24.5" cy="22" r="3.4" />
                <circle class="eye" cx="39.5" cy="22" r="3.4" />
                <path class="mouth" d="M25 29h14" />
                <rect class="body" x="17" y="40" width="30" height="20" rx="6" />
              </svg>
            </div>
            <div class="detail-hero-text">
              <div class="detail-name">{{ selected.name }}</div>
              <div class="detail-nick">{{ selected.display_name }}</div>
              <div class="detail-flavor">“{{ selected.flavor }}”</div>
              <div class="agent-card-status" :class="statusOf(selected).cls">
                <span class="agent-status-dot" :class="statusOf(selected).dot"></span>{{ statusOf(selected).label }}
                <span v-if="selected.activity" class="detail-activity">· {{ selected.activity }}</span>
              </div>
            </div>
          </div>

          <div class="detail-block">
            <div class="detail-label">설명</div>
            <p class="detail-desc">{{ selected.description }}</p>
          </div>

          <div class="detail-block">
            <div class="detail-label">모델</div>
            <div class="detail-kv">
              <div class="detail-row"><span class="detail-key">Current</span><span class="detail-val mono">{{ selected.model || '—' }}</span></div>
              <div class="detail-row"><span class="detail-key">Thinking</span><span class="detail-val">{{ selected.thinking ? '켜짐 · ' + (selected.reasoning_effort || '') : '꺼짐' }}</span></div>
              <div v-if="selected.escalation_model" class="detail-row"><span class="detail-key">Escalation</span><span class="detail-val mono">{{ selected.escalation_model }}</span></div>
            </div>
          </div>

          <div class="detail-block">
            <div class="detail-label">컨텍스트</div>
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
            <div class="prompt-source mono">{{ selected.prompt_source }} · {{ selected.prompt_hash }}</div>
          </div>
        </div>
      </template>
    </div>

    <!-- ───────────── Prompt Viewer (read-only) ───────────── -->
    <div v-if="showPrompt && promptData" class="prompt-overlay">
      <div class="prompt-head">
        <div class="prompt-head-text">
          <div class="prompt-title">{{ promptData.id }} · System Prompt</div>
          <div class="prompt-source mono">{{ promptData.source }} · {{ promptData.hash }}</div>
        </div>
        <div class="prompt-head-actions">
          <button class="prompt-btn" @click="copyPrompt()">{{ copied ? '복사됨' : '복사' }}</button>
          <button class="prompt-btn" @click="closePrompt()">닫기</button>
        </div>
      </div>
      <div class="prompt-note">읽기 전용 — 런타임이 사용하는 Base Role Prompt입니다. 동적 메모리·스킬·대화·비밀값은 포함하지 않습니다.</div>
      <pre class="prompt-body mono">{{ promptData.prompt }}</pre>
    </div>
  </div>
</template>
