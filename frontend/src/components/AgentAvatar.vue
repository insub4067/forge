<script setup>
// FORGE 로봇 family — 같은 종족, 다른 직업. 하나의 컴포넌트로 role별 실루엣·자세·장비·
// 눈매를 바꿔 첫눈에 역할이 읽히게 한다(코너 badge 하나가 아니라 avatar 자체가 다름).
// role은 /api/agents의 icon 값(hammer|map|magnifier|chat)을 그대로 쓴다 — frontend에서
// 새 metadata를 만들지 않는다. status/size는 표현용.
defineProps({
  role: { type: String, default: '' },
  status: { type: String, default: 'idle' }, // idle | working | recent
  size: { type: String, default: 'md' },      // sm | md | lg
})
</script>

<template>
  <div class="agent-avatar" :class="[role, status, 'size-' + size]">
    <svg class="robot" viewBox="0 0 64 64" aria-hidden="true">
      <line class="antenna" x1="32" y1="3" x2="32" y2="9" />
      <circle class="antenna-dot" cx="32" cy="3" r="2.6" />

      <!-- Developer — 렌치를 들어올린 적극적 자세, 야무진 눈매 -->
      <g v-if="role === 'hammer'">
        <rect class="head" x="13" y="9" width="38" height="27" rx="8" />
        <rect class="eye" x="21.5" y="19.5" width="6" height="4.5" rx="1.5" />
        <rect class="eye" x="36.5" y="19.5" width="6" height="4.5" rx="1.5" />
        <path class="mouth" d="M26 29h12" />
        <rect class="body" x="17" y="40" width="30" height="20" rx="6" />
        <line class="arm" x1="18" y1="46" x2="10" y2="43" />
        <line class="arm" x1="46" y1="45" x2="53" y2="37" />
        <g class="tool">
          <path d="M54 37l3.4-3.4a3.6 3.6 0 0 0-4.6-4.6l1.1 3.6-1.8 1.8-3.6-1.1a3.6 3.6 0 0 0 4.6 4.6z" />
        </g>
      </g>

      <!-- Planner — 펼친 설계도를 내려다봄, 생각하는 눈 -->
      <g v-else-if="role === 'map'">
        <circle class="think" cx="47" cy="7" r="1.8" />
        <rect class="head" x="13" y="10" width="38" height="26" rx="8" />
        <circle class="eye" cx="25" cy="25" r="2.5" />
        <circle class="eye" cx="39" cy="25" r="2.5" />
        <path class="mouth" d="M27 31h10" />
        <rect class="body" x="17" y="40" width="30" height="20" rx="6" />
        <g class="tool">
          <rect x="20" y="43" width="24" height="15" rx="2" />
          <path d="M32 43v15M20 48.5h24M20 53h24" />
        </g>
      </g>

      <!-- Reviewer — 돋보기로 한쪽 눈을 확대해 관찰 -->
      <g v-else-if="role === 'magnifier'">
        <rect class="head" x="13" y="9" width="38" height="27" rx="8" />
        <circle class="eye" cx="39.5" cy="22" r="2.6" />
        <circle class="eye lens" cx="24" cy="22" r="3.4" />
        <path class="mouth" d="M28 30h8" />
        <rect class="body" x="17" y="40" width="30" height="20" rx="6" />
        <line class="arm" x1="46" y1="46" x2="53" y2="49" />
        <g class="tool">
          <circle cx="24" cy="22" r="8.5" />
          <line x1="18" y1="28" x2="12" y2="41" />
        </g>
      </g>

      <!-- Chat — 헤드셋 + 말풍선, 편안하고 대화형 인상 -->
      <g v-else-if="role === 'chat'">
        <rect class="head" x="13" y="10" width="38" height="26" rx="10" />
        <circle class="eye" cx="25" cy="22" r="3.2" />
        <circle class="eye" cx="39" cy="22" r="3.2" />
        <path class="mouth" d="M25 28q7 5 14 0" />
        <rect class="body" x="17" y="41" width="30" height="19" rx="8" />
        <line class="arm" x1="18" y1="47" x2="11" y2="51" />
        <line class="arm" x1="46" y1="47" x2="53" y2="51" />
        <g class="gear">
          <path d="M14 23a18 18 0 0 1 36 0" />
          <rect x="10.5" y="21.5" width="6" height="9" rx="2.5" />
          <rect x="47.5" y="21.5" width="6" height="9" rx="2.5" />
        </g>
        <g class="tool">
          <path d="M49 5h10a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-4l-2.5 3v-3H49a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2z" />
        </g>
      </g>

      <!-- fallback — 소속 불명 로봇 -->
      <g v-else>
        <rect class="head" x="13" y="9" width="38" height="27" rx="8" />
        <circle class="eye" cx="24.5" cy="22" r="3.4" />
        <circle class="eye" cx="39.5" cy="22" r="3.4" />
        <path class="mouth" d="M25 29h14" />
        <rect class="body" x="17" y="40" width="30" height="20" rx="6" />
      </g>
    </svg>
  </div>
</template>

<style scoped>
.agent-avatar {
  position: relative;
  width: 80px;
  height: 80px;
}
.agent-avatar.size-lg { width: 96px; height: 96px; }
.agent-avatar.size-sm { width: 44px; height: 44px; }
.robot { width: 100%; height: 100%; overflow: visible; }

/* 공통 파츠 — 전역 .robot 토큰과 같은 색을 쓰되 컴포넌트 내부에서 확정한다. */
.robot :deep(.head),
.robot .head,
.robot .body { fill: var(--panel-2); stroke: var(--border); stroke-width: 2; }
.robot .antenna,
.robot .arm { stroke: var(--muted); stroke-width: 2.5; stroke-linecap: round; fill: none; }
.robot .antenna-dot { fill: var(--accent); }
.robot .eye { fill: var(--text); }
.robot .mouth { stroke: var(--muted); stroke-width: 2.5; stroke-linecap: round; fill: none; }
.robot .think { fill: var(--muted); opacity: 0.7; }

/* 역할 장비 — accent로 또렷하게, 하지만 rainbow는 아님(같은 FORGE accent family) */
.robot .tool { fill: none; stroke: var(--accent); stroke-width: 2.2; stroke-linejoin: round; stroke-linecap: round; }
.robot .gear { fill: var(--panel-2); stroke: var(--muted); stroke-width: 2.2; stroke-linecap: round; }
.robot .eye.lens { fill: var(--accent); }

/* 상태 생명감 — avatar 자체 status로 구동(카드 밖 detail hero에서도 동작).
   transform/opacity만. reduced-motion이면 정지. */
.agent-avatar.idle .robot { animation: av-breathe 3.6s ease-in-out infinite; }
.agent-avatar.working .robot { animation: av-work 0.9s ease-in-out infinite; }
.agent-avatar.working .tool,
.agent-avatar.working .gear { animation: av-tool 0.9s ease-in-out infinite; transform-origin: 50% 60%; }

@keyframes av-breathe { 0%,100% { transform: translateY(0); } 50% { transform: translateY(-1.5px); } }
@keyframes av-work { 0%,100% { transform: translateY(0); } 50% { transform: translateY(-2px); } }
@keyframes av-tool { 0%,100% { transform: rotate(0); } 50% { transform: rotate(-7deg); } }

@media (prefers-reduced-motion: reduce) {
  .agent-avatar .robot,
  .agent-avatar .tool,
  .agent-avatar .gear { animation: none !important; }
}
</style>
