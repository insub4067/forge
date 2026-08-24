<script setup>
// 칸반 패널 — todo/working/testing/done 4단계 작업 보드.
// App.vue의 showKanban 관련 상태·함수·마크업을 이 컴포넌트로 이관.
import { ref, watch } from 'vue'

const props = defineProps({
  tasks: { type: Array, default: () => [] },
  gates: { type: Array, default: () => [] },
  roomTitle: { type: String, default: 'FORGE' },
})
const emit = defineEmits(['close'])

const kanbanCols = [
  { key: 'todo', label: 'TODO' },
  { key: 'working', label: 'IN PROCESS' },
  { key: 'testing', label: 'QA' },
  { key: 'done', label: 'DONE' },
]

// 멈춘(실패/차단) task의 카드 뱃지. status 값 자체는 백엔드 계약(blocked 등)을 그대로 쓴다.
const failMarks = {
  blocked: '막힘',
  failed: '실패',
  abandoned: '포기',
  unavailable: '미검증',
}
function failBadge(s) {
  return failMarks[s] || ''
}

function laneCount(key) {
  return props.tasks.filter((x) => normStatus(x.status) === key).length
}

// gate 상태 → 표시 기호·레이블. passed/failed는 프로세스가 실제 검증 후 부여한다.
const gateMarks = {
  passed: { mark: '✓', label: '통과' },
  failed: { mark: '✗', label: '실패' },
  working: { mark: '○', label: '진행' },
  pending: { mark: '○', label: '대기' },
  unavailable: { mark: '!', label: '미검증' },
  blocked: { mark: '!', label: '차단' },
  abandoned: { mark: '–', label: '포기' },
}

function gateMark(s) {
  return gateMarks[s] || { mark: '?', label: s || '?' }
}

function gateNote(g) {
  if (g.status === 'failed') return '실패: ' + (g.failure_reason || '')
  if (g.status === 'blocked') return '차단: ' + (g.failure_reason || '')
  if (g.status === 'unavailable') return (g.failure_reason || '검증 방법 없음')
  return ''
}

const kanbanOpen = ref({ todo: false, working: false, testing: false, done: false })

// 레거시 status를 신뢰성 4단계로 정규화: todo → working → testing → done.
function normStatus(s) {
  if (s === 'planning') return 'todo'
  if (s === 'in_progress' || s === 'in-progress' || s === 'debug') return 'working'
  if (s === 'review' || s === 'verifying') return 'testing'
  // 실패/차단은 QA에서 멈춘 것 — 사라지지 않게 QA(testing) 레인에 유지하고 카드에 뱃지로 표시.
  if (s === 'blocked' || s === 'failed' || s === 'abandoned' || s === 'unavailable') return 'testing'
  return s // todo/working/testing/done는 그대로
}

// 진입하자마자 아이템이 있는 섹션은 기본 펼침(빈 섹션만 접힘). tasks가 채워질 때 반영.
watch(() => props.tasks, (list) => {
  for (const col of kanbanCols) {
    kanbanOpen.value[col.key] = (list || []).some((x) => normStatus(x.status) === col.key)
  }
}, { immediate: true })

function toggleKanban(key) {
  kanbanOpen.value[key] = !kanbanOpen.value[key]
}
</script>

<template>
  <div class="kanban-overlay">
    <div class="kanban-head">
      <span class="kanban-title">{{ roomTitle }}</span>
      <button @click="emit('close')">닫기</button>
    </div>
    <div class="kanban-board">
      <div v-for="col in kanbanCols" :key="col.key" class="kanban-section" :class="{ empty: laneCount(col.key) === 0 }">
        <div class="kanban-col-head" @click="toggleKanban(col.key)">
          <span>{{ col.label }}</span>
          <span class="kanban-count" :class="{ zero: laneCount(col.key) === 0 }">{{ laneCount(col.key) }}</span>
        </div>
        <div v-show="kanbanOpen[col.key]" class="kanban-cards">
          <div
            v-for="t in tasks.filter((x) => normStatus(x.status) === col.key)"
            :key="t.id"
            class="kanban-card"
            :class="{ failed: failBadge(t.status) }"
          >
            <div class="kanban-card-title">{{ t.title }}</div>
            <div v-if="failBadge(t.status)" class="kanban-card-badge">{{ failBadge(t.status) }}</div>
            <div v-else class="kanban-bar">
              <div class="kanban-bar-fill" :style="{ width: (t.progress || 0) + '%' }"></div>
            </div>
          </div>
          <div v-if="tasks.filter((x) => normStatus(x.status) === col.key).length === 0" class="kanban-empty">없음</div>
        </div>
      </div>

      <div v-if="gates.length" class="gate-section">
        <div class="gate-head">요구사항 게이트 · {{ gates.length }}</div>
        <div v-for="g in gates" :key="g.id" class="gate-row" :class="g.status">
          <span class="gate-mark">{{ gateMark(g.status).mark }}</span>
          <div class="gate-body">
            <div class="gate-title">{{ g.title }}</div>
            <div v-if="gateNote(g)" class="gate-note">{{ gateNote(g) }}</div>
          </div>
          <span class="gate-label">{{ gateMark(g.status).label }}</span>
        </div>
      </div>
    </div>
  </div>
</template>
