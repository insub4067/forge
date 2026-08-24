<script setup>
// 메뉴 패널 — 세션 사용량·파일·Git·칸반·Skills·알림·관리자·테마 진입점.
// App.vue의 showMenu 마크업을 이 컴포넌트로 이관. 액션은 emit으로 상위에 위임.
import { balance as adminBalance } from '../store'

const props = defineProps({
  ctxPct: { type: Number, default: 0 },
  ctxClass: { type: String, default: '' },
  theme: { type: String, default: 'dark' },
  themes: { type: Array, default: () => [] },
})
const emit = defineEmits([
  'close',
  'session-detail',
  'fork-session',
  'top-up',
  'files',
  'git',
  'kanban',
  'skills',
  'push',
  'agents',
  'admin',
  'set-theme',
])
</script>

<template>
  <div class="menu-overlay" @click="emit('close')">
    <div class="menu-panel" @click.stop>
      <div class="menu-item" @click="emit('session-detail')">
        <svg class="ctx menu-ctx-ring" viewBox="0 0 36 36">
          <circle class="ctx-bg" cx="18" cy="18" r="15" pathLength="100" />
          <circle class="ctx-fg" cx="18" cy="18" r="15" pathLength="100" :stroke-dasharray="`${ctxPct} 100`" :class="ctxClass" />
        </svg>
        <span>세션 사용량</span>
        <span class="menu-ctx">Context {{ ctxPct }}%</span>
      </div>
      <div v-if="adminBalance && adminBalance.ok" class="menu-item menu-balance" @click="emit('top-up')">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v10M9.5 9.5h5M9.5 14.5h5"/></svg>
        <span>충전 잔액</span>
        <span class="menu-ctx">${{ adminBalance.usd }}</span>
      </div>
      <div class="menu-item" @click="emit('fork-session')">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M5 12h14"/><circle cx="12" cy="12" r="9"/></svg>
        <span>새 세션 · 같은 워크스페이스</span>
        <span class="menu-ctx">컨텍스트 리셋</span>
      </div>
      <div class="menu-item" @click="emit('files')">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>
        <span>파일 브라우저</span>
      </div>
      <div class="menu-item" @click="emit('git')">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><line x1="6" y1="9" x2="6" y2="15"/><path d="M18 6c0 4-6 3-6 9"/></svg>
        <span>Git</span>
      </div>
      <div class="menu-item" @click="emit('kanban')">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M8 10l2 2 4-4"/><line x1="8" y1="16" x2="16" y2="16"/></svg>
        <span>칸반</span>
      </div>
      <div class="menu-item" @click="emit('skills')">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2L3 14h7l-1 8 10-12h-7z"/></svg>
        <span>Skills</span>
      </div>
      <div class="menu-item" @click="emit('push')">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>
        <span>알림 · 기기</span>
      </div>
      <div class="menu-item" @click="emit('agents')">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="7" width="16" height="12" rx="3"/><path d="M12 7V4M8 4h8"/><circle cx="9" cy="12" r="1"/><circle cx="15" cy="12" r="1"/></svg>
        <span>에이전트</span>
      </div>
      <div class="menu-item" @click="emit('admin')">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
        <span>관리자</span>
      </div>
      <div class="theme-row">
        <span class="theme-label">테마</span>
        <button
          v-for="t in themes"
          :key="t.id"
          class="theme-swatch"
          :class="{ active: theme === t.id }"
          :style="{ background: t.bg }"
          :title="t.label"
          @click.stop="emit('set-theme', t.id)"
        >
          <span class="theme-dot" :style="{ background: t.c }"></span>
        </button>
      </div>
    </div>
  </div>
</template>
