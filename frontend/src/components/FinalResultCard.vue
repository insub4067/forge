<script setup>
// 작업 종료 요약 카드 — 긴 응답보다 먼저 '상태·진행률·검증'을 빠르게 보여준다.
// 상태는 색만이 아니라 텍스트(완료/부분 완료/실패/중단됨)로도 표시(색맹·명암 고려).
// 실패·미검증은 '별도 경고 카드'로 분리하고 사유와 다음 행동을 함께 준다.
defineProps({
  status: { type: Object, required: true },   // {label, cls, glyph}
  summary: { type: String, default: '' },
  filesCount: { type: Number, default: 0 },
  verify: { type: Object, default: () => ({ passed: 0, failed: 0, unverified: 0 }) },
  progress: { type: Object, default: null },  // {done, total} | null
  warnings: { type: Array, default: () => [] }, // [{kind, title, reason}]
})
defineEmits(['action'])
</script>

<template>
  <div class="result-card" :class="status.cls">
    <div class="rc-head">
      <span class="rc-glyph" :class="status.cls" aria-hidden="true">{{ status.glyph }}</span>
      <span class="rc-label">{{ status.label }}</span>
      <span v-if="progress" class="rc-progress">{{ progress.done }}/{{ progress.total }}</span>
    </div>
    <p v-if="summary" class="rc-summary">{{ summary }}</p>
    <div class="rc-metrics">
      <span class="rc-metric">검증
        <b class="ok">{{ verify.passed }}</b> 통과 ·
        <b :class="{ bad: verify.failed }">{{ verify.failed }}</b> 실패 ·
        <b :class="{ warn: verify.unverified }">{{ verify.unverified }}</b> 미검증
      </span>
      <span v-if="filesCount" class="rc-metric">변경 파일 {{ filesCount }}</span>
    </div>
  </div>

  <!-- 실패·미검증은 별도 경고 카드 — ! 문자만이 아니라 종류·사유·다음 행동을 함께. -->
  <div v-for="(w, i) in warnings" :key="i" class="result-warn" :class="w.kind === '실패' ? 'error' : 'warn'">
    <div class="rw-head">
      <span class="rw-kind">{{ w.kind }}</span>
      <span v-if="w.title" class="rw-title">· {{ w.title }}</span>
    </div>
    <div class="rw-reason">{{ w.reason }}</div>
    <button class="rw-action" @click="$emit('action', w)">검증 상세</button>
  </div>
</template>
