<script setup>
// Agent 활동 상세 — Timeline 항목을 탭했을 때 여는 Detail Surface의 '내용' 컴포넌트.
// 모바일(bottom sheet)·데스크톱(우측 패널)이 이 하나를 공유한다. 내용을 두 번 구현하지 않는다.
// 원칙: Reasoning·Tool Result·Verification 같은 상세만 여기서 보여준다(Timeline은 흐름·요약만).
import { computed } from 'vue'

const props = defineProps({
  phase: { type: Object, required: true },
  message: { type: Object, default: null },
  gates: { type: Array, default: () => [] },
  renderMarkdown: { type: Function, required: true },
})
defineEmits(['close'])

const ROLE_LABELS = { triage: '분류', developer: '개발', chat: '응답', vision: '이미지 분석' }

function phaseLabel(p) {
  if (p.role && ROLE_LABELS[p.role]) return ROLE_LABELS[p.role]
  const names = (p.tools || []).map((t) => t.name)
  if (names.some((n) => n === 'write_file' || n === 'edit_file')) return '편집'
  if (names.includes('bash')) return '실행'
  if (names.some((n) => ['read_file', 'list_dir', 'grep'].includes(n))) return '탐색'
  return '응답'
}
function phaseStatus(p) {
  // Tool Failure ≠ Activity Failure — 도구 실패는 탐색 과정. Activity 실패(!)로 만들지 않는다.
  if (p.running) return 'running'
  return 'done'
}
// 상태를 색이 아니라 형태로 — ● 진행 / ✓ 성공 / ! 실패.
function phaseGlyph(p) {
  const s = phaseStatus(p)
  return s === 'running' ? '●' : s === 'error' ? '!' : '✓'
}
function shortModel(m) {
  if (!m) return ''
  if (m.includes('pro')) return 'Pro'
  if (m.includes('vision')) return 'Vision'
  if (m.includes('flash')) return 'Flash'
  return m.split('/').pop()
}
// 한 줄 요약 — 도구별로 의미 있는 필드만(경로·명령·패턴).
function summarizeArgs(args) {
  if (!args || typeof args !== 'object') return ''
  if (typeof args.command === 'string') return args.command.split('\n')[0].slice(0, 120)
  if (args.path) return String(args.path)
  if (args.pattern) return String(args.pattern)
  try {
    const s = JSON.stringify(args)
    return s.length > 120 ? s.slice(0, 120) + '…' : s
  } catch {
    return ''
  }
}
function diffLines(diff) {
  return String(diff || '').split('\n')
}
function diffClass(line) {
  if (line.startsWith('+') && !line.startsWith('+++')) return 'add'
  if (line.startsWith('-') && !line.startsWith('---')) return 'del'
  if (line.startsWith('@@')) return 'hunk'
  return ''
}
function gateGlyph(s) {
  return s === 'passed' ? '✓' : s === 'failed' ? '!' : '○'
}
// 결과가 길면(diff·멀티라인·장문) 기본 접힘 — list_dir·bash·pytest 출력이 상세를 잠식하지 않게.
// 실패한 도구는 길이와 무관하게 펼쳐 둔다(실패를 숨기지 않는다).
function toolOpen(t) {
  if (t.status === 'error') return true
  const r = t.result || ''
  return !t.diff && r.length <= 200 && r.split('\n').length <= 4
}

// 추론이 열린 상태에서 시트 본문(추론 텍스트 영역 포함)을 탭하면 접는다. 펼치면 reasoning-body가
// 영역을 채워 '빈 배경'이 없으므로, 추론 영역 탭도 닫기로 친다. 버튼·도구·링크만 제외(오작동 방지).
// 텍스트 드래그 선택은 click을 안 내므로 선택은 그대로 가능.
function onBodyTap(e) {
  if (!props.phase.thinkOpen) return
  if (e.target.closest('button, summary, details, a')) return
  props.phase.thinkOpen = false
}
// 펼친 도구 결과(<details>) 본문 탭 → 닫기. 링크·버튼 제외.
function closeParentDetails(e) {
  if (e.target.closest('a, button')) return
  const d = e.target.closest('details')
  if (d) d.open = false
}
function toggleThink() {
  props.phase.thinkOpen = !props.phase.thinkOpen
}

const errorCount = computed(() => (props.phase.tools || []).filter((t) => t.status === 'error').length)
</script>

<template>
  <div class="adp">
    <header class="adp-head">
      <span class="adp-glyph" :class="phaseStatus(phase)" aria-hidden="true">{{ phaseGlyph(phase) }}</span>
      <span class="adp-title">{{ phaseLabel(phase) }}</span>
      <span v-if="phase.model" class="adp-model">{{ shortModel(phase.model) }}</span>
      <span v-if="errorCount" class="adp-problem">실패 {{ errorCount }}</span>
      <button class="adp-x" @click="$emit('close')" aria-label="닫기">✕</button>
    </header>

    <div class="adp-body" @click="onBodyTap">
      <!-- 요약(핵심 결과) — phase의 응답 본문 원문 markdown. -->
      <section v-if="phase.text" class="detail-block">
        <div class="detail-label">요약</div>
        <div class="text adp-summary" v-html="renderMarkdown(phase.text)"></div>
      </section>

      <!-- 추론 — 기본 접힘, 열면 유지(phase.thinkOpen). 자동 요약 없이 원문 그대로. -->
      <section v-if="phase.thinking" class="detail-block">
        <div class="detail-label">추론</div>
        <button
          class="adp-reason-toggle"
          :aria-expanded="phase.thinkOpen ? 'true' : 'false'"
          @click="toggleThink"
        >
          <span>{{ phase.thinkOpen ? '추론 접기' : '추론 보기' }}</span>
          <svg class="adp-reason-chevron" :class="{ open: phase.thinkOpen }" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18l6-6-6-6"/></svg>
        </button>
        <div v-if="phase.thinkOpen" class="reasoning-body text" v-html="renderMarkdown(phase.thinking)"></div>
      </section>

      <!-- 도구 호출 + 결과 — 각 도구는 호출 정보(이름·인자)는 항상, 결과는 길면 접어 둔다. -->
      <section v-if="phase.tools && phase.tools.length" class="detail-block">
        <div class="detail-label">도구 {{ phase.tools.length }}</div>
        <details
          v-for="(t, ti) in phase.tools"
          :key="t.id != null ? t.id : ti"
          class="adp-tool"
          :class="t.status"
          :open="toolOpen(t)"
        >
          <summary>
            <span class="adp-tool-mark" :class="t.status" aria-hidden="true">{{ t.status === 'error' ? '!' : t.status === 'running' ? '●' : '✓' }}</span>
            <span class="adp-tool-name">{{ t.name }}</span>
            <span class="adp-tool-args">{{ summarizeArgs(t.args) }}</span>
            <svg class="adp-tool-chevron" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 18l6-6-6-6"/></svg>
          </summary>
          <div v-if="t.diff" class="diff adp-diff" @click="closeParentDetails">
            <div v-for="(line, li) in diffLines(t.diff)" :key="li" :class="diffClass(line)">{{ line || ' ' }}</div>
          </div>
          <pre v-else class="adp-result" @click="closeParentDetails">{{ t.status === 'running' ? '실행 중…' : (t.result || '(출력 없음)') }}</pre>
        </details>
      </section>

      <!-- 검증 — backend가 보낸 gate·verifyPhase만(없는 데이터 추측 금지). -->
      <section v-if="gates.length || message?.verifyPhase" class="detail-block">
        <div class="detail-label">검증</div>
        <div v-if="message?.verifyPhase" class="adp-verify-phase">{{ message.verifyPhase }}</div>
        <ul v-if="gates.length" class="adp-gates">
          <li v-for="g in gates" :key="g.id" :class="g.status">
            <span class="adp-gate-glyph" :class="g.status" aria-hidden="true">{{ gateGlyph(g.status) }}</span>
            <span class="adp-gate-title">{{ g.title }}</span>
            <span v-if="g.failure_reason" class="adp-gate-reason">{{ g.failure_reason }}</span>
          </li>
        </ul>
      </section>
    </div>
  </div>
</template>
