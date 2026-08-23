<script setup>
// 관리자 패널 — 잔액·모델 정책·토큰 통계·에러 로그를 표시한다.
// App.vue의 showAdmin 관련 상태·함수·마크업을 이 컴포넌트로 이관.
import { ref, onMounted } from 'vue'
import { balance as adminBalance, loadBalance } from '../store'

const props = defineProps({
  rooms: { type: Array, default: () => [] },
})
const emit = defineEmits(['close'])

const AVAILABLE_MODELS = ['deepseek-v4-pro', 'deepseek-v4-flash', 'deepseek-v4-flash-vision-exp']
const version = __APP_VERSION__

const adminStats = ref(null)
const adminErrors = ref([])
const adminPolicyOpen = ref(false)
const showAllRuns = ref(false)
const showErrorLog = ref(false)
const showModelPicker = ref(false)
const pickerRole = ref('')

async function loadAdmin() {
  try {
    const res = await fetch('/api/admin/stats')
    if (res.ok) adminStats.value = await res.json()
  } catch {}
}

async function loadErrors() {
  try {
    const res = await fetch('/api/admin/errors')
    if (res.ok) adminErrors.value = (await res.json()).errors || []
  } catch {}
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

function formatTokens(n) {
  if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M'
  if (n >= 1000) return (n / 1000).toFixed(1) + 'K'
  return String(n || 0)
}

function roomTitle(id) {
  return props.rooms.find((r) => r.id === id)?.title || id.slice(0, 8)
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

onMounted(() => {
  loadAdmin()
  loadBalance()
  loadErrors()
})
</script>

<template>
  <div class="kanban-overlay">
    <div class="kanban-head">
      <span class="kanban-title">관리자</span>
      <button @click="refreshAdmin">새로고침</button>
      <button @click="emit('close')">닫기</button>
    </div>
    <div class="admin-body">
      <div v-if="adminBalance && adminBalance.ok" class="admin-section">
        <div class="admin-stat-title">DeepSeek 잔액</div>
        <div class="admin-row">
          <span>USD 근사</span>
          <span class="admin-big">${{ adminBalance.usd }}</span>
        </div>
        <div class="admin-row">
          <span>{{ adminBalance.currency }}</span>
          <span class="mono">{{ adminBalance.total }}</span>
        </div>
        <a class="admin-charge" :href="adminBalance.top_up_url" target="_blank" rel="noopener">충전하러 가기</a>
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
          <div v-for="(p, role) in adminStats.policy?.roles" :key="role" class="policy-line">
            <span class="role-name">{{ role }}</span>
            <span class="policy-model">
              <span class="mono">{{ p.model }}</span>
              <span class="tag" :class="{ think: p.thinking }">{{ p.thinking ? 'think' : 'no-think' }}·{{ p.reasoning_effort }}</span>
            </span>
            <button class="admin-edit" @click="changeRoleModel(role)">변경</button>
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
        <div class="admin-stat-title">모델별 토큰 소비 ({{ adminStats.days }}일)</div>
        <div v-for="m in (adminStats.models || [])" :key="m.model" class="token-row">
          <div class="token-row-head">
            <span>{{ m.model }} <span class="run-count">×{{ m.count }}</span></span>
            <span class="mono">{{ formatTokens(m.tokens) }} · {{ m.percent }}%</span>
          </div>
          <div class="token-bar">
            <div class="token-bar-fill" :style="{ width: tokenBarPct(m.tokens) + '%' }"></div>
          </div>
        </div>
        <div v-if="!(adminStats.models || []).length" class="admin-sub">기록 없음</div>
      </div>
      <button v-if="adminStats" class="detail-link" @click="showAllRuns = true">
        세션별 실행 이력 {{ adminStats.rooms.length }}개 보기 →
      </button>

      <button class="detail-link" @click="showErrorLog = true">
        에러 로그 {{ adminErrors.length }}건 보기 →
      </button>

      <div class="admin-version">v{{ version }}</div>
    </div>
  </div>

  <div v-if="showAllRuns" class="kanban-overlay">
    <div class="kanban-head">
      <span class="kanban-title">세션별 실행 이력</span>
      <button @click="showAllRuns = false">닫기</button>
    </div>
    <div class="admin-body">
      <div v-if="!adminStats || !adminStats.rooms.length" class="admin-sub">기록 없음</div>
      <div v-for="room in (adminStats ? adminStats.rooms : [])" :key="room.session_id" class="admin-row">
        <span>{{ roomTitle(room.session_id) }}</span>
        <span class="mono">{{ room.count }}회</span>
      </div>
    </div>
  </div>

  <div v-if="showErrorLog" class="kanban-overlay">
    <div class="kanban-head">
      <span class="kanban-title">에러 로그</span>
      <button @click="showErrorLog = false">닫기</button>
    </div>
    <div class="admin-body">
      <div v-if="!adminErrors.length" class="admin-sub">기록된 에러가 없습니다.</div>
      <div v-for="(e, i) in adminErrors" :key="i" class="err-item">
        <div class="err-meta">{{ e.at }} · {{ e.source }}</div>
        <div class="err-msg">{{ e.message }}</div>
      </div>
    </div>
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
</template>
