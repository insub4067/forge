<script setup>
// 칸반 패널 — todo/working/testing/done 4단계 작업 보드.
// App.vue의 showKanban 관련 상태·함수·마크업을 이 컴포넌트로 이관.
import { ref } from 'vue'

const props = defineProps({
  tasks: { type: Array, default: () => [] },
  roomTitle: { type: String, default: 'FORGE' },
})
const emit = defineEmits(['close'])

const kanbanCols = [
  { key: 'todo', label: 'TODO' },
  { key: 'working', label: 'WORKING' },
  { key: 'testing', label: 'TESTING' },
  { key: 'done', label: 'DONE' },
]

const kanbanOpen = ref({ todo: false, working: false, testing: false, done: false })

// 레거시 status를 신뢰성 4단계로 정규화: todo → working → testing → done.
function normStatus(s) {
  if (s === 'planning') return 'todo'
  if (s === 'in_progress' || s === 'in-progress' || s === 'debug') return 'working'
  if (s === 'review' || s === 'verifying') return 'testing'
  return s // todo/working/testing/done는 그대로
}

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
      <div v-for="col in kanbanCols" :key="col.key" class="kanban-section">
        <div class="kanban-col-head" @click="toggleKanban(col.key)">
          <span>{{ col.label }}</span>
          <span class="kanban-count">{{ tasks.filter((x) => normStatus(x.status) === col.key).length }}</span>
        </div>
        <div v-show="kanbanOpen[col.key]" class="kanban-cards">
          <div
            v-for="t in tasks.filter((x) => normStatus(x.status) === col.key)"
            :key="t.id"
            class="kanban-card"
          >
            <div class="kanban-card-title">{{ t.title }}</div>
            <div class="kanban-bar">
              <div class="kanban-bar-fill" :style="{ width: (t.progress || 0) + '%' }"></div>
            </div>
          </div>
          <div v-if="tasks.filter((x) => normStatus(x.status) === col.key).length === 0" class="kanban-empty">없음</div>
        </div>
      </div>
    </div>
  </div>
</template>
